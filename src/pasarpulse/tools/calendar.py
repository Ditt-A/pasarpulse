"""Daily calendar features from curated official event dates."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import save_frame


def _safe_flag_name(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
    return f"is_{text}" if text else "is_event"


def _event_distance(dates: pd.Series, event_dates: pd.Series) -> tuple[pd.Series, pd.Series]:
    events = np.sort(pd.to_datetime(event_dates).dropna().values.astype("datetime64[D]"))
    current = pd.to_datetime(dates).values.astype("datetime64[D]")
    if len(events) == 0:
        nan = pd.Series(np.nan, index=dates.index)
        return nan, nan
    positions = np.searchsorted(events, current)
    previous = np.where(positions > 0, events[np.maximum(positions - 1, 0)], np.datetime64("NaT"))
    following = np.where(positions < len(events), events[np.minimum(positions, len(events) - 1)], np.datetime64("NaT"))
    days_since = (current - previous).astype("timedelta64[D]").astype(float)
    days_to = (following - current).astype("timedelta64[D]").astype(float)
    days_since[np.isnat(previous)] = np.nan
    days_to[np.isnat(following)] = np.nan
    return pd.Series(days_since, index=dates.index), pd.Series(days_to, index=dates.index)


def build_calendar_features(
    start_date: str,
    end_date: str,
    *,
    events_path: str | Path | None,
    output_base: str | Path,
    national_region_code: str = "NATIONAL",
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    result = pd.DataFrame({"date": pd.date_range(start_date, end_date, freq="D")})
    result["day_of_week"] = result["date"].dt.dayofweek.astype("int8")
    result["day_name"] = result["date"].dt.day_name()
    result["week_of_year"] = result["date"].dt.isocalendar().week.astype("int16")
    result["month"] = result["date"].dt.month.astype("int8")
    result["quarter"] = result["date"].dt.quarter.astype("int8")
    result["year"] = result["date"].dt.year.astype("int16")
    result["is_weekend"] = result["day_of_week"].isin([5, 6]).astype("int8")
    day_of_year = result["date"].dt.dayofyear
    result["seasonal_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    result["seasonal_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)

    events_file = Path(events_path) if events_path else None
    if events_file and events_file.exists() and events_file.stat().st_size > 0:
        events = pd.read_csv(events_file)
        required = {"date", "event_type", "event_name", "region_code"}
        missing = required.difference(events.columns)
        if missing:
            raise ValueError(f"Calendar event file misses columns: {sorted(missing)}")
        events["date"] = pd.to_datetime(events["date"], errors="coerce").dt.normalize()
        national = events[events["region_code"].fillna(national_region_code).eq(national_region_code)].copy()
        national["flag_name"] = national["event_type"].map(_safe_flag_name)
        flags = pd.crosstab(national["date"], national["flag_name"]).clip(upper=1).reset_index()
        result = result.merge(flags, on="date", how="left")
        flag_columns = [column for column in result if column.startswith("is_") and column != "is_weekend"]
        result[flag_columns] = result[flag_columns].fillna(0).astype("int8")

        # Distances are useful around Ramadan/Eid/Christmas-New Year without hard-coding dates.
        for event_type, group in national.groupby("event_type"):
            slug = re.sub(r"[^a-z0-9]+", "_", str(event_type).casefold()).strip("_")
            if not slug:
                continue
            since, to = _event_distance(result["date"], group["date"])
            result[f"days_since_{slug}"] = since
            result[f"days_to_{slug}"] = to
    result["calendar_status"] = "ok"
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return result, outputs
