#!/usr/bin/env python3
"""Build a product-safe replay snapshot from a real OOF forecast artifact.

This command is intentionally an artifact transformer, not a training command.
It computes warning fields from current and predicted prices only. The later
realized price is retained under ``target_price`` for an explicit historical
evaluation reveal and is never used in warning or ranking fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.backend.config import REPO_ROOT, SCHEMA_VERSION, SUPPORTED_HORIZONS, THRESHOLDS
from app.backend.rules import classify_warning, projected_change_pct


REQUIRED = {
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
    "model",
}


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


def data_version() -> str:
    source = REPO_ROOT / "data" / "processed" / "price_daily.csv"
    if not source.exists():
        return "PIHPS source version unavailable"
    sample = pd.read_csv(source, usecols=["source_version"], nrows=100)
    values = [str(value) for value in sample["source_version"].dropna().unique()]
    return values[0] if values else "PIHPS source version unavailable"


def load_and_normalize(source: Path, model_name: str) -> pd.DataFrame:
    if source.suffix.lower() in {".parquet", ".pq"}:
        frame = pd.read_parquet(source)
    else:
        frame = pd.read_csv(source)

    missing = sorted(REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"Forecast artifact is missing required columns: {missing}")

    if "actual_price" in frame.columns and "target_price" not in frame.columns:
        frame = frame.rename(columns={"actual_price": "target_price"})
    if model_name:
        frame = frame.loc[frame["model"].astype(str).eq(model_name)].copy()
    if frame.empty:
        raise ValueError(f"No rows found for model {model_name!r}")

    for column in ["forecast_origin", "target_date"]:
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.strftime("%Y-%m-%d")
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="raise").astype(int)
    invalid_horizons = sorted(set(frame["horizon_days"]) - set(SUPPORTED_HORIZONS))
    if invalid_horizons:
        raise ValueError(f"Unsupported horizons: {invalid_horizons}")

    origin = pd.to_datetime(frame["forecast_origin"])
    target = pd.to_datetime(frame["target_date"])
    if (target < origin).any():
        raise ValueError("target_date must not precede forecast_origin")
    if ((target - origin).dt.days != frame["horizon_days"]).any():
        raise ValueError("target_date must equal forecast_origin + horizon_days")

    for column in ["current_price", "predicted_price"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (~frame[column].map(pd.notna)).any() or (~frame[column].map(lambda value: float(value) >= 0)).any():
            raise ValueError(f"{column} contains invalid values")
    if (frame["current_price"] <= 0).any():
        raise ValueError("current_price must be positive")
    if "target_price" in frame.columns:
        frame["target_price"] = pd.to_numeric(frame["target_price"], errors="coerce")
    else:
        frame["target_price"] = pd.Series(float("nan"), index=frame.index, dtype="float64")

    frame["province_code"] = frame["province_code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(2)
    for column in ["series_id", "province_name", "commodity_code", "commodity_name", "market_level", "model"]:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} contains an empty identity")

    # These fields are deliberately derived only from forecast-time values.
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
    frame["model_version"] = "expert_lgb_logratio-final-fit"
    frame["data_version"] = data_version()
    frame["feature_version"] = "157-feature-order"
    frame["actual_available"] = frame.get("target_price", pd.Series(index=frame.index, dtype=float)).notna()
    frame["attribution_available"] = False
    frame["interval_available"] = False
    frame["shock_probability_available"] = False
    frame["propagation_available"] = False
    frame["abstention_required"] = False
    frame["forecast_target_known_at_origin"] = False

    logical_key = ["series_id", "forecast_origin", "horizon_days", "model"]
    if frame.duplicated(logical_key).any():
        duplicates = int(frame.duplicated(logical_key).sum())
        raise ValueError(f"Forecast artifact contains {duplicates} duplicate logical keys")

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
        "abstention_required",
    ]
    if "fold_id" not in frame.columns:
        frame["fold_id"] = pd.NA
    return frame[columns].sort_values(["forecast_origin", "horizon_days", "projected_change_pct"], ascending=[True, True, False])


def build_evidence(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Create availability/freshness records without pretending they are attributions."""

    calendar_path = REPO_ROOT / "data" / "processed" / "calendar_features.csv"
    production_path = REPO_ROOT / "data" / "processed" / "production_annual.csv"
    calendar_dates: set[str] = set()
    production_keys: set[tuple[str, str]] = set()
    if calendar_path.exists():
        calendar_dates = set(pd.read_csv(calendar_path, usecols=["date"])["date"].astype(str))
    if production_path.exists():
        production = pd.read_csv(production_path, usecols=["province_code", "commodity_code"])
        production_keys = set(
            zip(production["province_code"].astype(str).str.zfill(2), production["commodity_code"].astype(str))
        )

    records: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        prefix = str(row.forecast_id)
        origin = str(row.forecast_origin)
        key = (str(row.province_code).zfill(2), str(row.commodity_code))
        items = [
            {
                "evidence_id": f"EV-{prefix}-PRICE",
                "modality": "Price",
                "status": "FRESH" if row.actual_available else "MISSING",
                "available": bool(row.actual_available),
                "observation_date": origin,
                "observation_age_days": 0,
                "source": "PIHPS source snapshot",
                "note": "Observed price at the forecast origin; availability is not attribution.",
                "is_model_attribution": False,
            },
            {
                "evidence_id": f"EV-{prefix}-CALENDAR",
                "modality": "Calendar",
                "status": "AVAILABLE" if origin in calendar_dates else "MISSING",
                "available": origin in calendar_dates,
                "observation_date": origin if origin in calendar_dates else None,
                "observation_age_days": 0 if origin in calendar_dates else None,
                "source": "Official calendar feature snapshot",
                "note": "Calendar context is shown separately from model attribution.",
                "is_model_attribution": False,
            },
            {
                "evidence_id": f"EV-{prefix}-PRODUCTION",
                "modality": "Production",
                "status": "AVAILABLE" if key in production_keys else "MISSING",
                "available": key in production_keys,
                "observation_date": "2023 annual reference" if key in production_keys else None,
                "observation_age_days": None,
                "source": "BPS annual production context",
                "note": "Annual structural context; not a daily supply observation.",
                "is_model_attribution": False,
            },
            {
                "evidence_id": f"EV-{prefix}-WEATHER",
                "modality": "Weather",
                "status": "NOT_IN_ARTIFACT",
                "available": False,
                "observation_date": None,
                "observation_age_days": None,
                "source": "ERA5-Land research route",
                "note": "Weather evidence is not available in this forecast snapshot.",
                "is_model_attribution": False,
            },
            {
                "evidence_id": f"EV-{prefix}-SATELLITE",
                "modality": "Satellite",
                "status": "NOT_IN_ARTIFACT",
                "available": False,
                "observation_date": None,
                "observation_age_days": None,
                "source": "Sentinel-2 research route",
                "note": "Satellite evidence is not available in this forecast snapshot.",
                "is_model_attribution": False,
            },
            {
                "evidence_id": f"EV-{prefix}-PROPAGATION",
                "modality": "Propagation",
                "status": "NOT_IN_ARTIFACT",
                "available": False,
                "observation_date": None,
                "observation_age_days": None,
                "source": "PasarPulse graph artifact",
                "note": "Propagation outputs are not available for this forecast artifact.",
                "is_model_attribution": False,
            },
        ]
        records.append(
            {
                "forecast_id": prefix,
                "evidence_quality_score": None,
                "attribution_available": False,
                "attribution_note": "Model attribution is not available for this snapshot.",
                "abstention_required": False,
                "items": items,
            }
        )
    return records


def build_snapshot(source: Path, output_root: Path, model_name: str) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "forecasts").mkdir(exist_ok=True)
    (output_root / "evidence").mkdir(exist_ok=True)
    (output_root / "geography").mkdir(exist_ok=True)
    (output_root / "manifests").mkdir(exist_ok=True)

    frame = load_and_normalize(source, model_name)
    forecast_path = output_root / "forecasts" / "forecast_snapshot.csv"
    frame.to_csv(forecast_path, index=False, float_format="%.10g")
    evidence_path = output_root / "evidence" / "evidence_snapshot.json"
    evidence_path.write_text(json.dumps(build_evidence(frame), indent=2), encoding="utf-8")

    geography_source = REPO_ROOT / "data" / "reference" / "indonesia_provinces.geojson"
    geography_path = output_root / "geography" / "indonesia_provinces.geojson"
    if geography_source.exists():
        shutil.copyfile(geography_source, geography_path)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "source_model": model_name,
        "rows": int(len(frame)),
        "series": int(frame["series_id"].nunique()),
        "province_codes": sorted(frame["province_code"].unique().tolist()),
        "forecast_origins": sorted(frame["forecast_origin"].unique().tolist()),
        "commodities": sorted(frame["commodity_code"].unique().tolist()),
        "market_levels": sorted(frame["market_level"].unique().tolist()),
        "horizons": sorted(int(value) for value in frame["horizon_days"].unique()),
        "models": sorted(frame["model"].unique().tolist()),
        "model_version": "expert_lgb_logratio-final-fit",
        "data_version": str(frame["data_version"].iloc[0]),
        "feature_version": "157-feature-order",
        "git_revision_at_build": git_short_revision(),
        "warning_rule": {
            "watch": THRESHOLDS.watch,
            "elevated": THRESHOLDS.elevated,
            "high": THRESHOLDS.high,
            "note": "Product warning thresholds, not model probabilities or regulatory thresholds.",
        },
        "forecast_sha256": sha256_file(forecast_path),
        "evidence_path": str(evidence_path),
        "geography_path": str(geography_path),
        "actual_values": "target_price is evaluation-only and excluded from warnings, ranking, and Copilot context.",
    }
    manifest_path = output_root / "manifests" / "forecast_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "model_runs" / "proposed_model_run" / "results" / "oof_predictions.csv",
    )
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "demo_data")
    parser.add_argument("--model", default="expert_lgb_logratio")
    args = parser.parse_args()
    manifest = build_snapshot(args.source.resolve(), args.output_root.resolve(), args.model)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
