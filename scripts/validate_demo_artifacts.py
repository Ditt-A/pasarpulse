#!/usr/bin/env python3
"""Validate the generated demo snapshot, geography, and leakage boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.backend.config import SUPPORTED_HORIZONS, THRESHOLDS
from app.backend.rules import classify_warning, projected_change_pct


def validate(root: Path) -> dict[str, int | str]:
    forecast_path = root / "forecasts" / "forecast_snapshot.csv"
    evidence_path = root / "evidence" / "evidence_snapshot.json"
    geography_path = root / "geography" / "indonesia_provinces.geojson"
    manifest_path = root / "manifests" / "forecast_manifest.json"
    for path in [forecast_path, evidence_path, geography_path, manifest_path]:
        if not path.exists():
            raise FileNotFoundError(path)
    frame = pd.read_csv(forecast_path)
    required = {
        "forecast_id", "series_id", "province_code", "forecast_origin", "target_date",
        "horizon_days", "current_price", "predicted_price", "projected_change_pct", "warning_level",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing snapshot fields: {sorted(missing)}")
    if set(frame["horizon_days"].unique()) - set(SUPPORTED_HORIZONS):
        raise ValueError("unsupported horizon found")
    origins = pd.to_datetime(frame["forecast_origin"], errors="raise")
    targets = pd.to_datetime(frame["target_date"], errors="raise")
    if (targets < origins).any() or ((targets - origins).dt.days != frame["horizon_days"]).any():
        raise ValueError("invalid target/origin relationship")
    recomputed = [projected_change_pct(a, b) for a, b in zip(frame.current_price, frame.predicted_price)]
    if max(abs(a - b) for a, b in zip(recomputed, frame.projected_change_pct)) > 1e-6:
        raise ValueError("projected_change_pct is not derived from current and predicted prices")
    expected_warning = [classify_warning(value, THRESHOLDS) for value in recomputed]
    if expected_warning != frame.warning_level.tolist():
        raise ValueError("warning_level does not match the configured product rule")
    geometry = json.loads(geography_path.read_text(encoding="utf-8"))
    if len(geometry.get("features", [])) != 38:
        raise ValueError("geography must contain all 38 provinces")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if len(evidence) != len(frame):
        raise ValueError("evidence rows do not match forecast rows")
    return {"rows": len(frame), "origins": frame.forecast_origin.nunique(), "provinces": 38, "status": "valid"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("demo_data"))
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
