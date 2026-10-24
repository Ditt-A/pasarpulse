#!/usr/bin/env python3
"""Create native LightGBM top-five explanations for every deployed forecast.

The deployment snapshot contains selected out-of-fold forecasts from the
multimodal ablation run.  That run did not serialize its fold models, so this
utility recreates only the two selected LightGBM specifications with the same
chronological folds and parameters.  It refuses to publish an output unless
the recreated prices agree with the snapshot for every forecast.

The output deliberately contains no realized target values.  Contributions are
LightGBM ``pred_contrib`` values in log-ratio space, and should be described as
prediction drivers rather than causal or rupiah effects.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


SELECTED_VARIANTS = {
    7: "ALL_MODALITIES_DYNAMIC_GRAPH",
    14: "PRICE_CALENDAR",
}
FORBIDDEN_FEATURE_NAMES = {
    "target_price",
    "target_logratio",
    "target_scaled_delta",
    "target_delta",
    "threshold_exceeded",
}
IDENTITY_COLUMNS = [
    "series_id",
    "province_code",
    "commodity_code",
    "market_level",
    "forecast_origin",
    "target_date",
    "horizon_days",
    "model",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_experiment(project_root: Path):
    source = project_root / "experiments" / "pasarpulse_multimodal_ablation.py"
    if not source.exists():
        raise FileNotFoundError(f"Experiment source is missing: {source}")
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    spec = importlib.util.spec_from_file_location("dashboard_xai_experiment", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fit_with_contributions(
    experiment: Any,
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Mirror ``fit_lgbm`` exactly, retaining the native contribution matrix."""
    train_x, test_x, categorical = experiment.prepare_matrix(train, test, features)
    model = LGBMRegressor(
        objective="l1",
        n_estimators=520,
        learning_rate=0.03,
        num_leaves=47,
        min_child_samples=55,
        max_bin=127,
        reg_alpha=0.05,
        reg_lambda=2.5,
        colsample_bytree=0.90,
        random_state=seed,
        n_jobs=max(1, min(24, os.cpu_count() or 2)),
        verbosity=-1,
    )
    model.fit(train_x, train["target_logratio"], categorical_feature=categorical)
    raw = model.predict(test_x)
    prices = experiment.core.reconstruct_prediction(
        test["current_price"], raw, "target_logratio"
    )
    contributions = model.booster_.predict(test_x, pred_contrib=True)
    expected_columns = len(test_x.columns) + 1
    if contributions.shape != (len(test_x), expected_columns):
        raise RuntimeError(
            "Unexpected LightGBM contribution shape: "
            f"{contributions.shape}, expected {(len(test_x), expected_columns)}"
        )
    return np.asarray(prices, dtype=float), contributions, test_x


def json_value(value: object) -> str | float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def build_identity(
    test: pd.DataFrame,
    prices: np.ndarray,
    *,
    horizon: int,
    origin: pd.Timestamp,
    model: str,
) -> pd.DataFrame:
    part = test[["series_id", "province_code", "commodity_code", "market_level"]].copy()
    part["province_code"] = part["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    part["commodity_code"] = part["commodity_code"].astype(str)
    part["market_level"] = part["market_level"].astype(str)
    part["forecast_origin"] = origin.date().isoformat()
    part["target_date"] = (origin + pd.Timedelta(days=horizon)).date().isoformat()
    part["horizon_days"] = horizon
    part["model"] = model
    part["recreated_prediction"] = prices
    return part


def run(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    project_root = args.project_root.resolve()
    snapshot_path = args.snapshot.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    experiment = load_experiment(project_root)

    snapshot = pd.read_csv(snapshot_path)
    snapshot["forecast_origin"] = pd.to_datetime(snapshot["forecast_origin"]).dt.date.astype(str)
    snapshot["target_date"] = pd.to_datetime(snapshot["target_date"]).dt.date.astype(str)
    snapshot["province_code"] = snapshot["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    snapshot["commodity_code"] = snapshot["commodity_code"].astype(str)
    snapshot["market_level"] = snapshot["market_level"].astype(str)
    snapshot["horizon_days"] = pd.to_numeric(snapshot["horizon_days"], errors="raise").astype(int)

    expected_model = snapshot["horizon_days"].map(
        {horizon: f"LGBM_LOGRATIO__{variant}" for horizon, variant in SELECTED_VARIANTS.items()}
    )
    selected = snapshot.loc[snapshot["model"].eq(expected_model)].copy()
    if len(selected) != len(snapshot):
        unexpected = snapshot.loc[~snapshot.index.isin(selected.index), ["forecast_id", "model", "horizon_days"]]
        raise RuntimeError(f"Snapshot has non-selected dashboard models: {unexpected.head().to_dict('records')}")
    if selected["forecast_id"].duplicated().any() or selected.duplicated(IDENTITY_COLUMNS).any():
        raise RuntimeError("Dashboard snapshot has duplicate forecast identities.")

    panel_path = project_root / "data" / "ready" / "model_dataset_eligible.parquet"
    static_graph_path = project_root / "data" / "processed" / "province_graph_static.parquet"
    dynamic_graph_path = project_root / "data" / "processed" / "province_graph_dynamic.parquet"
    for path in (panel_path, static_graph_path, dynamic_graph_path):
        if not path.exists():
            raise FileNotFoundError(f"Required training input is missing: {path}")
    panel = pd.read_parquet(panel_path)
    static_graph = pd.read_parquet(static_graph_path)
    dynamic_graph = pd.read_parquet(dynamic_graph_path)
    frame = experiment.engineer_panel(panel, static_graph, dynamic_graph, args.static_graph_effective_date)
    experiment.validate_availability(frame)

    audit_rows: list[dict[str, object]] = []
    contribution_parts: list[pd.DataFrame] = []
    recreated_parts: list[pd.DataFrame] = []
    origins = pd.to_datetime(sorted(selected["forecast_origin"].unique()))
    for horizon, variant in SELECTED_VARIANTS.items():
        model_name = f"LGBM_LOGRATIO__{variant}"
        horizon_frame = experiment.supervised_frame(frame, horizon)
        for fold_id, origin in enumerate(origins, start=1):
            train, test = experiment.make_split_from_supervised(
                horizon_frame, horizon, origin, minimum_history=args.minimum_history
            )
            if train.empty or test.empty:
                raise RuntimeError(f"Empty fold h={horizon} origin={origin.date()}")
            features = experiment.requested_features(horizon_frame, variant)
            prices, contributions, test_x = fit_with_contributions(
                experiment, train, test, features, experiment.SEED + horizon * 100 + fold_id
            )
            recreated = build_identity(
                test, prices, horizon=horizon, origin=origin, model=model_name
            )
            recreated_parts.append(recreated)
            expected_fold = selected.loc[
                (selected["horizon_days"] == horizon)
                & (selected["forecast_origin"] == origin.date().isoformat())
            ]
            merged = expected_fold.merge(
                recreated,
                on=IDENTITY_COLUMNS,
                how="outer",
                validate="one_to_one",
                indicator=True,
            )
            if not merged["_merge"].eq("both").all():
                raise RuntimeError(
                    f"Identity mismatch h={horizon} origin={origin.date()}: "
                    f"{merged['_merge'].value_counts().to_dict()}"
                )
            error = np.abs(
                pd.to_numeric(merged["predicted_price"], errors="raise").to_numpy()
                - pd.to_numeric(merged["recreated_prediction"], errors="raise").to_numpy()
            )
            max_error = float(error.max(initial=0.0))
            audit_rows.append(
                {
                    "horizon_days": horizon,
                    "forecast_origin": origin.date().isoformat(),
                    "model": model_name,
                    "rows": len(merged),
                    "max_abs_prediction_error": max_error,
                    "mean_abs_prediction_error": float(error.mean()),
                }
            )
            if max_error > args.max_prediction_error:
                raise RuntimeError(
                    f"Recreated model does not match deployed snapshot h={horizon} "
                    f"origin={origin.date()}: max error {max_error:.10f} > {args.max_prediction_error}"
                )

            feature_names = list(test_x.columns)
            rows: list[dict[str, object]] = []
            for row_index, (_, test_row) in enumerate(test.iterrows()):
                identity = recreated.iloc[row_index][IDENTITY_COLUMNS]
                forecast = selected.merge(
                    pd.DataFrame([identity]), on=IDENTITY_COLUMNS, how="inner", validate="one_to_one"
                ).iloc[0]
                values = test_x.iloc[row_index]
                order = np.argsort(-np.abs(contributions[row_index, :-1]), kind="stable")[:5]
                for rank, feature_index in enumerate(order, start=1):
                    rows.append(
                        {
                            "forecast_id": forecast["forecast_id"],
                            "rank": rank,
                            "feature": feature_names[feature_index],
                            "feature_value": json_value(values.iloc[feature_index]),
                            "contribution_logratio": float(contributions[row_index, feature_index]),
                            "base_value_logratio": float(contributions[row_index, -1]),
                            "model": model_name,
                            "horizon_days": horizon,
                            "forecast_origin": origin.date().isoformat(),
                        }
                    )
            contribution_parts.append(pd.DataFrame(rows))
            print(
                f"completed h={horizon} fold={fold_id} origin={origin.date()} "
                f"rows={len(test):,} max_abs_error={max_error:.10f}", flush=True
            )

    top5 = pd.concat(contribution_parts, ignore_index=True).sort_values(["forecast_id", "rank"])
    expected_rows = len(selected) * 5
    if len(top5) != expected_rows or top5.groupby("forecast_id").size().ne(5).any():
        raise RuntimeError(f"Incomplete XAI output: expected {expected_rows} rows, got {len(top5)}")
    forbidden = top5["feature"].isin(FORBIDDEN_FEATURE_NAMES) | top5["feature"].str.startswith("future_")
    if forbidden.any():
        raise RuntimeError("XAI output includes prohibited target or future feature names.")
    audit = pd.DataFrame(audit_rows).sort_values(["horizon_days", "forecast_origin"])
    top5.to_csv(output / "forecast_top5.csv", index=False)
    audit.to_csv(output / "prediction_reproduction_audit.csv", index=False)
    manifest = {
        "schema_version": 1,
        "method": "native_lightgbm_pred_contrib",
        "contribution_scale": "log_ratio",
        "meaning": "Prediction drivers only; not causal effects and not rupiah contributions.",
        "snapshot": str(snapshot_path),
        "snapshot_sha256": sha256(snapshot_path),
        "project_root": str(project_root),
        "input_sha256": {str(path.relative_to(project_root)): sha256(path) for path in (panel_path, static_graph_path, dynamic_graph_path)},
        "selected_models": {str(horizon): f"LGBM_LOGRATIO__{variant}" for horizon, variant in SELECTED_VARIANTS.items()},
        "forecast_count": int(len(selected)),
        "contribution_count": int(len(top5)),
        "max_prediction_error": float(audit["max_abs_prediction_error"].max()),
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--static-graph-effective-date", default="2026-01-01")
    parser.add_argument("--minimum-history", type=int, default=240)
    # Snapshot prices are serialized to eight decimal places; 0.0001 IDR is
    # still far below that display precision while rejecting a different model.
    parser.add_argument("--max-prediction-error", type=float, default=1e-4)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
