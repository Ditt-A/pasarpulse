from __future__ import annotations

import argparse
import gc
import json
import math
import os
import re
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

SEED = 42
SEARCH_FOLD_IDS = (2,)          # one development origin per horizon for broad screening
DEV_FOLD_IDS = (1, 2, 3, 4)    # architecture selection only
HOLDOUT_FOLD_IDS = (5, 6, 7)   # untouched confirmation origins
TOP_DEV = 20
TOP_HOLDOUT = 8
MIN_HISTORY = 240


@dataclass(frozen=True)
class Variant:
    name: str
    family: str
    target: str
    feature_set: str
    profile: str
    group_mode: str = "global"


CAT_PROFILES: dict[str, dict[str, Any]] = {
    "shallow_recent": {
        "iterations": 180,
        "depth": 6,
        "learning_rate": 0.075,
        "l2_leaf_reg": 12.0,
        "random_strength": 0.20,
        "subsample": 0.88,
        "window_days": 365,
        "recency_tau": 120.0,
        "prediction_shrink": 0.82,
    },
    "balanced": {
        "iterations": 270,
        "depth": 7,
        "learning_rate": 0.052,
        "l2_leaf_reg": 8.0,
        "random_strength": 0.30,
        "subsample": 0.88,
        "window_days": 540,
        "recency_tau": 240.0,
        "prediction_shrink": 0.92,
    },
    "deep_full": {
        "iterations": 380,
        "depth": 9,
        "learning_rate": 0.035,
        "l2_leaf_reg": 6.0,
        "random_strength": 0.40,
        "subsample": 0.86,
        "window_days": None,
        "recency_tau": 365.0,
        "prediction_shrink": 1.00,
    },
}

XGB_PROFILES: dict[str, dict[str, Any]] = {
    "xgb_shallow": {
        "n_estimators": 340,
        "max_depth": 6,
        "learning_rate": 0.055,
        "min_child_weight": 12.0,
        "subsample": 0.88,
        "colsample_bytree": 0.82,
        "reg_alpha": 0.10,
        "reg_lambda": 6.0,
        "window_days": 540,
        "recency_tau": 180.0,
        "prediction_shrink": 0.90,
    },
    "xgb_deep": {
        "n_estimators": 520,
        "max_depth": 8,
        "learning_rate": 0.032,
        "min_child_weight": 18.0,
        "subsample": 0.86,
        "colsample_bytree": 0.80,
        "reg_alpha": 0.20,
        "reg_lambda": 8.0,
        "window_days": None,
        "recency_tau": 300.0,
        "prediction_shrink": 0.98,
    },
}

TARGETS = ("delta", "logratio", "level", "scaled_delta", "national_residual")
CAT_FEATURE_SETS = (
    "short_price",
    "price_calendar",
    "full_price_calendar",
    "dynamic_graph",
    "graph_production",
    "full_context_geo_missing",
)
XGB_FEATURE_SETS = ("price_calendar", "dynamic_graph", "full_context_geo_missing")


def log(message: str) -> None:
    print(message, flush=True)


def safe_name(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value)).strip("_")


def mae(y: Iterable[float], prediction: Iterable[float]) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(prediction, dtype=float)
    return float(np.mean(np.abs(y_arr - p_arr)))


def metric_row(y: Iterable[float], prediction: Iterable[float]) -> dict[str, float]:
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(prediction, dtype=float)
    denominator = np.abs(y_arr) + np.abs(p_arr)
    return {
        "mae": float(np.mean(np.abs(y_arr - p_arr))),
        "rmse": float(np.sqrt(np.mean((y_arr - p_arr) ** 2))),
        "smape": float(
            np.mean(2.0 * np.abs(y_arr - p_arr) / np.where(denominator == 0, 1.0, denominator))
            * 100.0
        ),
        "mean_error": float(np.mean(p_arr - y_arr)),
    }


def append_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False)


def recursive_coordinate_pairs(value: Any) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    if isinstance(value, (list, tuple)):
        if (
            len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            lon, lat = float(value[0]), float(value[1])
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                pairs.append((lon, lat))
        else:
            for item in value:
                pairs.extend(recursive_coordinate_pairs(item))
    return pairs


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def detect_geo_centroids(panel: pd.DataFrame, root: Path) -> dict[str, tuple[float, float]]:
    candidates = list(root.rglob("indonesia_provinces.geojson"))
    if not candidates:
        candidates = list(root.rglob("*.geojson"))
    if not candidates:
        log("No GeoJSON found; static geographic-neighbor features will remain missing.")
        return {}

    province_by_name = {
        normalize_text(row.province_name): str(row.province_code)
        for row in panel[["province_code", "province_name"]].drop_duplicates().itertuples(index=False)
    }
    centroids: dict[str, tuple[float, float]] = {}
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for feature in payload.get("features", []):
            properties = feature.get("properties", {}) or {}
            property_values = [str(value) for value in properties.values() if value is not None]
            code = None
            for key, value in properties.items():
                key_norm = normalize_text(key)
                text = str(value).strip()
                if "code" in key_norm or "kode" in key_norm or key_norm in {"id", "adm1_pcode"}:
                    digits = re.sub(r"\D", "", text)
                    if digits[:2] in set(panel["province_code"].astype(str)):
                        code = digits[:2]
                        break
            if code is None:
                for value in property_values:
                    normalized = normalize_text(value)
                    if normalized in province_by_name:
                        code = province_by_name[normalized]
                        break
            if code is None:
                continue
            pairs = recursive_coordinate_pairs(feature.get("geometry", {}).get("coordinates", []))
            if not pairs:
                continue
            coordinates = np.asarray(pairs, dtype=float)
            centroids[str(code)] = (
                float(np.nanmedian(coordinates[:, 0])),
                float(np.nanmedian(coordinates[:, 1])),
            )
        if len(centroids) >= max(20, panel["province_code"].nunique() - 4):
            log(f"Geo centroids loaded from {path}: {len(centroids)} provinces")
            break
    return centroids


def haversine_matrix(codes: list[str], centroids: dict[str, tuple[float, float]]) -> np.ndarray:
    coordinates = np.full((len(codes), 2), np.nan, dtype=float)
    for index, code in enumerate(codes):
        if code in centroids:
            coordinates[index] = centroids[code]
    lon = np.deg2rad(coordinates[:, 0])
    lat = np.deg2rad(coordinates[:, 1])
    dlon = lon[:, None] - lon[None, :]
    dlat = lat[:, None] - lat[None, :]
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2.0) ** 2
    distance = 6371.0 * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    invalid = ~np.isfinite(coordinates).all(axis=1)
    distance[invalid, :] = np.inf
    distance[:, invalid] = np.inf
    np.fill_diagonal(distance, np.inf)
    return distance


def add_geo_neighbor_features(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, list[str]]:
    centroids = detect_geo_centroids(panel, root)
    if len(centroids) < 4:
        return panel, []

    province_codes = sorted(panel["province_code"].astype(str).unique())
    distance = haversine_matrix(province_codes, centroids)
    weights = np.zeros_like(distance, dtype=float)
    for row_index in range(len(province_codes)):
        available = np.where(np.isfinite(distance[row_index]))[0]
        if available.size == 0:
            continue
        nearest = available[np.argsort(distance[row_index, available])[:4]]
        local_distance = distance[row_index, nearest]
        scale = max(float(np.nanmedian(local_distance)), 150.0)
        local_weights = np.exp(-local_distance / scale)
        if local_weights.sum() > 0:
            weights[row_index, nearest] = local_weights / local_weights.sum()

    parts: list[pd.DataFrame] = []
    for (commodity, market), group in panel.groupby(["commodity_code", "market_level"], observed=True):
        pivot = group.pivot_table(
            index="date",
            columns="province_code",
            values="price_filled",
            aggfunc="last",
        ).reindex(columns=province_codes)
        values = pivot.to_numpy(dtype=float)
        mask = np.isfinite(values).astype(float)
        numerator = np.nan_to_num(values, nan=0.0) @ weights.T
        denominator = mask @ weights.T
        neighbor_mean = np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan),
            where=denominator > 0,
        )
        long = (
            pd.DataFrame(neighbor_mean, index=pivot.index, columns=province_codes)
            .stack(dropna=False)
            .rename("geo_neighbor_mean")
            .reset_index()
        )
        long["commodity_code"] = commodity
        long["market_level"] = market
        parts.append(long)
    if not parts:
        return panel, []
    geo = pd.concat(parts, ignore_index=True)
    output = panel.merge(
        geo,
        on=["date", "province_code", "commodity_code", "market_level"],
        how="left",
    )
    output["geo_neighbor_gap"] = output["price_filled"] - output["geo_neighbor_mean"]
    geo_group = output.groupby("series_id", observed=True, sort=False)
    output["geo_neighbor_delta_7"] = output["geo_neighbor_mean"] - geo_group["geo_neighbor_mean"].shift(7)
    output["geo_neighbor_delta_14"] = output["geo_neighbor_mean"] - geo_group["geo_neighbor_mean"].shift(14)
    return output, [
        "geo_neighbor_mean",
        "geo_neighbor_gap",
        "geo_neighbor_delta_7",
        "geo_neighbor_delta_14",
    ]


def map_commodity(value: Any) -> str | None:
    text = normalize_text(value)
    if text in {"bm", "bawang merah"} or "bawang merah" in text:
        return "BM"
    if text in {"cmk", "cabai merah keriting", "cabai merah"} or "merah keriting" in text:
        return "CMK"
    if text in {"crm", "cabai rawit merah", "cabai rawit"} or "rawit" in text:
        return "CRM"
    return None


def add_production_features(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, list[str]]:
    paths = list(root.rglob("production_annual.csv"))
    if not paths:
        log("production_annual.csv not found; production feature sets degrade to graph-only.")
        return panel, []
    path = paths[0]
    production = pd.read_csv(path)
    log(f"Production source: {path}; columns={production.columns.tolist()}")

    lower = {column: normalize_text(column) for column in production.columns}
    year_column = next((column for column, value in lower.items() if value in {"year", "tahun"} or "year" in value or "tahun" in value), None)
    province_code_column = next((column for column, value in lower.items() if "province" in value and "code" in value or "kode prov" in value), None)
    province_name_column = next((column for column, value in lower.items() if "province" in value and "name" in value or value in {"province", "provinsi"}), None)
    commodity_code_column = next((column for column, value in lower.items() if "commodity" in value and "code" in value or "kode komod" in value), None)
    commodity_name_column = next((column for column, value in lower.items() if "commodity" in value and "name" in value or value in {"commodity", "komoditas"}), None)
    if year_column is None:
        log("Production table has no detectable year column; skipped.")
        return panel, []

    province_name_to_code = {
        normalize_text(row.province_name): str(row.province_code)
        for row in panel[["province_code", "province_name"]].drop_duplicates().itertuples(index=False)
    }
    normalized = pd.DataFrame()
    normalized["production_year"] = pd.to_numeric(production[year_column], errors="coerce").astype("Int64")
    if province_code_column:
        normalized["province_code"] = production[province_code_column].astype(str).str.extract(r"(\d{2})", expand=False)
    elif province_name_column:
        normalized["province_code"] = production[province_name_column].map(lambda value: province_name_to_code.get(normalize_text(value)))
    else:
        return panel, []
    if commodity_code_column:
        normalized["commodity_code"] = production[commodity_code_column].map(map_commodity)
        missing = normalized["commodity_code"].isna()
        normalized.loc[missing, "commodity_code"] = production.loc[missing, commodity_code_column].astype(str).str.upper()
    elif commodity_name_column:
        normalized["commodity_code"] = production[commodity_name_column].map(map_commodity)
    else:
        return panel, []

    id_columns = {year_column, province_code_column, province_name_column, commodity_code_column, commodity_name_column}
    feature_columns: list[str] = []
    for column in production.columns:
        if column in id_columns:
            continue
        name = normalize_text(column)
        if not any(token in name for token in ["production", "produksi", "harvest", "panen", "yield", "productivity", "produktiv"]):
            continue
        values = pd.to_numeric(production[column], errors="coerce")
        if values.notna().sum() < 20:
            continue
        new_name = "prod_" + safe_name(name)
        normalized[new_name] = values.astype(float)
        feature_columns.append(new_name)
    if not feature_columns:
        numeric_candidates = []
        for column in production.columns:
            if column in id_columns:
                continue
            values = pd.to_numeric(production[column], errors="coerce")
            if values.notna().sum() >= 20:
                numeric_candidates.append((values.notna().sum(), column, values))
        for _, column, values in sorted(numeric_candidates, reverse=True)[:4]:
            new_name = "prod_" + safe_name(column)
            normalized[new_name] = values.astype(float)
            feature_columns.append(new_name)
    normalized = normalized.dropna(subset=["production_year", "province_code", "commodity_code"])
    normalized["production_year"] = normalized["production_year"].astype(int)
    normalized = normalized.groupby(
        ["production_year", "province_code", "commodity_code"], observed=True
    )[feature_columns].mean().reset_index()
    for column in feature_columns:
        median = normalized.groupby(["production_year", "commodity_code"], observed=True)[column].transform("median")
        normalized[f"{column}_rel_nat"] = normalized[column] / median.replace(0, np.nan)
    all_features = feature_columns + [f"{column}_rel_nat" for column in feature_columns]

    output = panel.copy()
    output["production_year"] = output["date"].dt.year - 1  # lag annual statistics to avoid using future-year releases
    output = output.merge(
        normalized,
        on=["production_year", "province_code", "commodity_code"],
        how="left",
    )
    return output, all_features


def add_missingness_and_regime_features(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    output = panel.copy()
    group = output.groupby("series_id", observed=True, sort=False)
    shifted_observed = group["observed"].shift(1).fillna(0)
    feature_names = ["current_is_imputed"]
    output["current_is_imputed"] = (1 - output["observed"].fillna(0)).astype("int8")
    for window in (7, 28, 84):
        values = (
            shifted_observed.groupby(output["series_id"], observed=True)
            .rolling(window, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )
        name = f"observation_rate_{window}"
        output[name] = values.astype("float32")
        feature_names.append(name)
    if "roll_std_7" in output and "roll_std_56" in output:
        output["volatility_regime"] = output["roll_std_7"] / output["roll_std_56"].replace(0, np.nan)
        feature_names.append("volatility_regime")
    if "gap_nat" in output and "nat_std" in output:
        output["gap_nat_z"] = output["gap_nat"] / output["nat_std"].replace(0, np.nan)
        feature_names.append("gap_nat_z")
    if "gap_island" in output and "island_std" in output:
        output["gap_island_z"] = output["gap_island"] / output["island_std"].replace(0, np.nan)
        feature_names.append("gap_island_z")
    return output, feature_names


def enrich_panel(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    output, missing_features = add_missingness_and_regime_features(panel)
    output, production_features = add_production_features(output, root)
    output, geo_features = add_geo_neighbor_features(output, root)
    output = output.replace([np.inf, -np.inf], np.nan)
    return output, {
        "missing": missing_features,
        "production": production_features,
        "geo": geo_features,
    }


def feature_sets(core: Any, panel: pd.DataFrame, context: dict[str, list[str]]) -> dict[str, list[str]]:
    short_lags = [1, 2, 3, 5, 7, 14, 21, 28, 42]
    short_features = ["price_filled"]
    short_features += [f"price_lag_{lag}" for lag in short_lags]
    short_features += [f"delta_lag_{lag}" for lag in short_lags]
    short_features += [f"ratio_lag_{lag}" for lag in short_lags]
    short_features += [
        f"{prefix}_{window}"
        for window in [7, 14, 28, 56]
        for prefix in ["roll_mean", "roll_std", "roll_min", "roll_max", "mean_gap"]
    ]
    short_features += [f"{prefix}_{span}" for span in [7, 14, 28] for prefix in ["ewm", "ewm_gap"]]

    categories = list(core.CATEGORICAL)
    target_calendar = ["target_dow", "target_month", "target_doy_sin", "target_doy_cos"]
    sets = {
        "short_price": short_features + categories,
        "price_calendar": short_features + list(core.CALENDAR) + target_calendar + categories,
        "full_price_calendar": list(core.PRICE_BASE) + list(core.CALENDAR) + target_calendar + categories,
        "dynamic_graph": list(core.PRICE_BASE) + list(core.CALENDAR) + list(core.GRAPH) + target_calendar + categories,
        "graph_production": list(core.PRICE_BASE) + list(core.CALENDAR) + list(core.GRAPH) + context["production"] + target_calendar + categories,
        "full_context_geo_missing": list(core.PRICE_BASE) + list(core.CALENDAR) + list(core.GRAPH) + context["production"] + context["geo"] + context["missing"] + target_calendar + categories,
    }
    return {
        name: list(dict.fromkeys(feature for feature in features if feature in panel.columns or feature.startswith("target_")))
        for name, features in sets.items()
    }


def build_catalog() -> list[Variant]:
    variants: list[Variant] = []
    for target in TARGETS:
        for feature_set in CAT_FEATURE_SETS:
            for profile in CAT_PROFILES:
                variants.append(
                    Variant(
                        name=f"cat__{target}__{feature_set}__{profile}",
                        family="catboost_gpu",
                        target=target,
                        feature_set=feature_set,
                        profile=profile,
                    )
                )
    for target in TARGETS:
        for feature_set in XGB_FEATURE_SETS:
            for profile in XGB_PROFILES:
                variants.append(
                    Variant(
                        name=f"xgb__{target}__{feature_set}__{profile}",
                        family="xgboost_gpu",
                        target=target,
                        feature_set=feature_set,
                        profile=profile,
                    )
                )
    return variants


def supervised_frame(core: Any, panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    frame = core.create_supervised(panel, horizon)
    valid = (
        (frame["observed"] == 1)
        & (frame["target_observed"] == 1)
        & frame["target_price"].notna()
        & frame["price_filled"].notna()
    )
    frame = frame.loc[valid].copy()
    frame["target_scaled_delta"] = frame["target_delta"] / frame["price_filled"].clip(lower=5000.0)
    frame["target_national_residual"] = frame["target_price"] - frame["nat_median"].fillna(frame["price_filled"])
    return frame


def training_target_name(target: str) -> str:
    return {
        "delta": "target_delta",
        "logratio": "target_logratio",
        "level": "target_price",
        "scaled_delta": "target_scaled_delta",
        "national_residual": "target_national_residual",
    }[target]


def convert_prediction(target: str, raw_prediction: np.ndarray, test: pd.DataFrame) -> np.ndarray:
    current = test["price_filled"].to_numpy(dtype=float)
    if target == "delta":
        prediction = current + raw_prediction
    elif target == "logratio":
        prediction = current * np.exp(np.clip(raw_prediction, -1.2, 1.2))
    elif target == "level":
        prediction = raw_prediction
    elif target == "scaled_delta":
        prediction = current + raw_prediction * np.maximum(current, 5000.0)
    elif target == "national_residual":
        base = test["nat_median"].fillna(test["price_filled"]).to_numpy(dtype=float)
        prediction = base + raw_prediction
    else:
        raise ValueError(target)
    return np.clip(prediction, 1000.0, 500000.0)


def profile_for(variant: Variant) -> dict[str, Any]:
    if variant.family == "catboost_gpu":
        return CAT_PROFILES[variant.profile]
    return XGB_PROFILES[variant.profile]


def sample_weights(train: pd.DataFrame, origin: pd.Timestamp, tau: float) -> np.ndarray:
    age = (origin - train["date"]).dt.days.clip(lower=0).to_numpy(dtype=float)
    recency = 0.25 + 0.75 * np.exp(-age / tau)
    group_size = train.groupby(["commodity_code", "market_level"], observed=True)["series_id"].transform("count").to_numpy(dtype=float)
    balance = np.sqrt(np.nanmedian(group_size) / np.maximum(group_size, 1.0))
    target_volatility = train["roll_std_28"].fillna(train["roll_std_56"]).fillna(0).to_numpy(dtype=float)
    volatility_scale = np.nanmedian(target_volatility[target_volatility > 0]) if np.any(target_volatility > 0) else 1.0
    volatility = 1.0 + 0.15 * np.clip(target_volatility / max(volatility_scale, 1.0), 0.0, 4.0)
    return np.asarray(recency * balance * volatility, dtype="float32")


def prepare_cat_frames(train: pd.DataFrame, test: pd.DataFrame, features: list[str], categories: list[str]):
    train_frame = train[features].copy()
    test_frame = test[features].copy()
    categorical = [column for column in categories if column in features]
    for column in categorical:
        train_frame[column] = train_frame[column].fillna("missing").astype(str)
        test_frame[column] = test_frame[column].fillna("missing").astype(str)
    numeric = [column for column in features if column not in categorical]
    for column in numeric:
        train_frame[column] = pd.to_numeric(train_frame[column], errors="coerce").astype("float32")
        test_frame[column] = pd.to_numeric(test_frame[column], errors="coerce").astype("float32")
    return train_frame, test_frame, categorical


def fit_catboost(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    categories: list[str],
    target_column: str,
    weights: np.ndarray,
    profile: dict[str, Any],
    seed: int,
) -> np.ndarray:
    from catboost import CatBoostRegressor

    train_frame, test_frame, categorical = prepare_cat_frames(train, test, features, categories)
    model = CatBoostRegressor(
        loss_function="RMSE",
        eval_metric="RMSE",
        iterations=int(profile["iterations"]),
        depth=int(profile["depth"]),
        learning_rate=float(profile["learning_rate"]),
        l2_leaf_reg=float(profile["l2_leaf_reg"]),
        random_seed=int(seed),
        random_strength=float(profile["random_strength"]),
        bootstrap_type="Bernoulli",
        subsample=float(profile["subsample"]),
        border_count=128,
        max_ctr_complexity=2,
        task_type="GPU",
        devices="0",
        gpu_ram_part=0.72,
        allow_writing_files=False,
        verbose=False,
    )
    model.fit(
        train_frame,
        train[target_column].astype("float32"),
        cat_features=categorical,
        sample_weight=weights,
    )
    prediction = model.predict(test_frame)
    del model, train_frame, test_frame
    gc.collect()
    return np.asarray(prediction, dtype=float)


def prepare_xgb_frames(train: pd.DataFrame, test: pd.DataFrame, features: list[str], categories: list[str]):
    train_frame = train[features].copy()
    test_frame = test[features].copy()
    categorical = [column for column in categories if column in features]
    for column in categorical:
        values = pd.concat([train_frame[column], test_frame[column]], ignore_index=True).fillna("missing").astype(str)
        mapping = {value: index for index, value in enumerate(values.unique())}
        train_frame[column] = train_frame[column].fillna("missing").astype(str).map(mapping).astype("int32")
        test_frame[column] = test_frame[column].fillna("missing").astype(str).map(mapping).astype("int32")
    for column in features:
        if column not in categorical:
            train_frame[column] = pd.to_numeric(train_frame[column], errors="coerce").astype("float32")
            test_frame[column] = pd.to_numeric(test_frame[column], errors="coerce").astype("float32")
    return train_frame, test_frame


def fit_xgboost(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    categories: list[str],
    target_column: str,
    weights: np.ndarray,
    profile: dict[str, Any],
    seed: int,
) -> np.ndarray:
    from xgboost import XGBRegressor

    train_frame, test_frame = prepare_xgb_frames(train, test, features, categories)
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=int(profile["n_estimators"]),
        max_depth=int(profile["max_depth"]),
        learning_rate=float(profile["learning_rate"]),
        min_child_weight=float(profile["min_child_weight"]),
        subsample=float(profile["subsample"]),
        colsample_bytree=float(profile["colsample_bytree"]),
        reg_alpha=float(profile["reg_alpha"]),
        reg_lambda=float(profile["reg_lambda"]),
        max_bin=256,
        tree_method="hist",
        device="cuda",
        random_state=int(seed),
        n_jobs=2,
        verbosity=0,
    )
    model.fit(train_frame, train[target_column].astype("float32"), sample_weight=weights)
    prediction = model.predict(test_frame)
    del model, train_frame, test_frame
    gc.collect()
    return np.asarray(prediction, dtype=float)


def split_context(
    frame: pd.DataFrame,
    horizon: int,
    origin: pd.Timestamp,
    profile: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = frame[
        (frame["date"] < origin)
        & ((frame["date"] + pd.Timedelta(days=horizon)) <= origin)
    ].copy()
    test = frame[frame["date"] == origin].copy()
    counts = train.groupby("series_id", observed=True).size()
    allowed = counts[counts >= MIN_HISTORY].index
    train = train[train["series_id"].isin(allowed)].copy()
    test = test[test["series_id"].isin(allowed)].copy()
    window_days = profile.get("window_days")
    if window_days:
        cutoff = origin - pd.Timedelta(days=int(window_days))
        train = train[train["date"] >= cutoff].copy()
    return train, test


def fit_variant_groups(
    variant: Variant,
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    categories: list[str],
    origin: pd.Timestamp,
    seed: int,
) -> np.ndarray:
    profile = profile_for(variant)
    target_column = training_target_name(variant.target)
    prediction = np.full(len(test), np.nan, dtype=float)
    if variant.group_mode == "global":
        groups = [(None, train.index, test.index)]
    else:
        group_columns = {
            "per_commodity": ["commodity_code"],
            "per_market": ["market_level"],
            "per_commodity_market": ["commodity_code", "market_level"],
        }[variant.group_mode]
        groups = []
        for key, test_group in test.groupby(group_columns, observed=True):
            key_tuple = key if isinstance(key, tuple) else (key,)
            train_mask = np.ones(len(train), dtype=bool)
            for column, value in zip(group_columns, key_tuple):
                train_mask &= train[column].to_numpy() == value
            train_group = train.loc[train_mask]
            if len(train_group) < 1000:
                train_group = train
            groups.append((key_tuple, train_group.index, test_group.index))

    test_position = pd.Series(np.arange(len(test)), index=test.index)
    for group_index, (_, train_index, test_index) in enumerate(groups):
        group_train = train.loc[train_index]
        group_test = test.loc[test_index]
        weights = sample_weights(group_train, origin, float(profile["recency_tau"]))
        if variant.family == "catboost_gpu":
            raw = fit_catboost(
                group_train,
                group_test,
                features,
                categories,
                target_column,
                weights,
                profile,
                seed + group_index,
            )
        else:
            raw = fit_xgboost(
                group_train,
                group_test,
                features,
                categories,
                target_column,
                weights,
                profile,
                seed + group_index,
            )
        converted = convert_prediction(variant.target, raw, group_test)
        current = group_test["price_filled"].to_numpy(dtype=float)
        shrink = float(profile["prediction_shrink"])
        converted = current + shrink * (converted - current)
        maximum_change = np.maximum(9000.0, 0.45 * current)
        converted = np.clip(converted, current - maximum_change, current + maximum_change)
        positions = test_position.loc[test_index].to_numpy(dtype=int)
        prediction[positions] = np.clip(converted, 1000.0, 500000.0)
    return prediction


def evaluation_key(variant_name: str, horizon: int, fold_id: int) -> tuple[str, int, int]:
    return variant_name, int(horizon), int(fold_id)


def load_evaluations(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def evaluate_one(
    core: Any,
    supervised: dict[int, pd.DataFrame],
    sets: dict[str, list[str]],
    variant: Variant,
    horizon: int,
    fold_id: int,
    evaluations_path: Path,
    predictions_path: Path,
    existing_keys: set[tuple[str, int, int]],
) -> bool:
    key = evaluation_key(variant.name, horizon, fold_id)
    if key in existing_keys:
        return True
    origin = pd.Timestamp(core.ORIGINS[fold_id - 1])
    profile = profile_for(variant)
    train, test = split_context(supervised[horizon], horizon, origin, profile)
    if train.empty or test.empty:
        return False
    features = [feature for feature in sets[variant.feature_set] if feature in train.columns]
    target_column = training_target_name(variant.target)
    train = train[train[target_column].notna()].copy()
    if train.empty:
        return False
    baseline_prediction = test["price_filled"].to_numpy(dtype=float)
    baseline_mae = mae(test["target_price"], baseline_prediction)
    started = time.time()
    try:
        prediction = fit_variant_groups(
            variant,
            train,
            test,
            features,
            list(core.CATEGORICAL),
            origin,
            seed=SEED + horizon * 1000 + fold_id * 100,
        )
        metrics = metric_row(test["target_price"], prediction)
        status = "success"
        error = ""
    except Exception as exc:
        prediction = np.full(len(test), np.nan)
        metrics = {"mae": np.nan, "rmse": np.nan, "smape": np.nan, "mean_error": np.nan}
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        log(f"FAILED {variant.name} h={horizon} fold={fold_id}: {error}")
        traceback.print_exc()
    runtime = time.time() - started
    row = {
        **asdict(variant),
        "horizon_days": horizon,
        "fold_id": fold_id,
        "forecast_origin": origin.date().isoformat(),
        "rows_scored": len(test),
        "baseline_mae": baseline_mae,
        "mae_ratio": metrics["mae"] / baseline_mae if np.isfinite(metrics["mae"]) and baseline_mae > 0 else np.nan,
        "runtime_seconds": runtime,
        "status": status,
        "error": error,
        **metrics,
    }
    append_csv(pd.DataFrame([row]), evaluations_path)
    if status == "success":
        output = test[
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
        output = output.rename(
            columns={
                "date": "forecast_origin",
                "target_price": "actual_price",
                "price_filled": "current_price",
            }
        )
        output["target_date"] = output["forecast_origin"] + pd.Timedelta(days=horizon)
        output["horizon_days"] = horizon
        output["fold_id"] = fold_id
        output["variant"] = variant.name
        output["predicted_price"] = prediction
        output["absolute_error"] = np.abs(output["actual_price"] - output["predicted_price"])
        append_csv(output, predictions_path)
    existing_keys.add(key)
    log(
        f"{status.upper()} {variant.name} h={horizon} fold={fold_id} "
        f"MAE={metrics['mae']:.2f} ratio={row['mae_ratio']:.4f} runtime={runtime:.1f}s"
    )
    return status == "success"


def rank_variants(evaluations: pd.DataFrame, fold_ids: Iterable[int]) -> pd.DataFrame:
    successful = evaluations[
        (evaluations["status"] == "success")
        & evaluations["fold_id"].isin(list(fold_ids))
    ].copy()
    expected_contexts = len(set(fold_ids)) * 2
    ranking = (
        successful.groupby(
            ["name", "family", "target", "feature_set", "profile", "group_mode"],
            observed=True,
        )
        .agg(
            mean_mae_ratio=("mae_ratio", "mean"),
            median_mae_ratio=("mae_ratio", "median"),
            worst_mae_ratio=("mae_ratio", "max"),
            mean_mae=("mae", "mean"),
            contexts=("mae", "count"),
            runtime_seconds=("runtime_seconds", "sum"),
        )
        .reset_index()
    )
    ranking = ranking[ranking["contexts"] >= expected_contexts]
    ranking["robust_score"] = (
        0.55 * ranking["mean_mae_ratio"]
        + 0.25 * ranking["median_mae_ratio"]
        + 0.20 * ranking["worst_mae_ratio"]
    )
    return ranking.sort_values(["robust_score", "mean_mae_ratio", "runtime_seconds"]).reset_index(drop=True)


def variant_lookup(catalog: list[Variant]) -> dict[str, Variant]:
    return {variant.name: variant for variant in catalog}


def run_phase(
    phase_name: str,
    variants: list[Variant],
    fold_ids: Iterable[int],
    core: Any,
    supervised: dict[int, pd.DataFrame],
    sets: dict[str, list[str]],
    evaluations_path: Path,
    predictions_path: Path,
) -> None:
    evaluations = load_evaluations(evaluations_path)
    existing_keys = {
        evaluation_key(row.name, row.horizon_days, row.fold_id)
        for row in evaluations.itertuples(index=False)
    } if not evaluations.empty else set()
    log(f"=== {phase_name}: {len(variants)} variants × folds {list(fold_ids)} × horizons {list(core.HORIZONS)} ===")
    for variant_index, variant in enumerate(variants, 1):
        log(f"[{phase_name}] variant {variant_index}/{len(variants)}: {variant.name}")
        for horizon in core.HORIZONS:
            for fold_id in fold_ids:
                evaluate_one(
                    core,
                    supervised,
                    sets,
                    variant,
                    int(horizon),
                    int(fold_id),
                    evaluations_path,
                    predictions_path,
                    existing_keys,
                )


def evaluation_predictions(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["forecast_origin", "target_date"])


def add_group_refinements(
    best_variant: Variant,
    core: Any,
    supervised: dict[int, pd.DataFrame],
    sets: dict[str, list[str]],
    evaluations_path: Path,
    predictions_path: Path,
) -> list[Variant]:
    refinements = [
        Variant(
            name=f"{best_variant.name}__per_commodity",
            family=best_variant.family,
            target=best_variant.target,
            feature_set=best_variant.feature_set,
            profile=best_variant.profile,
            group_mode="per_commodity",
        ),
        Variant(
            name=f"{best_variant.name}__per_market",
            family=best_variant.family,
            target=best_variant.target,
            feature_set=best_variant.feature_set,
            profile=best_variant.profile,
            group_mode="per_market",
        ),
        Variant(
            name=f"{best_variant.name}__per_commodity_market",
            family=best_variant.family,
            target=best_variant.target,
            feature_set=best_variant.feature_set,
            profile=best_variant.profile,
            group_mode="per_commodity_market",
        ),
    ]
    run_phase(
        "group_refinement",
        refinements,
        tuple(range(1, 8)),
        core,
        supervised,
        sets,
        evaluations_path,
        predictions_path,
    )
    return refinements


def load_incumbent_predictions(root: Path) -> pd.DataFrame:
    candidates = list(root.rglob("proposed_model_run/results/oof_predictions.csv"))
    candidates += list(root.rglob("proposed_model_run/results/oof_predictions.csv"))
    for path in candidates:
        try:
            frame = pd.read_csv(path, parse_dates=["forecast_origin", "target_date"])
        except Exception:
            continue
        if "model" not in frame:
            continue
        subset = frame[frame["model"].isin(["expert_lgb_logratio", "PROPOSED_tree_dynamic_graph_ensemble"])].copy()
        if subset.empty:
            continue
        subset["variant"] = "INCUMBENT_" + subset["model"].astype(str)
        subset = subset.rename(columns={"actual_price": "actual_price", "predicted_price": "predicted_price"})
        keep = [
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
            "variant",
            "predicted_price",
        ]
        return subset[[column for column in keep if column in subset.columns]]
    return pd.DataFrame()


def candidate_pivot(predictions: pd.DataFrame, candidate_names: list[str]) -> pd.DataFrame:
    key_columns = [
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
    subset = predictions[predictions["variant"].isin(candidate_names)].copy()
    return (
        subset.pivot_table(
            index=key_columns,
            columns="variant",
            values="predicted_price",
            aggfunc="first",
        )
        .reset_index()
    )


def optimize_simplex(y: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    from scipy.optimize import minimize

    number = matrix.shape[1]
    starts = [np.ones(number) / number]
    starts.extend(np.eye(number))
    best = None
    for start in starts:
        result = minimize(
            lambda weights: np.mean(np.abs(y - matrix @ weights)) + 20.0 * np.sum(weights ** 2),
            start,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * number,
            constraints=({"type": "eq", "fun": lambda weights: weights.sum() - 1.0},),
            options={"maxiter": 400, "ftol": 1e-9},
        )
        if result.success and (best is None or result.fun < best.fun):
            best = result
    if best is None:
        return np.ones(number) / number
    weights = np.clip(best.x, 0.0, 1.0)
    return weights / weights.sum()


def evaluate_ensembles(
    predictions: pd.DataFrame,
    candidates: list[str],
    output_directory: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = candidate_pivot(predictions, candidates)
    prediction_rows: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    for horizon, horizon_frame in pivot.groupby("horizon_days", observed=True):
        available = [candidate for candidate in candidates if candidate in horizon_frame.columns]
        if len(available) < 2:
            continue
        dev = horizon_frame[horizon_frame["fold_id"].isin(DEV_FOLD_IDS)].dropna(subset=available)
        holdout = horizon_frame[horizon_frame["fold_id"].isin(HOLDOUT_FOLD_IDS)].dropna(subset=available)
        if dev.empty or holdout.empty:
            continue
        dev_matrix = dev[available].to_numpy(dtype=float)
        holdout_matrix = holdout[available].to_numpy(dtype=float)
        weights = optimize_simplex(dev["actual_price"].to_numpy(dtype=float), dev_matrix)
        methods: dict[str, np.ndarray] = {
            "FIXED_DEV_NNMAE_BLEND": holdout_matrix @ weights,
            "DEV_TOP1": holdout[available[int(np.argmin([mae(dev["actual_price"], dev[candidate]) for candidate in available]))]].to_numpy(dtype=float),
            "EQUAL_TOP3": holdout_matrix[:, np.argsort([mae(dev["actual_price"], dev[candidate]) for candidate in available])[:3]].mean(axis=1),
        }
        # Dev-selected blend with persistence shrinkage.
        blend_dev = dev_matrix @ weights
        current_dev = dev["current_price"].to_numpy(dtype=float)
        alpha_grid = np.linspace(0.0, 1.0, 21)
        alpha = min(alpha_grid, key=lambda value: mae(dev["actual_price"], current_dev + value * (blend_dev - current_dev)))
        current_holdout = holdout["current_price"].to_numpy(dtype=float)
        methods["DEV_SHRUNK_NNMAE_BLEND"] = current_holdout + alpha * ((holdout_matrix @ weights) - current_holdout)

        # Commodity × market router learned exclusively on development origins.
        router_prediction = np.empty(len(holdout), dtype=float)
        for group_values, holdout_group in holdout.groupby(["commodity_code", "market_level"], observed=True):
            dev_group = dev[
                (dev["commodity_code"] == group_values[0])
                & (dev["market_level"] == group_values[1])
            ]
            source = dev_group if len(dev_group) >= 30 else dev
            selected = min(available, key=lambda candidate: mae(source["actual_price"], source[candidate]))
            positions = holdout.index.get_indexer(holdout_group.index)
            router_prediction[positions] = holdout_group[selected].to_numpy(dtype=float)
        methods["DEV_COMMODITY_MARKET_ROUTER"] = router_prediction

        for method, prediction in methods.items():
            metrics = metric_row(holdout["actual_price"], prediction)
            metric_rows.append(
                {
                    "model": method,
                    "horizon_days": int(horizon),
                    "scope": "holdout_folds_5_7",
                    "rows": len(holdout),
                    "weights": json.dumps(dict(zip(available, weights))),
                    "shrink_alpha": alpha if method == "DEV_SHRUNK_NNMAE_BLEND" else np.nan,
                    **metrics,
                }
            )
            part = holdout[
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
            part["variant"] = method
            part["predicted_price"] = np.clip(prediction, 1000.0, 500000.0)
            part["absolute_error"] = np.abs(part["actual_price"] - part["predicted_price"])
            prediction_rows.append(part)
    metrics_frame = pd.DataFrame(metric_rows).sort_values(["horizon_days", "mae"])
    predictions_frame = pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame()
    metrics_frame.to_csv(output_directory / "ensemble_holdout_metrics.csv", index=False)
    predictions_frame.to_csv(output_directory / "ensemble_holdout_predictions.csv", index=False)
    return metrics_frame, predictions_frame


def summarize_variants(
    evaluations: pd.DataFrame,
    names: list[str],
    scope_folds: Iterable[int],
    scope_name: str,
) -> pd.DataFrame:
    subset = evaluations[
        (evaluations["status"] == "success")
        & evaluations["name"].isin(names)
        & evaluations["fold_id"].isin(list(scope_folds))
    ]
    rows = []
    for (name, horizon), group in subset.groupby(["name", "horizon_days"], observed=True):
        rows.append(
            {
                "variant": name,
                "horizon_days": int(horizon),
                "scope": scope_name,
                "folds": group["fold_id"].nunique(),
                "rows": int(group["rows_scored"].sum()),
                "mae": float(np.average(group["mae"], weights=group["rows_scored"])),
                "mean_mae_ratio": float(np.average(group["mae_ratio"], weights=group["rows_scored"])),
                "worst_fold_mae": float(group["mae"].max()),
                "runtime_seconds": float(group["runtime_seconds"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["scope", "horizon_days", "mae"])


def run_sweep(core: Any, panel: pd.DataFrame, root: Path, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    started = time.time()
    enriched, context = enrich_panel(panel, root)
    sets = feature_sets(core, enriched, context)
    catalog = build_catalog()
    pd.DataFrame([asdict(variant) for variant in catalog]).to_csv(output_directory / "variant_catalog.csv", index=False)
    (output_directory / "feature_context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
    log(f"Variant catalog contains {len(catalog)} distinct architectures/pipelines.")
    log(f"Feature-set sizes: { {name: len(features) for name, features in sets.items()} }")

    supervised = {int(horizon): supervised_frame(core, enriched, int(horizon)) for horizon in core.HORIZONS}
    evaluations_path = output_directory / "evaluations.csv"
    predictions_path = output_directory / "predictions.csv"

    run_phase(
        "phase1_broad_screen",
        catalog,
        SEARCH_FOLD_IDS,
        core,
        supervised,
        sets,
        evaluations_path,
        predictions_path,
    )
    evaluations = load_evaluations(evaluations_path)
    phase1_ranking = rank_variants(evaluations, SEARCH_FOLD_IDS)
    phase1_ranking.to_csv(output_directory / "phase1_ranking.csv", index=False)
    if phase1_ranking.empty:
        raise RuntimeError("No architecture completed the broad screen")
    lookup = variant_lookup(catalog)
    dev_variants = [lookup[name] for name in phase1_ranking.head(TOP_DEV)["name"] if name in lookup]

    run_phase(
        "phase2_development",
        dev_variants,
        DEV_FOLD_IDS,
        core,
        supervised,
        sets,
        evaluations_path,
        predictions_path,
    )
    evaluations = load_evaluations(evaluations_path)
    dev_ranking = rank_variants(evaluations, DEV_FOLD_IDS)
    dev_ranking.to_csv(output_directory / "phase2_dev_ranking.csv", index=False)
    promoted = [lookup[name] for name in dev_ranking.head(TOP_HOLDOUT)["name"] if name in lookup]

    run_phase(
        "phase3_holdout_confirmation",
        promoted,
        HOLDOUT_FOLD_IDS,
        core,
        supervised,
        sets,
        evaluations_path,
        predictions_path,
    )
    evaluations = load_evaluations(evaluations_path)
    holdout_ranking = rank_variants(evaluations, HOLDOUT_FOLD_IDS)
    holdout_ranking.to_csv(output_directory / "phase3_holdout_ranking.csv", index=False)

    best_dev_name = str(dev_ranking.iloc[0]["name"])
    best_variant = lookup[best_dev_name]
    refinements = add_group_refinements(
        best_variant,
        core,
        supervised,
        sets,
        evaluations_path,
        predictions_path,
    )
    evaluations = load_evaluations(evaluations_path)

    promoted_names = [variant.name for variant in promoted]
    refinement_names = [variant.name for variant in refinements]
    full_summary = summarize_variants(
        evaluations,
        promoted_names + refinement_names,
        range(1, 8),
        "all_7_origins_descriptive",
    )
    holdout_summary = summarize_variants(
        evaluations,
        promoted_names + refinement_names,
        HOLDOUT_FOLD_IDS,
        "holdout_origins_5_7",
    )
    summary = pd.concat([full_summary, holdout_summary], ignore_index=True)
    summary.to_csv(output_directory / "final_variant_metrics.csv", index=False)

    predictions = evaluation_predictions(predictions_path)
    incumbent = load_incumbent_predictions(root)
    if not incumbent.empty:
        predictions = pd.concat([predictions, incumbent], ignore_index=True, sort=False)
    candidate_names = promoted_names + refinement_names
    if not incumbent.empty:
        candidate_names += sorted(incumbent["variant"].unique().tolist())
    candidate_names = list(dict.fromkeys(candidate_names))
    ensemble_metrics, _ = evaluate_ensembles(predictions, candidate_names, output_directory)

    best_holdout = holdout_summary.sort_values(["horizon_days", "mae"]).groupby("horizon_days", observed=True).head(1)
    result = {
        "protocol": {
            "broad_screen_fold_ids": list(SEARCH_FOLD_IDS),
            "development_fold_ids": list(DEV_FOLD_IDS),
            "holdout_fold_ids": list(HOLDOUT_FOLD_IDS),
            "horizons": [int(value) for value in core.HORIZONS],
            "origins": [pd.Timestamp(value).date().isoformat() for value in core.ORIGINS],
        },
        "catalog_size": len(catalog),
        "successful_screen_variants": int(len(phase1_ranking)),
        "promoted_to_development": promoted_names,
        "best_development_variant": best_dev_name,
        "group_refinements": refinement_names,
        "best_holdout_by_horizon": best_holdout.to_dict(orient="records"),
        "best_ensemble_holdout_by_horizon": (
            ensemble_metrics.sort_values(["horizon_days", "mae"]).groupby("horizon_days", observed=True).head(1).to_dict(orient="records")
            if not ensemble_metrics.empty
            else []
        ),
        "runtime_seconds": time.time() - started,
    }
    (output_directory / "best_model_summary.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (output_directory / "runtime_seconds.txt").write_text(str(time.time() - started), encoding="utf-8")
    log("=== FINAL HOLDOUT SUMMARY ===")
    log(holdout_summary.sort_values(["horizon_days", "mae"]).to_string(index=False))
    if not ensemble_metrics.empty:
        log("=== FINAL HOLDOUT ENSEMBLES ===")
        log(ensemble_metrics.to_string(index=False))


def load_core(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("pasarpulse_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    core = load_core(args.core)
    panel = pd.read_parquet(args.panel)
    run_sweep(core, panel, args.root, args.outdir)



def add_geo_neighbor_features(panel, root):
    import json as _json
    import math as _math
    import re as _re
    from pathlib import Path as _Path

    def _norm(value):
        return _re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()

    def _coordinate_points(value):
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
                yield float(value[0]), float(value[1])
            else:
                for item in value:
                    yield from _coordinate_points(item)

    candidates = list(_Path(root).rglob("*province*.geojson"))
    candidates += list(_Path(root).rglob("*provinces*.json"))
    if not candidates:
        print("Geo override: no province GeoJSON found; continuing without geo features", flush=True)
        return panel, []
    geo_path = sorted(set(candidates), key=lambda path: ("reference" not in str(path), len(str(path))))[0]
    geo_payload = _json.loads(geo_path.read_text(encoding="utf-8"))

    lookup = {
        _norm(name): (str(code).zfill(2), str(name))
        for code, name in panel[["province_code", "province_name"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }
    centroid_rows = []
    for feature in geo_payload.get("features", []):
        properties = feature.get("properties") or {}
        matched = None
        for value in properties.values():
            normalized = _norm(value)
            if normalized in lookup:
                matched = lookup[normalized]
                break
        if matched is None:
            continue
        geometry = feature.get("geometry") or {}
        points = list(_coordinate_points(geometry.get("coordinates", [])))
        if not points:
            continue
        centroid_rows.append({
            "province_code": matched[0],
            "geo_longitude": float(np.mean([point[0] for point in points])),
            "geo_latitude": float(np.mean([point[1] for point in points])),
        })
    centroids = pd.DataFrame(centroid_rows)
    if centroids.empty:
        print("Geo override: no province names matched; continuing without geo features", flush=True)
        return panel, []
    centroids["province_code"] = centroids["province_code"].astype(str).str.zfill(2)
    centroids = centroids.drop_duplicates("province_code")
    print(f"Geo override matched {len(centroids)} centroids from {geo_path}", flush=True)
    if len(centroids) < 20:
        print("Geo override: fewer than 20 matched provinces; continuing without geo features", flush=True)
        return panel, []

    def _distance_km(lat1, lon1, lat2, lon2):
        radius = 6371.0088
        phi1, phi2 = _math.radians(lat1), _math.radians(lat2)
        dphi = _math.radians(lat2 - lat1)
        dlambda = _math.radians(lon2 - lon1)
        value = _math.sin(dphi / 2.0) ** 2 + _math.cos(phi1) * _math.cos(phi2) * _math.sin(dlambda / 2.0) ** 2
        return 2.0 * radius * _math.asin(min(1.0, _math.sqrt(value)))

    edge_rows = []
    records = list(centroids.itertuples(index=False))
    for current in records:
        distances = []
        for neighbor in records:
            if current.province_code == neighbor.province_code:
                continue
            distance = _distance_km(
                current.geo_latitude,
                current.geo_longitude,
                neighbor.geo_latitude,
                neighbor.geo_longitude,
            )
            distances.append((distance, neighbor.province_code))
        for distance, neighbor_code in sorted(distances)[:4]:
            edge_rows.append({
                "province_code": str(current.province_code).zfill(2),
                "neighbor_code": str(neighbor_code).zfill(2),
                "geo_neighbor_distance_km": distance,
                "geo_neighbor_weight": 1.0 / (25.0 + distance),
            })
    edges = pd.DataFrame(edge_rows)
    source = panel[["date", "province_code", "commodity_code", "market_level", "price_filled"]].copy()
    source["province_code"] = source["province_code"].astype(str).str.zfill(2)
    source = source.rename(columns={"province_code": "neighbor_code", "price_filled": "geo_neighbor_price"})
    expanded = edges.merge(source, on="neighbor_code", how="left")
    expanded = expanded[expanded["geo_neighbor_price"].notna()].copy()
    expanded["geo_weighted_price"] = expanded["geo_neighbor_price"] * expanded["geo_neighbor_weight"]
    keys = ["date", "province_code", "commodity_code", "market_level"]
    neighbor = (
        expanded.groupby(keys, observed=True)
        .agg(
            geo_weighted_price=("geo_weighted_price", "sum"),
            geo_weight_sum=("geo_neighbor_weight", "sum"),
            geo_neighbor_std=("geo_neighbor_price", "std"),
            geo_neighbor_min=("geo_neighbor_price", "min"),
            geo_neighbor_max=("geo_neighbor_price", "max"),
            geo_mean_neighbor_distance_km=("geo_neighbor_distance_km", "mean"),
        )
        .reset_index()
    )
    neighbor["geo_neighbor_mean"] = neighbor["geo_weighted_price"] / neighbor["geo_weight_sum"].replace(0.0, np.nan)
    keep = keys + [
        "geo_neighbor_mean", "geo_neighbor_std", "geo_neighbor_min",
        "geo_neighbor_max", "geo_mean_neighbor_distance_km",
    ]
    output = panel.copy()
    output["province_code"] = output["province_code"].astype(str).str.zfill(2)
    output = output.merge(centroids, on="province_code", how="left")
    output = output.merge(neighbor[keep], on=keys, how="left")
    output["geo_neighbor_gap"] = output["price_filled"] - output["geo_neighbor_mean"]
    output["geo_neighbor_ratio"] = output["price_filled"] / output["geo_neighbor_mean"] - 1.0
    output = output.sort_values(["province_code", "commodity_code", "market_level", "date"])
    geo_group = output.groupby(["province_code", "commodity_code", "market_level"], observed=True, sort=False)
    output["geo_neighbor_delta_7"] = output["geo_neighbor_mean"] - geo_group["geo_neighbor_mean"].shift(7)
    output["geo_neighbor_delta_14"] = output["geo_neighbor_mean"] - geo_group["geo_neighbor_mean"].shift(14)
    features = [
        "geo_longitude", "geo_latitude", "geo_neighbor_mean",
        "geo_neighbor_std", "geo_neighbor_min", "geo_neighbor_max",
        "geo_mean_neighbor_distance_km", "geo_neighbor_gap",
        "geo_neighbor_ratio", "geo_neighbor_delta_7", "geo_neighbor_delta_14",
    ]
    return output.replace([np.inf, -np.inf], np.nan), features


if __name__ == "__main__":
    main()
