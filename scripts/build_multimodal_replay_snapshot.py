#!/usr/bin/env python3
"""Build the deployable replay snapshot from the validated multimodal OOF run.

This is an offline artifact transformation.  It does not train a model and it
never uses ``target_price`` to derive a warning, rank an alert, or construct
Copilot evidence.  The validation winners are selected per horizon:

* 7 days: LightGBM log-ratio with all modalities and the dynamic graph
* 14 days: LightGBM log-ratio with price and calendar only

The second point is intentional.  The other modalities are still surfaced as
available/absent context, but are marked as outside the selected 14-day
feature contract instead of being presented as attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.backend.config import REPO_ROOT, SCHEMA_VERSION, SUPPORTED_HORIZONS, THRESHOLDS
from app.backend.rules import classify_warning, projected_change_pct


OOF_REQUIRED = {
    "series_id",
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
    "date",
    "current_price",
    "target_price",
    "model",
    "variant",
    "horizon_days",
    "fold_id",
    "forecast_origin",
    "target_date",
    "predicted_price",
}

SELECTED_MODELS = {
    7: "LGBM_LOGRATIO__ALL_MODALITIES_DYNAMIC_GRAPH",
    14: "LGBM_LOGRATIO__PRICE_CALENDAR",
}

MODALITIES = (
    "Price",
    "Calendar",
    "Weather",
    "Production",
    "Satellite",
    "Markets & static connectivity",
    "Dynamic price dependence graph",
)

CONTEXT_COLUMNS = [
    "series_id",
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
    "date",
    "price_observed",
    "price_ffill",
    "price_observation_age_days",
    "calendar_status",
    "is_weekend",
    "is_national_holiday",
    "is_ramadan_start",
    "is_eid_al_fitr",
    "is_eid_al_adha",
    "weather_observation_date",
    "weather_effective_date",
    "temperature_c_mean",
    "temperature_c_min",
    "temperature_c_max",
    "rainfall_mm_sum",
    "soil_moisture_layer1_mean",
    "solar_radiation_mj_m2_sum",
    "weather_grid_coverage",
    "weather_source",
    "weather_observation_age_days",
    "weather_status",
    "production_effective_date",
    "year_production",
    "production_kg",
    "harvested_area_ha",
    "productivity_kg_per_ha",
    "production_age_years",
    "production_status",
    "production_release_source",
    "satellite_observation_date",
    "satellite_effective_date",
    "satellite_available_at",
    "satellite_quality",
    "ndvi_mean",
    "ndvi_std",
    "ndwi_mean",
    "evi_mean",
    "evi_std",
    "valid_pixel_fraction",
    "cloud_cover",
    "satellite_observation_age_days",
    "satellite_status",
    "transport_snapshot_date",
    "transport_source",
    "candidate_connectivity_only",
    "major_road_length_km",
    "major_road_segment_count",
    "ferry_length_km",
    "ferry_segment_count",
    "ferry_terminal_count",
    "port_count",
    "marketplace_count",
    "transport_snapshot_age_days",
    "graph_status",
    "market_context_effective_date",
    "official_market_context_source",
    "official_market_source_vintage",
    "official_market_province_coverage_status",
    "official_market_count",
    "official_market_schedule_count",
    "official_market_every_day_count",
    "official_market_days_per_week_mean",
    "official_market_days_per_week_median",
    "official_market_schedule_coverage",
    "official_market_daily_equivalent",
    "official_market_context_status",
    "mask_price",
    "mask_weather",
    "mask_production",
    "mask_satellite",
    "mask_calendar",
    "mask_graph",
    "available_modality_count",
    "modality_availability_fraction",
    "evidence_quality_score",
    "evidence_status",
    "abstention_required",
    "abstention_reason",
    "data_version_date",
]

GRAPH_COLUMNS = [
    "snapshot_date",
    "commodity_code",
    "market_level",
    "source_province_code",
    "target_province_code",
    "lead_lag_corr",
    "abs_lead_lag_corr",
    "source_lead_days",
    "edge_interpretation",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_short_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _clean_code(value: Any) -> str:
    match = pd.Series([value]).astype(str).str.extract(r"(\d+)", expand=False).iloc[0]
    return str(match).zfill(2) if pd.notna(match) else str(value).strip()


def _date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _age_days(origin: str, observation_date: str | None) -> int | None:
    if not observation_date:
        return None
    delta = (pd.Timestamp(origin) - pd.Timestamp(observation_date)).days
    return max(0, int(delta))


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "nat", "none"} else None


def _bool(value: Any) -> bool | None:
    number = _number(value)
    if number is not None:
        return bool(number)
    text = (_text(value) or "").lower()
    if text in {"true", "yes", "y", "available", "fresh", "ok"}:
        return True
    if text in {"false", "no", "n", "missing", "stale"}:
        return False
    return None


def _values(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        if field.endswith("date") or field.endswith("_date") or field in {
            "satellite_available_at"
        }:
            value = _date(value)
        elif field.startswith("is_") or field.startswith("mask_") or field in {
            "price_observed",
            "candidate_connectivity_only",
            "abstention_required",
        }:
            value = _bool(value)
        elif isinstance(value, str):
            value = _text(value)
        else:
            value = _number(value)
        if value is not None:
            values[field] = value
    return values


def _status(row: dict[str, Any], field: str, *, fallback: str = "MISSING") -> str:
    value = (_text(row.get(field)) or "").lower()
    if value in {"fresh", "ok"}:
        return "FRESH"
    if value in {"available", "present"}:
        return "AVAILABLE"
    if value in {"stale", "aged"}:
        return "STALE"
    if value in {"missing", "not_available", "not_in_artifact"} or not value:
        return fallback
    return value.upper()


def _available(status: str) -> bool:
    return status not in {"MISSING", "NOT_IN_ARTIFACT", "UNAVAILABLE"}


def _contract_for_model(model: str) -> tuple[str, dict[str, bool]]:
    if model == SELECTED_MODELS[7]:
        return (
            "ALL_MODALITIES_DYNAMIC_GRAPH",
            {
                "Price": True,
                "Calendar": True,
                "Weather": True,
                "Production": True,
                "Satellite": True,
                "Markets & static connectivity": True,
                "Dynamic price dependence graph": True,
            },
        )
    if model == SELECTED_MODELS[14]:
        return (
            "PRICE_CALENDAR",
            {
                "Price": True,
                "Calendar": True,
                "Weather": False,
                "Production": False,
                "Satellite": False,
                "Markets & static connectivity": False,
                "Dynamic price dependence graph": False,
            },
        )
    raise ValueError(f"No selected feature contract is registered for {model!r}")


def _load_oof(source: Path) -> pd.DataFrame:
    frame = pd.read_parquet(source) if source.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(source)
    missing = sorted(OOF_REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"Multimodal OOF artifact is missing required columns: {missing}")
    frame = frame.loc[
        frame.apply(
            lambda row: str(row["model"]) == SELECTED_MODELS.get(int(row["horizon_days"]), ""),
            axis=1,
        )
    ].copy()
    if frame.empty:
        raise ValueError("No validation-winning multimodal rows were found")
    frame["forecast_origin"] = pd.to_datetime(frame["forecast_origin"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["target_date"] = pd.to_datetime(frame["target_date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="raise").astype(int)
    if set(frame["horizon_days"]) != set(SUPPORTED_HORIZONS):
        raise ValueError(f"Selected OOF horizons are {sorted(frame['horizon_days'].unique())}, expected {SUPPORTED_HORIZONS}")
    origin = pd.to_datetime(frame["forecast_origin"])
    target = pd.to_datetime(frame["target_date"])
    if (target < origin).any() or ((target - origin).dt.days != frame["horizon_days"]).any():
        raise ValueError("Multimodal OOF target dates do not align with forecast origins and horizons")
    for column in ["current_price", "predicted_price"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (~frame[column].map(math.isfinite)).any() or (frame[column] < 0).any():
            raise ValueError(f"{column} contains invalid values")
    if (frame["current_price"] <= 0).any():
        raise ValueError("current_price must be positive")
    frame["target_price"] = pd.to_numeric(frame["target_price"], errors="coerce")
    frame["province_code"] = frame["province_code"].map(_clean_code)
    if frame.duplicated(["series_id", "forecast_origin", "horizon_days", "model"]).any():
        raise ValueError("Selected multimodal OOF contains duplicate logical forecasts")
    return frame


def _extract_context(panel: Path, origins: set[str]) -> pd.DataFrame:
    if not panel.exists():
        raise FileNotFoundError(f"Multimodal feature panel not found: {panel}")
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(panel, usecols=CONTEXT_COLUMNS, chunksize=50_000, low_memory=False):
        subset = chunk.loc[chunk["date"].astype(str).isin(origins)]
        if not subset.empty:
            chunks.append(subset)
    if not chunks:
        raise ValueError("No feature-panel rows match the multimodal forecast origins")
    context = pd.concat(chunks, ignore_index=True)
    context["date"] = pd.to_datetime(context["date"], errors="raise").dt.strftime("%Y-%m-%d")
    context["province_code"] = context["province_code"].map(_clean_code)
    if context.duplicated(["series_id", "date"]).any():
        raise ValueError("Feature panel contains duplicate series/date context rows")
    return context


def _load_context(context_path: Path, panel_path: Path, origins: set[str]) -> pd.DataFrame:
    if context_path.exists():
        context = pd.read_csv(context_path, low_memory=False)
        missing = sorted(set(CONTEXT_COLUMNS) - set(context.columns))
        if missing:
            raise ValueError(f"Replay context is missing columns: {missing}")
        context = context[CONTEXT_COLUMNS].copy()
        context["date"] = pd.to_datetime(context["date"], errors="raise").dt.strftime("%Y-%m-%d")
        context["province_code"] = context["province_code"].map(_clean_code)
        return context
    return _extract_context(panel_path, origins)


def _load_graph(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=GRAPH_COLUMNS + ["_snapshot"])
    graph = pd.read_parquet(path, columns=GRAPH_COLUMNS) if path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path, usecols=GRAPH_COLUMNS)
    graph["_snapshot"] = pd.to_datetime(graph["snapshot_date"], errors="coerce")
    graph["commodity_code"] = graph["commodity_code"].astype(str)
    graph["market_level"] = graph["market_level"].astype(str)
    graph["source_province_code"] = graph["source_province_code"].map(_clean_code)
    graph["target_province_code"] = graph["target_province_code"].map(_clean_code)
    return graph.dropna(subset=["_snapshot"])


def _dynamic_summary(graph: pd.DataFrame, row: dict[str, Any], cache: dict[tuple[str, str, str, str], dict[str, Any] | None]) -> dict[str, Any] | None:
    key = (
        str(row["commodity_code"]),
        str(row["market_level"]),
        _clean_code(row["province_code"]),
        str(row["forecast_origin"]),
    )
    if key in cache:
        return cache[key]
    if graph.empty:
        cache[key] = None
        return None
    commodity, market, source, origin = key
    subset = graph.loc[
        graph["commodity_code"].eq(commodity)
        & graph["market_level"].eq(market)
        & graph["source_province_code"].eq(source)
        & (graph["_snapshot"] <= pd.Timestamp(origin))
    ]
    if subset.empty:
        cache[key] = None
        return None
    latest = subset["_snapshot"].max()
    edges = subset.loc[subset["_snapshot"].eq(latest)].copy()
    if edges.empty:
        cache[key] = None
        return None
    edges["abs_lead_lag_corr"] = pd.to_numeric(edges["abs_lead_lag_corr"], errors="coerce")
    edges = edges.sort_values("abs_lead_lag_corr", ascending=False)
    corr = pd.to_numeric(edges["abs_lead_lag_corr"], errors="coerce").dropna()
    lead = pd.to_numeric(edges["source_lead_days"], errors="coerce").dropna()
    examples: list[dict[str, Any]] = []
    for edge in edges.head(5).to_dict("records"):
        examples.append(
            {
                "source_province_code": str(edge["source_province_code"]),
                "target_province_code": str(edge["target_province_code"]),
                "lead_lag_corr": _number(edge["lead_lag_corr"]),
                "source_lead_days": _number(edge["source_lead_days"]),
                "edge_type": "Model-inferred price dependence",
            }
        )
    result = {
        "snapshot_date": _date(latest),
        "edge_count": int(len(edges)),
        "mean_abs_lead_lag_corr": _number(corr.mean()) if not corr.empty else None,
        "max_abs_lead_lag_corr": _number(corr.max()) if not corr.empty else None,
        "mean_source_lead_days": _number(lead.mean()) if not lead.empty else None,
        "edges": examples,
        "interpretation": "Candidate model-inferred price dependence; not confirmed commodity shipments and not a propagation probability.",
    }
    cache[key] = result
    return result


def _item(
    forecast_id: str,
    modality: str,
    status: str,
    available: bool,
    used_by_model: bool,
    *,
    observation_date: str | None = None,
    observation_age_days: Any = None,
    source: str | None = None,
    values: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if note is None:
        if used_by_model:
            note = "Included in the selected model feature contract; inclusion is not signed importance or attribution."
        elif available:
            note = "Available context in the feature panel, but outside the selected model feature contract; this is not attribution."
        else:
            note = "Not available for this forecast artifact."
    return {
        "evidence_id": f"EV-{forecast_id}-{modality.upper().replace(' ', '-').replace('&', 'AND').replace('/', '-')}",
        "modality": modality,
        "status": status,
        "available": bool(available),
        "observation_date": observation_date,
        "observation_age_days": _number(observation_age_days),
        "source": source,
        "note": note,
        "is_model_attribution": False,
        "used_by_model": bool(used_by_model),
        "values": values or {},
    }


def _build_items(forecast: dict[str, Any], context: dict[str, Any], contract: dict[str, bool], dynamic: dict[str, Any] | None) -> list[dict[str, Any]]:
    forecast_id = str(forecast["forecast_id"])
    origin = str(forecast["forecast_origin"])
    price_age = _number(context.get("price_observation_age_days"))
    price_observed = _bool(context.get("price_observed"))
    price_status = "FRESH" if price_observed is not False else ("STALE" if price_age not in {None, 0} else "AVAILABLE")

    weather_status = _status(context, "weather_status")
    weather_values = _values(
        context,
        [
            "temperature_c_mean",
            "temperature_c_min",
            "temperature_c_max",
            "rainfall_mm_sum",
            "soil_moisture_layer1_mean",
            "solar_radiation_mj_m2_sum",
            "weather_grid_coverage",
        ],
    )
    weather_date = _date(context.get("weather_observation_date")) or _date(context.get("weather_effective_date"))
    weather_available = _available(weather_status) and bool(weather_values)

    production_status = _status(context, "production_status")
    production_values = _values(context, ["year_production", "production_kg", "harvested_area_ha", "productivity_kg_per_ha", "production_age_years"])
    production_available = _available(production_status) and bool(production_values)

    satellite_status = _status(context, "satellite_status")
    satellite_values = _values(context, ["ndvi_mean", "ndvi_std", "ndwi_mean", "evi_mean", "evi_std", "valid_pixel_fraction", "cloud_cover"])
    satellite_date = _date(context.get("satellite_observation_date")) or _date(context.get("satellite_effective_date"))
    satellite_available = _available(satellite_status) and bool(satellite_values)

    market_status = _status(context, "official_market_context_status")
    graph_status = _status(context, "graph_status")
    static_values = _values(
        context,
        [
            "official_market_count",
            "official_market_schedule_count",
            "official_market_days_per_week_mean",
            "official_market_schedule_coverage",
            "official_market_daily_equivalent",
            "major_road_length_km",
            "major_road_segment_count",
            "ferry_length_km",
            "ferry_segment_count",
            "ferry_terminal_count",
            "port_count",
            "marketplace_count",
        ],
    )
    static_available = (_available(market_status) or _available(graph_status)) and bool(static_values)
    static_status = "AVAILABLE" if static_available else "MISSING"
    static_date = _date(context.get("market_context_effective_date")) or _date(context.get("transport_snapshot_date"))
    static_age_values = _values(context, ["transport_snapshot_age_days"])
    static_values.update(static_age_values)

    calendar_status = _status(context, "calendar_status")
    calendar_values = _values(context, ["is_weekend", "is_national_holiday", "is_ramadan_start", "is_eid_al_fitr", "is_eid_al_adha"])

    dynamic_values = dynamic or {}
    dynamic_available = dynamic is not None and int(dynamic.get("edge_count", 0)) > 0
    dynamic_status = "AVAILABLE" if dynamic_available else "MISSING"

    return [
        _item(
            forecast_id,
            "Price",
            price_status,
            True,
            contract["Price"],
            observation_date=origin,
            observation_age_days=price_age,
            source="PIHPS source snapshot",
            values={"price_observed": price_observed, "current_price": _number(forecast["current_price"])},
            note="Observed or carried-forward price at the forecast origin; availability is not attribution.",
        ),
        _item(
            forecast_id,
            "Calendar",
            calendar_status,
            _available(calendar_status),
            contract["Calendar"],
            observation_date=origin if _available(calendar_status) else None,
            source="Official Indonesian calendar feature snapshot",
            values=calendar_values,
        ),
        _item(
            forecast_id,
            "Weather",
            weather_status,
            weather_available,
            contract["Weather"],
            observation_date=weather_date,
            observation_age_days=context.get("weather_observation_age_days"),
            source=_text(context.get("weather_source")) or "ERA5-Land daily context",
            values=weather_values,
        ),
        _item(
            forecast_id,
            "Production",
            production_status,
            production_available,
            contract["Production"],
            observation_date=_date(context.get("production_effective_date")),
            observation_age_days=_age_days(origin, _date(context.get("production_effective_date"))),
            source=_text(context.get("production_release_source")) or "BPS annual production context",
            values=production_values,
            note=(
                "Annual structural context; included in the selected feature contract, not a daily supply observation."
                if contract["Production"]
                else "Annual structural context is available, but outside the selected 14-day feature contract."
            ),
        ),
        _item(
            forecast_id,
            "Satellite",
            satellite_status,
            satellite_available,
            contract["Satellite"],
            observation_date=satellite_date,
            observation_age_days=context.get("satellite_observation_age_days"),
            source="Sentinel-2 L2A vegetation feature snapshot",
            values=satellite_values,
            note=(
                "Cloud-aware Sentinel-2 context is included in the selected feature contract; this is not signed attribution."
                if contract["Satellite"]
                else "Cloud-aware Sentinel-2 context is available, but outside the selected 14-day feature contract."
            ),
        ),
        _item(
            forecast_id,
            "Markets & static connectivity",
            static_status,
            static_available,
            contract["Markets & static connectivity"],
            observation_date=static_date,
            observation_age_days=context.get("transport_snapshot_age_days"),
            source=(
                _text(context.get("official_market_context_source"))
                or _text(context.get("transport_source"))
                or "Official market and OSM-derived static context"
            ),
            values=static_values,
            note=(
                "Official market and candidate connectivity context is included in the selected feature contract; it is not confirmed shipment flow."
                if contract["Markets & static connectivity"]
                else "Official market and candidate connectivity context is available, but outside the selected 14-day feature contract."
            ),
        ),
        _item(
            forecast_id,
            "Dynamic price dependence graph",
            dynamic_status,
            dynamic_available,
            contract["Dynamic price dependence graph"],
            observation_date=_date(dynamic_values.get("snapshot_date")),
            source="Rolling province price-dependence graph",
            values=dynamic_values,
            note=(
                "Rolling graph features are included in the selected feature contract. Edges are model-inferred price dependence, not confirmed shipments or propagation probabilities."
                if contract["Dynamic price dependence graph"]
                else "A rolling price-dependence graph is available, but outside the selected 14-day feature contract; no propagation probability is available."
            ),
        ),
    ]


def _normalize_forecasts(oof: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    context_key = context.set_index(["series_id", "date"])
    missing_keys = [
        (str(row.series_id), str(row.forecast_origin))
        for row in oof.itertuples()
        if (str(row.series_id), str(row.forecast_origin)) not in context_key.index
    ]
    if missing_keys:
        raise ValueError(f"Feature panel is missing {len(missing_keys)} selected forecast context rows")
    frame = oof.copy()
    frame["projected_change"] = frame["predicted_price"] - frame["current_price"]
    frame["projected_change_pct"] = [
        projected_change_pct(current, predicted)
        for current, predicted in zip(frame["current_price"], frame["predicted_price"])
    ]
    frame["warning_level"] = [classify_warning(value, THRESHOLDS) for value in frame["projected_change_pct"]]
    frame["forecast_id"] = (
        "FP-"
        + frame["forecast_origin"].str.replace("-", "", regex=False)
        + "-"
        + frame["province_code"]
        + "-"
        + frame["commodity_code"].astype(str)
        + "-"
        + frame["market_level"].str.upper()
        + "-"
        + frame["horizon_days"].astype(str)
    )
    frame["model_version"] = "A100-multimodal-ablation-v1"
    frame["data_version"] = frame["forecast_origin"].map(
        context.drop_duplicates("date").set_index("date")["data_version_date"].to_dict()
    ).fillna("multimodal feature panel version unavailable")
    frame["feature_version"] = frame["variant"].map(lambda value: f"multimodal:{value}")
    frame["actual_available"] = frame["target_price"].notna()
    frame["attribution_available"] = False
    frame["interval_available"] = False
    frame["shock_probability_available"] = False
    frame["propagation_available"] = False
    frame["forecast_target_known_at_origin"] = False

    context_quality = context.drop_duplicates(["series_id", "date"])[
        ["series_id", "date", "evidence_quality_score", "abstention_required"]
    ]
    frame = frame.merge(
        context_quality,
        left_on=["series_id", "forecast_origin"],
        right_on=["series_id", "date"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_context"),
    ).drop(columns=["date"])
    frame["abstention_required"] = frame["abstention_required"].fillna(False).astype(bool)
    frame["fold_id"] = pd.to_numeric(frame["fold_id"], errors="coerce").astype("Int64")
    columns = [
        "forecast_id",
        "series_id",
        "province_code",
        "province_name",
        "commodity_code",
        "commodity_name",
        "market_level",
        "forecast_origin",
        "target_date",
        "horizon_days",
        "current_price",
        "predicted_price",
        "projected_change",
        "projected_change_pct",
        "warning_level",
        "model",
        "model_version",
        "data_version",
        "feature_version",
        "fold_id",
        "target_price",
        "actual_available",
        "forecast_target_known_at_origin",
        "attribution_available",
        "interval_available",
        "shock_probability_available",
        "propagation_available",
        "evidence_quality_score",
        "abstention_required",
    ]
    return frame[columns].sort_values(
        ["forecast_origin", "horizon_days", "projected_change_pct"],
        ascending=[True, True, False],
    ).reset_index(drop=True)


def build_snapshot(
    source: Path,
    context_path: Path,
    panel_path: Path,
    graph_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    for folder in ["forecasts", "evidence", "geography", "manifests"]:
        (output_root / folder).mkdir(exist_ok=True)

    oof = _load_oof(source)
    context = _load_context(context_path, panel_path, set(oof["forecast_origin"]))
    if not context_path.exists():
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context.to_csv(context_path, index=False)
    frame = _normalize_forecasts(oof, context)
    graph = _load_graph(graph_path)
    graph_cache: dict[tuple[str, str, str, str], dict[str, Any] | None] = {}
    context_lookup = context.set_index(["series_id", "date"]).to_dict("index")
    records: list[dict[str, Any]] = []
    for forecast in frame.to_dict("records"):
        context_row = context_lookup[(str(forecast["series_id"]), str(forecast["forecast_origin"]))]
        contract_name, contract = _contract_for_model(str(forecast["model"]))
        dynamic = _dynamic_summary(graph, {**forecast, **context_row}, graph_cache)
        items = _build_items(forecast, context_row, contract, dynamic)
        records.append(
            {
                "forecast_id": forecast["forecast_id"],
                "evidence_quality_score": _number(context_row.get("evidence_quality_score")),
                "attribution_available": False,
                "attribution_note": "No SHAP, TimeSHAP, or GNN attribution was exported. used_by_model flags indicate feature-contract inclusion only.",
                "abstention_required": bool(forecast["abstention_required"]),
                "abstention_reason": _text(context_row.get("abstention_reason")),
                "model": forecast["model"],
                "model_feature_contract": contract_name,
                "model_modalities": [modality for modality in MODALITIES if contract[modality]],
                "items": items,
            }
        )

    forecast_path = output_root / "forecasts" / "forecast_snapshot.csv"
    frame.to_csv(forecast_path, index=False, float_format="%.10g")
    evidence_path = output_root / "evidence" / "evidence_snapshot.json"
    evidence_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    geography_source = REPO_ROOT / "data" / "reference" / "indonesia_provinces.geojson"
    geography_path = output_root / "geography" / "indonesia_provinces.geojson"
    if geography_source.exists():
        shutil.copyfile(geography_source, geography_path)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_type": "historical_replay_multimodal_validation_winners",
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "context_path": str(context_path),
        "context_sha256": sha256_file(context_path),
        "dynamic_graph_path": str(graph_path),
        "dynamic_graph_sha256": sha256_file(graph_path) if graph_path.exists() else None,
        "rows": int(len(frame)),
        "series": int(frame["series_id"].nunique()),
        "province_codes": sorted(frame["province_code"].unique().tolist()),
        "forecast_origins": sorted(frame["forecast_origin"].unique().tolist()),
        "commodities": sorted(frame["commodity_code"].unique().tolist()),
        "market_levels": sorted(frame["market_level"].unique().tolist()),
        "horizons": sorted(int(value) for value in frame["horizon_days"].unique()),
        "models": sorted(frame["model"].unique().tolist()),
        "model_version": "A100-multimodal-ablation-v1",
        "model_selection": {
            "7": {
                "model": SELECTED_MODELS[7],
                "feature_contract": "ALL_MODALITIES_DYNAMIC_GRAPH",
                "reason": "Best pooled MAE among validated 7-day ablation rows.",
                "mae_idr_per_kg": 3538.4895695741798,
                "folds": 7,
            },
            "14": {
                "model": SELECTED_MODELS[14],
                "feature_contract": "PRICE_CALENDAR",
                "reason": "Best pooled MAE among validated 14-day ablation rows; added modalities remain context only for this horizon.",
                "mae_idr_per_kg": 5308.467049599704,
                "folds": 7,
            },
        },
        "data_version": str(frame["data_version"].dropna().iloc[0]) if frame["data_version"].notna().any() else None,
        "feature_contracts": {
            "7": "ALL_MODALITIES_DYNAMIC_GRAPH",
            "14": "PRICE_CALENDAR",
        },
        "git_revision_at_build": git_short_revision(),
        "warning_rule": {
            "watch": THRESHOLDS.watch,
            "elevated": THRESHOLDS.elevated,
            "high": THRESHOLDS.high,
            "note": "Product warning thresholds, not model probabilities or regulatory thresholds.",
        },
        "forecast_sha256": sha256_file(forecast_path),
        "evidence_sha256": sha256_file(evidence_path),
        "evidence_path": str(evidence_path),
        "geography_path": str(geography_path),
        "actual_values": "target_price is evaluation-only and excluded from warnings, ranking, and Copilot context.",
        "unsupported_outputs": [
            "shock_probability",
            "propagation_probability",
            "SHAP / TimeSHAP / GNN explanations",
            "uncertainty intervals",
        ],
    }
    manifest_path = output_root / "manifests" / "forecast_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "results" / "multimodal_ablation" / "oof_predictions.csv",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=REPO_ROOT / "results" / "multimodal_ablation" / "replay_context.csv",
    )
    parser.add_argument(
        "--panel",
        type=Path,
        default=REPO_ROOT / "data" / "ready" / "model_dataset_eligible.csv",
    )
    parser.add_argument(
        "--dynamic-graph",
        type=Path,
        default=REPO_ROOT / "data" / "processed" / "province_graph_dynamic.csv",
    )
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "demo_data")
    args = parser.parse_args()
    manifest = build_snapshot(
        args.source.resolve(),
        args.context.resolve(),
        args.panel.resolve(),
        args.dynamic_graph.resolve(),
        args.output_root.resolve(),
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
