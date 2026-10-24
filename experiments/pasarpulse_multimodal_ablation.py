#!/usr/bin/env python3
"""Leakage-safe chronological ablation for the implemented PasarPulse trees.

This experiment evaluates the repository's executable LightGBM/CatBoost
models.  It does not claim that the paper's proposed TFT/CNN/GNN architecture
has been trained.  Every contextual feature is gated by its source-availability
date before it enters a fold.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


# Remote Jupyter kernels export an inline backend string that standalone
# subprocesses cannot resolve.  The experiment only writes tabular artifacts.
os.environ["MPLBACKEND"] = "Agg"


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments import pasarpulse_notebook_finalist as core


SEED = 2026
CATEGORICAL = ["province_code", "commodity_code", "market_level"]
ORIGINS = core.FINALIST_ORIGINS
HORIZONS = core.FINALIST_HORIZONS

# Coverage-audit summaries are calculated over the complete archived period.
# They define the fixed evaluation cohort but must not be model inputs at an
# earlier replay origin, because later observations contribute to them.
FULL_PERIOD_AUDIT_COLUMNS = {"price_series_coverage", "months_available"}
PRICE_FEATURES = [
    column
    for column in dict.fromkeys(core.FINALIST_PRICE_FEATURES)
    if column not in FULL_PERIOD_AUDIT_COLUMNS
]
CALENDAR_FEATURES = [
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
    "days_since_collective_leave",
    "days_since_eid_al_adha",
    "days_since_eid_al_fitr",
    "days_since_national_holiday",
    "days_since_new_year",
    "days_since_ramadan_start",
    "target_day_of_week",
    "target_week_of_year",
    "target_month",
    "target_quarter",
    "target_seasonal_sin",
    "target_seasonal_cos",
    "mask_calendar",
]
WEATHER_FEATURES = [
    "temperature_c_mean",
    "temperature_c_min",
    "temperature_c_max",
    "rainfall_mm_sum",
    "soil_moisture_layer1_mean",
    "solar_radiation_mj_m2_sum",
    "weather_grid_coverage",
    "weather_observation_age_days",
    "mask_weather",
]
PRODUCTION_FEATURES = [
    "production_kg",
    "harvested_area_ha",
    "productivity_kg_per_ha",
    "production_year",
    "production_age_years",
    "mask_production",
]
SATELLITE_FEATURES = [
    "ndvi_mean",
    "ndvi_std",
    "ndvi_p10",
    "ndvi_p90",
    "ndwi_mean",
    "evi_mean",
    "evi_std",
    "ndvi_anomaly",
    "ndvi_zscore",
    "evi_anomaly",
    "evi_zscore",
    "valid_pixel_fraction",
    "cloud_cover",
    "satellite_observation_age_days",
    "mask_satellite",
]
MARKET_AND_STATIC_GRAPH_FEATURES = [
    "major_road_length_km",
    "major_road_segment_count",
    "ferry_length_km",
    "ferry_segment_count",
    "ferry_terminal_count",
    "port_count",
    "marketplace_count",
    "transport_snapshot_age_days",
    "official_market_count",
    "official_market_schedule_count",
    "official_market_every_day_count",
    "official_market_days_per_week_mean",
    "official_market_days_per_week_median",
    "official_market_schedule_coverage",
    "official_market_daily_equivalent",
    "static_candidate_degree",
    "static_adjacent_degree",
    "static_osm_transport_degree",
    "static_centroid_distance_km_mean",
    "static_centroid_distance_km_min",
    "static_osm_road_length_km_sum",
    "static_osm_ferry_length_km_sum",
    "mask_graph",
]
DYNAMIC_GRAPH_FEATURES = [
    "dynamic_out_degree",
    "dynamic_out_corr_mean",
    "dynamic_out_corr_max",
    "dynamic_out_lag_mean",
    "dynamic_out_shock_cooccurrence_mean",
    "dynamic_out_conditional_shock_mean",
    "dynamic_out_seasonal_similarity_mean",
    "dynamic_in_degree",
    "dynamic_in_corr_mean",
    "dynamic_in_corr_max",
    "dynamic_in_lag_mean",
    "dynamic_in_shock_cooccurrence_mean",
    "dynamic_in_conditional_shock_mean",
    "dynamic_in_seasonal_similarity_mean",
    "dynamic_graph_age_days",
    "mask_dynamic_graph",
]

PROGRESSIVE_VARIANTS = {
    "PRICE": PRICE_FEATURES,
    "PRICE_CALENDAR": PRICE_FEATURES + CALENDAR_FEATURES,
    "PRICE_CALENDAR_WEATHER": PRICE_FEATURES + CALENDAR_FEATURES + WEATHER_FEATURES,
    "PRICE_CALENDAR_WEATHER_PRODUCTION": (
        PRICE_FEATURES + CALENDAR_FEATURES + WEATHER_FEATURES + PRODUCTION_FEATURES
    ),
    "PRICE_CALENDAR_WEATHER_PRODUCTION_SATELLITE": (
        PRICE_FEATURES
        + CALENDAR_FEATURES
        + WEATHER_FEATURES
        + PRODUCTION_FEATURES
        + SATELLITE_FEATURES
    ),
    "ALL_MODALITIES_STATIC_GRAPH": (
        PRICE_FEATURES
        + CALENDAR_FEATURES
        + WEATHER_FEATURES
        + PRODUCTION_FEATURES
        + SATELLITE_FEATURES
        + MARKET_AND_STATIC_GRAPH_FEATURES
    ),
    "ALL_MODALITIES_DYNAMIC_GRAPH": (
        PRICE_FEATURES
        + CALENDAR_FEATURES
        + WEATHER_FEATURES
        + PRODUCTION_FEATURES
        + SATELLITE_FEATURES
        + MARKET_AND_STATIC_GRAPH_FEATURES
        + DYNAMIC_GRAPH_FEATURES
    ),
}

FORBIDDEN_FEATURE_PREFIXES = (
    "price_t_plus_",
    "future_",
    "shock_",
    "target_price",
    "target_logratio",
    "target_scaled_delta",
    "target_delta",
    "threshold_exceeded",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)


def attach_static_graph(
    frame: pd.DataFrame,
    edges: pd.DataFrame,
    effective_date: str,
) -> pd.DataFrame:
    if edges.empty:
        for column in MARKET_AND_STATIC_GRAPH_FEATURES:
            if column.startswith("static_"):
                frame[column] = np.nan
        frame["static_graph_effective_date"] = pd.NaT
        return frame
    graph = edges.copy()
    for column in ("source_province_code", "target_province_code"):
        graph[column] = normalize_code(graph[column])
    numeric_defaults = {
        "adjacent_border": 0.0,
        "osm_transport_connection": 0.0,
        "centroid_distance_km": np.nan,
        "osm_road_length_km": 0.0,
        "osm_ferry_length_km": 0.0,
    }
    for column, default in numeric_defaults.items():
        graph[column] = pd.to_numeric(
            graph[column] if column in graph else default, errors="coerce"
        )
    endpoint_rows = []
    for endpoint in ("source_province_code", "target_province_code"):
        part = graph.copy()
        part["province_code"] = part[endpoint]
        endpoint_rows.append(part)
    endpoints = pd.concat(endpoint_rows, ignore_index=True)
    summary = (
        endpoints.groupby("province_code", as_index=False)
        .agg(
            static_candidate_degree=("edge_id", "nunique"),
            static_adjacent_degree=("adjacent_border", "sum"),
            static_osm_transport_degree=("osm_transport_connection", "sum"),
            static_centroid_distance_km_mean=("centroid_distance_km", "mean"),
            static_centroid_distance_km_min=("centroid_distance_km", "min"),
            static_osm_road_length_km_sum=("osm_road_length_km", "sum"),
            static_osm_ferry_length_km_sum=("osm_ferry_length_km", "sum"),
        )
    )
    result = frame.merge(summary, on="province_code", how="left", validate="many_to_one")
    result["static_graph_effective_date"] = pd.Timestamp(effective_date)
    unavailable = result["date"].lt(result["static_graph_effective_date"])
    static_columns = [column for column in summary if column != "province_code"]
    result.loc[unavailable, static_columns] = np.nan
    result.loc[unavailable, "static_graph_effective_date"] = pd.NaT
    return result


def _asof_by_series(
    frame: pd.DataFrame,
    context: pd.DataFrame,
    *,
    right_on: str,
) -> pd.DataFrame:
    keys = ["province_code", "commodity_code", "market_level"]
    context_groups = {
        key if isinstance(key, tuple) else (key,): group
        for key, group in context.groupby(keys, dropna=False)
    }
    parts = []
    for key, left in frame.groupby(keys, dropna=False, sort=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        right = context_groups.get(key_tuple)
        if right is None or right.empty:
            parts.append(left)
            continue
        payload = right.drop(columns=keys, errors="ignore").sort_values(right_on)
        parts.append(
            pd.merge_asof(
                left.sort_values("date"),
                payload,
                left_on="date",
                right_on=right_on,
                direction="backward",
            )
        )
    return pd.concat(parts, ignore_index=True)


def _dynamic_side(edges: pd.DataFrame, *, side: str) -> pd.DataFrame:
    province_column = (
        "source_province_code" if side == "out" else "target_province_code"
    )
    keys = ["snapshot_date", "commodity_code", "market_level", province_column]
    result = (
        edges.groupby(keys, as_index=False)
        .agg(
            degree=("edge_id", "nunique"),
            corr_mean=("abs_lead_lag_corr", "mean"),
            corr_max=("abs_lead_lag_corr", "max"),
            lag_mean=("source_lead_days", "mean"),
            shock_cooccurrence_mean=("shock_cooccurrence_rate", "mean"),
            conditional_shock_mean=("target_shock_given_source", "mean"),
            seasonal_similarity_mean=("seasonal_similarity", "mean"),
        )
        .rename(columns={province_column: "province_code"})
    )
    result = result.rename(
        columns={
            column: f"dynamic_{side}_{column}"
            for column in (
                "degree",
                "corr_mean",
                "corr_max",
                "lag_mean",
                "shock_cooccurrence_mean",
                "conditional_shock_mean",
                "seasonal_similarity_mean",
            )
        }
    )
    result = result.rename(columns={"snapshot_date": f"dynamic_{side}_snapshot_date"})
    return result


def attach_dynamic_graph(frame: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if edges.empty:
        for column in DYNAMIC_GRAPH_FEATURES:
            frame[column] = 0 if column == "mask_dynamic_graph" else np.nan
        return frame
    graph = edges.copy()
    graph["snapshot_date"] = pd.to_datetime(graph["snapshot_date"]).dt.normalize()
    for column in ("source_province_code", "target_province_code"):
        graph[column] = normalize_code(graph[column])
    result = frame
    for side in ("out", "in"):
        context = _dynamic_side(graph, side=side)
        snapshot_column = f"dynamic_{side}_snapshot_date"
        result = _asof_by_series(result, context, right_on=snapshot_column)
    snapshot = pd.concat(
        [result["dynamic_out_snapshot_date"], result["dynamic_in_snapshot_date"]],
        axis=1,
    ).max(axis=1)
    result["dynamic_graph_snapshot_date"] = pd.to_datetime(snapshot)
    result["dynamic_graph_age_days"] = (
        result["date"] - result["dynamic_graph_snapshot_date"]
    ).dt.days
    dynamic_columns = [
        column
        for column in DYNAMIC_GRAPH_FEATURES
        if column not in {"dynamic_graph_age_days", "mask_dynamic_graph"}
    ]
    existing = [column for column in dynamic_columns if column in result]
    result["mask_dynamic_graph"] = (
        result[existing].notna().any(axis=1).astype("int8") if existing else 0
    )
    return result


def engineer_panel(
    panel: pd.DataFrame,
    static_graph: pd.DataFrame,
    dynamic_graph: pd.DataFrame,
    static_graph_effective_date: str,
) -> pd.DataFrame:
    result = panel.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result["province_code"] = normalize_code(result["province_code"])
    result = core.engineer_features(result)
    result = attach_static_graph(result, static_graph, static_graph_effective_date)
    result = attach_dynamic_graph(result, dynamic_graph)
    return result.replace([np.inf, -np.inf], np.nan)


def add_target_calendar(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    result = frame.copy()
    target_date = result["date"] + pd.Timedelta(days=horizon)
    day_of_year = target_date.dt.dayofyear
    result["target_day_of_week"] = target_date.dt.dayofweek
    result["target_week_of_year"] = target_date.dt.isocalendar().week.astype(int)
    result["target_month"] = target_date.dt.month
    result["target_quarter"] = target_date.dt.quarter
    result["target_seasonal_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    result["target_seasonal_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)
    return result


def supervised_frame(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return core.supervised_frame(add_target_calendar(frame, horizon), horizon)


def make_split(
    frame: pd.DataFrame,
    horizon: int,
    origin: pd.Timestamp,
    minimum_history: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    supervised = supervised_frame(frame, horizon)
    return make_split_from_supervised(
        supervised, horizon, origin, minimum_history
    )


def make_split_from_supervised(
    supervised: pd.DataFrame,
    horizon: int,
    origin: pd.Timestamp,
    minimum_history: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = supervised["current_price"].notna() & supervised["target_price"].notna()
    train = supervised[
        valid
        & supervised["date"].lt(origin)
        & (supervised["date"] + pd.Timedelta(days=horizon)).le(origin)
    ].copy()
    test = supervised[valid & supervised["date"].eq(origin)].copy()
    counts = train.groupby("series_id", observed=True).size()
    eligible = counts[counts.ge(minimum_history)].index
    train = train[train["series_id"].isin(eligible)].copy()
    test = test[test["series_id"].isin(eligible)].copy()
    if not train.empty and not (
        train["date"] + pd.Timedelta(days=horizon)
    ).le(origin).all():
        raise AssertionError("Training labels cross the forecast origin.")
    return train, test


def requested_features(frame: pd.DataFrame, variant: str) -> list[str]:
    requested = CATEGORICAL + PROGRESSIVE_VARIANTS[variant]
    features = [column for column in dict.fromkeys(requested) if column in frame]
    forbidden = [
        column
        for column in features
        if column.startswith(FORBIDDEN_FEATURE_PREFIXES)
        and column not in CALENDAR_FEATURES
    ]
    if forbidden:
        raise AssertionError(f"Forbidden realized-label features requested: {forbidden}")
    return features


def prepare_matrix(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    categorical = [column for column in CATEGORICAL if column in features]
    usable = []
    for column in features:
        if column in categorical or pd.to_numeric(train[column], errors="coerce").notna().any():
            usable.append(column)
    train_x = train[usable].copy()
    test_x = test[usable].copy()
    for column in categorical:
        categories = pd.Index(train_x[column].fillna("missing").astype(str).unique())
        train_values = pd.Categorical(
            train_x[column].fillna("missing").astype(str), categories=categories
        ).codes
        test_values = pd.Categorical(
            test_x[column].fillna("missing").astype(str), categories=categories
        ).codes
        train_x[column] = train_values.astype("int32")
        test_x[column] = test_values.astype("int32")
    numeric = [column for column in usable if column not in categorical]
    medians = train_x[numeric].apply(pd.to_numeric, errors="coerce").median()
    for column in numeric:
        train_x[column] = (
            pd.to_numeric(train_x[column], errors="coerce").fillna(medians[column]).astype("float32")
        )
        test_x[column] = (
            pd.to_numeric(test_x[column], errors="coerce").fillna(medians[column]).astype("float32")
        )
    return train_x, test_x, categorical


def fit_lgbm(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target: str,
    seed: int,
) -> tuple[np.ndarray, int, str]:
    from lightgbm import LGBMRegressor

    train_x, test_x, categorical = prepare_matrix(train, test, features)
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
    model.fit(train_x, train[target], categorical_feature=categorical)
    raw = model.predict(test_x)
    predicted = core.reconstruct_prediction(test["current_price"], raw, target)
    return predicted, train_x.shape[1], "CPU"


def fit_catboost(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target: str,
    seed: int,
) -> tuple[np.ndarray, int, str]:
    from catboost import CatBoostRegressor

    train_x, test_x, categorical = prepare_matrix(train, test, features)
    cat_indices = [train_x.columns.get_loc(column) for column in categorical]
    params = dict(
        loss_function="MAE",
        iterations=320,
        depth=8,
        learning_rate=0.045,
        l2_leaf_reg=8.0,
        random_strength=0.30,
        random_seed=seed,
        allow_writing_files=False,
        verbose=False,
        task_type="GPU",
        devices="0",
    )
    try:
        model = CatBoostRegressor(**params)
        model.fit(train_x, train[target], cat_features=cat_indices)
        backend = "GPU"
    except Exception as error:
        print(f"CatBoost GPU unavailable ({type(error).__name__}); using CPU", flush=True)
        params.pop("task_type")
        params.pop("devices")
        model = CatBoostRegressor(**params)
        model.fit(train_x, train[target], cat_features=cat_indices)
        backend = "CPU"
    raw = model.predict(test_x)
    predicted = core.reconstruct_prediction(test["current_price"], raw, target)
    return predicted, train_x.shape[1], backend


def validate_availability(frame: pd.DataFrame) -> dict[str, object]:
    checks: dict[str, object] = {}
    pairs = {
        "weather": "weather_effective_date",
        "production": "production_effective_date",
        "satellite": "satellite_effective_date",
        "transport": "transport_snapshot_date",
        "official_markets": "market_context_effective_date",
        "static_graph": "static_graph_effective_date",
        "dynamic_graph": "dynamic_graph_snapshot_date",
    }
    for name, column in pairs.items():
        if column not in frame:
            checks[name] = {"available_rows": 0, "violations": 0}
            continue
        timestamp = pd.to_datetime(frame[column], errors="coerce")
        violations = timestamp.notna() & timestamp.gt(frame["date"])
        checks[name] = {
            "available_rows": int(timestamp.notna().sum()),
            "violations": int(violations.sum()),
            "latest_effective_date": str(timestamp.max()),
        }
        if violations.any():
            raise AssertionError(f"{name} has {int(violations.sum())} future-availability rows")
    all_requested = {
        column
        for columns in PROGRESSIVE_VARIANTS.values()
        for column in columns
    }
    forbidden = sorted(
        column
        for column in all_requested
        if column.startswith(FORBIDDEN_FEATURE_PREFIXES)
        and column not in CALENDAR_FEATURES
    )
    checks["forbidden_feature_columns"] = forbidden
    if forbidden:
        raise AssertionError(f"Realized outcomes entered the feature contract: {forbidden}")
    full_period_audit_features = sorted(
        FULL_PERIOD_AUDIT_COLUMNS.intersection(all_requested)
    )
    checks["full_period_audit_features"] = full_period_audit_features
    if full_period_audit_features:
        raise AssertionError(
            "Full-period coverage summaries entered the feature contract: "
            f"{full_period_audit_features}"
        )
    checks["passed"] = True
    return checks


def append_prediction_rows(
    test: pd.DataFrame,
    predicted: np.ndarray,
    *,
    model: str,
    variant: str,
    horizon: int,
    fold_id: int,
    origin: pd.Timestamp,
) -> pd.DataFrame:
    columns = [
        "series_id",
        "province_code",
        "province_name",
        "commodity_code",
        "commodity_name",
        "market_level",
        "date",
        "current_price",
        "target_price",
    ]
    part = test[columns].copy()
    part["model"] = model
    part["variant"] = variant
    part["horizon_days"] = horizon
    part["fold_id"] = fold_id
    part["forecast_origin"] = origin
    part["target_date"] = origin + pd.Timedelta(days=horizon)
    part["predicted_price"] = predicted
    return part


def pooled_metrics(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in oof.groupby(["model", "variant", "horizon_days"]):
        model, variant, horizon = keys
        rows.append(
            {
                "model": model,
                "variant": variant,
                "horizon_days": int(horizon),
                "folds": int(group["fold_id"].nunique()),
                "rows_scored": len(group),
                **core.metric_row(group["target_price"], group["predicted_price"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["horizon_days", "mae", "model"])


def run(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    args.output.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(args.panel)
    static_graph = pd.read_parquet(args.static_graph)
    dynamic_graph = pd.read_parquet(args.dynamic_graph)
    frame = engineer_panel(
        panel,
        static_graph,
        dynamic_graph,
        args.static_graph_effective_date,
    )
    availability_audit = validate_availability(frame)
    (args.output / "availability_leakage_audit.json").write_text(
        json.dumps(availability_audit, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    fold_rows: list[dict[str, object]] = []
    prediction_parts: list[pd.DataFrame] = []
    availability_rows: list[dict[str, object]] = []
    full_variant = "ALL_MODALITIES_DYNAMIC_GRAPH"
    origins = pd.to_datetime(args.origins)
    horizons = tuple(args.horizons)
    variants = list(args.variants)
    for horizon in horizons:
        horizon_frame = supervised_frame(frame, horizon)
        for fold_id, origin in enumerate(origins, start=1):
            train, test = make_split_from_supervised(
                horizon_frame,
                horizon,
                origin,
                minimum_history=args.minimum_history,
            )
            if train.empty or test.empty:
                raise RuntimeError(
                    f"Empty chronological fold h={horizon} origin={origin.date()}"
                )
            availability_rows.append(
                {
                    "horizon_days": horizon,
                    "fold_id": fold_id,
                    "forecast_origin": origin.date().isoformat(),
                    "rows": len(test),
                    **{
                        f"{mask}_fraction": float(
                            pd.to_numeric(
                                test[mask]
                                if mask in test
                                else pd.Series(0, index=test.index),
                                errors="coerce",
                            ).mean()
                        )
                        for mask in (
                            "mask_price",
                            "mask_calendar",
                            "mask_weather",
                            "mask_production",
                            "mask_satellite",
                            "mask_graph",
                            "mask_dynamic_graph",
                        )
                    },
                }
            )

            persistence = test["current_price"].to_numpy(dtype=float)
            fold_rows.append(
                {
                    "model": "PERSISTENCE",
                    "variant": "PRICE",
                    "horizon_days": horizon,
                    "fold_id": fold_id,
                    "forecast_origin": origin.date().isoformat(),
                    "train_rows": len(train),
                    "rows_scored": len(test),
                    "feature_count": 1,
                    "backend": "RULE",
                    **core.metric_row(test["target_price"], persistence),
                }
            )
            prediction_parts.append(
                append_prediction_rows(
                    test,
                    persistence,
                    model="PERSISTENCE",
                    variant="PRICE",
                    horizon=horizon,
                    fold_id=fold_id,
                    origin=origin,
                )
            )

            for variant in variants:
                features = requested_features(horizon_frame, variant)
                prediction, feature_count, backend = fit_lgbm(
                    train,
                    test,
                    features,
                    "target_logratio",
                    SEED + horizon * 100 + fold_id,
                )
                name = f"LGBM_LOGRATIO__{variant}"
                fold_rows.append(
                    {
                        "model": name,
                        "variant": variant,
                        "horizon_days": horizon,
                        "fold_id": fold_id,
                        "forecast_origin": origin.date().isoformat(),
                        "train_rows": len(train),
                        "rows_scored": len(test),
                        "feature_count": feature_count,
                        "backend": backend,
                        **core.metric_row(test["target_price"], prediction),
                    }
                )
                prediction_parts.append(
                    append_prediction_rows(
                        test,
                        prediction,
                        model=name,
                        variant=variant,
                        horizon=horizon,
                        fold_id=fold_id,
                        origin=origin,
                    )
                )

            full_features = requested_features(horizon_frame, full_variant)
            catboost_targets = (
                ()
                if args.skip_catboost or full_variant not in variants
                else ("target_logratio", "target_scaled_delta")
            )
            for target in catboost_targets:
                prediction, feature_count, backend = fit_catboost(
                    train,
                    test,
                    full_features,
                    target,
                    SEED + horizon * 100 + fold_id + (1 if target.endswith("logratio") else 2),
                )
                target_name = "LOGRATIO" if target.endswith("logratio") else "SCALED_DELTA"
                name = f"CATBOOST_{target_name}__{full_variant}"
                fold_rows.append(
                    {
                        "model": name,
                        "variant": full_variant,
                        "horizon_days": horizon,
                        "fold_id": fold_id,
                        "forecast_origin": origin.date().isoformat(),
                        "train_rows": len(train),
                        "rows_scored": len(test),
                        "feature_count": feature_count,
                        "backend": backend,
                        **core.metric_row(test["target_price"], prediction),
                    }
                )
                prediction_parts.append(
                    append_prediction_rows(
                        test,
                        prediction,
                        model=name,
                        variant=full_variant,
                        horizon=horizon,
                        fold_id=fold_id,
                        origin=origin,
                    )
                )

            fold_frame = pd.DataFrame(fold_rows)
            oof = pd.concat(prediction_parts, ignore_index=True)
            fold_frame.to_csv(args.output / "fold_metrics.partial.csv", index=False)
            oof.to_parquet(args.output / "oof_predictions.partial.parquet", index=False)
            print(
                f"completed h={horizon} fold={fold_id} origin={origin.date()} "
                f"train={len(train):,} test={len(test):,}",
                flush=True,
            )

    fold_frame = pd.DataFrame(fold_rows)
    oof = pd.concat(prediction_parts, ignore_index=True)
    pooled = pooled_metrics(oof)
    fold_frame.to_csv(args.output / "fold_metrics.csv", index=False)
    oof.to_parquet(args.output / "oof_predictions.parquet", index=False)
    pooled.to_csv(args.output / "pooled_metrics.csv", index=False)
    pd.DataFrame(availability_rows).to_csv(
        args.output / "origin_modality_availability.csv", index=False
    )
    feature_contract = {
        variant: requested_features(add_target_calendar(frame, 7), variant)
        for variant in PROGRESSIVE_VARIANTS
    }
    (args.output / "feature_contract.json").write_text(
        json.dumps(feature_contract, indent=2) + "\n", encoding="utf-8"
    )
    runtime = time.perf_counter() - started
    manifest = {
        "experiment": "implemented_tree_multimodal_progressive_ablation",
        "scientific_scope": (
            "Executable LightGBM/CatBoost trees; proposed TFT/CNN/GNN is not trained here."
        ),
        "origins": [value.date().isoformat() for value in origins],
        "horizons": list(horizons),
        "variants": variants,
        "minimum_history": args.minimum_history,
        "panel": str(args.panel),
        "panel_sha256": sha256(args.panel),
        "static_graph": str(args.static_graph),
        "static_graph_sha256": sha256(args.static_graph),
        "dynamic_graph": str(args.dynamic_graph),
        "dynamic_graph_sha256": sha256(args.dynamic_graph),
        "runtime_seconds": runtime,
        "random_seed": SEED,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "package_versions": {
            package: importlib.metadata.version(package)
            for package in (
                "catboost",
                "lightgbm",
                "numpy",
                "pandas",
                "pyarrow",
                "scikit-learn",
            )
        },
        "best_by_horizon": pooled.sort_values("mae").groupby("horizon_days").first().reset_index().to_dict("records"),
    }
    (args.output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(pooled.to_string(index=False), flush=True)
    print(f"runtime_seconds={runtime:.2f}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--panel",
        type=Path,
        default=ROOT / "data/ready/model_dataset_eligible.parquet",
    )
    parser.add_argument(
        "--static-graph",
        type=Path,
        default=ROOT / "data/processed/province_graph_static.parquet",
    )
    parser.add_argument(
        "--dynamic-graph",
        type=Path,
        default=ROOT / "data/processed/province_graph_dynamic.parquet",
    )
    parser.add_argument(
        "--static-graph-effective-date", default="2026-01-01"
    )
    parser.add_argument("--minimum-history", type=int, default=240)
    parser.add_argument(
        "--origins",
        nargs="+",
        default=[value.date().isoformat() for value in ORIGINS],
    )
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        choices=(7, 14),
        default=list(HORIZONS),
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=tuple(PROGRESSIVE_VARIANTS),
        default=list(PROGRESSIVE_VARIANTS),
    )
    parser.add_argument("--skip-catboost", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results/multimodal_ablation",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
