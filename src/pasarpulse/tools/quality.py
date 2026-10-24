"""Data-readiness checks, modality coverage, manifest, and data dictionary."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..utils import file_sha256, save_frame, save_json

DESCRIPTIONS = {
    "date": "Observation date in the province-commodity-market-level daily panel.",
    "province_code": "Canonical two-digit BPS province code.",
    "province_name": "Canonical province name.",
    "commodity_code": "BM, CRM, or CMK commodity identifier.",
    "market_level": "producer, wholesale, retail, or optional retail_modern.",
    "price_idr_per_kg": "Observed raw price in Indonesian rupiah per kilogram.",
    "price_unit": "Unit recorded by the source; PIHPS is normalized to IDR/kg.",
    "source_version": "Checksum-derived version of the retained raw source snapshot.",
    "revision_flag": "Source-snapshot marker; revisions remain auditable in the raw snapshot manifest.",
    "price_ffill": "Bounded forward-filled price feature; raw price is never overwritten.",
    "price_observation_age_days": "Age of the last observed price used by bounded carry-forward.",
    "production_kg": "Annual BPS production, used only as structural context.",
    "harvested_area_ha": "Annual harvested area from BPS.",
    "productivity_kg_per_ha": "Production divided by harvested area.",
    "ndvi_anomaly": "Regional vegetation anomaly relative to zone-month baseline.",
    "satellite_observation_age_days": "Days since the last valid Sentinel-2 observation.",
    "shock_7d": "Candidate label: price rises at least the configured threshold within seven days.",
    "mask_price": "1 when raw price is observed; 0 otherwise.",
    "mask_weather": "1 when at least one weather feature is present.",
    "mask_production": "1 when annual production context is present and not stale.",
    "mask_satellite": "1 when satellite features are present and within the carry window.",
    "mask_calendar": "1 when calendar features are available.",
    "evidence_quality_score": "Weighted modality-availability score used for abstention diagnostics.",
    "abstention_required": "True when evidence is insufficient for publishable decision support.",
}


def _frame_summary(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    date_min = date_max = None
    if "date" in frame and not frame.empty:
        dates = pd.to_datetime(frame["date"], errors="coerce")
        date_min, date_max = dates.min(), dates.max()
    return {
        "artifact": name,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "date_min": date_min,
        "date_max": date_max,
        "province_count": int(frame["province_code"].nunique()) if "province_code" in frame else np.nan,
        "commodity_count": int(frame["commodity_code"].nunique()) if "commodity_code" in frame else np.nan,
        "series_count": int(frame["series_id"].nunique()) if "series_id" in frame else np.nan,
        "duplicate_rows": int(frame.duplicated().sum()),
        "memory_mb": float(frame.memory_usage(deep=True).sum() / 1_048_576),
    }


def _modality_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    modality_columns = {
        "price": "mask_price",
        "weather": "mask_weather",
        "production": "mask_production",
        "satellite": "mask_satellite",
        "calendar": "mask_calendar",
    }
    rows: list[dict[str, Any]] = []
    grouping = [column for column in ["province_code", "commodity_code", "market_level"] if column in frame]
    for modality, column in modality_columns.items():
        if column not in frame:
            continue
        overall = pd.to_numeric(frame[column], errors="coerce").mean()
        rows.append({"scope": "national", "scope_id": "ALL", "modality": modality, "coverage": overall, "rows": len(frame)})
        if grouping:
            for key, group in frame.groupby(grouping, dropna=False):
                key_tuple = key if isinstance(key, tuple) else (key,)
                rows.append(
                    {
                        "scope": "series",
                        "scope_id": "|".join(map(str, key_tuple)),
                        "modality": modality,
                        "coverage": pd.to_numeric(group[column], errors="coerce").mean(),
                        "rows": len(group),
                    }
                )
    return pd.DataFrame(rows)


def _data_dictionary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        series = frame[column]
        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "non_null_rows": int(series.notna().sum()),
                "missing_fraction": float(series.isna().mean()),
                "unique_values": int(series.nunique(dropna=True)),
                "description": DESCRIPTIONS.get(column, "Generated pipeline field; inspect source module and metadata for details."),
            }
        )
    return pd.DataFrame(rows)


def build_quality_artifacts(
    frames: dict[str, pd.DataFrame],
    *,
    ready_dataset_name: str,
    reports_tables_dir: str | Path,
    manifest_path: str | Path,
    source_files: dict[str, str | Path | None] | None = None,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> dict[str, Any]:
    reports_dir = Path(reports_tables_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summaries = pd.DataFrame([_frame_summary(name, frame) for name, frame in frames.items()])
    save_frame(summaries, reports_dir / "artifact_summary", save_csv=save_csv, save_parquet=save_parquet)

    ready = frames.get(ready_dataset_name, pd.DataFrame())
    coverage = _modality_coverage(ready)
    save_frame(coverage, reports_dir / "modality_coverage", save_csv=save_csv, save_parquet=save_parquet)
    dictionary = _data_dictionary(ready)
    save_frame(dictionary, reports_dir / "data_dictionary", save_csv=True, save_parquet=False)

    key_columns = ["date", "province_code", "commodity_code", "market_level"]
    duplicate_key_rows = int(ready.duplicated([column for column in key_columns if column in ready], keep=False).sum()) if not ready.empty else 0
    checks = {
        "ready_dataset_nonempty": not ready.empty,
        "unique_panel_key": duplicate_key_rows == 0,
        "has_38_provinces": int(ready["province_code"].nunique()) == 38 if "province_code" in ready else False,
        "has_three_target_commodities": int(ready["commodity_code"].nunique()) == 3 if "commodity_code" in ready else False,
        "eligible_series_count": int(ready.loc[ready.get("is_eligible_series", False).astype(bool), "series_id"].nunique()) if "series_id" in ready and "is_eligible_series" in ready else 0,
        "duplicate_panel_key_rows": duplicate_key_rows,
    }

    file_records: list[dict[str, Any]] = []
    for name, raw_path in (source_files or {}).items():
        if raw_path is None:
            continue
        path = Path(raw_path)
        file_records.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
                "sha256": file_sha256(path) if path.exists() and path.is_file() else None,
            }
        )
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "artifacts": summaries.to_dict("records"),
        "source_files": file_records,
    }
    save_json(manifest, manifest_path)
    return {"summary": summaries, "coverage": coverage, "dictionary": dictionary, "manifest": manifest}
