#!/usr/bin/env python3
"""Validate the completed chronological multimodal experiment outputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPECTED_HORIZONS = {7, 14}
EXPECTED_FOLDS = set(range(1, 8))
FORBIDDEN_FEATURES = (
    "price_t_plus_",
    "future_",
    "shock_",
    "target_price",
    "target_logratio",
    "target_scaled_delta",
    "target_delta",
    "threshold_exceeded",
)


def validate(root: Path) -> dict[str, Any]:
    output_root = root / "results/multimodal_ablation"
    required = {
        name: output_root / name
        for name in (
            "fold_metrics.csv",
            "pooled_metrics.csv",
            "oof_predictions.parquet",
            "availability_leakage_audit.json",
            "feature_contract.json",
            "run_manifest.json",
        )
    }
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, observed: Any = None, expected: Any = None) -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if condition else "failed",
                "observed": observed,
                "expected": expected,
            }
        )
        if not condition:
            errors.append(f"{name}: observed={observed!r}, expected={expected!r}")

    for name, path in required.items():
        check(f"required.{name}", path.exists(), str(path), "file exists")
    if errors:
        return finish(checks, errors, root)

    folds = pd.read_csv(required["fold_metrics.csv"])
    pooled = pd.read_csv(required["pooled_metrics.csv"])
    oof = pd.read_parquet(required["oof_predictions.parquet"])
    audit = json.loads(required["availability_leakage_audit.json"].read_text())
    feature_contract = json.loads(required["feature_contract.json"].read_text())

    check("folds.horizons", set(folds["horizon_days"]) == EXPECTED_HORIZONS, sorted(folds["horizon_days"].unique()), sorted(EXPECTED_HORIZONS))
    check("folds.no_duplicate_model_fold", not folds.duplicated(["model", "horizon_days", "fold_id"]).any())
    model_counts = folds.groupby(["horizon_days", "model"])["fold_id"].nunique()
    observed_model_counts = {
        f"{horizon}|{model}": int(count)
        for (horizon, model), count in model_counts.items()
    }
    check("folds.seven_per_model_horizon", bool(model_counts.eq(7).all()), observed_model_counts, 7)
    fold_ids = folds.groupby("horizon_days")["fold_id"].agg(lambda values: set(values))
    check("folds.expected_fold_ids", bool(fold_ids.apply(lambda values: values == EXPECTED_FOLDS).all()), {int(k): sorted(v) for k, v in fold_ids.items()}, sorted(EXPECTED_FOLDS))
    check("folds.rows_scored_positive", bool(pd.to_numeric(folds["rows_scored"], errors="coerce").gt(0).all()))
    metric_columns = ["mae", "rmse", "smape", "mean_error"]
    check("folds.metrics_finite", bool(np.isfinite(folds[metric_columns].to_numpy(dtype=float)).all()))
    check("folds.metrics_nonnegative", bool((folds[["mae", "rmse", "smape"]] >= 0).all().all()))

    check("oof.horizons", set(oof["horizon_days"]) == EXPECTED_HORIZONS, sorted(oof["horizon_days"].unique()), sorted(EXPECTED_HORIZONS))
    check("oof.predictions_finite", bool(np.isfinite(oof["predicted_price"].to_numpy(dtype=float)).all()))
    check("oof.targets_finite", bool(np.isfinite(oof["target_price"].to_numpy(dtype=float)).all()))
    origin = pd.to_datetime(oof["forecast_origin"])
    target_date = pd.to_datetime(oof["target_date"])
    expected_target_date = origin + pd.to_timedelta(oof["horizon_days"], unit="D")
    check("oof.target_date_alignment", bool(target_date.eq(expected_target_date).all()))
    check("oof.origin_precedes_target", bool(origin.lt(target_date).all()))
    key_columns = ["model", "variant", "horizon_days", "fold_id", "series_id", "date"]
    check("oof.no_duplicate_forecasts", not oof.duplicated(key_columns).any())

    expected_rows = folds.set_index(["model", "variant", "horizon_days", "fold_id"])["rows_scored"]
    observed_rows = oof.groupby(["model", "variant", "horizon_days", "fold_id"]).size()
    aligned = observed_rows.reindex(expected_rows.index)
    check("oof.rows_match_fold_metrics", bool(aligned.eq(expected_rows).all()), int((aligned != expected_rows).sum()), 0)

    pooled_counts = pooled.groupby("horizon_days")["folds"].unique().to_dict()
    check("pooled.seven_folds", all(set(values) == {7} for values in pooled_counts.values()), pooled_counts, {7})
    check("pooled.metrics_finite", bool(np.isfinite(pooled[metric_columns].to_numpy(dtype=float)).all()))

    check("availability.audit_passed", audit.get("passed") is True, audit.get("passed"), True)
    check(
        "availability.no_violations",
        all(value.get("violations", 0) == 0 for value in audit.values() if isinstance(value, dict) and "violations" in value),
    )
    forbidden = sorted(
        column
        for columns in feature_contract.values()
        for column in columns
        if column.startswith(FORBIDDEN_FEATURES)
    )
    check("feature_contract.no_realized_labels", not forbidden, forbidden, [])

    return finish(checks, errors, root)


def finish(checks: list[dict[str, Any]], errors: list[str], root: Path) -> dict[str, Any]:
    return {
        "status": "passed" if not errors else "failed",
        "project_root": str(root.resolve()),
        "checks_passed": sum(item["status"] == "passed" for item in checks),
        "checks_failed": sum(item["status"] == "failed" for item in checks),
        "errors": errors,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("results/multimodal_ablation/validation.json"))
    args = parser.parse_args()
    payload = validate(args.project_root.resolve())
    output = args.output if args.output.is_absolute() else args.project_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
