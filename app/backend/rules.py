"""Pure, leakage-safe domain rules shared by snapshot building and the API."""

from __future__ import annotations

import math
from typing import Literal

from .config import THRESHOLDS, WarningThresholds

WarningLevel = Literal["STABLE", "WATCH", "ELEVATED", "HIGH", "INSUFFICIENT"]


def projected_change_pct(current_price: float, predicted_price: float) -> float:
    """Return the signed price movement using forecast-time values only."""

    current = float(current_price)
    predicted = float(predicted_price)
    if not math.isfinite(current) or current <= 0:
        raise ValueError("current_price must be a finite positive value")
    if not math.isfinite(predicted) or predicted < 0:
        raise ValueError("predicted_price must be a finite non-negative value")
    return (predicted - current) / current * 100.0


def classify_warning(change_pct: float, thresholds: WarningThresholds = THRESHOLDS) -> WarningLevel:
    """Classify a projected rise under the configurable product rule.

    This is intentionally not a probability or a learned classifier output.
    Negative movement is stable for the price-rise warning view.
    """

    value = float(change_pct)
    if not math.isfinite(value):
        raise ValueError("projected change must be finite")
    if value >= thresholds.high:
        return "HIGH"
    if value >= thresholds.elevated:
        return "ELEVATED"
    if value >= thresholds.watch:
        return "WATCH"
    return "STABLE"


WARNING_ORDER = {"INSUFFICIENT": 0, "STABLE": 1, "WATCH": 2, "ELEVATED": 3, "HIGH": 4}


def warning_rank(level: str) -> int:
    return WARNING_ORDER.get(str(level).upper(), 0)
