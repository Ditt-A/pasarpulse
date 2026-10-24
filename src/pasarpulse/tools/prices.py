"""Normalize public/manual price sources and apply the price-series data contract."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..utils import read_table, save_frame

CANONICAL_COLUMNS = [
    "date",
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
    "price_idr_per_kg",
    "price_unit",
    "source",
    "source_location_name",
    "extraction_timestamp",
    "source_version",
    "revision_flag",
    "quality_flag",
]

PROVINCE_ALIASES = {
    "aceh": ("11", "Aceh"),
    "sumatera utara": ("12", "Sumatera Utara"),
    "sumatra utara": ("12", "Sumatera Utara"),
    "sumatera barat": ("13", "Sumatera Barat"),
    "sumatra barat": ("13", "Sumatera Barat"),
    "riau": ("14", "Riau"),
    "jambi": ("15", "Jambi"),
    "sumatera selatan": ("16", "Sumatera Selatan"),
    "sumatra selatan": ("16", "Sumatera Selatan"),
    "bengkulu": ("17", "Bengkulu"),
    "lampung": ("18", "Lampung"),
    "kepulauan bangka belitung": ("19", "Kepulauan Bangka Belitung"),
    "bangka belitung": ("19", "Kepulauan Bangka Belitung"),
    "kepulauan riau": ("21", "Kepulauan Riau"),
    "dki jakarta": ("31", "DKI Jakarta"),
    "jakarta": ("31", "DKI Jakarta"),
    "jawa barat": ("32", "Jawa Barat"),
    "jawa tengah": ("33", "Jawa Tengah"),
    "di yogyakarta": ("34", "DI Yogyakarta"),
    "daerah istimewa yogyakarta": ("34", "DI Yogyakarta"),
    "yogyakarta": ("34", "DI Yogyakarta"),
    "jawa timur": ("35", "Jawa Timur"),
    "banten": ("36", "Banten"),
    "bali": ("51", "Bali"),
    "nusa tenggara barat": ("52", "Nusa Tenggara Barat"),
    "ntb": ("52", "Nusa Tenggara Barat"),
    "nusa tenggara timur": ("53", "Nusa Tenggara Timur"),
    "ntt": ("53", "Nusa Tenggara Timur"),
    "kalimantan barat": ("61", "Kalimantan Barat"),
    "kalimantan tengah": ("62", "Kalimantan Tengah"),
    "kalimantan selatan": ("63", "Kalimantan Selatan"),
    "kalimantan timur": ("64", "Kalimantan Timur"),
    "kalimantan utara": ("65", "Kalimantan Utara"),
    "sulawesi utara": ("71", "Sulawesi Utara"),
    "sulawesi tengah": ("72", "Sulawesi Tengah"),
    "sulawesi selatan": ("73", "Sulawesi Selatan"),
    "sulawesi tenggara": ("74", "Sulawesi Tenggara"),
    "gorontalo": ("75", "Gorontalo"),
    "sulawesi barat": ("76", "Sulawesi Barat"),
    "maluku": ("81", "Maluku"),
    "maluku utara": ("82", "Maluku Utara"),
    "papua barat": ("91", "Papua Barat"),
    "papua barat daya": ("92", "Papua Barat Daya"),
    "papua": ("94", "Papua"),
    "papua selatan": ("95", "Papua Selatan"),
    "papua tengah": ("96", "Papua Tengah"),
    "papua pegunungan": ("97", "Papua Pegunungan"),
}

COMMODITY_ALIASES = {
    "bawang merah": ("BM", "Bawang Merah"),
    "shallot": ("BM", "Bawang Merah"),
    "cabai rawit merah": ("CRM", "Cabai Rawit Merah"),
    "cabai rawit": ("CRM", "Cabai Rawit Merah"),
    "cabe rawit merah": ("CRM", "Cabai Rawit Merah"),
    "cabai merah keriting": ("CMK", "Cabai Merah Keriting"),
    "cabai keriting": ("CMK", "Cabai Merah Keriting"),
    "cabe merah keriting": ("CMK", "Cabai Merah Keriting"),
}

MARKET_ALIASES = {
    "produsen": "producer",
    "producer": "producer",
    "pedagang besar": "wholesale",
    "grosir": "wholesale",
    "wholesale": "wholesale",
    "pasar tradisional": "retail",
    "eceran": "retail",
    "retail": "retail",
    "pasar modern": "retail_modern",
    "retail modern": "retail_modern",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = text.replace("\xa0", " ").casefold().strip()
    return re.sub(r"\s+", " ", text)


def _parse_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"[^0-9,\.\-]", "", str(value).strip())
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        # Accept both Indonesian (1.234,56) and international (1,234.56)
        # spellings.  The last separator is the decimal separator when it is
        # followed by one or two digits; otherwise both separators are
        # treated as thousands separators.
        last_comma, last_dot = text.rfind(","), text.rfind(".")
        decimal_pos = max(last_comma, last_dot)
        decimals = len(text) - decimal_pos - 1
        if decimals in {1, 2}:
            decimal = text[decimal_pos]
            thousands = "." if decimal == "," else ","
            text = text.replace(thousands, "").replace(decimal, ".")
        else:
            text = text.replace(",", "").replace(".", "")
    elif "," in text:
        decimals = len(text.rsplit(",", 1)[1])
        text = text.replace(",", ".") if decimals in {1, 2} else text.replace(",", "")
    elif text.count(".") == 1:
        decimals = len(text.rsplit(".", 1)[1])
        if decimals == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _load_column_map(column_map: str | Path | dict[str, str] | None) -> dict[str, str]:
    if column_map is None:
        return {}
    if isinstance(column_map, dict):
        return {str(k): str(v) for k, v in column_map.items()}
    mapping = read_table(column_map)
    required = {"source_column", "canonical_column"}
    if not required.issubset(mapping.columns):
        raise ValueError(f"Column-map file must contain {sorted(required)}")
    return dict(zip(mapping["source_column"].astype(str), mapping["canonical_column"].astype(str)))


def normalize_price_frame(
    frame: pd.DataFrame,
    *,
    source: str,
    column_map: str | Path | dict[str, str] | None = None,
    default_market_level: str | None = None,
) -> pd.DataFrame:
    """Canonicalize an in-memory price table."""
    frame = frame.copy().rename(columns=_load_column_map(column_map))
    if default_market_level and "market_level" not in frame:
        frame["market_level"] = default_market_level

    required = ["date", "province_name", "commodity_name", "market_level", "price_idr_per_kg"]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"Price table masih kehilangan kolom wajib setelah mapping: {missing}")

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["price_idr_per_kg"] = frame["price_idr_per_kg"].map(_parse_number)

    province_meta = frame["province_name"].map(lambda value: PROVINCE_ALIASES.get(_norm(value)))
    if "province_code" not in frame:
        frame["province_code"] = province_meta.map(lambda value: value[0] if value else pd.NA)
    frame["province_name"] = [meta[1] if meta else str(raw).strip() for meta, raw in zip(province_meta, frame["province_name"])]

    commodity_meta = frame["commodity_name"].map(lambda value: COMMODITY_ALIASES.get(_norm(value)))
    if "commodity_code" not in frame:
        frame["commodity_code"] = commodity_meta.map(lambda value: value[0] if value else pd.NA)
    frame["commodity_name"] = [meta[1] if meta else str(raw).strip() for meta, raw in zip(commodity_meta, frame["commodity_name"])]
    frame["market_level"] = frame["market_level"].map(lambda value: MARKET_ALIASES.get(_norm(value), _norm(value).replace(" ", "_")))
    frame["source"] = source.upper()

    if "extraction_timestamp" not in frame:
        frame["extraction_timestamp"] = pd.Timestamp.now(tz="Asia/Jakarta").isoformat()
    if "quality_flag" not in frame:
        frame["quality_flag"] = "ok"
    if "price_unit" not in frame:
        frame["price_unit"] = "IDR/kg"
    frame.loc[frame["province_code"].isna(), "quality_flag"] = "unmapped_province"
    frame.loc[frame["commodity_code"].isna(), "quality_flag"] = "unmapped_commodity"

    for column in CANONICAL_COLUMNS:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[CANONICAL_COLUMNS]
    frame = frame.dropna(subset=["date", "province_name", "commodity_name", "market_level", "price_idr_per_kg"])
    frame["province_code"] = frame["province_code"].astype("string")
    frame["commodity_code"] = frame["commodity_code"].astype("string")
    return frame


def normalize_price_source(
    input_path: str | Path,
    *,
    source: str,
    column_map: str | Path | dict[str, str] | None = None,
    sheet_name: str | int = 0,
    default_market_level: str | None = None,
) -> pd.DataFrame:
    frame = read_table(input_path, sheet_name=sheet_name) if Path(input_path).suffix.lower() in {".xlsx", ".xls"} else read_table(input_path)
    return normalize_price_frame(
        frame,
        source=source,
        column_map=column_map,
        default_market_level=default_market_level,
    )


def ingest_price_sources(
    inputs: list[dict[str, Any]],
    output_base: str | Path,
    *,
    project_root: str | Path,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    root = Path(project_root)
    parts: list[pd.DataFrame] = []
    for spec in inputs:
        raw_path = Path(spec["path"])
        path = raw_path if raw_path.is_absolute() else root / raw_path
        if not path.exists():
            raise FileNotFoundError(f"Price input tidak ditemukan: {path}")
        raw_map = spec.get("column_map")
        column_map = None
        if raw_map:
            map_path = Path(raw_map)
            column_map = map_path if map_path.is_absolute() else root / map_path
        parts.append(
            normalize_price_source(
                path,
                source=str(spec.get("source", "UNKNOWN")),
                column_map=column_map,
                sheet_name=spec.get("sheet_name", 0),
                default_market_level=spec.get("default_market_level"),
            )
        )
    if not parts:
        raise ValueError("prices.inputs kosong. Tambahkan file manual atau gunakan prices.source: sp2kp.")

    result = pd.concat(parts, ignore_index=True)
    keys = ["date", "province_code", "commodity_code", "market_level", "source"]
    result = result.sort_values(keys + ["extraction_timestamp"]).drop_duplicates(keys, keep="last")
    result = result.sort_values(["province_code", "commodity_code", "market_level", "date"]).reset_index(drop=True)
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return result, outputs


def audit_price_coverage(
    frame: pd.DataFrame,
    *,
    min_months: int = 24,
    min_coverage: float = 0.80,
    scheduled_days: str = "business",
) -> pd.DataFrame:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    keys = ["province_code", "province_name", "commodity_code", "commodity_name", "market_level"]
    rows: list[dict[str, Any]] = []
    for key, group in data.groupby(keys, dropna=False):
        group = group.sort_values("date")
        start, end = group["date"].min(), group["date"].max()
        if pd.isna(start) or pd.isna(end):
            continue
        scheduled = pd.bdate_range(start, end) if scheduled_days == "business" else pd.date_range(start, end, freq="D")
        observed = group.loc[group["price_idr_per_kg"].notna(), "date"].nunique()
        coverage = observed / len(scheduled) if len(scheduled) else 0.0
        months = (end.to_period("M") - start.to_period("M")).n + 1
        duplicates = int(group.duplicated(["date"], keep=False).sum())
        unresolved = int(group["quality_flag"].fillna("ok").ne("ok").sum())
        eligible = months >= min_months and coverage >= min_coverage and duplicates == 0 and unresolved == 0
        reasons: list[str] = []
        if months < min_months:
            reasons.append("insufficient_months")
        if coverage < min_coverage:
            reasons.append("low_coverage")
        if duplicates:
            reasons.append("duplicate_dates")
        if unresolved:
            reasons.append("quality_flags")
        rows.append(
            dict(zip(keys, key))
            | {
                "start_date": start,
                "end_date": end,
                "months_available": months,
                "scheduled_days": len(scheduled),
                "observed_days": observed,
                "coverage": coverage,
                "duplicate_rows": duplicates,
                "unresolved_quality_rows": unresolved,
                "eligible": eligible,
                "reason": "eligible" if eligible else ";".join(reasons),
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["eligible", "coverage"], ascending=[False, False]).reset_index(drop=True)
    return result


def add_price_grid_and_features(
    prices: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    bounded_ffill_days: int,
    shock_threshold: float,
) -> pd.DataFrame:
    """Expand every observed series to a daily grid while preserving raw missingness."""
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    keys = ["province_code", "province_name", "commodity_code", "commodity_name", "market_level"]
    daily_index = pd.date_range(start_date, end_date, freq="D")
    parts: list[pd.DataFrame] = []
    for key, group in data.groupby(keys, dropna=False):
        group = group.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        expanded = group.reindex(daily_index)
        expanded.index.name = "date"
        for column, value in zip(keys, key):
            expanded[column] = value
        expanded["price_observed"] = expanded["price_idr_per_kg"].notna().astype("int8")
        expanded["price_ffill"] = expanded["price_idr_per_kg"].ffill(limit=bounded_ffill_days)
        last_obs = pd.Series(expanded.index.where(expanded["price_observed"].eq(1)), index=expanded.index).ffill()
        expanded["price_observation_age_days"] = (expanded.index.to_series() - last_obs).dt.days
        expanded.loc[expanded["price_ffill"].isna(), "price_observation_age_days"] = np.nan
        parts.append(expanded.reset_index())
    panel = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if panel.empty:
        return panel

    group_cols = ["province_code", "commodity_code", "market_level"]
    panel = panel.sort_values(group_cols + ["date"])
    for horizon in (7, 14):
        panel[f"price_t_plus_{horizon}"] = panel.groupby(group_cols, dropna=False)["price_idr_per_kg"].shift(-horizon)
    # Forward maximum in the next seven calendar days, excluding the current day.
    def forward_max(series: pd.Series, horizon: int) -> pd.Series:
        reversed_roll = series.iloc[::-1].rolling(horizon, min_periods=1).max().iloc[::-1]
        return reversed_roll.shift(-1)

    panel["future_max_price_7d"] = panel.groupby(group_cols, group_keys=False)["price_idr_per_kg"].apply(lambda s: forward_max(s, 7))
    panel["future_return_max_7d"] = panel["future_max_price_7d"] / panel["price_idr_per_kg"] - 1.0
    panel["shock_7d"] = np.where(
        panel["price_idr_per_kg"].notna() & panel["future_max_price_7d"].notna(),
        (panel["future_return_max_7d"] >= shock_threshold).astype("int8"),
        pd.NA,
    )
    panel["series_id"] = panel[group_cols].astype(str).agg("|".join, axis=1)
    panel["node_id"] = panel["series_id"]
    return panel.reset_index(drop=True)
