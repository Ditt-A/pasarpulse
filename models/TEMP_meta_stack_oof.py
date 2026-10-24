from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor


RESULT_DIR = Path("proposed_gpu_v2/results")
RAW_PATH = RESULT_DIR / "oof_predictions.csv"
POST_PATH = RESULT_DIR / "postprocessed_predictions.csv"
EXPERTS = [
    "CAT_GPU_V2_delta",
    "CAT_GPU_V2_logratio",
    "CAT_GPU_V2_level",
    "CAT_GPU_V2_last_price",
]
CATEGORICAL = ["province_code", "commodity_code", "market_level"]


def mae(y, prediction):
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(prediction, float))))


def make_panel():
    raw = pd.read_csv(RAW_PATH, parse_dates=["forecast_origin", "target_date"])
    keys = [
        "series_id",
        "province_code",
        "province_name",
        "commodity_code",
        "commodity_name",
        "market_level",
        "forecast_origin",
        "target_date",
        "horizon_days",
        "fold_id",
        "actual_price",
        "current_price",
    ]
    panel = (
        raw[raw["model"].isin(EXPERTS)]
        .pivot_table(
            index=keys,
            columns="model",
            values="predicted_price",
            aggfunc="first",
        )
        .reset_index()
    )
    if POST_PATH.exists():
        post = pd.read_csv(POST_PATH, parse_dates=["forecast_origin", "target_date"])
        grid = post[
            post["model"] == "CHRONOLOGICAL_COMMODITY_MARKET_GRID_BLEND"
        ][keys[:-2] + ["actual_price", "predicted_price"]].copy()
        grid = grid.rename(columns={"predicted_price": "hierarchical_grid"})
        merge_keys = keys[:-2] + ["actual_price"]
        panel = panel.merge(grid, on=merge_keys, how="left")
    if "hierarchical_grid" not in panel:
        panel["hierarchical_grid"] = panel["CAT_GPU_V2_logratio"]
    panel["hierarchical_grid"] = panel["hierarchical_grid"].fillna(
        panel["CAT_GPU_V2_logratio"]
    )
    for column in CATEGORICAL:
        panel[column] = panel[column].fillna("missing").astype(str)
    panel["month"] = panel["forecast_origin"].dt.month.astype(str)
    panel["dow"] = panel["forecast_origin"].dt.dayofweek.astype(str)
    panel["doy_sin"] = np.sin(
        2 * np.pi * panel["forecast_origin"].dt.dayofyear / 366.0
    )
    panel["doy_cos"] = np.cos(
        2 * np.pi * panel["forecast_origin"].dt.dayofyear / 366.0
    )
    expert_columns = EXPERTS + ["hierarchical_grid"]
    for column in expert_columns:
        panel[f"change_{column}"] = panel[column] - panel["current_price"]
        panel[f"ratio_{column}"] = panel[column] / panel["current_price"].clip(1000) - 1.0
    matrix = panel[expert_columns].to_numpy(float)
    panel["expert_spread"] = np.max(matrix, axis=1) - np.min(matrix, axis=1)
    panel["expert_std"] = np.std(matrix, axis=1)
    panel["target_residual"] = panel["actual_price"] - panel["current_price"]
    return panel


def features(panel):
    return [
        "province_code",
        "commodity_code",
        "market_level",
        "month",
        "dow",
        "current_price",
        "CAT_GPU_V2_delta",
        "CAT_GPU_V2_logratio",
        "CAT_GPU_V2_level",
        "CAT_GPU_V2_last_price",
        "hierarchical_grid",
        "change_CAT_GPU_V2_delta",
        "change_CAT_GPU_V2_logratio",
        "change_CAT_GPU_V2_level",
        "change_CAT_GPU_V2_last_price",
        "change_hierarchical_grid",
        "ratio_CAT_GPU_V2_delta",
        "ratio_CAT_GPU_V2_logratio",
        "ratio_CAT_GPU_V2_level",
        "ratio_CAT_GPU_V2_last_price",
        "ratio_hierarchical_grid",
        "expert_spread",
        "expert_std",
        "doy_sin",
        "doy_cos",
    ]


def cat_model(seed):
    return CatBoostRegressor(
        loss_function="MAE",
        iterations=350,
        depth=4,
        learning_rate=0.035,
        l2_leaf_reg=12.0,
        random_seed=seed,
        random_strength=0.2,
        bootstrap_type="Bernoulli",
        subsample=0.85,
        allow_writing_files=False,
        thread_count=2,
        verbose=False,
    )


def encode_for_lgb(train, test, feature_columns):
    train_x = train[feature_columns].copy()
    test_x = test[feature_columns].copy()
    categorical = CATEGORICAL + ["month", "dow"]
    for column in categorical:
        values = pd.concat([train_x[column], test_x[column]], ignore_index=True).astype(str)
        mapping = {value: index for index, value in enumerate(values.unique())}
        train_x[column] = train_x[column].astype(str).map(mapping).astype("int32")
        test_x[column] = test_x[column].astype(str).map(mapping).astype("int32")
    return train_x, test_x, categorical


def chronological_predictions(panel):
    feature_columns = features(panel)
    categorical = CATEGORICAL + ["month", "dow"]
    outputs = []
    expert_for_router = EXPERTS + ["hierarchical_grid"]
    for horizon, horizon_frame in panel.groupby("horizon_days", observed=True):
        horizon_frame = horizon_frame.sort_values(["fold_id", "series_id"])
        for fold_id in sorted(horizon_frame["fold_id"].unique()):
            current = horizon_frame[horizon_frame["fold_id"] == fold_id].copy()
            prior = horizon_frame[horizon_frame["fold_id"] < fold_id].copy()
            candidate_predictions = {}
            metadata = {}
            if prior.empty:
                fallback = current["CAT_GPU_V2_delta"].to_numpy(float)
                for name in [
                    "META_CAT_RESIDUAL",
                    "META_CAT_TARGET",
                    "META_LGB_RESIDUAL",
                    "META_ERROR_ROUTER",
                    "META_SOFT_ERROR_BLEND",
                    "META_SHRUNK_RESIDUAL_GRID",
                ]:
                    candidate_predictions[name] = fallback
                metadata["selected_expert"] = "CAT_GPU_V2_delta"
            else:
                train_x = prior[feature_columns]
                test_x = current[feature_columns]

                residual_model = cat_model(1000 + int(horizon) * 10 + int(fold_id))
                residual_model.fit(
                    train_x,
                    prior["target_residual"],
                    cat_features=categorical,
                )
                predicted_residual = residual_model.predict(test_x)
                limit = np.maximum(12000.0, 0.50 * current["current_price"].to_numpy(float))
                predicted_residual = np.clip(predicted_residual, -limit, limit)
                residual_prediction = np.clip(
                    current["current_price"].to_numpy(float) + predicted_residual,
                    1000.0,
                    500000.0,
                )
                candidate_predictions["META_CAT_RESIDUAL"] = residual_prediction

                target_model = cat_model(2000 + int(horizon) * 10 + int(fold_id))
                target_model.fit(
                    train_x,
                    prior["actual_price"],
                    cat_features=categorical,
                )
                target_prediction = np.clip(target_model.predict(test_x), 1000.0, 500000.0)
                candidate_predictions["META_CAT_TARGET"] = target_prediction

                lgb_train, lgb_test, lgb_cats = encode_for_lgb(
                    prior, current, feature_columns
                )
                lgb_model = LGBMRegressor(
                    objective="l1",
                    n_estimators=260,
                    learning_rate=0.025,
                    num_leaves=15,
                    min_child_samples=45,
                    max_bin=127,
                    reg_alpha=0.2,
                    reg_lambda=8.0,
                    subsample=0.85,
                    colsample_bytree=0.85,
                    random_state=3000 + int(horizon) * 10 + int(fold_id),
                    n_jobs=2,
                    verbosity=-1,
                )
                lgb_model.fit(
                    lgb_train,
                    prior["target_residual"],
                    categorical_feature=lgb_cats,
                )
                lgb_residual = np.clip(lgb_model.predict(lgb_test), -limit, limit)
                candidate_predictions["META_LGB_RESIDUAL"] = np.clip(
                    current["current_price"].to_numpy(float) + lgb_residual,
                    1000.0,
                    500000.0,
                )

                predicted_errors = []
                for expert_index, expert in enumerate(expert_for_router):
                    error_model = CatBoostRegressor(
                        loss_function="MAE",
                        iterations=220,
                        depth=4,
                        learning_rate=0.04,
                        l2_leaf_reg=15.0,
                        random_seed=(
                            4000
                            + expert_index * 100
                            + int(horizon) * 10
                            + int(fold_id)
                        ),
                        random_strength=0.2,
                        bootstrap_type="Bernoulli",
                        subsample=0.85,
                        allow_writing_files=False,
                        thread_count=2,
                        verbose=False,
                    )
                    error_target = np.abs(
                        prior["actual_price"].to_numpy(float)
                        - prior[expert].to_numpy(float)
                    )
                    error_model.fit(
                        train_x,
                        error_target,
                        cat_features=categorical,
                    )
                    predicted_errors.append(
                        np.maximum(250.0, error_model.predict(test_x))
                    )
                error_matrix = np.column_stack(predicted_errors)
                prediction_matrix = current[expert_for_router].to_numpy(float)
                selected_index = np.argmin(error_matrix, axis=1)
                candidate_predictions["META_ERROR_ROUTER"] = prediction_matrix[
                    np.arange(len(current)), selected_index
                ]
                inverse = 1.0 / np.maximum(error_matrix, 500.0) ** 1.5
                inverse /= inverse.sum(axis=1, keepdims=True)
                candidate_predictions["META_SOFT_ERROR_BLEND"] = np.sum(
                    prediction_matrix * inverse, axis=1
                )
                metadata["selected_expert"] = np.asarray(expert_for_router)[selected_index]

                prior_residual_mae = mae(
                    prior["actual_price"],
                    prior["current_price"]
                    + np.clip(
                        residual_model.predict(prior[feature_columns]),
                        -np.maximum(12000.0, 0.50 * prior["current_price"]),
                        np.maximum(12000.0, 0.50 * prior["current_price"]),
                    ),
                )
                prior_grid_mae = mae(prior["actual_price"], prior["hierarchical_grid"])
                if prior_residual_mae + 50 < prior_grid_mae:
                    residual_weight = 0.65
                elif prior_grid_mae + 50 < prior_residual_mae:
                    residual_weight = 0.25
                else:
                    residual_weight = 0.45
                candidate_predictions["META_SHRUNK_RESIDUAL_GRID"] = (
                    residual_weight * residual_prediction
                    + (1.0 - residual_weight)
                    * current["hierarchical_grid"].to_numpy(float)
                )
                metadata["residual_weight"] = residual_weight

            for model_name, prediction in candidate_predictions.items():
                part = current[
                    [
                        "series_id",
                        "province_code",
                        "province_name",
                        "commodity_code",
                        "commodity_name",
                        "market_level",
                        "forecast_origin",
                        "target_date",
                        "horizon_days",
                        "fold_id",
                        "actual_price",
                        "current_price",
                    ]
                ].copy()
                part["model"] = model_name
                part["predicted_price"] = np.clip(prediction, 1000.0, 500000.0)
                part["absolute_error"] = np.abs(
                    part["actual_price"] - part["predicted_price"]
                )
                if model_name == "META_ERROR_ROUTER" and "selected_expert" in metadata:
                    part["selected_expert"] = metadata["selected_expert"]
                if "residual_weight" in metadata:
                    part["residual_weight"] = metadata["residual_weight"]
                outputs.append(part)
    return pd.concat(outputs, ignore_index=True)


def summarize(predictions):
    rows = []
    for (model, horizon), group in predictions.groupby(
        ["model", "horizon_days"], observed=True
    ):
        rows.append(
            {
                "model": model,
                "horizon_days": int(horizon),
                "folds": int(group["fold_id"].nunique()),
                "rows": len(group),
                "mae": mae(group["actual_price"], group["predicted_price"]),
                "rmse": float(
                    np.sqrt(
                        np.mean(
                            (group["actual_price"] - group["predicted_price"]) ** 2
                        )
                    )
                ),
                "mean_error": float(
                    np.mean(group["predicted_price"] - group["actual_price"])
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["horizon_days", "mae"])


def main():
    if not RAW_PATH.exists():
        raise SystemExit("OOF predictions do not exist yet")
    panel = make_panel()
    predictions = chronological_predictions(panel)
    summary = summarize(predictions)
    predictions.to_csv(RESULT_DIR / "meta_oof_predictions.csv", index=False)
    summary.to_csv(RESULT_DIR / "meta_metrics.csv", index=False)
    print("=== Prior-fold-only meta models ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
