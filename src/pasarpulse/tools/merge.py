"""Asynchronous multimodal alignment and model-ready panel construction."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..utils import save_frame, save_json
from .prices import add_price_grid_and_features


def _load_frame(value: pd.DataFrame | str | Path | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def _groupwise_asof(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    by: list[str],
    left_on: str,
    right_on: str,
    suffix: str,
) -> pd.DataFrame:
    if right.empty:
        return left
    right_groups = {key if isinstance(key, tuple) else (key,): group for key, group in right.groupby(by, dropna=False)}
    parts: list[pd.DataFrame] = []
    for key, left_group in left.groupby(by, dropna=False, sort=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        right_group = right_groups.get(key_tuple)
        if right_group is None or right_group.empty:
            parts.append(left_group)
            continue
        left_payload = left_group.copy()
        right_payload = right_group.drop(columns=by, errors="ignore").sort_values(right_on)
        if pd.api.types.is_datetime64_any_dtype(
            left_payload[left_on]
        ) and pd.api.types.is_datetime64_any_dtype(right_payload[right_on]):
            # Parquet sources may preserve millisecond resolution while the
            # daily price panel uses nanoseconds.  pandas merge_asof requires
            # an exact dtype match even when the timestamps are identical.
            left_payload[left_on] = pd.to_datetime(
                left_payload[left_on], errors="coerce"
            ).astype("datetime64[ns]")
            right_payload[right_on] = pd.to_datetime(
                right_payload[right_on], errors="coerce"
            ).astype("datetime64[ns]")
        merged = pd.merge_asof(
            left_payload.sort_values(left_on),
            right_payload,
            left_on=left_on,
            right_on=right_on,
            direction="backward",
            suffixes=("", suffix),
        )
        parts.append(merged)
    return pd.concat(parts, ignore_index=True) if parts else left


def _merge_weather(
    panel: pd.DataFrame,
    weather: pd.DataFrame,
    publication_lag_days: int,
    max_carry_days: int,
) -> pd.DataFrame:
    feature_prefixes = (
        "temperature_",
        "rainfall_",
        "soil_moisture_",
        "solar_radiation_",
    )
    if weather.empty:
        panel["weather_observation_date"] = pd.NaT
        panel["weather_effective_date"] = pd.NaT
        panel["weather_observation_age_days"] = np.nan
        panel["weather_status"] = "missing"
        return panel
    context = weather.copy()
    context["province_code"] = (
        context["province_code"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(2)
    )
    context["weather_observation_date"] = pd.to_datetime(
        context["date"], errors="coerce"
    ).dt.normalize()
    context["weather_effective_date"] = context["weather_observation_date"] + pd.to_timedelta(
        int(publication_lag_days), unit="D"
    )
    context = context.rename(columns={"weather_status": "weather_source_status"})
    features = [column for column in context if column.startswith(feature_prefixes)]
    metadata = [
        column
        for column in (
            "weather_grid_coverage",
            "weather_source",
            "weather_day_timezone",
            "accumulation_convention",
            "spatial_aggregation",
            "weather_source_status",
        )
        if column in context
    ]
    context = context[
        [
            "province_code",
            "weather_observation_date",
            "weather_effective_date",
            *features,
            *metadata,
        ]
    ].drop_duplicates(["province_code", "weather_effective_date"], keep="last")
    merged = _groupwise_asof(
        panel,
        context,
        by=["province_code"],
        left_on="date",
        right_on="weather_effective_date",
        suffix="_weather",
    )
    merged["weather_observation_age_days"] = (
        merged["date"] - merged["weather_observation_date"]
    ).dt.days
    stale = merged["weather_observation_age_days"].gt(int(max_carry_days))
    merged.loc[stale, features] = np.nan
    merged["weather_status"] = (
        np.select(
            [stale, merged[features].isna().all(axis=1)],
            ["stale", "missing"],
            default="fresh",
        )
        if features
        else "missing"
    )
    return merged


def _merge_production(panel: pd.DataFrame, production: pd.DataFrame, max_age_years: int) -> pd.DataFrame:
    if production.empty:
        for column in ("production_kg", "harvested_area_ha", "productivity_kg_per_ha", "production_year", "production_age_years"):
            panel[column] = np.nan
        panel["production_effective_date"] = pd.NaT
        panel["production_status"] = "missing"
        return panel
    prod = production.copy()
    prod["province_code"] = prod["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    prod["year"] = pd.to_numeric(prod["year"], errors="coerce").astype("Int64")
    if "production_effective_date" not in prod:
        prod["production_effective_date"] = pd.NaT
    prod["production_effective_date"] = pd.to_datetime(
        prod["production_effective_date"], errors="coerce"
    ).dt.normalize()
    keep = [
        "province_code", "commodity_code", "production_effective_date", "year",
        "production_kg", "harvested_area_ha", "productivity_kg_per_ha", "quality_flag",
        "production_release_source",
    ]
    merged = _groupwise_asof(
        panel, prod[[column for column in keep if column in prod]],
        by=["province_code", "commodity_code"], left_on="date", right_on="production_effective_date", suffix="_production",
    )
    merged = merged.rename(columns={"year": "production_year", "quality_flag": "production_quality_flag"})
    merged["production_age_years"] = merged["date"].dt.year - pd.to_numeric(merged["production_year"], errors="coerce")
    stale = merged["production_age_years"].gt(max_age_years).fillna(False).astype(bool)
    feature_cols = ["production_kg", "harvested_area_ha", "productivity_kg_per_ha"]
    merged.loc[stale, feature_cols] = np.nan
    merged["production_status"] = np.select(
        [stale, merged["production_kg"].isna()], ["stale", "missing"], default="fresh"
    )
    return merged


def _merge_satellite(
    panel: pd.DataFrame,
    satellite: pd.DataFrame,
    max_carry_days: int,
    publication_lag_days: int,
) -> pd.DataFrame:
    satellite_features = [
        "ndvi_mean", "ndvi_std", "ndvi_p10", "ndvi_p90", "ndwi_mean",
        "evi_mean", "evi_std", "evi_anomaly", "evi_zscore",
        "valid_pixel_fraction", "ndvi_anomaly", "ndvi_zscore", "cloud_cover",
    ]
    if satellite.empty:
        for column in satellite_features + [
            "satellite_observation_date",
            "satellite_effective_date",
            "satellite_observation_age_days",
        ]:
            panel[column] = np.nan
        panel["satellite_status"] = "missing"
        return panel
    sat = satellite.copy()
    if "date" not in sat:
        sat["date"] = pd.to_datetime(sat["datetime"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    else:
        sat["date"] = pd.to_datetime(sat["date"], errors="coerce").dt.normalize()
    sat["province_code"] = sat.get("province_code", sat.get("zone_code")).astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    sat = sat.sort_values(["province_code", "date"]).drop_duplicates(["province_code", "date"], keep="last")
    sat = sat.rename(columns={"date": "satellite_observation_date", "status": "satellite_source_status"})
    fallback_effective_date = sat["satellite_observation_date"] + pd.to_timedelta(
        int(publication_lag_days), unit="D"
    )
    # Prefer the STAC publication timestamp when the provider exposes it.
    # Observation time alone is not sufficient evidence that a scene was
    # available to a replay model at that instant.
    missing_timestamp = pd.Series(pd.NaT, index=sat.index, dtype="datetime64[ns, UTC]")
    created = pd.to_datetime(
        sat["created"] if "created" in sat else missing_timestamp,
        errors="coerce",
        utc=True,
    )
    updated = pd.to_datetime(
        sat["updated"] if "updated" in sat else missing_timestamp,
        errors="coerce",
        utc=True,
    )
    published = created.fillna(updated)
    sat["satellite_available_at"] = published.dt.tz_convert(None)
    sat["satellite_effective_date"] = (
        sat["satellite_available_at"].dt.normalize().fillna(fallback_effective_date)
    )
    keep = [
        "province_code",
        "satellite_observation_date",
        "satellite_effective_date",
        "satellite_available_at",
        "satellite_source_status",
        "satellite_quality",
    ] + satellite_features
    merged = _groupwise_asof(
        panel, sat[[column for column in keep if column in sat]],
        by=["province_code"], left_on="date", right_on="satellite_effective_date", suffix="_satellite",
    )
    merged["satellite_observation_age_days"] = (merged["date"] - merged["satellite_observation_date"]).dt.days
    stale = merged["satellite_observation_age_days"].gt(max_carry_days)
    existing_features = [column for column in satellite_features if column in merged]
    merged.loc[stale, existing_features] = np.nan
    merged["satellite_status"] = np.select(
        [stale, merged[existing_features].isna().all(axis=1)], ["stale", "missing"], default="fresh"
    ) if existing_features else "missing"
    return merged


def _merge_transport(panel: pd.DataFrame, transport: pd.DataFrame) -> pd.DataFrame:
    """Attach only transport context available on or before each panel date."""
    features = [
        "major_road_length_km",
        "major_road_segment_count",
        "ferry_length_km",
        "ferry_segment_count",
        "ferry_terminal_count",
        "port_count",
        "marketplace_count",
    ]
    if transport.empty:
        for column in features + ["transport_snapshot_date", "transport_snapshot_age_days"]:
            panel[column] = np.nan
        panel["graph_status"] = "missing"
        return panel

    context = transport.copy()
    required = {"province_code", "snapshot_date"}
    missing = required.difference(context.columns)
    if missing:
        raise ValueError(f"OSM transport summary misses columns: {sorted(missing)}")
    context["province_code"] = (
        context["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    )
    context["transport_snapshot_date"] = pd.to_datetime(
        context["snapshot_date"], errors="coerce"
    ).dt.normalize()
    context = context.rename(
        columns={"source": "transport_source", "source_url": "transport_source_url"}
    )
    keep = [
        "province_code",
        "transport_snapshot_date",
        "transport_source",
        "transport_source_url",
        "candidate_connectivity_only",
        *features,
    ]
    context = context[[column for column in keep if column in context]].drop_duplicates(
        ["province_code", "transport_snapshot_date"], keep="last"
    )
    merged = _groupwise_asof(
        panel,
        context,
        by=["province_code"],
        left_on="date",
        right_on="transport_snapshot_date",
        suffix="_transport",
    )
    merged["transport_snapshot_age_days"] = (
        merged["date"] - merged["transport_snapshot_date"]
    ).dt.days
    available = [column for column in features if column in merged]
    merged["graph_status"] = (
        np.where(merged[available].notna().any(axis=1), "available", "missing")
        if available
        else "missing"
    )
    return merged


def _merge_official_markets(
    panel: pd.DataFrame, official_markets: pd.DataFrame
) -> pd.DataFrame:
    features = [
        "official_market_count",
        "official_market_schedule_count",
        "official_market_every_day_count",
        "official_market_days_per_week_mean",
        "official_market_days_per_week_median",
        "official_market_schedule_coverage",
        "official_market_daily_equivalent",
    ]
    if official_markets.empty:
        for column in features:
            panel[column] = np.nan
        panel["official_market_context_status"] = "missing"
        return panel
    context = official_markets.copy()
    context["province_code"] = (
        context["province_code"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(2)
    )
    context["market_context_effective_date"] = pd.to_datetime(
        context["market_context_effective_date"], errors="coerce"
    ).dt.normalize()
    keep = [
        "province_code",
        "market_context_effective_date",
        "official_market_context_source",
        "official_market_source_vintage",
        "official_market_province_coverage_status",
        *features,
    ]
    merged = _groupwise_asof(
        panel,
        context[[column for column in keep if column in context]],
        by=["province_code"],
        left_on="date",
        right_on="market_context_effective_date",
        suffix="_official_market",
    )
    available = [column for column in features if column in merged]
    merged["official_market_context_status"] = (
        np.where(merged[available].notna().any(axis=1), "available", "missing")
        if available
        else "missing"
    )
    return merged


def _merge_thresholds(panel: pd.DataFrame, thresholds: pd.DataFrame) -> pd.DataFrame:
    if thresholds.empty:
        panel["threshold_type"] = pd.NA
        panel["threshold_value_idr_per_kg"] = np.nan
        panel["threshold_exceeded"] = pd.NA
        return panel
    required = {"commodity_code", "market_level", "effective_start", "threshold_type", "threshold_value_idr_per_kg"}
    missing = required.difference(thresholds.columns)
    if missing:
        raise ValueError(f"Official-threshold file misses columns: {sorted(missing)}")
    right = thresholds.copy()
    right["effective_start"] = pd.to_datetime(right["effective_start"], errors="coerce")
    right["effective_end"] = pd.to_datetime(right.get("effective_end"), errors="coerce")
    merged = _groupwise_asof(
        panel, right, by=["commodity_code", "market_level"], left_on="date", right_on="effective_start", suffix="_threshold",
    )
    expired = merged["effective_end"].notna() & merged["date"].gt(merged["effective_end"])
    merged.loc[expired, ["threshold_type", "threshold_value_idr_per_kg"]] = pd.NA
    merged["threshold_exceeded"] = np.where(
        merged["price_idr_per_kg"].notna() & pd.to_numeric(merged["threshold_value_idr_per_kg"], errors="coerce").notna(),
        (merged["price_idr_per_kg"] > pd.to_numeric(merged["threshold_value_idr_per_kg"], errors="coerce")).astype("int8"),
        pd.NA,
    )
    return merged


def build_model_ready_dataset(
    prices: pd.DataFrame | str | Path,
    *,
    coverage_audit: pd.DataFrame | str | Path | None,
    weather: pd.DataFrame | str | Path | None,
    production: pd.DataFrame | str | Path | None,
    satellite: pd.DataFrame | str | Path | None,
    calendar: pd.DataFrame | str | Path | None,
    transport: pd.DataFrame | str | Path | None,
    official_markets: pd.DataFrame | str | Path | None,
    thresholds: pd.DataFrame | str | Path | None,
    start_date: str,
    end_date: str,
    bounded_price_ffill_days: int,
    satellite_max_carry_days: int,
    satellite_publication_lag_days: int,
    weather_publication_lag_days: int,
    weather_max_carry_days: int,
    production_max_age_years: int,
    shock_threshold: float,
    output_all_base: str | Path,
    output_eligible_base: str | Path,
    metadata_path: str | Path,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path], dict[str, Path]]:
    price_frame = _load_frame(prices)
    if price_frame.empty:
        raise ValueError("Price dataset is required as the anchor modality.")
    price_frame["province_code"] = price_frame["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    panel = add_price_grid_and_features(
        price_frame,
        start_date=start_date,
        end_date=end_date,
        bounded_ffill_days=bounded_price_ffill_days,
        shock_threshold=shock_threshold,
    )
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()

    calendar_frame = _load_frame(calendar)
    if not calendar_frame.empty:
        calendar_frame["date"] = pd.to_datetime(calendar_frame["date"], errors="coerce").dt.normalize()
        panel = panel.merge(calendar_frame, on="date", how="left", validate="many_to_one")

    panel = _merge_weather(
        panel,
        _load_frame(weather),
        weather_publication_lag_days,
        weather_max_carry_days,
    )

    panel = _merge_production(panel, _load_frame(production), production_max_age_years)
    panel = _merge_satellite(
        panel,
        _load_frame(satellite),
        satellite_max_carry_days,
        satellite_publication_lag_days,
    )
    panel = _merge_transport(panel, _load_frame(transport))
    panel = _merge_official_markets(panel, _load_frame(official_markets))
    panel = _merge_thresholds(panel, _load_frame(thresholds))

    audit = _load_frame(coverage_audit)
    audit_keys = ["province_code", "commodity_code", "market_level"]
    if not audit.empty:
        audit["province_code"] = audit["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
        audit_payload = audit[audit_keys + [column for column in ["coverage", "months_available", "eligible", "reason"] if column in audit]].drop_duplicates(audit_keys)
        panel = panel.merge(audit_payload, on=audit_keys, how="left", validate="many_to_one")
    else:
        panel["eligible"] = False
        panel["reason"] = "coverage_audit_missing"
    panel = panel.rename(columns={"eligible": "is_eligible_series", "reason": "eligibility_reason", "coverage": "price_series_coverage"})
    panel["is_eligible_series"] = panel["is_eligible_series"].fillna(False).astype(bool)

    weather_cols = [column for column in panel if column.startswith(("temperature_", "rainfall_", "soil_moisture_", "solar_radiation_"))]
    satellite_cols = [column for column in panel if column.startswith(("ndvi_", "ndwi_", "evi_"))]
    calendar_cols = [column for column in panel if column.startswith("is_") and column not in {"is_eligible_series"}]
    panel["mask_price"] = panel["price_idr_per_kg"].notna().astype("int8")
    panel["mask_weather"] = panel[weather_cols].notna().any(axis=1).astype("int8") if weather_cols else 0
    panel["mask_production"] = panel["production_kg"].notna().astype("int8")
    panel["mask_satellite"] = panel[satellite_cols].notna().any(axis=1).astype("int8") if satellite_cols else 0
    panel["mask_calendar"] = panel[calendar_cols].notna().any(axis=1).astype("int8") if calendar_cols else 0
    graph_cols = [
        column
        for column in (
            "major_road_length_km",
            "ferry_length_km",
            "ferry_terminal_count",
            "port_count",
            "marketplace_count",
            "official_market_count",
            "official_market_daily_equivalent",
        )
        if column in panel
    ]
    panel["mask_graph"] = panel[graph_cols].notna().any(axis=1).astype("int8") if graph_cols else 0
    modality_masks = [
        "mask_price",
        "mask_weather",
        "mask_production",
        "mask_satellite",
        "mask_calendar",
        "mask_graph",
    ]
    panel["available_modality_count"] = panel[modality_masks].sum(axis=1).astype("int8")
    panel["modality_availability_fraction"] = (
        panel["available_modality_count"] / len(modality_masks)
    )
    # Availability is not attribution or confidence. No quality model has been
    # fitted, so evidence quality remains explicitly unavailable.
    panel["evidence_quality_score"] = np.nan
    panel["evidence_status"] = "not_assessed"
    panel["abstention_required"] = (
        panel["mask_price"].eq(0) | ~panel["is_eligible_series"]
    )
    panel["abstention_reason"] = np.select(
        [panel["mask_price"].eq(0), ~panel["is_eligible_series"]],
        ["missing_current_price", "ineligible_price_history"],
        default="none",
    )
    panel["data_version_date"] = pd.Timestamp.utcnow().isoformat()
    panel = panel.sort_values(["province_code", "commodity_code", "market_level", "date"]).reset_index(drop=True)
    eligible = panel[panel["is_eligible_series"]].copy()

    all_outputs = save_frame(panel, output_all_base, save_csv=save_csv, save_parquet=save_parquet)
    eligible_outputs = save_frame(eligible, output_eligible_base, save_csv=save_csv, save_parquet=save_parquet)
    label_columns = [
        "price_t_plus_7",
        "price_t_plus_14",
        "future_max_price_7d",
        "future_return_max_7d",
        "shock_7d",
        "threshold_exceeded",
    ]
    metadata = {
        "unit_of_analysis": "province-commodity-market_level-day",
        "date_range": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "rows_all": len(panel),
        "rows_eligible": len(eligible),
        "series_all": int(panel["series_id"].nunique()),
        "series_eligible": int(eligible["series_id"].nunique()),
        "feature_columns": [
            column for column in panel.columns if column not in label_columns
        ],
        "label_columns": label_columns,
        "missingness_columns": ["mask_price", "mask_weather", "mask_production", "mask_satellite", "mask_calendar", "mask_graph"],
    }
    save_json(metadata, metadata_path)
    return panel, eligible, all_outputs, eligible_outputs
