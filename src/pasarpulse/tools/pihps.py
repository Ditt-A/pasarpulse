"""Acquire and canonicalize the public PIHPS province price tables.

PIHPS exposes a report-oriented endpoint rather than a bulk download.  The
"by commodity" report is useful here because one response contains all
available province rows and one daily date range.  We retain every response as
a raw snapshot and keep its request metadata, checksum, and mapping audit next
to the canonical panel.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils import save_frame, save_json
from .prices import COMMODITY_ALIASES, PROVINCE_ALIASES, normalize_price_frame, _norm

DEFAULT_ENDPOINT = (
    "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/"
    "GetGridDataKomoditas"
)
DEFAULT_PAGE_URL = "https://www.bi.go.id/hargapangan/TabelHarga/PedagangBesarKomoditas"

DEFAULT_COMMODITIES: dict[str, dict[str, Any]] = {
    "BM": {"source_id": "com_11", "source_name": "Bawang Merah"},
    "CMK": {"source_id": "com_14", "source_name": "Cabai Merah Keriting"},
    "CRM": {"source_id": "com_16", "source_name": "Cabai Rawit Merah"},
}

# PIHPS' public table currently exposes these three useful levels.  The IDs
# are the values used by the official page's price-type selector.
DEFAULT_MARKET_TYPES: dict[str, int] = {
    "retail": 1,       # pasar tradisional
    "wholesale": 3,    # pedagang besar
    "producer": 4,     # produsen
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "PasarPulse-MM/0.6 academic data pipeline",
    })
    return session


def _month_chunks(start_date: str, end_date: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError(f"PIHPS start_date is after end_date: {start_date} > {end_date}")
    chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current = start
    while current <= end:
        month_end = (current + pd.offsets.MonthEnd(0)).normalize()
        chunks.append((current, min(month_end, end)))
        current = (month_end + pd.Timedelta(days=1)).normalize()
    return chunks


def _is_date_key(value: object) -> bool:
    text = str(value)
    return len(text) in {10} and text[2:3] == "/" and text[5:6] == "/"


def _parse_snapshot(
    payload: dict[str, Any],
    *,
    commodity_code: str,
    market_level: str,
    source_version: str,
    extraction_timestamp: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    records: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    commodity_name = DEFAULT_COMMODITIES.get(commodity_code, {}).get("source_name", commodity_code)
    commodity_meta = COMMODITY_ALIASES.get(_norm(commodity_name))
    if commodity_meta:
        commodity_name = commodity_meta[1]

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", ""))
        source_name = str(row.get("name", "")).strip()
        province_meta = PROVINCE_ALIASES.get(_norm(source_name))
        mapping_rows.append({
            "source_province_name": source_name,
            "province_code": province_meta[0] if province_meta else pd.NA,
            "canonical_province_name": province_meta[1] if province_meta else pd.NA,
            "commodity_code": commodity_code,
            "market_level": market_level,
            "source_level": level,
            "mapping_status": "mapped" if province_meta and level == "1" else "ignored_non_province_or_unmapped",
        })
        # level 0 is the national total; level 1 is the province row.  The
        # endpoint can also return city/market rows when its UI flags change.
        if level != "1" or province_meta is None:
            continue
        for key, value in row.items():
            if not _is_date_key(key):
                continue
            observation_date = pd.to_datetime(key, dayfirst=True, errors="coerce")
            if pd.isna(observation_date) or not start_date <= observation_date <= end_date:
                continue
            if value is None or str(value).strip() in {"", "-", "nan", "None"}:
                continue
            records.append({
                "date": observation_date,
                "province_name": province_meta[1],
                "commodity_name": commodity_name,
                "market_level": market_level,
                "price_idr_per_kg": value,
                "price_unit": "IDR/kg",
                "source_location_name": "PIHPS province average",
                "extraction_timestamp": extraction_timestamp,
                "source_version": source_version,
                "revision_flag": "source_snapshot",
                "quality_flag": "ok",
            })
    if not records:
        return pd.DataFrame(), mapping_rows
    return normalize_price_frame(pd.DataFrame(records), source="PIHPS"), mapping_rows


def _mapping_audit(
    frame: pd.DataFrame,
    *,
    commodities: dict[str, dict[str, Any]],
    market_types: dict[str, int],
) -> pd.DataFrame:
    expected = {
        code: name
        for code, name in (value for value in PROVINCE_ALIASES.values())
    }
    observed = (
        frame.groupby(["commodity_code", "market_level"])["province_code"]
        .apply(lambda values: set(values.dropna().astype(str)))
        .to_dict()
        if not frame.empty
        else {}
    )
    rows: list[dict[str, Any]] = []
    for commodity_code, commodity in commodities.items():
        for market_level in market_types:
            present = observed.get((commodity_code, market_level), set())
            for province_code, province_name in sorted(expected.items()):
                rows.append({
                    "source": "PIHPS",
                    "source_commodity_id": commodity.get("source_id"),
                    "source_commodity_name": commodity.get("source_name"),
                    "commodity_code": commodity_code,
                    "market_level": market_level,
                    "source_province_name": province_name,
                    "province_code": province_code,
                    "canonical_province_name": province_name,
                    "unit": "IDR/kg",
                    "mapping_status": "observed" if province_code in present else "not_returned_by_pihps",
                })
    return pd.DataFrame(rows)


def ingest_pihps(
    *,
    start_date: str,
    end_date: str,
    raw_dir: str | Path,
    output_base: str | Path,
    manifest_base: str | Path,
    mapping_base: str | Path,
    endpoint: str = DEFAULT_ENDPOINT,
    page_url: str = DEFAULT_PAGE_URL,
    commodities: dict[str, dict[str, Any]] | None = None,
    market_types: dict[str, int] | None = None,
    timeout: int = 90,
    overwrite_snapshots: bool = False,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path], pd.DataFrame, dict[str, Path], pd.DataFrame, dict[str, Path]]:
    """Download PIHPS monthly daily snapshots and return canonical artifacts."""
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    commodities = commodities or DEFAULT_COMMODITIES
    market_types = market_types or DEFAULT_MARKET_TYPES
    chunks = _month_chunks(start_date, end_date)
    session = _session()
    parts: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, Any]] = []
    raw_mapping_rows: list[dict[str, Any]] = []

    for market_level, price_type_id in market_types.items():
        for commodity_code, commodity in commodities.items():
            source_id = str(commodity["source_id"])
            for chunk_start, chunk_end in chunks:
                retrieved_at = _utc_now()
                stem = f"pihps_{market_level}_{commodity_code}_{chunk_start:%Y_%m}"
                target = raw / f"{stem}.json"
                status = "downloaded"
                error = ""
                response_url = ""
                payload: dict[str, Any] | None = None

                try:
                    params = {
                        "price_type_id": int(price_type_id),
                        "comcat_id": source_id,
                        "province_id": "",
                        "regency_id": "",
                        "showKota": "false",
                        "showPasar": "false",
                        "tipe_laporan": 1,
                        "start_date": chunk_start.strftime("%Y-%m-%d"),
                        "end_date": chunk_end.strftime("%Y-%m-%d"),
                        "skip": 0,
                        "take": 100,
                        "requireTotalCount": "true",
                    }
                    response_url = requests.Request("GET", endpoint, params=params).prepare().url
                    if target.exists() and target.stat().st_size > 0 and not overwrite_snapshots:
                        payload = json.loads(target.read_text(encoding="utf-8"))
                        status = "cached"
                    else:
                        response = session.get(endpoint, params=params, timeout=timeout)
                        response.raise_for_status()
                        payload = response.json()
                        response_url = response.url
                        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                            raise ValueError("PIHPS response does not contain a data list")
                        if target.exists() and overwrite_snapshots:
                            snapshot_stamp = retrieved_at.replace(":", "").replace("+", "_")
                            target = raw / f"{stem}_{snapshot_stamp}.json"
                        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    payload = payload or {}
                    snapshot_hash = _sha256(target)
                    source_version = f"PIHPS:{snapshot_hash[:16]}"
                    parsed, mapping_rows = _parse_snapshot(
                        payload,
                        commodity_code=commodity_code,
                        market_level=market_level,
                        source_version=source_version,
                        extraction_timestamp=retrieved_at,
                        start_date=chunk_start,
                        end_date=chunk_end,
                    )
                    parts.append(parsed)
                    raw_mapping_rows.extend(mapping_rows)
                    manifest_rows.append({
                        "retrieved_at_utc": retrieved_at,
                        "source": "PIHPS",
                        "source_page_url": page_url,
                        "endpoint": endpoint,
                        "source_commodity_id": source_id,
                        "commodity_code": commodity_code,
                        "market_level": market_level,
                        "price_type_id": int(price_type_id),
                        "requested_start_date": chunk_start.date(),
                        "requested_end_date": chunk_end.date(),
                        "response_url": response_url,
                        "raw_path": str(target),
                        "raw_sha256": snapshot_hash,
                        "raw_bytes": target.stat().st_size,
                        "source_rows": len(payload.get("data", [])),
                        "parsed_rows": len(parsed),
                        "status": status,
                        "error": "",
                    })
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    manifest_rows.append({
                        "retrieved_at_utc": retrieved_at,
                        "source": "PIHPS",
                        "source_page_url": page_url,
                        "endpoint": endpoint,
                        "source_commodity_id": source_id,
                        "commodity_code": commodity_code,
                        "market_level": market_level,
                        "price_type_id": int(price_type_id),
                        "requested_start_date": chunk_start.date(),
                        "requested_end_date": chunk_end.date(),
                        "response_url": response_url,
                        "raw_path": str(target),
                        "raw_sha256": "",
                        "raw_bytes": None,
                        "source_rows": None,
                        "parsed_rows": 0,
                        "status": "failed",
                        "error": error,
                    })

    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if frame.empty:
        raise RuntimeError("No PIHPS observations were downloaded or parsed.")
    keys = ["date", "province_code", "commodity_code", "market_level"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = (
        frame.sort_values(keys + ["extraction_timestamp", "source_version"])
        .drop_duplicates(keys, keep="last")
        .sort_values(["province_code", "commodity_code", "market_level", "date"])
        .reset_index(drop=True)
    )
    manifest = pd.DataFrame(manifest_rows)
    mapping = _mapping_audit(frame, commodities=commodities, market_types=market_types)
    outputs = save_frame(frame, output_base, save_csv=save_csv, save_parquet=save_parquet)
    manifest_outputs = save_frame(manifest, manifest_base, save_csv=True, save_parquet=save_parquet)
    revision_audit = manifest.copy()
    if not revision_audit.empty:
        revision_audit["revision_policy"] = "retain_raw_snapshot_and_select_latest_canonical"
        revision_audit["revision_flag"] = "source_snapshot"
    revision_outputs = save_frame(
        revision_audit,
        Path(manifest_base).with_name("pihps_revision_audit"),
        save_csv=True,
        save_parquet=save_parquet,
    )
    manifest_outputs.update({f"revision_{key}": value for key, value in revision_outputs.items()})
    mapping_outputs = save_frame(mapping, mapping_base, save_csv=True, save_parquet=save_parquet)
    summary_path = save_json(
        {
            "source": "PIHPS",
            "source_page_url": page_url,
            "endpoint": endpoint,
            "date_range": [str(pd.Timestamp(start_date).date()), str(pd.Timestamp(end_date).date())],
            "rows": int(len(frame)),
            "series": int(frame[["province_code", "commodity_code", "market_level"]].drop_duplicates().shape[0]),
            "snapshot_count": int(len(manifest)),
            "failed_snapshots": int(manifest["status"].eq("failed").sum()),
            "observed_province_codes": sorted(frame["province_code"].dropna().astype(str).unique()),
            "missing_expected_province_codes": sorted(
                set(meta[0] for meta in PROVINCE_ALIASES.values())
                - set(frame["province_code"].dropna().astype(str).unique())
            ),
        },
        Path(manifest_base).with_name("pihps_acquisition_summary.json"),
    )
    manifest_outputs["summary"] = summary_path
    return frame, outputs, manifest, manifest_outputs, mapping, mapping_outputs
