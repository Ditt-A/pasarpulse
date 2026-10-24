"""Leakage-safe price-only rolling-origin baselines."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..utils import save_frame, save_json


SERIES_KEYS = [
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
]


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def _score(group: pd.DataFrame) -> dict[str, Any]:
    errors = pd.to_numeric(group["error"], errors="coerce").dropna()
    actual = group["actual_shock"].astype(bool)
    predicted = group["predicted_shock"].astype(bool)
    true_positive = int((actual & predicted).sum())
    false_positive = int((~actual & predicted).sum())
    false_negative = int((actual & ~predicted).sum())
    precision = _safe_div(true_positive, true_positive + false_positive)
    recall = _safe_div(true_positive, true_positive + false_negative)
    f1 = _safe_div(2 * precision * recall, precision + recall) if np.isfinite(precision) and np.isfinite(recall) else float("nan")
    return {
        "model": group["model"].iloc[0],
        "horizon_days": int(group["horizon_days"].iloc[0]),
        "rows_scored": int(len(group)),
        "series_scored": int(group["series_id"].nunique()),
        "mae_idr_per_kg": float(errors.abs().mean()) if not errors.empty else float("nan"),
        "rmse_idr_per_kg": float(np.sqrt(np.mean(np.square(errors)))) if not errors.empty else float("nan"),
        "mean_error_idr_per_kg": float(errors.mean()) if not errors.empty else float("nan"),
        "actual_shock_rate": float(actual.mean()) if len(actual) else float("nan"),
        "predicted_shock_rate": float(predicted.mean()) if len(predicted) else float("nan"),
        "shock_precision": precision,
        "shock_recall": recall,
        "shock_f1": f1,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def run_price_only_baselines(
    prices: pd.DataFrame,
    coverage_audit: pd.DataFrame,
    *,
    output_dir: str | Path,
    metadata_path: str | Path,
    start_date: str,
    end_date: str,
    bounded_ffill_days: int = 3,
    shock_threshold: float = 0.10,
    min_train_days: int = 365,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path], dict[str, Path]]:
    """Score fixed price-only forecasts on eligible series.

    The two baselines are deliberately fixed before scoring: the last usable
    price and a same-horizon seasonal lag.  Every prediction uses observations
    available on or before its forecast origin; no future label is used to
    choose a model or hyperparameter.
    """
    data = prices.copy()
    if data.empty:
        raise ValueError("Price data is required for price-only baselines.")
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data["price_idr_per_kg"] = pd.to_numeric(data["price_idr_per_kg"], errors="coerce")
    data = data.dropna(subset=["date", "price_idr_per_kg"])
    data = data[data["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]

    audit = coverage_audit.copy()
    if audit.empty:
        eligible_keys: set[tuple[str, str, str]] = set()
    else:
        audit["province_code"] = audit["province_code"].astype("string")
        eligible_keys = {
            (str(row.province_code), str(row.commodity_code), str(row.market_level))
            for row in audit[audit["eligible"].fillna(False).astype(bool)].itertuples()
        }

    prediction_rows: list[dict[str, Any]] = []
    for key, original in data.groupby(["province_code", "commodity_code", "market_level"], dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        series_key = (str(key_tuple[0]), str(key_tuple[1]), str(key_tuple[2]))
        if series_key not in eligible_keys:
            continue
        group = original.sort_values("date").drop_duplicates("date", keep="last")
        index_start = max(pd.Timestamp(start_date), group["date"].min())
        index_end = min(pd.Timestamp(end_date), group["date"].max())
        index = pd.date_range(index_start, index_end, freq="D")
        raw = group.set_index("date")["price_idr_per_kg"].reindex(index)
        current = raw.ffill(limit=int(bounded_ffill_days))
        observed_before = raw.notna().cumsum()
        metadata = {column: group[column].iloc[0] for column in SERIES_KEYS if column in group}
        series_id = "|".join(str(series_key_part) for series_key_part in series_key)

        for horizon in (7, 14):
            actual = raw.shift(-horizon)
            seasonal = current.shift(horizon)
            candidates = {
                "last_price": current,
                "seasonal_lag": seasonal,
            }
            train_ready = observed_before.ge(int(min_train_days))
            for model, forecast in candidates.items():
                valid = train_ready & current.notna() & actual.notna() & forecast.notna() & current.gt(0)
                for origin in index[valid]:
                    origin_pos = index.get_loc(origin)
                    actual_value = float(actual.iloc[origin_pos])
                    current_value = float(current.iloc[origin_pos])
                    forecast_value = float(forecast.iloc[origin_pos])
                    prediction_rows.append(
                        {
                            **metadata,
                            "series_id": series_id,
                            "forecast_origin": origin,
                            "horizon_days": horizon,
                            "model": model,
                            "current_price_idr_per_kg": current_value,
                            "actual_price_idr_per_kg": actual_value,
                            "predicted_price_idr_per_kg": forecast_value,
                            "error": forecast_value - actual_value,
                            "actual_shock": int(actual_value / current_value - 1.0 >= shock_threshold),
                            "predicted_shock": int(forecast_value / current_value - 1.0 >= shock_threshold),
                        }
                    )

    predictions = pd.DataFrame(prediction_rows)
    if predictions.empty:
        metrics = pd.DataFrame()
    else:
        metrics = pd.DataFrame(
            [_score(group) for _, group in predictions.groupby(["model", "horizon_days"], sort=True)]
        ).sort_values(["horizon_days", "rmse_idr_per_kg", "model"]).reset_index(drop=True)

    out_dir = Path(output_dir)
    prediction_outputs = save_frame(
        predictions,
        out_dir / "price_only_baseline_predictions",
        save_csv=save_csv,
        save_parquet=save_parquet,
    )
    metric_outputs = save_frame(
        metrics,
        out_dir / "price_only_baseline_metrics",
        save_csv=save_csv,
        save_parquet=save_parquet,
    )
    save_json(
        {
            "protocol": "rolling_origin_price_only",
            "source_date_range": [str(pd.Timestamp(start_date).date()), str(pd.Timestamp(end_date).date())],
            "eligible_series_available": len(eligible_keys),
            "series_scored": int(predictions["series_id"].nunique()) if not predictions.empty else 0,
            "prediction_rows": int(len(predictions)),
            "models": ["last_price", "seasonal_lag"],
            "horizons_days": [7, 14],
            "min_train_days": int(min_train_days),
            "bounded_ffill_days": int(bounded_ffill_days),
            "shock_threshold": float(shock_threshold),
            "leakage_guard": "forecast uses only dates <= forecast_origin; labels are scored after the origin",
        },
        metadata_path,
    )
    return metrics, prediction_outputs, metric_outputs
