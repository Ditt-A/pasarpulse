"""Direct public-HTML BPS acquisition without the tokenized BPS WebAPI.

The current BPS statistics-table pages are Next.js documents. Their official
table payload is embedded in ``self.__next_f.push`` script records, so the
public table can be acquired reproducibly with requests while retaining the
source HTML and normalized selected columns. This is intentionally separate
from the legacy Selenium scraper because the public WebAPI token is not
required for the table page.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..utils import save_frame


PRODUCTION_URL = (
    "https://www.bps.go.id/id/statistics-table/3/"
    "ZUhFd1JtZzJWVVpqWTJsV05XTllhVmhRSzFoNFFUMDkjMw%3D%3D/"
    "produksi-tanaman-sayuran.html"
)
HARVESTED_AREA_URL = (
    "https://www.bps.go.id/id/statistics-table/3/"
    "YlhOVmIxcG1abmRxVURoS1dFbFVTamhaUml0aWR6MDkjMw%3D%3D/"
    "luas-panen-tanaman-sayuran-menurut-provinsi-dan-jenis-tanaman--2023.html"
)

COMMODITIES = {
    "BM": {"commodity_name": "Bawang Merah", "pattern": r"bawang\s+merah"},
    "CRM": {"commodity_name": "Cabai Rawit", "pattern": r"cabai\s+rawit"},
    "CMK": {"commodity_name": "Cabai Keriting", "pattern": r"cabai\s+keriting"},
}

PROVINCE_CODES = {
    "aceh": "11", "sumatera utara": "12", "sumatera barat": "13", "riau": "14",
    "jambi": "15", "sumatera selatan": "16", "bengkulu": "17", "lampung": "18",
    "kepulauan bangka belitung": "19", "kepulauan riau": "21", "dki jakarta": "31",
    "jawa barat": "32", "jawa tengah": "33", "di yogyakarta": "34",
    "daerah istimewa yogyakarta": "34", "jawa timur": "35", "banten": "36",
    "bali": "51", "nusa tenggara barat": "52", "nusa tenggara timur": "53",
    "kalimantan barat": "61", "kalimantan tengah": "62", "kalimantan selatan": "63",
    "kalimantan timur": "64", "kalimantan utara": "65", "sulawesi utara": "71",
    "sulawesi tengah": "72", "sulawesi selatan": "73", "sulawesi tenggara": "74",
    "gorontalo": "75", "sulawesi barat": "76", "maluku": "81", "maluku utara": "82",
    "papua barat": "91", "papua barat daya": "92", "papua": "94",
    "papua selatan": "95", "papua tengah": "96", "papua pegunungan": "97",
}

BPS_RELEASE_DATES = {
    2023: "2024-06-10",
    2024: "2025-06-10",
    2025: "2026-06-12",
}


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_key(value: object) -> str:
    return normalize_text(value).casefold()


def parse_bps_number(value: object) -> float | None:
    """Parse BPS Indonesian number formats such as 136.726 or 1.234,50."""

    if value is None or pd.isna(value):
        return None
    text = normalize_text(value)
    if text.casefold() in {"", "-", "–", "—", "...", "na", "n/a"}:
        return None
    text = re.sub(r"[^0-9,\.\-]", "", text)
    if not text or text == "-":
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif text.count(".") == 1:
        left, right = text.split(".")
        if len(right) == 3 and left not in {"0", "-0"}:
            text = left + right
    try:
        return float(text)
    except ValueError:
        return None


def _walk_table_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        rows = value.get("data")
        columns = value.get("kolom")
        if (
            isinstance(rows, list)
            and rows
            and isinstance(rows[0], dict)
            and "label" in rows[0]
            and isinstance(columns, dict)
        ):
            return value
        for child in value.values():
            found = _walk_table_payload(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_table_payload(child)
            if found is not None:
                return found
    return None


def extract_next_table(html: str) -> dict[str, Any]:
    """Extract the table object from BPS's embedded React flight payload."""

    marker = "self.__next_f.push([1,"
    scripts = re.finditer(r"<script\b[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
    for script_match in scripts:
        script = script_match.group(1)
        start = 0
        while True:
            position = script.find(marker, start)
            if position < 0:
                break
            tail = script[position + len(marker):]
            end = tail.rfind("])" )
            if end >= 0:
                try:
                    decoded = json.loads(tail[:end])
                    if ":" in decoded:
                        payload = json.loads(decoded.split(":", 1)[1])
                        found = _walk_table_payload(payload)
                        if found is not None:
                            return found
                except (json.JSONDecodeError, TypeError):
                    pass
            start = position + len(marker)
    raise RuntimeError("No embedded BPS statistics-table payload was found.")


def _request_page(
    session: requests.Session,
    url: str,
    year: int,
    timeout: int,
    retries: int = 4,
) -> tuple[str, str]:
    full_url = f"{url}?year={int(year)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.bps.go.id/",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(full_url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text, response.url
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"BPS page request failed for {full_url}: {last_error}")


def _find_variable_id(columns: dict[str, Any], pattern: str, measure: str) -> str:
    candidates: list[tuple[int, str]] = []
    for variable_id, metadata in columns.items():
        name = normalize_text((metadata or {}).get("nama_variabel", ""))
        lowered = name.casefold()
        if not re.search(pattern, lowered, re.IGNORECASE):
            continue
        terms = ["produksi"] if measure == "production" else ["luas", "panen"]
        score = 10 + sum(3 for term in terms if term in lowered)
        candidates.append((score, variable_id))
    if not candidates:
        raise KeyError(f"BPS variable not found: /{pattern}/ for {measure}")
    return sorted(candidates, reverse=True)[0][1]


def _selected_wide_frame(
    table: dict[str, Any],
    year: int,
    measure: str,
    source_url: str,
) -> pd.DataFrame:
    columns = table["kolom"]
    variable_ids = {
        code: _find_variable_id(columns, meta["pattern"], measure)
        for code, meta in COMMODITIES.items()
    }
    rows: list[dict[str, Any]] = []
    for record in table["data"]:
        province_name = normalize_text(record.get("label"))
        if not province_name or normalize_key(province_name) in {"indonesia", "jumlah", "total"}:
            continue
        row: dict[str, Any] = {"Provinsi": province_name}
        variables = record.get("variables") or {}
        for code, meta in COMMODITIES.items():
            variable_id = variable_ids[code]
            variable = variables.get(variable_id) or {}
            label = columns[variable_id].get("nama_variabel", meta["commodity_name"])
            row[label] = variable.get("value_raw", variable.get("value"))
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError(f"BPS {measure} {year} returned no province rows.")
    result["source_url"] = source_url
    result["source_year"] = int(year)
    result["source_measure"] = measure
    return result


def _normalize_long(
    frame: pd.DataFrame,
    year: int,
    measure: str,
    source_url: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        province_name = normalize_text(record["Provinsi"])
        province_code = PROVINCE_CODES.get(normalize_key(province_name))
        for commodity_code, meta in COMMODITIES.items():
            pattern = re.compile(meta["pattern"], re.IGNORECASE)
            candidates = [
                column for column in frame.columns
                if pattern.search(normalize_text(column))
                and (
                    "produksi" in normalize_text(column).casefold()
                    if measure == "production"
                    else "luas" in normalize_text(column).casefold()
                )
            ]
            if not candidates:
                raise KeyError(f"No selected BPS column for {commodity_code} {measure}.")
            value_column = candidates[0]
            rows.append(
                {
                    "year": int(year),
                    "province_code": province_code,
                    "province_name": province_name,
                    "commodity_code": commodity_code,
                    "commodity_name": meta["commodity_name"],
                    "value": parse_bps_number(record[value_column]),
                    "source_column": value_column,
                    "source_url": source_url,
                    "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
                    "province_mapping_status": "mapped" if province_code else "unmapped",
                }
            )
    result = pd.DataFrame(rows)
    if measure == "production":
        result = result.rename(columns={"value": "production_quintal"})
        result["production_kg"] = result["production_quintal"] * 100.0
    else:
        result = result.rename(columns={"value": "harvested_area_ha"})
    return result


def build_annual_dataset_direct(
    years: list[int],
    *,
    output_base: str | Path,
    raw_dir: str | Path,
    save_csv: bool = True,
    save_parquet: bool = True,
    timeout: int = 120,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    raw_root = Path(raw_dir)
    raw_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_base).resolve()
    project_root = output_path.parents[2]

    def portable_path(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(project_root))
        except ValueError:
            return str(path.resolve())

    session = requests.Session()
    production_parts: list[pd.DataFrame] = []
    area_parts: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, Any]] = []
    for year in sorted(set(int(value) for value in years)):
        production_html, production_url = _request_page(session, PRODUCTION_URL, year, timeout)
        production_table = extract_next_table(production_html)
        production_wide = _selected_wide_frame(production_table, year, "production", production_url)
        production_csv = raw_root / f"production_{year}_rendered.csv"
        production_html_path = raw_root / f"production_{year}_page.html"
        production_wide.to_csv(production_csv, index=False)
        production_html_path.write_text(production_html, encoding="utf-8")
        manifest_rows.append(
            {
                "year": year,
                "measure": "production",
                "source_url": production_url,
                "raw_html_path": portable_path(production_html_path),
                "raw_table_path": portable_path(production_csv),
                "raw_html_sha256": hashlib.sha256(production_html_path.read_bytes()).hexdigest(),
                "raw_html_bytes": production_html_path.stat().st_size,
                "table_rows": len(production_wide),
                "status": "complete",
            }
        )
        production_parts.append(_normalize_long(production_wide, year, "production", production_url))

        area_html, area_url = _request_page(session, HARVESTED_AREA_URL, year, timeout)
        area_table = extract_next_table(area_html)
        area_wide = _selected_wide_frame(area_table, year, "harvested_area", area_url)
        area_csv = raw_root / f"harvested_area_{year}_rendered.csv"
        area_html_path = raw_root / f"harvested_area_{year}_page.html"
        area_wide.to_csv(area_csv, index=False)
        area_html_path.write_text(area_html, encoding="utf-8")
        manifest_rows.append(
            {
                "year": year,
                "measure": "harvested_area",
                "source_url": area_url,
                "raw_html_path": portable_path(area_html_path),
                "raw_table_path": portable_path(area_csv),
                "raw_html_sha256": hashlib.sha256(area_html_path.read_bytes()).hexdigest(),
                "raw_html_bytes": area_html_path.stat().st_size,
                "table_rows": len(area_wide),
                "status": "complete",
            }
        )
        area_parts.append(_normalize_long(area_wide, year, "harvested_area", area_url))

    production = pd.concat(production_parts, ignore_index=True)
    area = pd.concat(area_parts, ignore_index=True)
    keys = ["year", "province_code", "province_name", "commodity_code", "commodity_name"]
    result = production.merge(
        area[keys + ["harvested_area_ha", "source_column", "source_url", "extracted_at_utc"]],
        on=keys,
        how="outer",
        suffixes=("_production", "_area"),
    )
    harvested_area = pd.to_numeric(result["harvested_area_ha"], errors="coerce")
    harvested_area = harvested_area.mask(harvested_area.eq(0))
    result["productivity_kg_per_ha"] = pd.to_numeric(result["production_kg"], errors="coerce") / harvested_area
    result["production_available"] = result["production_kg"].notna().astype(int)
    result["harvested_area_available"] = result["harvested_area_ha"].notna().astype(int)
    result["production_effective_date"] = pd.to_datetime(
        result["year"].map(BPS_RELEASE_DATES), errors="coerce"
    )
    result["production_release_source"] = (
        "BPS Statistics of Horticulture national publication"
    )
    result["quality_flag"] = "ok"
    result.loc[result["province_code"].isna(), "quality_flag"] = "unmapped_province"
    result.loc[result["production_kg"].isna() & result["harvested_area_ha"].isna(), "quality_flag"] = "missing_production_and_harvested_area"
    result.loc[result["production_kg"].isna() & result["harvested_area_ha"].notna(), "quality_flag"] = "missing_production"
    result.loc[result["production_kg"].notna() & result["harvested_area_ha"].isna(), "quality_flag"] = "missing_harvested_area"
    result = result.sort_values(["year", "province_code", "commodity_code"], na_position="last").reset_index(drop=True)
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    manifest = pd.DataFrame(manifest_rows).sort_values(["year", "measure"]).reset_index(drop=True)
    manifest_outputs = save_frame(
        manifest,
        Path(output_base).parent / "bps_acquisition_manifest",
        save_csv=save_csv,
        save_parquet=save_parquet,
    )
    outputs.update({f"manifest_{key}": value for key, value in manifest_outputs.items()})
    return result, outputs
