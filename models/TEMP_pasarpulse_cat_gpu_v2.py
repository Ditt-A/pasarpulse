from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize


MODEL_NAME = "CAT_GPU_V2_adaptive_ensemble"
EXPERT_NAMES = [
    "CAT_GPU_V2_delta",
    "CAT_GPU_V2_logratio",
    "CAT_GPU_V2_level",
    "CAT_GPU_V2_last_price",
    "CAT_GPU_V2_momentum",
]


def load_core(path: Path):
    spec = importlib.util.spec_from_file_location("pasarpulse_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def metric_row(y, prediction):
    y = np.asarray(y, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    denominator = np.abs(y) + np.abs(prediction)
    return {
        "mae_idr_per_kg": float(np.mean(np.abs(y - prediction))),
        "rmse_idr_per_kg": float(np.sqrt(np.mean((y - prediction) ** 2))),
        "smape_percent": float(
            np.mean(
                2.0
                * np.abs(y - prediction)
                / np.where(denominator == 0.0, 1.0, denominator)
            )
            * 100.0
        ),
        "mean_error_idr_per_kg": float(np.mean(prediction - y)),
    }


def optimize_weights(y, predictions):
    names = list(predictions)
    matrix = np.column_stack([predictions[name] for name in names])

    def objective(weights):
        return float(np.mean(np.abs(y - matrix @ weights)))

    constraints = ({"type": "eq", "fun": lambda weights: weights.sum() - 1.0},)
    bounds = [(0.0, 1.0)] * len(names)
    starts = [np.ones(len(names), dtype=float) / len(names)]
    starts.extend(np.eye(len(names), dtype=float))
    best = None
    for start in starts:
        result = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 300, "ftol": 1e-8},
        )
        if result.success and (best is None or result.fun < best.fun):
            best = result
    if best is None:
        weights = np.ones(len(names), dtype=float) / len(names)
        score = objective(weights)
    else:
        weights = np.clip(best.x, 0.0, 1.0)
        weights /= weights.sum()
        score = float(best.fun)
    return dict(zip(names, weights)), score


def prepare_frames(train, test, features, categorical_features):
    train_frame = train[features].copy()
    test_frame = test[features].copy()
    categorical = [
        column for column in categorical_features if column in features
    ]
    for column in categorical:
        train_frame[column] = train_frame[column].fillna("missing").astype(str)
        test_frame[column] = test_frame[column].fillna("missing").astype(str)
    numeric = [column for column in features if column not in categorical]
    for column in numeric:
        train_frame[column] = pd.to_numeric(
            train_frame[column], errors="coerce"
        ).astype("float32")
        test_frame[column] = pd.to_numeric(
            test_frame[column], errors="coerce"
        ).astype("float32")
    return train_frame, test_frame, categorical


def fit_gpu_model(
    train,
    test,
    features,
    categorical_features,
    target,
    sample_weight,
    seed,
):
    from catboost import CatBoostRegressor

    train_frame, test_frame, categorical = prepare_frames(
        train, test, features, categorical_features
    )
    model = CatBoostRegressor(
        loss_function="RMSE",
        eval_metric="RMSE",
        iterations=400,
        depth=8,
        learning_rate=0.06,
        l2_leaf_reg=8.0,
        random_seed=seed,
        random_strength=0.35,
        bootstrap_type="Bernoulli",
        subsample=0.86,
        border_count=128,
        max_ctr_complexity=2,
        task_type="GPU",
        devices="0",
        gpu_ram_part=0.78,
        allow_writing_files=False,
        verbose=100,
    )
    model.fit(
        train_frame,
        train[target].astype("float32"),
        cat_features=categorical,
        sample_weight=np.asarray(sample_weight, dtype="float32"),
    )
    return model.predict(test_frame), model


def read_existing(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def append_csv(frame: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False)


def completed_folds(output_directory: Path):
    path = output_directory / "fold_metrics.csv"
    existing = read_existing(path)
    if existing.empty:
        return set()
    rows = existing[existing["model"] == MODEL_NAME]
    return {
        (int(row.horizon_days), int(row.fold_id))
        for row in rows.itertuples(index=False)
    }


def historical_experts(output_directory: Path, horizon: int):
    path = output_directory / "oof_predictions.csv"
    existing = read_existing(path)
    if existing.empty:
        return None, None
    existing = existing[existing["horizon_days"] == horizon].copy()
    if existing.empty:
        return None, None
    keys = [
        "series_id",
        "forecast_origin",
        "target_date",
        "fold_id",
        "actual_price",
    ]
    pivot = existing[existing["model"].isin(EXPERT_NAMES)].pivot_table(
        index=keys,
        columns="model",
        values="predicted_price",
        aggfunc="first",
    )
    if not set(EXPERT_NAMES).issubset(pivot.columns):
        return None, None
    y = pivot.index.get_level_values("actual_price").to_numpy(dtype=float)
    predictions = {
        name: pivot[name].to_numpy(dtype=float) for name in EXPERT_NAMES
    }
    return y, predictions


def write_partial_summary(output_directory: Path):
    predictions = read_existing(output_directory / "oof_predictions.csv")
    if predictions.empty:
        return
    pooled_rows = []
    for (model, horizon), group in predictions.groupby(
        ["model", "horizon_days"], observed=True
    ):
        pooled_rows.append(
            {
                "model": model,
                "horizon_days": int(horizon),
                "rows_scored": len(group),
                "series_scored": group["series_id"].nunique(),
                "folds_scored": group["fold_id"].nunique(),
                **metric_row(group["actual_price"], group["predicted_price"]),
            }
        )
    pooled = pd.DataFrame(pooled_rows).sort_values(
        ["horizon_days", "mae_idr_per_kg"]
    )
    pooled.to_csv(output_directory / "pooled_metrics_partial.csv", index=False)
    print("=== GPU V2 partial pooled metrics ===", flush=True)
    print(pooled.to_string(index=False), flush=True)


def run(core, panel: pd.DataFrame, output_directory: Path):
    output_directory.mkdir(parents=True, exist_ok=True)
    complete = completed_folds(output_directory)
    feature_request = list(
        dict.fromkeys(
            core.PRICE_BASE
            + core.CALENDAR
            + core.GRAPH
            + core.CATEGORICAL
            + [
                "target_dow",
                "target_month",
                "target_doy_sin",
                "target_doy_cos",
            ]
        )
    )

    for horizon in core.HORIZONS:
        supervised = core.create_supervised(panel, horizon)
        valid = (
            (supervised["observed"] == 1)
            & (supervised["target_observed"] == 1)
            & supervised["target_price"].notna()
            & supervised["price_filled"].notna()
        )
        supervised = supervised.loc[valid].copy()

        for fold_id, origin in enumerate(core.ORIGINS, 1):
            if (horizon, fold_id) in complete:
                print(
                    f"GPU V2 skipping completed h={horizon} fold={fold_id}",
                    flush=True,
                )
                continue

            print(
                f"GPU V2 h={horizon} fold={fold_id}/{len(core.ORIGINS)} "
                f"origin={origin.date()}",
                flush=True,
            )
            train = supervised[
                (supervised["date"] < origin)
                & (
                    (supervised["date"] + pd.Timedelta(days=horizon))
                    <= origin
                )
            ].copy()
            test = supervised[supervised["date"] == origin].copy()
            counts = train.groupby("series_id", observed=True).size()
            eligible = counts[counts >= 240].index
            train = train[train["series_id"].isin(eligible)].copy()
            test = test[test["series_id"].isin(eligible)].copy()
            if train.empty or test.empty:
                print("GPU V2 empty fold; skipping", flush=True)
                continue

            features = [feature for feature in feature_request if feature in train]
            sample_weight = core.recent_weights(train["date"], origin)
            delta, delta_model = fit_gpu_model(
                train,
                test,
                features,
                core.CATEGORICAL,
                "target_delta",
                sample_weight,
                core.SEED + fold_id + horizon,
            )
            logratio, logratio_model = fit_gpu_model(
                train,
                test,
                features,
                core.CATEGORICAL,
                "target_logratio",
                sample_weight,
                core.SEED + 100 + fold_id + horizon,
            )
            level, level_model = fit_gpu_model(
                train,
                test,
                features,
                core.CATEGORICAL,
                "target_price",
                sample_weight,
                core.SEED + 200 + fold_id + horizon,
            )

            current = test["price_filled"].to_numpy(dtype=float)
            lag = test[f"price_lag_{horizon}"].to_numpy(dtype=float)
            lag = np.where(np.isfinite(lag), lag, current)
            experts = {
                "CAT_GPU_V2_delta": np.clip(
                    current + delta, 1000.0, 500000.0
                ),
                "CAT_GPU_V2_logratio": np.clip(
                    current * np.exp(np.clip(logratio, -1.2, 1.2)),
                    1000.0,
                    500000.0,
                ),
                "CAT_GPU_V2_level": np.clip(level, 1000.0, 500000.0),
                "CAT_GPU_V2_last_price": current,
                "CAT_GPU_V2_momentum": np.clip(
                    current + 0.5 * (current - lag), 1000.0, 500000.0
                ),
            }

            historical_y, historical_predictions = historical_experts(
                output_directory, horizon
            )
            if historical_y is None:
                weights = {
                    "CAT_GPU_V2_delta": 0.40,
                    "CAT_GPU_V2_logratio": 0.25,
                    "CAT_GPU_V2_level": 0.15,
                    "CAT_GPU_V2_last_price": 0.20,
                    "CAT_GPU_V2_momentum": 0.00,
                }
                historical_mae = np.nan
            else:
                weights, historical_mae = optimize_weights(
                    historical_y, historical_predictions
                )

            ensemble = sum(weights[name] * experts[name] for name in weights)
            maximum_change = np.maximum(9000.0, 0.40 * current)
            ensemble = np.clip(
                ensemble,
                current - maximum_change,
                current + maximum_change,
            )
            y = test["target_price"].to_numpy(dtype=float)

            fold_rows = []
            output_predictions = {**experts, MODEL_NAME: ensemble}
            for model, prediction in output_predictions.items():
                fold_rows.append(
                    {
                        "model": model,
                        "horizon_days": horizon,
                        "fold_id": fold_id,
                        "forecast_origin": origin.date().isoformat(),
                        "rows_scored": len(test),
                        "historical_blend_mae": historical_mae,
                        **metric_row(y, prediction),
                    }
                )
            append_csv(
                pd.DataFrame(fold_rows), output_directory / "fold_metrics.csv"
            )

            base = test[
                [
                    "series_id",
                    "province_code",
                    "province_name",
                    "commodity_code",
                    "commodity_name",
                    "market_level",
                    "date",
                    "target_price",
                    "price_filled",
                ]
            ].copy()
            base = base.rename(
                columns={
                    "date": "forecast_origin",
                    "target_price": "actual_price",
                    "price_filled": "current_price",
                }
            )
            base["target_date"] = base["forecast_origin"] + pd.Timedelta(
                days=horizon
            )
            base["horizon_days"] = horizon
            base["fold_id"] = fold_id
            prediction_frames = []
            for model, prediction in output_predictions.items():
                part = base.copy()
                part["model"] = model
                part["predicted_price"] = prediction
                part["absolute_error"] = np.abs(
                    part["actual_price"] - part["predicted_price"]
                )
                prediction_frames.append(part)
            append_csv(
                pd.concat(prediction_frames, ignore_index=True),
                output_directory / "oof_predictions.csv",
            )

            append_csv(
                pd.DataFrame(
                    [
                        {
                            "horizon_days": horizon,
                            "fold_id": fold_id,
                            "forecast_origin": origin.date().isoformat(),
                            "historical_blend_mae": historical_mae,
                            "weights": json.dumps(weights, sort_keys=True),
                        }
                    ]
                ),
                output_directory / "adaptive_weights.csv",
            )

            importance_rows = []
            for component, model in [
                ("delta", delta_model),
                ("logratio", logratio_model),
                ("level", level_model),
            ]:
                for feature, importance in zip(
                    features, model.get_feature_importance()
                ):
                    importance_rows.append(
                        {
                            "model_component": component,
                            "horizon_days": horizon,
                            "fold_id": fold_id,
                            "feature": feature,
                            "importance": float(importance),
                        }
                    )
            append_csv(
                pd.DataFrame(importance_rows),
                output_directory / "feature_importance.csv",
            )
            write_partial_summary(output_directory)

    predictions = read_existing(output_directory / "oof_predictions.csv")
    pooled_rows = []
    for (model, horizon), group in predictions.groupby(
        ["model", "horizon_days"], observed=True
    ):
        pooled_rows.append(
            {
                "model": model,
                "horizon_days": int(horizon),
                "rows_scored": len(group),
                "series_scored": group["series_id"].nunique(),
                "folds_scored": group["fold_id"].nunique(),
                **metric_row(group["actual_price"], group["predicted_price"]),
            }
        )
    pooled = pd.DataFrame(pooled_rows).sort_values(
        ["horizon_days", "mae_idr_per_kg"]
    )
    pooled.to_csv(output_directory / "pooled_metrics.csv", index=False)
    print("=== GPU V2 final pooled metrics ===", flush=True)
    print(pooled.to_string(index=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    core = load_core(args.core)
    panel = pd.read_parquet(args.panel)
    args.outdir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run(core, panel, args.outdir)
    (args.outdir / "runtime_seconds.txt").write_text(str(time.time() - started))
    Path(args.outdir.parent / "DONE").write_text("success\n")


if __name__ == "__main__":
    main()
