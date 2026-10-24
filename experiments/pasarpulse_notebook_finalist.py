from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd


FINALIST_SEED = 2026
FINALIST_ORIGINS = pd.to_datetime(
    [
        "2026-02-02",
        "2026-03-02",
        "2026-03-30",
        "2026-04-27",
        "2026-05-25",
        "2026-06-22",
        "2026-07-17",
    ]
)
FINALIST_HORIZONS = (7, 14)
FINALIST_CATEGORICAL = ["province_code", "commodity_code", "market_level"]
FINALIST_PRICE_FEATURES = [
    "current_price",
    "price_observed",
    "price_observation_age_days",
    "price_series_coverage",
    "months_available",
    "price_lag_1",
    "price_lag_7",
    "price_lag_14",
    "price_lag_28",
    "price_lag_56",
    "price_delta_7",
    "price_delta_14",
    "price_roll_mean_7",
    "price_roll_mean_14",
    "price_roll_mean_28",
    "price_roll_median_28",
    "price_roll_std_28",
]
FINALIST_CALENDAR_FEATURES = [
    "day_of_week",
    "week_of_year",
    "month",
    "quarter",
    "year",
    "is_weekend",
    "seasonal_sin",
    "seasonal_cos",
    "is_christmas",
    "is_collective_leave",
    "is_eid_al_adha",
    "is_eid_al_fitr",
    "is_national_holiday",
    "is_new_year",
    "is_ramadan_start",
    "days_since_christmas",
    "days_to_christmas",
    "days_since_collective_leave",
    "days_to_collective_leave",
    "days_since_eid_al_adha",
    "days_to_eid_al_adha",
    "days_since_eid_al_fitr",
    "days_to_eid_al_fitr",
    "days_since_national_holiday",
    "days_to_national_holiday",
    "days_since_new_year",
    "days_to_new_year",
    "days_since_ramadan_start",
    "days_to_ramadan_start",
]
FINALIST_CONTEXT_FEATURES = [
    "production_kg",
    "harvested_area_ha",
    "productivity_kg_per_ha",
    "production_year",
    "production_age_years",
    "ndvi_mean",
    "ndvi_std",
    "ndvi_p10",
    "ndvi_p90",
    "ndwi_mean",
    "valid_pixel_fraction",
    "ndvi_anomaly",
    "ndvi_zscore",
    "cloud_cover",
    "satellite_observation_age_days",
    "mask_price",
    "mask_weather",
    "mask_production",
    "mask_satellite",
    "mask_calendar",
    "evidence_quality_score",
    "price_series_coverage",
    "months_available",
]


def engineer_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["series_id", "date"]).reset_index(drop=True)
    out["current_price"] = pd.to_numeric(out["price_ffill"], errors="coerce")
    grouped = out.groupby("series_id", observed=True, sort=False)["current_price"]
    for lag in (1, 7, 14, 28, 56):
        out[f"price_lag_{lag}"] = grouped.shift(lag)
    for window in (7, 14, 28):
        out[f"price_roll_mean_{window}"] = grouped.transform(
            lambda values: values.shift(1).rolling(
                window, min_periods=max(3, window // 2)
            ).mean()
        )
    out["price_roll_median_28"] = grouped.transform(
        lambda values: values.shift(1).rolling(28, min_periods=14).median()
    )
    out["price_roll_std_28"] = grouped.transform(
        lambda values: values.shift(1).rolling(28, min_periods=14).std()
    )
    out["price_delta_7"] = out["current_price"] - out["price_lag_7"]
    out["price_delta_14"] = out["current_price"] - out["price_lag_14"]
    return out.replace([np.inf, -np.inf], np.nan)


def load_panel(root: Path) -> pd.DataFrame:
    path = root / "data" / "ready" / "model_dataset_eligible.parquet"
    if not path.exists():
        return pd.DataFrame()
    return engineer_features(pd.read_parquet(path))


def feature_columns(frame: pd.DataFrame) -> list[str]:
    requested = (
        FINALIST_CATEGORICAL
        + FINALIST_PRICE_FEATURES
        + FINALIST_CALENDAR_FEATURES
        + FINALIST_CONTEXT_FEATURES
    )
    return [column for column in dict.fromkeys(requested) if column in frame.columns]


def supervised_frame(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    out = frame.copy()
    out["target_price"] = pd.to_numeric(
        out[f"price_t_plus_{horizon}"], errors="coerce"
    )
    current = pd.to_numeric(out["current_price"], errors="coerce").clip(lower=1000)
    out["target_delta"] = out["target_price"] - current
    out["target_logratio"] = np.log(out["target_price"] / current)
    out["target_scaled_delta"] = out["target_delta"] / current
    out["target_observed"] = out["target_price"].notna()
    return out.replace([np.inf, -np.inf], np.nan)


def make_origin_split(
    frame: pd.DataFrame,
    horizon: int,
    origin: pd.Timestamp,
    minimum_history: int = 240,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    supervised = supervised_frame(frame, horizon)
    valid = (
        supervised["current_price"].notna()
        & supervised["target_price"].notna()
        & supervised["target_observed"]
    )
    train = supervised[
        valid
        & (supervised["date"] < origin)
        & (
            supervised["date"] + pd.Timedelta(days=horizon)
            <= origin
        )
    ].copy()
    test = supervised[valid & supervised["date"].eq(origin)].copy()
    counts = train.groupby("series_id", observed=True).size()
    eligible = counts[counts >= minimum_history].index
    return (
        train[train["series_id"].isin(eligible)].copy(),
        test[test["series_id"].isin(eligible)].copy(),
    )


def prepare_tree_matrix(
    train: pd.DataFrame, test: pd.DataFrame, features: list[str]
):
    train_x = train[features].copy()
    test_x = test[features].copy()
    categorical = [column for column in FINALIST_CATEGORICAL if column in features]
    numeric = [column for column in features if column not in categorical]
    for column in categorical:
        train_x[column] = train_x[column].fillna("missing").astype(str)
        test_x[column] = test_x[column].fillna("missing").astype(str)
    medians = train_x[numeric].apply(pd.to_numeric, errors="coerce").median()
    for column in numeric:
        train_x[column] = (
            pd.to_numeric(train_x[column], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(medians[column])
            .astype("float32")
        )
        test_x[column] = (
            pd.to_numeric(test_x[column], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(medians[column])
            .astype("float32")
        )
    return train_x, test_x, categorical


def reconstruct_prediction(current, raw_prediction, target_kind: str):
    current = np.asarray(current, dtype=float)
    raw_prediction = np.asarray(raw_prediction, dtype=float)
    if target_kind in ("logratio", "target_logratio"):
        prediction = current * np.exp(np.clip(raw_prediction, -1.2, 1.2))
    elif target_kind in ("scaled_delta", "target_scaled_delta"):
        prediction = current + current * np.clip(raw_prediction, -0.75, 0.75)
    elif target_kind in ("delta", "target_delta"):
        prediction = current + np.clip(raw_prediction, -12000, 12000)
    else:
        prediction = raw_prediction
    return np.clip(prediction, 1000, 500000)


def metric_row(actual, predicted) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    denominator = np.abs(actual) + np.abs(predicted)
    return {
        "mae": float(np.mean(np.abs(actual - predicted))),
        "rmse": float(np.sqrt(np.mean((actual - predicted) ** 2))),
        "smape": float(
            np.mean(
                2 * np.abs(actual - predicted)
                / np.where(denominator == 0, 1, denominator)
            )
            * 100
        ),
        "mean_error": float(np.mean(predicted - actual)),
    }


def fit_lightgbm(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target_kind: str,
    seed: int,
):
    from lightgbm import LGBMRegressor

    train_x, test_x, categorical = prepare_tree_matrix(train, test, features)
    for column in categorical:
        categories = pd.Index(
            pd.concat(
                [train_x[column], test_x[column]], ignore_index=True
            ).astype(str).unique()
        )
        train_x[column] = pd.Categorical(
            train_x[column].astype(str), categories=categories
        ).codes
        test_x[column] = pd.Categorical(
            test_x[column].astype(str), categories=categories
        ).codes
    model = LGBMRegressor(
        objective="l1",
        n_estimators=420,
        learning_rate=0.035,
        num_leaves=39,
        min_child_samples=65,
        max_bin=127,
        reg_lambda=2.0,
        colsample_bytree=0.90,
        random_state=seed,
        n_jobs=max(1, min(8, os.cpu_count() or 2)),
        verbosity=-1,
    )
    model.fit(train_x, train[target_kind], categorical_feature=categorical)
    prediction = reconstruct_prediction(
        test["current_price"].to_numpy(), model.predict(test_x), target_kind
    )
    return prediction, model, (train_x, test_x, categorical, "CPU")


def fit_catboost(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target_kind: str,
    seed: int,
):
    from catboost import CatBoostRegressor

    train_x, test_x, categorical = prepare_tree_matrix(train, test, features)
    cat_indices = [train_x.columns.get_loc(column) for column in categorical]
    common = dict(
        loss_function="MAE",
        iterations=280,
        depth=8,
        learning_rate=0.045,
        l2_leaf_reg=8.0,
        random_strength=0.30,
        random_seed=seed,
        allow_writing_files=False,
        verbose=False,
    )
    task = os.environ.get("PASARPULSE_CATBOOST_TASK", "GPU")
    if task.upper() == "GPU":
        common.update(task_type="GPU", devices="0")
    try:
        model = CatBoostRegressor(**common)
        model.fit(train_x, train[target_kind], cat_features=cat_indices)
        backend = task.upper()
    except Exception as error:
        if task.upper() != "GPU":
            raise
        print("GPU fit unavailable; using CPU fallback:", type(error).__name__)
        common.pop("task_type", None)
        common.pop("devices", None)
        model = CatBoostRegressor(**common)
        model.fit(train_x, train[target_kind], cat_features=cat_indices)
        backend = "CPU"
    prediction = reconstruct_prediction(
        test["current_price"].to_numpy(), model.predict(test_x), target_kind
    )
    return prediction, model, (train_x, test_x, categorical, backend)


def summarize_lightgbm_native_contributions(
    fitted_models: dict,
    *,
    top_k: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Summarise native LightGBM additive feature contributions.

    LightGBM's ``pred_contrib=True`` returns one contribution per input feature
    plus the expected value.  These values reconstruct the model's raw
    log-ratio prediction; they are model attributions, not causal effects and
    not contributions in rupiah space after inverse transformation.
    """
    global_rows: list[dict[str, object]] = []
    local_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    if top_k < 1:
        raise ValueError("top_k must be positive")

    for (model_name, horizon, fold_id), entry in sorted(fitted_models.items()):
        if model_name != "LGBM_LOGRATIO":
            continue
        model = entry["model"]
        _, test_x, _, _ = entry["prep"]
        feature_names = list(test_x.columns)
        contribution = np.asarray(model.predict(test_x, pred_contrib=True), dtype=float)
        expected_columns = len(feature_names) + 1
        if contribution.ndim != 2 or contribution.shape[1] != expected_columns:
            raise RuntimeError(
                "LightGBM contribution output does not match the feature contract"
            )
        feature_contribution = contribution[:, :-1]
        expected_value = contribution[:, -1]
        raw_prediction = np.asarray(model.predict(test_x), dtype=float)
        reconstructed = feature_contribution.sum(axis=1) + expected_value
        max_error = float(np.max(np.abs(raw_prediction - reconstructed)))
        audit_rows.append(
            {
                "model": model_name,
                "horizon_days": int(horizon),
                "fold_id": int(fold_id),
                "rows_explained": int(len(test_x)),
                "feature_count": int(len(feature_names)),
                "max_abs_additivity_error": max_error,
            }
        )

        mean_abs = np.abs(feature_contribution).mean(axis=0)
        mean_signed = feature_contribution.mean(axis=0)
        for feature, abs_value, signed_value in zip(
            feature_names, mean_abs, mean_signed, strict=True
        ):
            global_rows.append(
                {
                    "model": model_name,
                    "horizon_days": int(horizon),
                    "fold_id": int(fold_id),
                    "feature": feature,
                    "mean_abs_contribution_logratio": float(abs_value),
                    "mean_signed_contribution_logratio": float(signed_value),
                }
            )

        identity = entry["test_rows"].reset_index(drop=True)
        top_count = min(top_k, len(feature_names))
        for row_index in range(len(test_x)):
            top_indices = np.argsort(np.abs(feature_contribution[row_index]))[-top_count:][::-1]
            for rank, feature_index in enumerate(top_indices, start=1):
                row = {
                    "model": model_name,
                    "horizon_days": int(horizon),
                    "fold_id": int(fold_id),
                    "rank": rank,
                    "feature": feature_names[feature_index],
                    "feature_value": float(test_x.iloc[row_index, feature_index]),
                    "contribution_logratio": float(
                        feature_contribution[row_index, feature_index]
                    ),
                    "expected_value_logratio": float(expected_value[row_index]),
                    "raw_prediction_logratio": float(raw_prediction[row_index]),
                }
                row.update(identity.iloc[row_index].to_dict())
                local_rows.append(row)

    global_summary = pd.DataFrame(global_rows)
    if not global_summary.empty:
        global_summary = (
            global_summary.groupby(["model", "horizon_days", "feature"], as_index=False)
            .agg(
                mean_abs_contribution_logratio=(
                    "mean_abs_contribution_logratio", "mean"
                ),
                mean_signed_contribution_logratio=(
                    "mean_signed_contribution_logratio", "mean"
                ),
                folds=("fold_id", "nunique"),
            )
            .sort_values(
                ["horizon_days", "mean_abs_contribution_logratio"],
                ascending=[True, False],
            )
            .reset_index(drop=True)
        )
    return global_summary, pd.DataFrame(local_rows), pd.DataFrame(audit_rows)


def run_finalist_cv(
    frame: pd.DataFrame,
    artifact_dir: Path,
    origins: pd.DatetimeIndex = FINALIST_ORIGINS,
    horizons: tuple[int, ...] = FINALIST_HORIZONS,
):
    features = feature_columns(frame)
    rows = []
    predictions = []
    fitted_models = {}
    started = time.perf_counter()
    for horizon in horizons:
        for fold_id, origin in enumerate(origins, start=1):
            train, test = make_origin_split(frame, horizon, origin)
            if train.empty or test.empty:
                continue
            specs = [
                ("LGBM_LOGRATIO", "target_logratio", fit_lightgbm),
                ("CATBOOST_SCALED_DELTA", "target_scaled_delta", fit_catboost),
            ]
            prediction_map = {}
            for offset, (name, target_kind, fitter) in enumerate(specs):
                prediction, model, prep = fitter(
                    train,
                    test,
                    features,
                    target_kind,
                    FINALIST_SEED + horizon + fold_id + offset,
                )
                prediction_map[name] = prediction
                fitted_models[(name, horizon, fold_id)] = {
                    "model": model,
                    "prep": prep,
                    "features": features,
                    "test_rows": test[
                        [
                            "series_id",
                            "province_code",
                            "province_name",
                            "commodity_code",
                            "commodity_name",
                            "market_level",
                            "date",
                            "current_price",
                        ]
                    ].reset_index(drop=True),
                }
                rows.append(
                    {
                        "model": name,
                        "horizon_days": horizon,
                        "fold_id": fold_id,
                        "forecast_origin": origin.date().isoformat(),
                        "rows_scored": len(test),
                        **metric_row(test["target_price"], prediction),
                    }
                )
                part = test[
                    [
                        "series_id",
                        "province_code",
                        "province_name",
                        "commodity_code",
                        "commodity_name",
                        "market_level",
                        "date",
                        "target_price",
                        "current_price",
                    ]
                ].copy()
                part["model"] = name
                part["horizon_days"] = horizon
                part["fold_id"] = fold_id
                part["forecast_origin"] = origin
                part["target_date"] = origin + pd.Timedelta(days=horizon)
                part["predicted_price"] = prediction
                predictions.append(part)
            inverse = {
                name: 1.0
                / max(
                    metric_row(test["target_price"], prediction)["mae"],
                    1.0,
                )
                for name, prediction in prediction_map.items()
            }
            total = sum(inverse.values())
            weights = {name: value / total for name, value in inverse.items()}
            blend = sum(
                weights[name] * prediction
                for name, prediction in prediction_map.items()
            )
            rows.append(
                {
                    "model": "FINALIST_INVERSE_MAE_BLEND",
                    "horizon_days": horizon,
                    "fold_id": fold_id,
                    "forecast_origin": origin.date().isoformat(),
                    "rows_scored": len(test),
                    "blend_weights": json.dumps(weights),
                    **metric_row(test["target_price"], blend),
                }
            )
            blend_part = part.copy()
            blend_part["model"] = "FINALIST_INVERSE_MAE_BLEND"
            blend_part["predicted_price"] = blend
            predictions.append(blend_part)
            print(
                f"h={horizon} fold={fold_id} origin={origin.date()} "
                f"train={len(train):,} test={len(test):,}",
                flush=True,
            )
    fold_metrics = pd.DataFrame(rows)
    oof = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    runtime_seconds = time.perf_counter() - started
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fold_metrics.to_csv(artifact_dir / "finalist_fold_metrics.csv", index=False)
    oof.to_csv(artifact_dir / "finalist_oof_predictions.csv", index=False)
    (artifact_dir / "finalist_runtime_seconds.txt").write_text(
        str(runtime_seconds)
    )
    return fold_metrics, oof, fitted_models, runtime_seconds
