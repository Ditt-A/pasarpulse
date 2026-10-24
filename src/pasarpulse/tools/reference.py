"""Download and validate BIG province polygons for PasarPulse-MM.

The BIG province layer may return multiple polygon fragments for one province,
rows with missing ``kdpbps``, and simplified rings that are not topologically
valid. This module:

1. resolves province codes from ``kdpbps`` or province-name aliases;
2. ignores non-province rows;
3. repairs every geometry with Shapely;
4. dissolves fragments into one Polygon/MultiPolygon per province; and
5. validates the official 38-province schema before writing GeoJSON.

The output is suitable for analytical aggregation and pipeline smoke tests. It
is not intended to replace authoritative legal-boundary products.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from urllib3.util.retry import Retry

BIG_LAYER_URL = (
    "https://geoservices.big.go.id/rbi/rest/services/"
    "BATASWILAYAH/BATAS_WILAYAH/MapServer/12/query"
)

# Canonical BPS province codes for Indonesia's 38 provinces.
PROVINCE_CODE_TO_NAME: dict[str, str] = {
    "11": "Aceh",
    "12": "Sumatera Utara",
    "13": "Sumatera Barat",
    "14": "Riau",
    "15": "Jambi",
    "16": "Sumatera Selatan",
    "17": "Bengkulu",
    "18": "Lampung",
    "19": "Kepulauan Bangka Belitung",
    "21": "Kepulauan Riau",
    "31": "DKI Jakarta",
    "32": "Jawa Barat",
    "33": "Jawa Tengah",
    "34": "DI Yogyakarta",
    "35": "Jawa Timur",
    "36": "Banten",
    "51": "Bali",
    "52": "Nusa Tenggara Barat",
    "53": "Nusa Tenggara Timur",
    "61": "Kalimantan Barat",
    "62": "Kalimantan Tengah",
    "63": "Kalimantan Selatan",
    "64": "Kalimantan Timur",
    "65": "Kalimantan Utara",
    "71": "Sulawesi Utara",
    "72": "Sulawesi Tengah",
    "73": "Sulawesi Selatan",
    "74": "Sulawesi Tenggara",
    "75": "Gorontalo",
    "76": "Sulawesi Barat",
    "81": "Maluku",
    "82": "Maluku Utara",
    "91": "Papua Barat",
    "92": "Papua Barat Daya",
    "94": "Papua",
    "95": "Papua Selatan",
    "96": "Papua Tengah",
    "97": "Papua Pegunungan",
}
OFFICIAL_PROVINCE_CODES = frozenset(PROVINCE_CODE_TO_NAME)


def _normalise_name(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper()
    text = re.sub(r"\b(PROVINSI|PROPINSI)\b", " ", text)
    text = re.sub(r"\bDAERAH KHUSUS IBUKOTA\b", "DKI", text)
    text = re.sub(r"\bDAERAH ISTIMEWA\b", "DI", text)
    text = re.sub(r"\bKEP\.?(?=\s|$)", "KEPULAUAN", text)
    text = re.sub(r"\bNUSA TENGGARA BARAT\b", "NTB", text)
    text = re.sub(r"\bNUSA TENGGARA TIMUR\b", "NTT", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


_NAME_ALIASES: dict[str, str] = {
    _normalise_name(name): code for code, name in PROVINCE_CODE_TO_NAME.items()
}
_NAME_ALIASES.update(
    {
        "NANGGROE ACEH DARUSSALAM": "11",
        "SUMUT": "12",
        "SUMBAR": "13",
        "SUMSEL": "16",
        "KEPULAUAN BANGKA BELITUNG": "19",
        "BANGKA BELITUNG": "19",
        "KEPULAUAN RIAU": "21",
        "KEPRI": "21",
        "DKI JAKARTA": "31",
        "JAKARTA": "31",
        "DI YOGYAKARTA": "34",
        "DAERAH ISTIMEWA YOGYAKARTA": "34",
        "YOGYAKARTA": "34",
        "NTB": "52",
        "NTT": "53",
        "KALBAR": "61",
        "KALTENG": "62",
        "KALSEL": "63",
        "KALTIM": "64",
        "KALTARA": "65",
        "SULUT": "71",
        "SULTENG": "72",
        "SULSEL": "73",
        "SULTRA": "74",
        "SULBAR": "76",
        "PAPUA BARATDAYA": "92",
    }
)


def _http_session(*, retries: int = 5, backoff_factor: float = 1.5) -> requests.Session:
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
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "PasarPulse-MM/1.0 academic data pipeline",
            "Accept": "application/geo+json, application/json, */*",
        }
    )
    return session


def _extract_raw_name(properties: dict[str, Any]) -> str:
    return str(
        properties.get("wadmpr")
        or properties.get("WADMPR")
        or properties.get("namobj")
        or properties.get("NAMOBJ")
        or ""
    ).strip()


def _resolve_province_code(properties: dict[str, Any], raw_name: str) -> str | None:
    raw_code = properties.get("kdpbps")
    if raw_code in (None, ""):
        raw_code = properties.get("KDPBPS")

    code = str(raw_code or "").strip()
    if code.endswith(".0"):
        code = code[:-2]
    code = code.zfill(2) if code else ""

    if code in OFFICIAL_PROVINCE_CODES:
        return code
    return _NAME_ALIASES.get(_normalise_name(raw_name))


def _polygonal_parts(geometry: BaseGeometry) -> list[Polygon]:
    """Return only Polygon members from any repaired geometry."""
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for member in geometry.geoms:
            parts.extend(_polygonal_parts(member))
        return parts
    return []


def _repair_shapely_geometry(geometry: BaseGeometry) -> Polygon | MultiPolygon:
    """Repair topology and retain polygonal components only."""
    if geometry.is_empty:
        raise ValueError("Geometry is empty before repair.")

    repaired = geometry if geometry.is_valid else make_valid(geometry)
    parts = _polygonal_parts(repaired)

    # ``make_valid`` can produce a GeometryCollection. Unioning only polygonal
    # members removes collapsed lines/points while preserving usable area.
    if not parts:
        fallback = geometry.buffer(0)
        parts = _polygonal_parts(fallback)
    if not parts:
        raise ValueError("Geometry repair produced no polygonal area.")

    merged = unary_union(parts)
    if not merged.is_valid:
        merged = make_valid(merged)
        merged_parts = _polygonal_parts(merged)
        if not merged_parts:
            merged_parts = _polygonal_parts(merged.buffer(0))
        if not merged_parts:
            raise ValueError("Geometry remains non-polygonal after repair.")
        merged = unary_union(merged_parts)

    if not merged.is_valid:
        merged = merged.buffer(0)
    if merged.is_empty or not merged.is_valid:
        raise ValueError("Geometry could not be repaired into a valid polygon.")

    polygon_parts = _polygonal_parts(merged)
    if not polygon_parts:
        raise ValueError("Repaired geometry contains no polygonal component.")
    if len(polygon_parts) == 1:
        return polygon_parts[0]
    return MultiPolygon(polygon_parts)


def _repair_geometry_dict(geometry: dict[str, Any]) -> dict[str, Any]:
    try:
        repaired = _repair_shapely_geometry(shape(geometry))
    except Exception as exc:
        raise ValueError(f"Invalid province geometry: {exc}") from exc
    return mapping(repaired)


def _canonical_feature(
    feature: dict[str, Any],
    endpoint: str,
) -> dict[str, Any] | None:
    properties = feature.get("properties") or feature.get("attributes") or {}
    raw_name = _extract_raw_name(properties)
    code = _resolve_province_code(properties, raw_name)
    geometry = feature.get("geometry")

    # BIG can return auxiliary rows without a usable province identifier.
    if code is None or not geometry:
        return None

    return {
        "type": "Feature",
        "properties": {
            "province_code": code,
            "province_name": PROVINCE_CODE_TO_NAME[code],
            "source": "BIG",
            "source_layer": endpoint.rsplit("/query", 1)[0],
            "geometry_usage": "simplified_repaired_for_analysis",
            "big_raw_name": raw_name,
        },
        "geometry": _repair_geometry_dict(geometry),
    }


def _dissolve_by_province(features: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_geometries: dict[str, list[BaseGeometry]] = {}
    grouped_properties: dict[str, dict[str, Any]] = {}

    for feature in features:
        properties = feature.get("properties") or {}
        code = str(properties.get("province_code", "")).strip()
        geometry = feature.get("geometry")
        if code not in OFFICIAL_PROVINCE_CODES or not geometry:
            continue
        grouped_geometries.setdefault(code, []).append(shape(geometry))
        grouped_properties.setdefault(code, deepcopy(properties))

    dissolved: list[dict[str, Any]] = []
    for code in sorted(grouped_geometries):
        merged = unary_union(grouped_geometries[code])
        repaired = _repair_shapely_geometry(merged)
        properties = grouped_properties[code]
        properties["province_code"] = code
        properties["province_name"] = PROVINCE_CODE_TO_NAME[code]
        properties["geometry_repaired"] = True
        dissolved.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(repaired),
            }
        )
    return dissolved


def _repair_feature_collection(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Repair an existing FeatureCollection and dissolve duplicate provinces."""
    if payload.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON is not a FeatureCollection.")

    changed = False
    canonical: list[dict[str, Any]] = []
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        code = str(properties.get("province_code", "")).strip()
        raw_name = str(properties.get("province_name") or "").strip()

        if code not in OFFICIAL_PROVINCE_CODES:
            code = _NAME_ALIASES.get(_normalise_name(raw_name), "")
        if code not in OFFICIAL_PROVINCE_CODES or not feature.get("geometry"):
            changed = True
            continue

        original_geometry = shape(feature["geometry"])
        repaired_geometry = _repair_shapely_geometry(original_geometry)
        if not original_geometry.is_valid or not original_geometry.equals(repaired_geometry):
            changed = True

        new_feature = deepcopy(feature)
        new_feature["properties"]["province_code"] = code
        new_feature["properties"]["province_name"] = PROVINCE_CODE_TO_NAME[code]
        new_feature["properties"]["geometry_repaired"] = True
        new_feature["geometry"] = mapping(repaired_geometry)
        canonical.append(new_feature)

    dissolved = _dissolve_by_province(canonical)
    if len(dissolved) != len(canonical):
        changed = True

    repaired_payload = deepcopy(payload)
    repaired_payload["features"] = dissolved
    repaired_payload.setdefault("metadata", {})["geometry_repair"] = (
        "shapely_make_valid_polygonal_union"
    )
    return repaired_payload, changed


def _validate_feature_collection(payload: dict[str, Any], *, expected_count: int = 38) -> None:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("BIG response is not a GeoJSON FeatureCollection.")

    features = payload.get("features") or []
    if not features:
        raise ValueError("BIG response contains no province features.")

    codes = [
        str((feature.get("properties") or {}).get("province_code", "")).strip()
        for feature in features
    ]
    if any(not code for code in codes):
        raise ValueError("One or more province features have an empty province_code.")
    if len(set(codes)) != len(codes):
        raise ValueError("Duplicate province_code values remain after dissolve.")

    if expected_count and len(features) != expected_count:
        missing = sorted(OFFICIAL_PROVINCE_CODES.difference(codes))
        extra = sorted(set(codes).difference(OFFICIAL_PROVINCE_CODES))
        raise ValueError(
            f"Expected {expected_count} provinces, received {len(features)}. "
            f"Missing={missing}; extra={extra}."
        )

    if expected_count == 38 and set(codes) != OFFICIAL_PROVINCE_CODES:
        missing = sorted(OFFICIAL_PROVINCE_CODES.difference(codes))
        extra = sorted(set(codes).difference(OFFICIAL_PROVINCE_CODES))
        raise ValueError(f"Province-code mismatch. Missing={missing}; extra={extra}.")

    for feature in features:
        code = str((feature.get("properties") or {}).get("province_code", ""))
        geometry_dict = feature.get("geometry")
        if not geometry_dict:
            raise ValueError(f"Province {code} has empty geometry.")
        geometry = shape(geometry_dict)
        if geometry.is_empty:
            raise ValueError(f"Province {code} has an empty Shapely geometry.")
        if not geometry.is_valid:
            raise ValueError(f"Province {code} still has invalid geometry.")
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Province {code} has unsupported geometry type {geometry.geom_type}."
            )
        min_x, min_y, max_x, max_y = geometry.bounds
        if not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y)):
            raise ValueError(f"Province {code} has non-finite coordinates.")
        if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
            raise ValueError(f"Province {code} has coordinates outside EPSG:4326 bounds.")


def _request_geojson(
    session: requests.Session,
    endpoint: str,
    *,
    timeout: int,
    geometry_precision: int,
    max_allowable_offset: float,
    result_offset: int | None = None,
    result_record_count: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "returnZ": "false",
        "returnM": "false",
        "outSR": "4326",
        "geometryPrecision": str(geometry_precision),
        "f": "geojson",
    }
    if max_allowable_offset > 0:
        params["maxAllowableOffset"] = str(max_allowable_offset)
    if result_offset is not None:
        params["resultOffset"] = str(result_offset)
    if result_record_count is not None:
        params["resultRecordCount"] = str(result_record_count)

    response = session.get(endpoint, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"BIG ArcGIS error: {payload['error']}")
    if payload.get("type") != "FeatureCollection":
        raise RuntimeError("BIG did not return a GeoJSON FeatureCollection.")
    return payload


def _canonicalise_payload(payload: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        row = _canonical_feature(feature, endpoint)
        if row is not None:
            canonical.append(row)
    return canonical


def _download_all_at_once(
    session: requests.Session,
    endpoint: str,
    *,
    timeout: int,
    geometry_precision: int,
    max_allowable_offset: float,
) -> list[dict[str, Any]]:
    payload = _request_geojson(
        session,
        endpoint,
        timeout=timeout,
        geometry_precision=geometry_precision,
        max_allowable_offset=max_allowable_offset,
    )
    return _dissolve_by_province(_canonicalise_payload(payload, endpoint))


def _download_by_pagination(
    session: requests.Session,
    endpoint: str,
    *,
    timeout: int,
    geometry_precision: int,
    max_allowable_offset: float,
    page_size: int = 25,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """Fallback that avoids BIG's unreliable object-ID query path."""
    canonical: list[dict[str, Any]] = []
    seen_page_fingerprints: set[tuple[str, ...]] = set()

    for page in range(max_pages):
        offset = page * page_size
        payload = _request_geojson(
            session,
            endpoint,
            timeout=timeout,
            geometry_precision=geometry_precision,
            max_allowable_offset=max_allowable_offset,
            result_offset=offset,
            result_record_count=page_size,
        )
        rows = payload.get("features") or []
        if not rows:
            break

        fingerprint = tuple(
            sorted(
                f"{_extract_raw_name(row.get('properties') or {})}|"
                f"{(row.get('properties') or {}).get('kdpbps', '')}|"
                f"{(row.get('properties') or {}).get('objectid', '')}"
                for row in rows
            )
        )
        if fingerprint in seen_page_fingerprints:
            break
        seen_page_fingerprints.add(fingerprint)

        canonical.extend(_canonicalise_payload(payload, endpoint))
        dissolved = _dissolve_by_province(canonical)
        if len(dissolved) >= 38:
            return dissolved
        if len(rows) < page_size:
            break

    return _dissolve_by_province(canonical)


def download_province_boundaries(
    output_path: str | Path,
    *,
    endpoint: str = BIG_LAYER_URL,
    expected_count: int = 38,
    overwrite: bool = False,
    timeout: int = 180,
    geometry_precision: int = 4,
    max_allowable_offset: float = 0.005,
    chunk_by_province: bool = True,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Existing files are repaired in place. This avoids an unnecessary network
    # call when the 38 provinces have already been downloaded successfully.
    if output.exists() and output.stat().st_size > 0 and not overwrite:
        payload = json.loads(output.read_text(encoding="utf-8"))
        payload, changed = _repair_feature_collection(payload)
        _validate_feature_collection(payload, expected_count=expected_count)
        if changed:
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return output

    session = _http_session()
    warnings: list[str] = []

    try:
        features = _download_all_at_once(
            session,
            endpoint,
            timeout=timeout,
            geometry_precision=geometry_precision,
            max_allowable_offset=max_allowable_offset,
        )
        probe = {"type": "FeatureCollection", "features": features}
        _validate_feature_collection(probe, expected_count=expected_count)
        strategy = "national_query_repair_then_dissolve"
    except Exception as exc:
        warnings.append(f"national query: {type(exc).__name__}: {exc}")
        if not chunk_by_province:
            raise
        try:
            features = _download_by_pagination(
                session,
                endpoint,
                timeout=min(max(timeout // 2, 45), 120),
                geometry_precision=geometry_precision,
                max_allowable_offset=max_allowable_offset,
            )
            probe = {"type": "FeatureCollection", "features": features}
            _validate_feature_collection(probe, expected_count=expected_count)
            strategy = "pagination_repair_then_dissolve"
        except Exception as page_exc:
            warnings.append(f"pagination: {type(page_exc).__name__}: {page_exc}")
            raise RuntimeError(
                "Unable to download BIG province boundaries. " + " || ".join(warnings)
            ) from page_exc

    result = {
        "type": "FeatureCollection",
        "name": "indonesia_provinces",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "metadata": {
            "source": "Badan Informasi Geospasial",
            "source_endpoint": endpoint,
            "geometry_precision": geometry_precision,
            "max_allowable_offset_degrees": max_allowable_offset,
            "download_strategy": strategy,
            "geometry_repair": "shapely_make_valid_polygonal_union",
            "geometry_usage": "analysis_not_legal_boundary",
            "warnings": warnings,
        },
        "features": features,
    }
    result, _ = _repair_feature_collection(result)
    _validate_feature_collection(result, expected_count=expected_count)
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return output


def build_satellite_zones(
    province_path: str | Path,
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    source = Path(province_path)
    output = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"Province GeoJSON not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    province_payload = json.loads(source.read_text(encoding="utf-8"))
    province_payload, province_changed = _repair_feature_collection(province_payload)
    _validate_feature_collection(province_payload, expected_count=38)
    if province_changed:
        source.write_text(
            json.dumps(province_payload, ensure_ascii=False), encoding="utf-8"
        )

    if output.exists() and output.stat().st_size > 0 and not overwrite:
        existing = json.loads(output.read_text(encoding="utf-8"))
        existing, changed = _repair_feature_collection(existing)
        _validate_feature_collection(existing, expected_count=38)
        if changed:
            output.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        return output

    result = deepcopy(province_payload)
    result["name"] = "satellite_zones_province_fallback"
    result.setdefault("metadata", {})["zone_warning"] = (
        "Province polygons are a fallback zone, not commodity-specific cropland."
    )
    for feature in result.get("features", []):
        props = feature.setdefault("properties", {})
        props["zone_method"] = "province_fallback"
        props["zone_source"] = "BIG simplified and Shapely-repaired province polygon"
        props["zone_version"] = "smoke_test_v5"

    _validate_feature_collection(result, expected_count=38)
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return output


def prepare_reference_files(
    province_path: str | Path,
    satellite_zone_path: str | Path,
    *,
    endpoint: str = BIG_LAYER_URL,
    expected_count: int = 38,
    overwrite: bool = False,
    timeout: int = 180,
    geometry_precision: int = 4,
    max_allowable_offset: float = 0.005,
    chunk_by_province: bool = True,
) -> dict[str, Path]:
    province = download_province_boundaries(
        province_path,
        endpoint=endpoint,
        expected_count=expected_count,
        overwrite=overwrite,
        timeout=timeout,
        geometry_precision=geometry_precision,
        max_allowable_offset=max_allowable_offset,
        chunk_by_province=chunk_by_province,
    )
    zones = build_satellite_zones(province, satellite_zone_path, overwrite=overwrite)
    return {"province_boundaries": province, "satellite_zones": zones}