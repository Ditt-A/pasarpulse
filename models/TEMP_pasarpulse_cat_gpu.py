from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def load_core(path: Path):
    spec = importlib.util.spec_from_file_location("pasarpulse_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def metrics(y, pred):
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    denom = np.abs(y) + np.abs(pred)
    return {
        "mae_idr_per_kg": float(np.mean(np.abs(y - pred))),
        "rmse_idr_per_kg": float(np.sqrt(np.mean((y - pred) ** 2))),
        "smape_percent": float(
            np.mean(2.0 * np.abs(y - pred) / np.where(denom == 0, 1.0, denom))
            * 100.0
        ),
        "mean_error_idr_per_kg": float(np.mean(pred - y)),
    }


def optimize_weights(y, predictions):
    names = list(predictions)
    matrix = np.column_stack([np.asarray(predictions[name], dtype=float) for name in names])

    def objective(weights):
        return float(np.mean(np.abs(y - matrix @ weights)))

    constraints = ({"type": "eq", "fun": lambda weights: np.sum(weights) - 1.0},)
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


def prepare_frames(train, test, features, categorical):
    train_frame = train[features].copy()
    test_frame = test[features].copy()
    cats = [column for column in categorical if column in features]
    for column in cats:
        train_frame[column] = train_frame[column].fillna("missing").astype(str)
        test_frame[column] = test_frame[column].fillna("missing").astype(str)
    return train_frame, test_frame, cats


def fit_catboost_gpu(train, test, features, categorical, target, sample_weight, seed):
    from catboost import CatBoostError, CatBoostRegressor

    train_frame, test_frame, cats = prepare_frames(
        train, test, features, categorical
    )
    common = dict(
        iterations=650,
        depth=8,
        learning_rate=0.045,
        l2_leaf_reg=6.0,
        random_seed=seed,
        random_strength=0.25,
        bootstrap_type="Bernoulli",
        subsample=0.88,
        eval_metric="MAE",
        task_type="GPU",
        devices="0",
        gpu_ram_part=0.82,
        allow_writing_files=False,
        verbose=100,
    )
    try:
        model = CatBoostRegressor(loss_function="MAE", **common)
        model.fit(
            train_frame,
            train[target],
            cat_features=cats,
            sample_weight=sample_weight,
        )
        objective = "MAE"
    except CatBoostError as exc:
        print(
            f"GPU MAE objective unavailable for {target}; falling back to RMSE: {exc}",
            flush=True,
        )
        model = CatBoostRegressor(loss_function="RMSE", **common)
        model.fit(
            train_frame,
            train[target],
            cat_features=cats,
            sample_weight=sample_weight,
        )
        objective = "RMSE"
    return model.predict(test_frame), model, objective


def run(core, panel, output_directory: Path):
    output_directory.mkdir(parents=True, exist_ok=True)
    feature_request = (
        core.PRICE_BASE
        + core.CALENDAR
        + core.GRAPH
        + core.CATEGORICAL
        + ["target_dow", "target_month", "target_doy_sin", "target_doy_cos"]
    )
    fold_rows = []
    prediction_rows = []
    weight_rows = []
    feature_rows = []

    for horizon in core.HORIZONS:
        supervised = core.create_supervised(panel, horizon)
        valid = (
            (supervised["observed"] == 1)
            & (supervised["target_observed"] == 1)
            & supervised["target_price"].notna()
            & supervised["price_filled"].notna()
        )
        supervised = supervised.loc[valid].copy()
        prior_actual = []
        prior_experts = {
            "gpu_delta": [],
            "gpu_logratio": [],
            "gpu_level": [],
            "last_price": [],
            "momentum": [],
        }

        for fold_id, origin in enumerate(core.ORIGINS, 1):
            print(
                f"GPU h={horizon} fold={fold_id}/{len(core.ORIGINS)} "
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
                print("Skipping empty GPU fold", flush=True)
                continue

            features = [feature for feature in feature_request if feature in train.columns]
            sample_weight = core.recent_weights(train["date"], origin)
            delta, delta_model, delta_loss = fit_catboost_gpu(
                train,
                test,
                features,
                core.CATEGORICAL,
                "target_delta",
                sample_weight,
                core.SEED + fold_id + horizon,
            )
            logratio, logratio_model, logratio_loss = fit_catboost_gpu(
                train,
                test,
                features,
                core.CATEGORICAL,
                "target_logratio",
                sample_weight,
                core.SEED + 100 + fold_id + horizon,
            )
            level, level_model, level_loss = fit_catboost_gpu(
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
                "gpu_delta": np.clip(current + delta, 1000.0, 500000.0),
                "gpu_logratio": np.clip(
                    current * np.exp(np.clip(logratio, -1.2, 1.2)),
                    1000.0,
                    500000.0,
                ),
                "gpu_level": np.clip(level, 1000.0, 500000.0),
                "last_price": current,
                "momentum": np.clip(
                    current + 0.5 * (current - lag), 1000.0, 500000.0
                ),
            }

            if prior_actual:
                previous_y = np.concatenate(prior_actual)
                previous_predictions = {
                    name: np.concatenate(parts)
                    for name, parts in prior_experts.items()
                }
                weights, historical_mae = optimize_weights(
                    previous_y, previous_predictions
                )
            else:
                weights = {
                    "gpu_delta": 0.40,
                    "gpu_logratio": 0.25,
                    "gpu_level": 0.15,
                    "last_price": 0.20,
                    "momentum": 0.00,
                }
                historical_mae = np.nan

            adaptive = sum(weights[name] * experts[name] for name in weights)
            maximum_change = np.maximum(9000.0, 0.40 * current)
            adaptive = np.clip(
                adaptive,
                current - maximum_change,
                current + maximum_change,
            )

            y = test["target_price"].to_numpy(dtype=float)
            prior_actual.append(y)
            for name, prediction in experts.items():
                prior_experts[name].append(prediction)

            output_predictions = {
                **{f"CAT_GPU_{name}": prediction for name, prediction in experts.items()},
                "CAT_GPU_adaptive_ensemble": adaptive,
            }
            for model_name, prediction in output_predictions.items():
                fold_rows.append(
                    {
                        "model": model_name,
                        "horizon_days": horizon,
                        "fold_id": fold_id,
                        "forecast_origin": origin.date().isoformat(),
                        "rows_scored": len(test),
                        "historical_blend_mae": historical_mae,
                        **metrics(y, prediction),
                    }
                )

            weight_rows.append(
                {
                    "horizon_days": horizon,
                    "fold_id": fold_id,
                    "forecast_origin": origin.date().isoformat(),
                    "historical_blend_mae": historical_mae,
                    "weights": json.dumps(weights, sort_keys=True),
                    "delta_loss": delta_loss,
                    "logratio_loss": logratio_loss,
                    "level_loss": level_loss,
                }
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
            for model_name, prediction in output_predictions.items():
                part = base.copy()
                part["model"] = model_name
                part["predicted_price"] = prediction
                part["absolute_error"] = np.abs(
                    part["actual_price"] - part["predicted_price"]
                )
                prediction_rows.append(part)

            for model_label, model in [
                ("delta", delta_model),
                ("logratio", logratio_model),
                ("level", level_model),
            ]:
                importances = model.get_feature_importance()
                for feature, importance in zip(features, importances):
                    feature_rows.append(
                        {
                            "model_component": model_label,
                            "horizon_days": horizon,
                            "fold_id": fold_id,
                            "feature": feature,
                            "importance": float(importance),
                        }
                    )

    predictions = pd.concat(prediction_rows, ignore_index=True)
    folds = pd.DataFrame(fold_rows)
    pooled_rows = []
    for (model_name, horizon), group in predictions.groupby(
        ["model", "horizon_days"], observed=True
    ):
        pooled_rows.append(
            {
                "model": model_name,
                "horizon_days": horizon,
                "rows_scored": len(group),
                "series_scored": group["series_id"].nunique(),
                "folds_scored": group["fold_id"].nunique(),
                **metrics(group["actual_price"], group["predicted_price"]),
            }
        )
    pooled = pd.DataFrame(pooled_rows).sort_values(
        ["horizon_days", "mae_idr_per_kg"]
    )
    predictions.to_csv(output_directory / "oof_predictions.csv", index=False)
    folds.to_csv(output_directory / "fold_metrics.csv", index=False)
    pooled.to_csv(output_directory / "pooled_metrics.csv", index=False)
    pd.DataFrame(weight_rows).to_csv(
        output_directory / "adaptive_weights.csv", index=False
    )
    pd.DataFrame(feature_rows).to_csv(
        output_directory / "feature_importance.csv", index=False
    )
    print("=== GPU pooled metrics ===", flush=True)
    print(pooled.to_string(index=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    core = load_core(args.core)
    panel = pd.read_parquet(args.panel)
    started = time.time()
    run(core, panel, args.outdir)
    (args.outdir / "runtime_seconds.txt").write_text(
        str(time.time() - started)
    )


if __name__ == "__main__":
    main()
