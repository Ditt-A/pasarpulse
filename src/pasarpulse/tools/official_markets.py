"""Acquire BIG/Kemendag official market-location and operating-frequency context."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from ..utils import save_frame, save_json


DEFAULT_LAYER_URL = (
    "https://kspservices.big.go.id/satupeta/rest/services/PUBLIK/"
    "SARANA_PRASARANA/MapServer/28"
)
SOURCE_EFFECTIVE_DATE = "2024-07-04"


def parse_operating_days_per_week(value: object) -> float:
    """Parse only frequencies explicitly supported by the source string."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if text == "setiap hari":
        return 7.0
    match = re.fullmatch(r"([1-7])\s*hari\s*seminggu", text)
    return float(match.group(1)) if match else np.nan


def _request_json(url: str, *, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"BIG market service error: {payload['error']}")
    return payload


def acquire_official_markets(
    *,
    provinces_path: str | Path,
    output_dir: str | Path,
    layer_url: str = DEFAULT_LAYER_URL,
    province_code_col: str = "province_code",
    province_name_col: str = "province_name",
    minimum_expected_features: int = 600,
    nearest_join_max_km: float = 30.0,
    timeout: int = 120,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path]]:
    """Download, province-normalize, and summarize the official market layer."""
    output_root = Path(output_dir)
    raw_root = output_root.parent / "raw" / "big_markets"
    raw_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    metadata = _request_json(layer_url, params={"f": "pjson"}, timeout=timeout)
    iteminfo_url = layer_url.rsplit("/", 1)[0] + "/info/iteminfo"
    iteminfo = _request_json(iteminfo_url, params={"f": "json"}, timeout=timeout)
    count_payload = _request_json(
        layer_url + "/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        timeout=timeout,
    )
    payload = _request_json(
        layer_url + "/query",
        params={
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=timeout,
    )
    features = payload.get("features") or []
    reported_count = int(count_payload.get("count", -1))
    if len(features) != reported_count:
        raise RuntimeError(
            f"BIG market feature count mismatch: query={len(features)} count={reported_count}"
        )
    if len(features) < int(minimum_expected_features):
        raise RuntimeError(
            f"BIG market layer returned only {len(features)} features; expected at least "
            f"{minimum_expected_features}."
        )

    raw_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    raw_path = raw_root / "big_official_markets.geojson"
    raw_path.write_bytes(raw_bytes)

    markets = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    provinces = gpd.read_file(provinces_path).to_crs(4326)
    required = {province_code_col, province_name_col}
    missing = required.difference(provinces.columns)
    if missing:
        raise ValueError(f"Province boundary file misses columns: {sorted(missing)}")
    provinces[province_code_col] = (
        provinces[province_code_col]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(2)
    )
    province_columns = [province_code_col, province_name_col, "geometry"]
    joined = gpd.sjoin(
        markets,
        provinces[province_columns],
        how="left",
        predicate="intersects",
    ).drop(columns=["index_right"], errors="ignore").reset_index(drop=True)
    joined["province_join_method"] = np.where(
        joined[province_code_col].notna(), "point_in_polygon", "unmapped"
    )
    joined["province_join_distance_km"] = np.where(
        joined[province_code_col].notna(), 0.0, np.nan
    )
    missing_rows = joined[province_code_col].isna()
    if missing_rows.any():
        nearest_left = joined.loc[missing_rows].drop(
            columns=[province_code_col, province_name_col], errors="ignore"
        )
        nearest = gpd.sjoin_nearest(
            nearest_left.to_crs(6933),
            provinces[province_columns].to_crs(6933),
            how="left",
            max_distance=float(nearest_join_max_km) * 1000.0,
            distance_col="province_join_distance_m",
        )
        nearest = nearest.sort_values("province_join_distance_m").loc[
            lambda value: ~value.index.duplicated(keep="first")
        ]
        joined.loc[nearest.index, province_code_col] = nearest[province_code_col]
        joined.loc[nearest.index, province_name_col] = nearest[province_name_col]
        joined.loc[nearest.index, "province_join_method"] = "nearest_boundary_fallback"
        joined.loc[nearest.index, "province_join_distance_km"] = (
            nearest["province_join_distance_m"] / 1000.0
        )
    joined = joined.rename(
        columns={
            province_code_col: "province_code",
            province_name_col: "province_name",
            "objectid": "source_object_id",
            "namobj": "market_name",
            "harops": "operating_schedule_raw",
            "alamat": "address",
        }
    )
    joined["province_code"] = joined["province_code"].astype("string").str.zfill(2)
    joined["market_id"] = joined["source_object_id"].map(
        lambda value: f"BIG-MARKET-{int(value):05d}"
    )
    joined["operating_days_per_week"] = joined["operating_schedule_raw"].map(
        parse_operating_days_per_week
    )
    joined["longitude"] = joined.geometry.x
    joined["latitude"] = joined.geometry.y
    joined["source"] = "BIG/Kemendag Peta Sebaran Pasar Rakyat dan Pasar Desa"
    joined["source_vintage"] = "2020-2021 acquisition"
    joined["market_context_effective_date"] = pd.Timestamp(SOURCE_EFFECTIVE_DATE)
    joined["acquired_at_utc"] = datetime.now(timezone.utc).isoformat()
    joined["province_mapping_status"] = np.where(
        joined["province_code"].notna(), "mapped", "unmapped"
    )

    unmapped = int(joined["province_code"].isna().sum())
    if unmapped:
        raise RuntimeError(f"{unmapped} official market points did not join to a province.")
    if joined["market_id"].duplicated().any():
        raise RuntimeError("Official market IDs are not unique after province join.")

    table_columns = [
        "market_id",
        "source_object_id",
        "market_name",
        "province_code",
        "province_name",
        "operating_schedule_raw",
        "operating_days_per_week",
        "tippsr",
        "kpmlkn",
        "luaslh",
        "luasbg",
        "address",
        "remark",
        "metadata",
        "longitude",
        "latitude",
        "source",
        "source_vintage",
        "market_context_effective_date",
        "acquired_at_utc",
        "province_mapping_status",
        "province_join_method",
        "province_join_distance_km",
    ]
    table = pd.DataFrame(joined[[column for column in table_columns if column in joined]])
    summary_with_points = (
        table.groupby(["province_code", "province_name"], as_index=False)
        .agg(
            official_market_count=("market_id", "nunique"),
            official_market_schedule_count=("operating_days_per_week", "count"),
            official_market_every_day_count=(
                "operating_days_per_week",
                lambda values: int(pd.Series(values).eq(7).sum()),
            ),
            official_market_days_per_week_mean=("operating_days_per_week", "mean"),
            official_market_days_per_week_median=("operating_days_per_week", "median"),
            market_context_effective_date=("market_context_effective_date", "max"),
        )
    )
    summary_with_points["official_market_schedule_coverage"] = (
        summary_with_points["official_market_schedule_count"]
        / summary_with_points["official_market_count"]
    )
    summary_with_points["official_market_daily_equivalent"] = (
        summary_with_points["official_market_count"]
        * summary_with_points["official_market_days_per_week_mean"]
        / 7.0
    )
    province_reference = pd.DataFrame(
        provinces[[province_code_col, province_name_col]].drop_duplicates()
    ).rename(
        columns={
            province_code_col: "province_code",
            province_name_col: "province_name",
        }
    )
    summary = province_reference.merge(
        summary_with_points,
        on=["province_code", "province_name"],
        how="left",
        validate="one_to_one",
    )
    summary["official_market_province_coverage_status"] = np.where(
        summary["official_market_count"].notna(),
        "available",
        "no_points_in_source",
    )
    summary["market_context_effective_date"] = pd.Timestamp(SOURCE_EFFECTIVE_DATE)
    summary["official_market_context_source"] = table["source"].iloc[0]
    summary["official_market_source_vintage"] = table["source_vintage"].iloc[0]

    table_outputs = save_frame(
        table,
        output_root / "official_markets",
        save_csv=save_csv,
        save_parquet=save_parquet,
    )
    summary_outputs = save_frame(
        summary,
        output_root / "official_market_province_summary",
        save_csv=save_csv,
        save_parquet=save_parquet,
    )
    normalized_geojson_path = output_root / "official_markets.geojson"
    joined.to_file(normalized_geojson_path, driver="GeoJSON")
    manifest_path = output_root / "official_market_manifest.json"
    save_json(
        {
            "source_layer_url": layer_url,
            "source_name": metadata.get("name"),
            "source_description": metadata.get("description"),
            "source_copyright": metadata.get("copyrightText"),
            "source_service_item_id": metadata.get("serviceItemId"),
            "service_iteminfo": {
                "title": iteminfo.get("title"),
                "description": iteminfo.get("description"),
                "snippet": iteminfo.get("snippet"),
            },
            "source_effective_date": SOURCE_EFFECTIVE_DATE,
            "feature_count": len(table),
            "province_reference_count": int(summary["province_code"].nunique()),
            "provinces_with_points": int(
                summary["official_market_count"].notna().sum()
            ),
            "provinces_without_points": summary.loc[
                summary["official_market_count"].isna(), "province_code"
            ].astype(str).tolist(),
            "point_in_polygon_count": int(
                table["province_join_method"].eq("point_in_polygon").sum()
            ),
            "nearest_boundary_fallback_count": int(
                table["province_join_method"].eq("nearest_boundary_fallback").sum()
            ),
            "maximum_nearest_join_distance_km": float(
                pd.to_numeric(table["province_join_distance_km"], errors="coerce").max()
            ),
            "operating_schedule_parsed_count": int(
                table["operating_days_per_week"].notna().sum()
            ),
            "raw_geojson": (
                str(raw_path.resolve().relative_to(Path(output_dir).resolve().parents[1]))
                if raw_path.resolve().is_relative_to(Path(output_dir).resolve().parents[1])
                else str(raw_path.resolve())
            ),
            "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        manifest_path,
    )
    outputs = {
        "raw_geojson": raw_path,
        "normalized_geojson": normalized_geojson_path,
        "manifest": manifest_path,
        **{f"table_{key}": value for key, value in table_outputs.items()},
        **{f"summary_{key}": value for key, value in summary_outputs.items()},
    }
    return table, summary, outputs
