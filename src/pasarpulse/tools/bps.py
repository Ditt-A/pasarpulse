"""Browser-based scraper for public BPS horticulture statistics tables.

This intentionally does not use the tokenized BPS WebAPI. It renders the public
statistics table in a real Chrome session, then parses the visible HTML table.
Raw rendered tables and debug captures are retained for auditability.
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from ..credentials import load_project_credentials
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


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def normalize_key(value: object) -> str:
    return normalize_text(value).casefold()


def parse_bps_number(value: object) -> float | None:
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
        text = text.replace(".", "").replace(",", ".")
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


def add_year_query(url: str, year: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["year"] = str(year)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        flattened: list[str] = []
        for column in result.columns:
            parts: list[str] = []
            for item in column:
                text = normalize_text(item)
                if not text or text.casefold().startswith("unnamed"):
                    continue
                if text not in parts:
                    parts.append(text)
            flattened.append(" | ".join(parts))
        result.columns = flattened
    else:
        result.columns = [normalize_text(column) for column in result.columns]
    return result


def select_bps_table(html: str, expected_terms: Iterable[str]) -> pd.DataFrame:
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError as exc:
        raise RuntimeError("No HTML table was found on the rendered BPS page.") from exc
    candidates: list[tuple[int, pd.DataFrame]] = []
    for table in tables:
        table = flatten_columns(table)
        header = " | ".join(map(str, table.columns)).casefold()
        score = 10 if "provinsi" in header else 0
        score += sum(3 for term in expected_terms if term.casefold() in header)
        score += min(len(table), 50) // 10
        if score:
            candidates.append((score, table))
    if not candidates:
        raise RuntimeError("BPS statistics table could not be identified in rendered HTML.")
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def clean_province_name(value: object) -> str:
    text = re.sub(r"^\d+[\.\)]?\s*", "", normalize_text(value))
    text = re.sub(r"\s*[\*†‡¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", text).strip()
    text = re.sub(r"\s*\((?:[a-z]|\d+)\)$", "", text, flags=re.IGNORECASE).strip()
    return text


def _province_column(columns: Iterable[object]) -> str:
    for column in columns:
        if re.search(r"\bprovinsi\b", normalize_text(column), flags=re.IGNORECASE):
            return str(column)
    raise KeyError("Province column was not found.")


def _measure_column(columns: Iterable[object], commodity_pattern: str, year: int, measure: str) -> str:
    candidates: list[tuple[int, str]] = []
    measure_terms = ["produksi"] if measure == "production" else ["luas", "panen"]
    for column in columns:
        text = normalize_text(column)
        lowered = text.casefold()
        if not re.search(commodity_pattern, lowered, flags=re.IGNORECASE):
            continue
        score = 10
        if str(year) in text:
            score += 5
        score += sum(2 for term in measure_terms if term in lowered)
        candidates.append((score, str(column)))
    if not candidates:
        raise KeyError(f"No {measure} column for /{commodity_pattern}/ and year {year}.")
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def normalize_one_table(frame: pd.DataFrame, year: int, measure: str, source_url: str) -> pd.DataFrame:
    province_col = _province_column(frame.columns)
    extracted_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for commodity_code, meta in COMMODITIES.items():
        value_col = _measure_column(frame.columns, meta["pattern"], year, measure)
        for _, record in frame[[province_col, value_col]].iterrows():
            province_name = clean_province_name(record[province_col])
            key = normalize_key(province_name)
            if not province_name or key in {"indonesia", "jumlah", "total"}:
                continue
            province_code = PROVINCE_CODES.get(key)
            rows.append(
                {
                    "year": int(year),
                    "province_code": province_code,
                    "province_name": province_name,
                    "commodity_code": commodity_code,
                    "commodity_name": meta["commodity_name"],
                    "value": parse_bps_number(record[value_col]),
                    "source_column": value_col,
                    "source_url": source_url,
                    "extracted_at_utc": extracted_at,
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


def create_driver(*, headless: bool, project_root: str | Path) -> uc.Chrome:
    import undetected_chromedriver as uc

    from selenium.webdriver.common.by import By

    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    for argument in (
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        "--window-size=1920,1080", "--lang=id-ID",
    ):
        options.add_argument(argument)
    settings = load_project_credentials(project_root=project_root, allow_missing_setup_file=True)
    kwargs: dict[str, object] = {"options": options}
    if settings.get("CHROME_MAJOR_VERSION"):
        kwargs["version_main"] = int(settings["CHROME_MAJOR_VERSION"])
    return uc.Chrome(**kwargs)


def wait_for_page(driver: uc.Chrome, timeout: int) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, timeout).until(lambda current: current.execute_script("return document.readyState") == "complete")
    WebDriverWait(driver, timeout).until(lambda current: len(current.find_elements(By.CSS_SELECTOR, "table")) > 0)
    time.sleep(2.0)


def scrape_rendered_table(
    driver: uc.Chrome,
    *,
    base_url: str,
    year: int,
    expected_terms: Iterable[str],
    timeout: int,
    debug_dir: Path,
    label: str,
) -> tuple[pd.DataFrame, str]:
    from selenium.common.exceptions import TimeoutException, WebDriverException

    url = add_year_query(base_url, year)
    try:
        driver.get(url)
        wait_for_page(driver, timeout)
        return select_bps_table(driver.page_source, expected_terms), url
    except (TimeoutException, WebDriverException, RuntimeError, KeyError) as exc:
        debug_dir.mkdir(parents=True, exist_ok=True)
        try:
            (debug_dir / f"{label}_{year}_debug.html").write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot(str(debug_dir / f"{label}_{year}_debug.png"))
        except Exception:
            pass
        raise RuntimeError(f"Failed to scrape BPS {label} {year}: {exc}") from exc


def build_annual_dataset(
    years: list[int],
    *,
    output_base: str | Path,
    raw_dir: str | Path,
    project_root: str | Path,
    headless: bool = True,
    timeout: int = 60,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    from .bps_direct import build_annual_dataset_direct

    # Prefer the official public HTML table payload. It avoids the tokenized
    # BPS WebAPI and does not require Chrome; the legacy Selenium code below is
    # retained for older page deployments.
    return build_annual_dataset_direct(
        years,
        output_base=output_base,
        raw_dir=raw_dir,
        save_csv=save_csv,
        save_parquet=save_parquet,
        timeout=timeout,
    )

    raw_root = Path(raw_dir)
    raw_root.mkdir(parents=True, exist_ok=True)
    debug_dir = raw_root / "debug"
    production_parts: list[pd.DataFrame] = []
    area_parts: list[pd.DataFrame] = []
    driver = create_driver(headless=headless, project_root=project_root)
    try:
        for year in sorted(set(years)):
            production_raw, production_url = scrape_rendered_table(
                driver, base_url=PRODUCTION_URL, year=year,
                expected_terms=["bawang merah", "cabai rawit", "cabai keriting"],
                timeout=timeout, debug_dir=debug_dir, label="production",
            )
            production_raw.to_csv(raw_root / f"production_{year}_rendered.csv", index=False)
            production_parts.append(normalize_one_table(production_raw, year, "production", production_url))

            area_raw, area_url = scrape_rendered_table(
                driver, base_url=HARVESTED_AREA_URL, year=year,
                expected_terms=["bawang merah", "cabai rawit", "cabai keriting"],
                timeout=timeout, debug_dir=debug_dir, label="harvested_area",
            )
            area_raw.to_csv(raw_root / f"harvested_area_{year}_rendered.csv", index=False)
            area_parts.append(normalize_one_table(area_raw, year, "harvested_area", area_url))
    finally:
        driver.quit()

    production = pd.concat(production_parts, ignore_index=True)
    area = pd.concat(area_parts, ignore_index=True)
    keys = ["year", "province_code", "province_name", "commodity_code", "commodity_name"]
    result = production.merge(
        area[keys + ["harvested_area_ha", "source_column", "source_url", "extracted_at_utc"]],
        on=keys,
        how="outer",
        suffixes=("_production", "_area"),
    )
    result["productivity_kg_per_ha"] = result["production_kg"] / result["harvested_area_ha"].replace(0, pd.NA)
    result["quality_flag"] = "ok"
    result.loc[result["province_code"].isna(), "quality_flag"] = "unmapped_province"
    result.loc[result["production_kg"].isna(), "quality_flag"] = "missing_production"
    result.loc[result["harvested_area_ha"].isna(), "quality_flag"] = "missing_harvested_area"
    result = result.sort_values(["year", "province_code", "commodity_code"], na_position="last").reset_index(drop=True)
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return result, outputs
