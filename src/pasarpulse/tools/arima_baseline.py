"""Paper B1 ARIMA baseline for province-commodity-market price series.

This module intentionally implements the paper's B1 baseline only.  It does
not call the existing naive baselines and does not contain any of the later
multimodal or graph architectures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import warnings

import numpy as np
import pandas as pd


SERIES_KEYS = [
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
]


@dataclass(frozen=True)
class ARIMAConfig:
    """Predeclared B1 configuration.

    The paper names ARIMA as B1 but does not publish an order selection
    protocol.  We therefore freeze ARIMA(1,1,1) before scoring and do not use
    future labels to select an order.
    """

    order: tuple[int, int, int] = (1, 1, 1)
    min_train_observations: int = 365
    max_horizon_days: int = 14
    shock_threshold: float = 0.10
    confidence_alpha: float = 0.05
    enforce_stationarity: bool = False
    enforce_invertibility: bool = False


def _as_key(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def eligible_series_keys(coverage_audit: pd.DataFrame) -> set[tuple[str, str, str]]:
    """Return eligible province/commodity/market keys from the audit table."""

    if coverage_audit.empty:
        return set()
    audit = coverage_audit.copy()
    eligible = audit["eligible"].astype("string").str.lower().isin(
        ["true", "1", "yes"]
    )
    return {
        (_as_key(row.province_code), _as_key(row.commodity_code), _as_key(row.market_level))
        for row in audit.loc[eligible].itertuples()
    }


def make_rolling_origins(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    *,
    min_train_days: int = 365,
    max_horizon_days: int = 14,
    evaluation_start: str | pd.Timestamp | None = None,
    stride_days: int = 28,
    available_dates: Iterable[str | pd.Timestamp] | None = None,
) -> list[pd.Timestamp]:
    """Create fixed rolling-origin dates for the paper's temporal protocol.

    When ``available_dates`` is provided, origins are selected from the
    common observed calendar and only dates whose seven- and fourteen-day
    targets are also in that calendar are retained. This is useful for the
    PIHPS panel, whose scheduled observations are weekdays rather than all
    seven calendar days.
    """

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    first = start + pd.Timedelta(days=int(min_train_days))
    if evaluation_start is not None:
        first = max(first, pd.Timestamp(evaluation_start).normalize())
    last = end - pd.Timedelta(days=int(max_horizon_days))
    if first > last:
        return []
    if available_dates is not None:
        available = pd.DatetimeIndex(pd.to_datetime(list(available_dates))).normalize().unique()
        available_set = set(available)
        candidates = [
            value
            for value in available.sort_values()
            if first <= value <= last
            and value + pd.Timedelta(days=7) in available_set
            and value + pd.Timedelta(days=14) in available_set
        ]
        step = max(int(stride_days), 1)
        origins = candidates[::step]
        if candidates and (not origins or origins[-1] != candidates[-1]):
            origins.append(candidates[-1])
        return [pd.Timestamp(origin).normalize() for origin in origins]
    origins = list(pd.date_range(first, last, freq=f"{int(stride_days)}D"))
    if not origins or origins[-1] != last:
        origins.append(last)
    return [pd.Timestamp(origin).normalize() for origin in origins]


def _smape(actual: pd.Series, predicted: pd.Series) -> float:
    denominator = actual.abs() + predicted.abs()
    valid = denominator.gt(0)
    if not valid.any():
        return float("nan")
    return float((2.0 * (actual[valid] - predicted[valid]).abs() / denominator[valid]).mean() * 100.0)


def _safe_div(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def _metric_row(group: pd.DataFrame) -> dict[str, Any]:
    actual = pd.to_numeric(group["actual_price_idr_per_kg"], errors="coerce")
    predicted = pd.to_numeric(group["predicted_price_idr_per_kg"], errors="coerce")
    error = predicted - actual
    actual_shock = group["actual_shock"].astype(bool)
    predicted_shock = group["predicted_shock"].astype(bool)
    true_positive = int((actual_shock & predicted_shock).sum())
    false_positive = int((~actual_shock & predicted_shock).sum())
    false_negative = int((actual_shock & ~predicted_shock).sum())
    precision = _safe_div(true_positive, true_positive + false_positive)
    recall = _safe_div(true_positive, true_positive + false_negative)
    f1 = (
        float(2.0 * precision * recall / (precision + recall))
        if np.isfinite(precision) and np.isfinite(recall) and precision + recall
        else float("nan")
    )
    interval_valid = group[["lower_95_idr_per_kg", "upper_95_idr_per_kg"]].notna().all(axis=1)
    interval_coverage = (
        float(
            (
                actual[interval_valid].ge(group.loc[interval_valid, "lower_95_idr_per_kg"])
                & actual[interval_valid].le(group.loc[interval_valid, "upper_95_idr_per_kg"])
            ).mean()
        )
        if interval_valid.any()
        else float("nan")
    )
    return {
        "model": group["model"].iloc[0],
        "arima_order": group["arima_order"].iloc[0],
        "horizon_days": int(group["horizon_days"].iloc[0]),
        "rows_scored": int(len(group)),
        "series_scored": int(group["series_id"].nunique()),
        "folds_scored": int(group["fold_id"].nunique()),
        "mae_idr_per_kg": float(error.abs().mean()),
        "rmse_idr_per_kg": float(np.sqrt(np.mean(np.square(error)))),
        "mean_error_idr_per_kg": float(error.mean()),
        "smape_percent": _smape(actual, predicted),
        "interval_coverage_95": interval_coverage,
        "actual_shock_rate": float(actual_shock.mean()),
        "predicted_shock_rate": float(predicted_shock.mean()),
        "shock_precision": precision,
        "shock_recall": recall,
        "shock_f1": f1,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def _fit_one_series(
    raw: pd.Series,
    *,
    origins: Iterable[pd.Timestamp],
    metadata: dict[str, Any],
    series_id: str,
    config: ARIMAConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fit ARIMA at each origin and return predictions plus fit audit rows."""

    # Import lazily so the data-pipeline package remains importable when the
    # optional modeling dependency is not installed on a data-only machine.
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError as exc:  # pragma: no cover - exercised in missing-env use
        raise ImportError(
            "The paper B1 notebook requires statsmodels>=0.14. Install the "
            "project requirements or run it on the configured A100 environment."
        ) from exc

    predictions: list[dict[str, Any]] = []
    fit_audit: list[dict[str, Any]] = []
    raw = raw.sort_index().astype(float)
    model_name = f"B1_ARIMA{config.order}"

    for fold_id, origin in enumerate(origins, start=1):
        origin = pd.Timestamp(origin).normalize()
        if origin not in raw.index:
            continue
        current = raw.loc[origin]
        train = raw.loc[:origin]
        observed_count = int(train.notna().sum())
        audit_row = {
            **metadata,
            "series_id": series_id,
            "fold_id": fold_id,
            "forecast_origin": origin,
            "model": model_name,
            "arima_order": str(config.order),
            "n_observed_train": observed_count,
            "fit_status": "not_run",
            "aic": np.nan,
            "fit_error": "",
        }
        if pd.isna(current) or current <= 0 or observed_count < config.min_train_observations:
            audit_row["fit_error"] = "insufficient_observed_history_or_missing_origin"
            fit_audit.append(audit_row)
            continue

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fitted = ARIMA(
                    train,
                    order=config.order,
                    enforce_stationarity=config.enforce_stationarity,
                    enforce_invertibility=config.enforce_invertibility,
                    missing="drop",
                ).fit()
                forecast = fitted.get_forecast(steps=config.max_horizon_days)
                mean = np.asarray(forecast.predicted_mean, dtype=float)
                interval = np.asarray(
                    forecast.conf_int(alpha=config.confidence_alpha), dtype=float
                )
            audit_row["fit_status"] = "ok"
            audit_row["aic"] = float(fitted.aic)
            fit_audit.append(audit_row)
        except Exception as exc:  # keep one unstable series/fold from aborting all scoring
            audit_row["fit_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
            fit_audit.append(audit_row)
            continue

        for horizon in (7, 14):
            target_date = origin + pd.Timedelta(days=horizon)
            if target_date not in raw.index:
                continue
            actual = raw.loc[target_date]
            if pd.isna(actual) or actual <= 0:
                continue
            position = horizon - 1
            predicted = float(mean[position])
            lower = float(interval[position, 0]) if interval.ndim == 2 else np.nan
            upper = float(interval[position, 1]) if interval.ndim == 2 else np.nan
            predictions.append(
                {
                    **metadata,
                    "series_id": series_id,
                    "fold_id": fold_id,
                    "forecast_origin": origin,
                    "target_date": target_date,
                    "horizon_days": horizon,
                    "model": model_name,
                    "arima_order": str(config.order),
                    "current_price_idr_per_kg": float(current),
                    "actual_price_idr_per_kg": float(actual),
                    "predicted_price_idr_per_kg": predicted,
                    "lower_95_idr_per_kg": lower,
                    "upper_95_idr_per_kg": upper,
                    "error": predicted - float(actual),
                    "actual_shock": int(float(actual) / float(current) - 1.0 >= config.shock_threshold),
                    "predicted_shock": int(predicted / float(current) - 1.0 >= config.shock_threshold),
                }
            )
    return predictions, fit_audit


def run_arima_baseline(
    prices: pd.DataFrame,
    coverage_audit: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    origins: Iterable[str | pd.Timestamp],
    config: ARIMAConfig = ARIMAConfig(),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run the paper's B1 ARIMA rolling-origin baseline.

    Each eligible province-commodity-market series gets its own fixed
    ARIMA(1,1,1) fit at every declared origin. Missing price observations are
    represented as NaN on a daily index and handled by statsmodels' state-space
    missing-value support; labels are scored only when the target date is
    observed.
    """

    if prices.empty:
        raise ValueError("Price data is required for the ARIMA baseline.")
    date_column = "date" if "date" in prices.columns else "observed_date"
    data = prices.copy()
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce").dt.normalize()
    data["price_idr_per_kg"] = pd.to_numeric(data["price_idr_per_kg"], errors="coerce")
    data = data.dropna(subset=[date_column, "price_idr_per_kg"])
    data = data[data[date_column].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
    data.loc[data["price_idr_per_kg"] <= 0, "price_idr_per_kg"] = np.nan
    eligible = eligible_series_keys(coverage_audit)
    origin_list = [pd.Timestamp(value).normalize() for value in origins]
    if not origin_list:
        raise ValueError("At least one rolling-origin date is required.")

    prediction_rows: list[dict[str, Any]] = []
    fit_rows: list[dict[str, Any]] = []
    series_seen = 0
    for key, original in data.groupby(
        ["province_code", "commodity_code", "market_level"], dropna=False
    ):
        key_tuple = key if isinstance(key, tuple) else (key,)
        series_key = tuple(_as_key(part) for part in key_tuple)
        if series_key not in eligible:
            continue
        series_seen += 1
        group = original.sort_values(date_column).drop_duplicates(date_column, keep="last")
        index = pd.date_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq="D")
        raw = group.set_index(date_column)["price_idr_per_kg"].reindex(index)
        metadata = {
            column: group[column].iloc[0]
            for column in SERIES_KEYS
            if column in group.columns
        }
        series_id = "|".join(series_key)
        predictions, fits = _fit_one_series(
            raw,
            origins=origin_list,
            metadata=metadata,
            series_id=series_id,
            config=config,
        )
        prediction_rows.extend(predictions)
        fit_rows.extend(fits)

    predictions_frame = pd.DataFrame(prediction_rows)
    fit_audit_frame = pd.DataFrame(fit_rows)
    if predictions_frame.empty:
        metrics_frame = pd.DataFrame()
    else:
        metrics_frame = pd.DataFrame(
            [
                _metric_row(group)
                for _, group in predictions_frame.groupby("horizon_days", sort=True)
            ]
        ).sort_values("horizon_days").reset_index(drop=True)
    metadata = {
        "protocol": "paper_B1_ARIMA_rolling_origin",
        "model": f"B1_ARIMA{config.order}",
        "arima_order": list(config.order),
        "source_date_range": [str(pd.Timestamp(start_date).date()), str(pd.Timestamp(end_date).date())],
        "declared_origins": [str(value.date()) for value in origin_list],
        "eligible_series_available": len(eligible),
        "series_seen": series_seen,
        "series_scored": int(predictions_frame["series_id"].nunique()) if not predictions_frame.empty else 0,
        "fit_attempts": int(len(fit_audit_frame)),
        "successful_fits": int((fit_audit_frame["fit_status"] == "ok").sum()) if not fit_audit_frame.empty else 0,
        "prediction_rows": int(len(predictions_frame)),
        "horizons_days": [7, 14],
        "min_train_observations": config.min_train_observations,
        "shock_threshold": config.shock_threshold,
        "confidence_alpha": config.confidence_alpha,
        "leakage_guard": "each fit uses only price observations on or before its forecast origin",
    }
    return metrics_frame, predictions_frame, fit_audit_frame, metadata
