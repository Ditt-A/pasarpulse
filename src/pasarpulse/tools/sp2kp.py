"""Public SP2KP discovery, download, and canonical parsing.

Primary discovery uses the official Kementerian Perdagangan DCAT catalog. If
catalog discovery is unavailable, monthly public download URLs are generated
from the official SP2KP URL pattern so ingestion does not depend on data.go.id
HTML or CKAN DNS availability.
"""
from __future__ import annotations

import calendar
import hashlib
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import requests
from lxml import html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils import save_frame
from .prices import CANONICAL_COLUMNS, normalize_price_frame

DEFAULT_DATASET_ID = "6ea910f4-4b55-422b-80d7-8346c2aae076"
DEFAULT_DATASET_PAGE = "https://data.go.id/dataset/dataset/tingkat-harga-daerah"
DEFAULT_DCAT_URL = "https://api-splp.layanan.go.id/sdi-kemendag/1.1/dcat"
DEFAULT_DIRECT_URL_TEMPLATE = (
    "https://api-sp2kp.kemendag.go.id/kld/api/list-harga-harian/{year}/{month:02d}"
)
DEFAULT_CATALOG_APIS = [
    "https://katalog.data.go.id/api/3/action/package_show",
    "https://katalog.data.go.id/api/action/package_show",
    "https://data.go.id/api/3/action/package_show",
]

MONTHS = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2,
    "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "oktober": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "desember": 12, "december": 12, "dec": 12,
}

PROVINCE_COL_ALIASES = {"provinsi", "nama provinsi", "province", "wilayah", "daerah"}
DATE_COL_ALIASES = {"tanggal", "date", "tgl", "waktu", "periode"}
COMMODITY_COL_ALIASES = {"komoditas", "komoditi", "nama komoditas", "nama komoditi", "bahan pokok"}
PRICE_COL_ALIASES = {"harga", "harga rata rata", "harga rp kg", "harga rp per kg", "nilai", "price"}

TARGET_COMMODITIES = {
    "bawang merah": ("BM", "Bawang Merah"),
    "cabai rawit merah": ("CRM", "Cabai Rawit Merah"),
    "cabe rawit merah": ("CRM", "Cabai Rawit Merah"),
    "cabai merah keriting": ("CMK", "Cabai Merah Keriting"),
    "cabe merah keriting": ("CMK", "Cabai Merah Keriting"),
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = text.replace("\xa0", " ").casefold().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_year_month(text: str) -> tuple[int | None, int | None]:
    norm = _norm(text)
    year_match = re.search(r"\b(20\d{2})\b", norm)
    year = int(year_match.group(1)) if year_match else None
    month = None
    for token, number in MONTHS.items():
        if re.search(rf"\b{re.escape(token)}\b", norm):
            month = number
            break
    return year, month


def _http_session(*, retries: int = 4, backoff_factor: float = 1.0) -> requests.Session:
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "PasarPulse-MM/0.7 academic data pipeline",
        "Accept": "application/json, text/csv, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*",
    })
    return session


def _resource_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", payload)
    resources = result.get("resources", []) if isinstance(result, dict) else []
    rows = []
    for item in resources:
        name = str(item.get("name") or item.get("title") or "")
        year, month = _parse_year_month(name)
        rows.append({
            "resource_id": item.get("id"),
            "name": name,
            "url": item.get("url") or item.get("download_url"),
            "format": str(item.get("format") or "").upper(),
            "last_modified": item.get("last_modified") or item.get("metadata_modified") or item.get("created"),
            "size": item.get("size"),
            "year": year,
            "month": month,
        })
    return rows


def _dcat_resource_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    datasets = payload.get("dataset", []) if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for dataset in datasets:
        title = str(dataset.get("title") or "")
        if "tingkat harga daerah" not in _norm(title):
            continue
        modified = dataset.get("modified") or dataset.get("issued")
        for item in dataset.get("distribution", []) or []:
            name = str(item.get("title") or item.get("description") or "")
            year, month = _parse_year_month(name)
            url = item.get("downloadURL") or item.get("accessURL")
            rows.append({
                "resource_id": hashlib.sha1(f"{name}|{url}".encode()).hexdigest()[:16],
                "name": name,
                "url": url,
                "format": str(item.get("format") or "").upper(),
                "last_modified": modified,
                "size": None,
                "year": year,
                "month": month,
            })
    return rows


def _discover_from_dcat(dcat_url: str, timeout: int) -> tuple[list[dict[str, Any]], str]:
    session = _http_session()
    response = session.get(dcat_url, timeout=timeout)
    response.raise_for_status()
    rows = _dcat_resource_records(response.json())
    if not rows:
        raise RuntimeError("Official Kemendag DCAT contains no Tingkat Harga Daerah resources.")
    return rows, dcat_url


def _discover_from_api(dataset_id: str, api_urls: Iterable[str], timeout: int) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    session = _http_session(retries=2)
    for endpoint in api_urls:
        try:
            response = session.get(endpoint, params={"id": dataset_id}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is False:
                raise RuntimeError(str(payload.get("error")))
            rows = _resource_records(payload)
            if rows:
                return rows, endpoint
            errors.append(f"{endpoint}: no resources")
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def _discover_from_html(page_url: str, timeout: int) -> tuple[list[dict[str, Any]], str]:
    session = _http_session(retries=2)
    response = session.get(page_url, timeout=timeout)
    response.raise_for_status()
    document = html.fromstring(response.content)
    rows: list[dict[str, Any]] = []
    for link in document.xpath("//a[@href]"):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        surrounding = " ".join(link.xpath("ancestor-or-self::*[self::a or self::div or self::section][1]//text()"))
        text = " ".join(str(t) for t in link.itertext())
        blob = f"{text} {surrounding}"
        if "sp2kp" not in _norm(blob) and "download" not in _norm(text):
            continue
        if href.startswith("/"):
            parsed = urlparse(page_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        year, month = _parse_year_month(blob)
        if year and month:
            rows.append({
                "resource_id": hashlib.sha1(href.encode()).hexdigest()[:16],
                "name": re.sub(r"\s+", " ", blob).strip()[:240],
                "url": href,
                "format": Path(urlparse(href).path).suffix.lstrip(".").upper(),
                "last_modified": None,
                "size": None,
                "year": year,
                "month": month,
            })
    if not rows:
        raise RuntimeError("No downloadable SP2KP links found in data.go.id HTML.")
    return rows, page_url


def _direct_resource_rows(start_date: str, end_date: str, template: str) -> list[dict[str, Any]]:
    periods = pd.period_range(pd.Timestamp(start_date).to_period("M"), pd.Timestamp(end_date).to_period("M"), freq="M")
    rows: list[dict[str, Any]] = []
    for period in periods:
        year, month = int(period.year), int(period.month)
        url = template.format(year=year, month=month)
        rows.append({
            "resource_id": f"direct-{year:04d}-{month:02d}",
            "name": f"Harga Komoditas Bahan Pokok SP2KP {year:04d}-{month:02d}",
            "url": url,
            "format": "XLSX",
            "last_modified": None,
            "size": None,
            "year": year,
            "month": month,
            "discovery_source": "official_direct_url_pattern",
        })
    return rows


def discover_sp2kp_resources(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_page_url: str = DEFAULT_DATASET_PAGE,
    dcat_url: str = DEFAULT_DCAT_URL,
    direct_url_template: str = DEFAULT_DIRECT_URL_TEMPLATE,
    catalog_api_urls: Iterable[str] = DEFAULT_CATALOG_APIS,
    use_catalog_discovery: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout: int = 60,
) -> pd.DataFrame:
    """Discover monthly public resources without tokens or access requests.

    Discovery order is official Kemendag DCAT, legacy catalogue APIs, data.go.id
    HTML, then deterministic official SP2KP monthly URLs. Missing months are
    always filled with deterministic official URLs.
    """
    start = start_date or "2024-02-01"
    end = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    discovery_errors: list[str] = []

    if use_catalog_discovery:
        strategies = [
            ("dcat", lambda: _discover_from_dcat(dcat_url, timeout)),
            ("catalog_api", lambda: _discover_from_api(dataset_id, catalog_api_urls, timeout)),
            ("html", lambda: _discover_from_html(dataset_page_url, timeout)),
        ]
        for name, strategy in strategies:
            try:
                discovered, source = strategy()
                for row in discovered:
                    row = dict(row)
                    row["discovery_source"] = source
                    rows.append(row)
                if rows:
                    break
            except Exception as exc:
                discovery_errors.append(f"{name}: {type(exc).__name__}: {exc}")

    # Official URL pattern is the default path and also fills catalog gaps.
    direct_rows = _direct_resource_rows(start, end, direct_url_template)
    rows.extend(direct_rows)

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("SP2KP resource discovery returned an empty result.")
    frame = frame.dropna(subset=["url", "year", "month"])
    frame["year"] = frame["year"].astype(int)
    frame["month"] = frame["month"].astype(int)
    frame["period"] = pd.to_datetime(dict(year=frame["year"], month=frame["month"], day=1))
    frame["last_modified_parsed"] = pd.to_datetime(frame.get("last_modified"), errors="coerce", utc=True)
    frame["size_numeric"] = pd.to_numeric(frame.get("size"), errors="coerce")
    frame["discovery_errors"] = " | ".join(discovery_errors)

    frame = frame[frame["period"].between(
        pd.Timestamp(start).to_period("M").to_timestamp(),
        pd.Timestamp(end).to_period("M").to_timestamp(),
    )]
    # Prefer catalog/DCAT records over deterministic rows when both exist.
    frame["source_priority"] = frame["discovery_source"].eq("official_direct_url_pattern").astype(int)
    frame = frame.sort_values(
        ["year", "month", "source_priority", "last_modified_parsed", "size_numeric", "resource_id"],
        ascending=[True, True, True, True, True, True],
        na_position="first",
    ).drop_duplicates(["year", "month"], keep="first")
    return frame.sort_values(["year", "month"]).reset_index(drop=True)


def _google_drive_direct(url: str) -> str:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return url
    match = re.search(r"/file/d/([^/]+)", parsed.path)
    file_id = match.group(1) if match else parse_qs(parsed.query).get("id", [None])[0]
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t" if file_id else url


def _extension(resource: pd.Series, response: requests.Response) -> str:
    fmt = str(resource.get("format") or "").lower().strip(".")
    if fmt in {"xlsx", "xls", "csv", "zip"}:
        return f".{fmt}"
    suffix = Path(urlparse(str(resource["url"])).path).suffix.lower()
    if suffix in {".xlsx", ".xls", ".csv", ".zip"}:
        return suffix
    content_type = response.headers.get("content-type", "").lower()
    if "spreadsheetml" in content_type:
        return ".xlsx"
    if "ms-excel" in content_type:
        return ".xls"
    if "csv" in content_type or "text/plain" in content_type:
        return ".csv"
    return ".bin"


def download_sp2kp_resources(
    resources: pd.DataFrame,
    raw_dir: str | Path,
    *,
    overwrite: bool = False,
    timeout: int = 180,
    direct_url_template: str = DEFAULT_DIRECT_URL_TEMPLATE,
) -> pd.DataFrame:
    """Download monthly resources and retain per-month failures in the manifest."""
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, Any]] = []
    session = _http_session(retries=4, backoff_factor=1.5)
    for _, resource in resources.iterrows():
        year, month = int(resource.year), int(resource.month)
        target_stub = raw / f"sp2kp_{year:04d}_{month:02d}"
        existing = next((p for p in raw.glob(target_stub.name + ".*") if p.suffix != ".part"), None)
        if existing and existing.stat().st_size > 0 and not overwrite:
            downloaded.append(dict(resource) | {
                "local_path": str(existing),
                "download_status": "cached",
                "download_error": "",
                "resolved_url": str(resource.url),
            })
            continue

        primary = _google_drive_direct(str(resource.url))
        deterministic = direct_url_template.format(year=year, month=month)
        candidates = list(dict.fromkeys([primary, deterministic]))
        errors: list[str] = []
        completed = False
        for url in candidates:
            try:
                response = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
                response.raise_for_status()
                ext = _extension(resource, response)
                target = target_stub.with_suffix(ext)
                temp = target.with_suffix(target.suffix + ".part")
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                if not temp.exists() or temp.stat().st_size == 0:
                    raise RuntimeError("empty response body")
                detected = _detect_file_extension(temp, declared_format=str(resource.get("format") or ""))
                if detected == ".html":
                    sample = temp.read_text(encoding="utf-8", errors="ignore")[:500]
                    temp.unlink(missing_ok=True)
                    raise RuntimeError(f"HTML returned instead of data: {sample!r}")
                if detected and detected != target.suffix:
                    target = target_stub.with_suffix(detected)
                temp.replace(target)
                downloaded.append(dict(resource) | {
                    "local_path": str(target),
                    "download_status": "downloaded",
                    "download_error": "",
                    "resolved_url": url,
                })
                completed = True
                break
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
        if not completed:
            downloaded.append(dict(resource) | {
                "local_path": "",
                "download_status": "failed",
                "download_error": " | ".join(errors),
                "resolved_url": "",
            })
    return pd.DataFrame(downloaded)


def _detect_file_extension(path: Path, *, declared_format: str = "") -> str:
    head = path.read_bytes()[:4096]
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html")):
        return ".html"
    if head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return ".xls"
    if head.startswith(b"PK\x03\x04"):
        # XLSX is itself a ZIP container. Check its member names.
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" in names and any(name.startswith("xl/") for name in names):
                return ".xlsx"
        except zipfile.BadZipFile:
            pass
        return ".zip" if declared_format.casefold() == "zip" else ".xlsx"
    if b"," in head or b";" in head or b"\t" in head:
        try:
            head.decode("utf-8")
            return ".csv"
        except UnicodeDecodeError:
            try:
                head.decode("latin-1")
                return ".csv"
            except UnicodeDecodeError:
                pass
    return Path(path).suffix.removesuffix(".part") or ".bin"


def _dedupe_headers(values: Iterable[object]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for value in values:
        base = str(value).strip() if value is not None and not pd.isna(value) else "unnamed"
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count}")
    return result


def _find_column(columns: Iterable[object], aliases: set[str]) -> object | None:
    exact = {column: _norm(column) for column in columns}
    for column, normalized in exact.items():
        if normalized in aliases:
            return column
    for column, normalized in exact.items():
        if any(alias in normalized for alias in aliases):
            return column
    return None


def _commodity_column_map(columns: Iterable[object]) -> dict[object, tuple[str, str]]:
    found = {}
    for column in columns:
        normalized = _norm(column)
        for alias, meta in TARGET_COMMODITIES.items():
            if alias in normalized:
                found[column] = meta
                break
    return found


def _day_from_column(column: object, year: int, month: int) -> pd.Timestamp | None:
    if isinstance(column, (pd.Timestamp, np.datetime64)):
        value = pd.Timestamp(column)
        return value.normalize() if value.year == year and value.month == month else None
    normalized = _norm(column)
    parsed = pd.to_datetime(str(column), errors="coerce", dayfirst=True)
    if not pd.isna(parsed) and parsed.year == year and parsed.month == month:
        return parsed.normalize()
    match = re.fullmatch(r"(?:tanggal|tgl)?\s*(\d{1,2})", normalized)
    if match:
        day = int(match.group(1))
        if 1 <= day <= calendar.monthrange(year, month)[1]:
            return pd.Timestamp(year=year, month=month, day=day)
    return None


def _infer_target(text: str, mapping: dict[str, Any]) -> Any | None:
    normalized = _norm(text)
    hits = [value for key, value in mapping.items() if key in normalized]
    unique = []
    for value in hits:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else None


def _candidate_score(frame: pd.DataFrame, year: int, month: int, context: str) -> int:
    if frame.empty or len(frame.columns) < 2:
        return -1
    province = _find_column(frame.columns, PROVINCE_COL_ALIASES)
    date = _find_column(frame.columns, DATE_COL_ALIASES)
    commodity = _find_column(frame.columns, COMMODITY_COL_ALIASES)
    price = _find_column(frame.columns, PRICE_COL_ALIASES)
    comm_cols = _commodity_column_map(frame.columns)
    day_cols = [c for c in frame.columns if _day_from_column(c, year, month) is not None]
    score = 0
    score += 5 if province is not None else 0
    score += 4 if date is not None else 0
    score += 4 if commodity is not None else 0
    score += 4 if price is not None else 0
    score += min(len(comm_cols), 3) * 3
    score += min(len(day_cols), 31)
    score += 3 if _infer_target(context, TARGET_COMMODITIES) else 0
    return score


def _best_sheet_frame(path: Path, sheet_name: str, year: int, month: int) -> tuple[pd.DataFrame, str]:
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    context = f"{sheet_name} " + " ".join(raw.head(12).astype(str).fillna("").to_numpy().ravel())
    best_score = -1
    best = pd.DataFrame()
    for header_idx in range(min(15, len(raw))):
        headers = _dedupe_headers(raw.iloc[header_idx].tolist())
        frame = raw.iloc[header_idx + 1:].copy()
        frame.columns = headers
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        score = _candidate_score(frame, year, month, context)
        if score > best_score:
            best_score, best = score, frame
    return best, context


def _canonical_from_frame(frame: pd.DataFrame, *, year: int, month: int, context: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    province_col = _find_column(frame.columns, PROVINCE_COL_ALIASES)
    date_col = _find_column(frame.columns, DATE_COL_ALIASES)
    commodity_col = _find_column(frame.columns, COMMODITY_COL_ALIASES)
    price_col = _find_column(frame.columns, PRICE_COL_ALIASES)
    commodity_cols = _commodity_column_map(frame.columns)
    day_columns = {c: _day_from_column(c, year, month) for c in frame.columns}
    day_columns = {c: d for c, d in day_columns.items() if d is not None}

    inferred_commodity = _infer_target(context, TARGET_COMMODITIES)
    inferred_province = None
    # Existing canonical province normalization will validate inferred values.

    out: pd.DataFrame
    if province_col is not None and date_col is not None and commodity_col is not None and price_col is not None:
        out = frame[[date_col, province_col, commodity_col, price_col]].rename(columns={
            date_col: "date", province_col: "province_name", commodity_col: "commodity_name", price_col: "price_idr_per_kg"
        })
    elif province_col is not None and date_col is not None and commodity_cols:
        keep = [date_col, province_col] + list(commodity_cols)
        out = frame[keep].melt(id_vars=[date_col, province_col], var_name="commodity_source", value_name="price_idr_per_kg")
        out["commodity_name"] = out["commodity_source"].map(lambda c: commodity_cols[c][1])
        out = out.rename(columns={date_col: "date", province_col: "province_name"})
    elif province_col is not None and commodity_col is not None and day_columns:
        keep = [province_col, commodity_col] + list(day_columns)
        out = frame[keep].melt(id_vars=[province_col, commodity_col], var_name="day_source", value_name="price_idr_per_kg")
        out["date"] = out["day_source"].map(day_columns)
        out = out.rename(columns={province_col: "province_name", commodity_col: "commodity_name"})
    elif province_col is not None and day_columns and inferred_commodity:
        keep = [province_col] + list(day_columns)
        out = frame[keep].melt(id_vars=[province_col], var_name="day_source", value_name="price_idr_per_kg")
        out["date"] = out["day_source"].map(day_columns)
        out["commodity_name"] = inferred_commodity[1]
        out = out.rename(columns={province_col: "province_name"})
    else:
        return pd.DataFrame()

    out["market_level"] = "retail"
    out["source"] = "SP2KP"
    return out[["date", "province_name", "commodity_name", "market_level", "price_idr_per_kg", "source"]]


def parse_sp2kp_file(path: str | Path, *, year: int, month: int) -> pd.DataFrame:
    file_path = Path(path)
    parts: list[pd.DataFrame] = []
    if file_path.suffix.lower() == ".zip":
        extract_dir = file_path.parent / f"{file_path.stem}_extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(file_path) as archive:
            safe_members = [
                member for member in archive.namelist()
                if not member.endswith("/")
                and Path(member).suffix.lower() in {".xlsx", ".xls", ".csv"}
                and ".." not in Path(member).parts
            ]
            if not safe_members:
                raise ValueError(f"ZIP has no Excel/CSV SP2KP files: {file_path.name}")
            for member in safe_members:
                target = extract_dir / Path(member).name
                with archive.open(member) as source, target.open("wb") as destination:
                    destination.write(source.read())
                parts.append(parse_sp2kp_file(target, year=year, month=month))
        combined = pd.concat(parts, ignore_index=True)
        keys = ["date", "province_code", "commodity_code", "market_level", "source"]
        return combined.sort_values(keys).drop_duplicates(keys, keep="last").reset_index(drop=True)
    if file_path.suffix.lower() in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(file_path)
        for sheet in workbook.sheet_names:
            try:
                frame, context = _best_sheet_frame(file_path, sheet, year, month)
                parsed = _canonical_from_frame(frame, year=year, month=month, context=context)
                if not parsed.empty:
                    parts.append(parsed)
            except Exception:
                continue
    elif file_path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                raw = pd.read_csv(file_path, header=None, encoding=encoding, dtype=object)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UnicodeDecodeError("unknown", b"", 0, 1, "Unable to decode CSV")
        context = " ".join(raw.head(12).astype(str).fillna("").to_numpy().ravel())
        best_score, best = -1, pd.DataFrame()
        for idx in range(min(15, len(raw))):
            frame = raw.iloc[idx + 1:].copy()
            frame.columns = _dedupe_headers(raw.iloc[idx].tolist())
            score = _candidate_score(frame, year, month, context)
            if score > best_score:
                best_score, best = score, frame
        parsed = _canonical_from_frame(best, year=year, month=month, context=context)
        if not parsed.empty:
            parts.append(parsed)
    else:
        raise ValueError(f"Unsupported SP2KP file type: {file_path.suffix}")

    if not parts:
        raise ValueError(f"No recognizable SP2KP table found in {file_path.name}")
    raw_result = pd.concat(parts, ignore_index=True)
    canonical = normalize_price_frame(raw_result, source="SP2KP", default_market_level="retail")
    canonical = canonical[canonical["commodity_code"].isin(["BM", "CRM", "CMK"])].copy()
    canonical["source_version"] = f"SP2KP_{year:04d}_{month:02d}"
    canonical["source_location_name"] = "Province-level average retail price"
    return canonical[CANONICAL_COLUMNS]


def ingest_sp2kp(
    *,
    output_base: str | Path,
    raw_dir: str | Path,
    manifest_base: str | Path,
    start_date: str,
    end_date: str,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_page_url: str = DEFAULT_DATASET_PAGE,
    dcat_url: str = DEFAULT_DCAT_URL,
    direct_url_template: str = DEFAULT_DIRECT_URL_TEMPLATE,
    catalog_api_urls: Iterable[str] = DEFAULT_CATALOG_APIS,
    use_catalog_discovery: bool = False,
    overwrite_downloads: bool = False,
    timeout: int = 180,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path], pd.DataFrame, dict[str, Path]]:
    resources = discover_sp2kp_resources(
        dataset_id=dataset_id,
        dataset_page_url=dataset_page_url,
        dcat_url=dcat_url,
        direct_url_template=direct_url_template,
        catalog_api_urls=catalog_api_urls,
        use_catalog_discovery=use_catalog_discovery,
        start_date=start_date,
        end_date=end_date,
        timeout=min(timeout, 90),
    )
    manifest = download_sp2kp_resources(
        resources, raw_dir, overwrite=overwrite_downloads, timeout=timeout,
        direct_url_template=direct_url_template,
    )
    parts = []
    parse_status = []
    for _, item in manifest.iterrows():
        try:
            if str(item.get("download_status", "")) == "failed" or not str(item.get("local_path", "")).strip():
                raise RuntimeError(str(item.get("download_error") or "download failed"))
            parsed = parse_sp2kp_file(item.local_path, year=int(item.year), month=int(item.month))
            parts.append(parsed)
            parse_status.append("parsed")
        except Exception as exc:
            parse_status.append(f"failed: {type(exc).__name__}: {exc}")
    manifest["parse_status"] = parse_status
    manifest_outputs = save_frame(manifest, manifest_base, save_csv=True, save_parquet=save_parquet)
    if not parts:
        failed = manifest[["year", "month", "local_path", "parse_status"]].to_dict("records")
        raise RuntimeError(f"All SP2KP files failed to parse: {failed}")

    result = pd.concat(parts, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    result = result[result["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
    keys = ["date", "province_code", "commodity_code", "market_level", "source"]
    result = result.sort_values(keys + ["source_version"]).drop_duplicates(keys, keep="last")
    result = result.sort_values(["province_code", "commodity_code", "market_level", "date"]).reset_index(drop=True)
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return result, outputs, manifest, manifest_outputs