#!/usr/bin/env python3
"""Validate PasarPulse multimodal artifacts and their replay-time availability."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


CANONICAL_PROVINCE_CODES = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
    "31", "32", "33", "34", "35", "36", "51", "52", "53", "61",
    "62", "63", "64", "65", "71", "72", "73", "74", "75", "76",
    "81", "82", "91", "92", "94", "95", "96", "97",
}
EXPECTED_COMMODITIES = {"BM", "CMK", "CRM"}
EXPECTED_MARKETS = {"producer", "retail", "wholesale"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_codes(values: pd.Series) -> set[str]:
    return set(
        values.dropna()
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(2)
    )


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(
        self,
        name: str,
        condition: bool,
        *,
        observed: Any = None,
        expected: Any = None,
        warning: bool = False,
    ) -> None:
        status = "passed" if condition else ("warning" if warning else "failed")
        self.checks.append(
            {
                "name": name,
                "status": status,
                "observed": observed,
                "expected": expected,
            }
        )
        if not condition:
            message = f"{name}: observed={observed!r}, expected={expected!r}"
            (self.warnings if warning else self.errors).append(message)


def read_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def validate(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve()
    data = root / "data"
    audit = Audit()
    start = pd.Timestamp(args.start_date).normalize()
    end = pd.Timestamp(args.end_date).normalize()
    expected_dates = len(pd.date_range(start, end, freq="D"))

    required = {
        "provinces": data / "reference/indonesia_provinces.geojson",
        "satellite_zones": data / "reference/satellite_zones.geojson",
        "price": data / "processed/price_daily.parquet",
        "production": data / "processed/production_annual.parquet",
        "calendar": data / "processed/calendar_features.parquet",
        "weather": data / "processed/weather_daily.parquet",
        "weather_metadata": data / "processed/weather_metadata.json",
        "sentinel_manifest": data / "raw/sentinel2_asset_manifest.parquet",
        "satellite": data / "processed/satellite_features.parquet",
        "osm_summary": data / "processed/osm_province_transport_summary.parquet",
        "osm_edges": data / "processed/osm_transport_edges.parquet",
        "osm_manifest": data / "processed/osm_download_manifest.json",
        "official_markets": data / "processed/official_markets.parquet",
        "official_market_summary": data / "processed/official_market_province_summary.parquet",
        "official_market_manifest": data / "processed/official_market_manifest.json",
        "static_graph": data / "processed/province_graph_static.parquet",
        "dynamic_graph": data / "processed/province_graph_dynamic.parquet",
        "ready_all": data / "ready/model_dataset_all.parquet",
        "ready_eligible": data / "ready/model_dataset_eligible.parquet",
        "ready_metadata": data / "ready/model_dataset_metadata.json",
    }
    for name, path in required.items():
        audit.check(f"required_file.{name}", path.exists(), observed=str(path))
    if audit.errors:
        return finish_payload(audit, root, required, {})

    provinces = gpd.read_file(required["provinces"]).to_crs(4326)
    province_codes = normalize_codes(provinces["province_code"])
    audit.check("geography.province_count", len(provinces) == 38, observed=len(provinces), expected=38)
    audit.check(
        "geography.canonical_codes",
        province_codes == CANONICAL_PROVINCE_CODES,
        observed=sorted(province_codes),
        expected=sorted(CANONICAL_PROVINCE_CODES),
    )
    audit.check(
        "geography.valid_geometry",
        bool(provinces.geometry.notna().all() and provinces.geometry.is_valid.all()),
    )
    zones = gpd.read_file(required["satellite_zones"])
    audit.check("satellite_zones.count", len(zones) == 38, observed=len(zones), expected=38)
    audit.check(
        "satellite_zones.codes",
        normalize_codes(zones["province_code"]) == CANONICAL_PROVINCE_CODES,
    )
    zone_methods = set(zones.get("zone_method", pd.Series(dtype=str)).dropna().astype(str))
    audit.check(
        "satellite_zones.method_documented",
        bool(zone_methods),
        observed=sorted(zone_methods),
    )
    if any("fallback" in value for value in zone_methods):
        audit.warnings.append(
            "Satellite zones use a documented province fallback and are regional vegetation proxies, not crop parcels."
        )

    price = read_frame(required["price"])
    price["date"] = pd.to_datetime(price["date"])
    price_province_codes = normalize_codes(price["province_code"])
    audit.check("price.province_codes", price_province_codes.issubset(CANONICAL_PROVINCE_CODES))
    audit.check("price.commodities", set(price["commodity_code"].dropna()) == EXPECTED_COMMODITIES, observed=sorted(price["commodity_code"].dropna().unique()))
    audit.check("price.market_levels", set(price["market_level"].dropna()) == EXPECTED_MARKETS, observed=sorted(price["market_level"].dropna().unique()))
    audit.check("price.positive_values", bool(pd.to_numeric(price["price_idr_per_kg"], errors="coerce").gt(0).all()))
    audit.check(
        "price.unique_keys",
        not price.duplicated(["date", "province_code", "commodity_code", "market_level"]).any(),
    )
    audit.check("price.end_coverage", price["date"].max() >= end, observed=str(price["date"].max()), expected=str(end))

    production = read_frame(required["production"])
    effective = pd.to_datetime(production["production_effective_date"], errors="coerce")
    expected_releases = {
        2023: pd.Timestamp("2024-06-10"),
        2024: pd.Timestamp("2025-06-10"),
        2025: pd.Timestamp("2026-06-12"),
    }
    release_ok = all(
        set(effective[pd.to_numeric(production["year"]).eq(year)].dropna()) == {date}
        for year, date in expected_releases.items()
    )
    audit.check("production.rows", len(production) == 342, observed=len(production), expected=342)
    audit.check("production.provinces", normalize_codes(production["province_code"]) == CANONICAL_PROVINCE_CODES)
    audit.check("production.release_dates", release_ok)
    audit.check(
        "production.unique_keys",
        not production.duplicated(["year", "province_code", "commodity_code"]).any(),
    )

    calendar = read_frame(required["calendar"])
    calendar["date"] = pd.to_datetime(calendar["date"])
    audit.check("calendar.unique_dates", not calendar["date"].duplicated().any())
    audit.check("calendar.start", calendar["date"].min() <= start, observed=str(calendar["date"].min()), expected=str(start))
    audit.check("calendar.end", calendar["date"].max() >= end, observed=str(calendar["date"].max()), expected=str(end))

    weather = read_frame(required["weather"])
    weather["date"] = pd.to_datetime(weather["date"])
    audit.check("weather.rows", len(weather) == 38 * expected_dates, observed=len(weather), expected=38 * expected_dates)
    audit.check("weather.provinces", normalize_codes(weather["province_code"]) == CANONICAL_PROVINCE_CODES)
    audit.check("weather.unique_keys", not weather.duplicated(["province_code", "date"]).any())
    audit.check("weather.date_min", weather["date"].min() == start, observed=str(weather["date"].min()), expected=str(start))
    audit.check("weather.date_max", weather["date"].max() == end, observed=str(weather["date"].max()), expected=str(end))
    range_checks = {
        "temperature_c_mean": (-10.0, 50.0),
        "rainfall_mm_sum": (0.0, 1000.0),
        "soil_moisture_layer1_mean": (0.0, 1.0),
        "solar_radiation_mj_m2_sum": (0.0, 60.0),
    }
    for column, (lower, upper) in range_checks.items():
        values = pd.to_numeric(weather[column], errors="coerce").dropna()
        audit.check(
            f"weather.range.{column}",
            bool(values.between(lower, upper).all()),
            observed=[float(values.min()), float(values.max())],
            expected=[lower, upper],
        )
    weather_metadata = json.loads(required["weather_metadata"].read_text())
    audit.check(
        "weather.accumulation_convention",
        weather_metadata.get("accumulation_convention") == "next_day_00utc_previous_24h",
        observed=weather_metadata.get("accumulation_convention"),
    )
    def weather_source_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    weather_files_valid = all(
        weather_source_path(item["path"]).exists()
        and weather_source_path(item["path"]).stat().st_size == item["bytes"]
        and sha256(weather_source_path(item["path"])) == item["sha256"]
        for item in weather_metadata.get("source_files", [])
    )
    audit.check(
        "weather.source_file_count",
        len(weather_metadata.get("source_files", [])) == 35,
        observed=len(weather_metadata.get("source_files", [])),
        expected=35,
    )
    audit.check("weather.source_hashes", weather_files_valid)

    sentinel = read_frame(required["sentinel_manifest"])
    sentinel["datetime"] = pd.to_datetime(sentinel["datetime"], errors="coerce", utc=True)
    audit.check("sentinel_manifest.zones", normalize_codes(sentinel["zone_code"]) == CANONICAL_PROVINCE_CODES)
    audit.check("sentinel_manifest.unique_periods", not sentinel.duplicated(["zone_code", "period_start"]).any())
    uri_columns = ["red_uri", "nir_uri", "scl_uri"]
    audit.check("sentinel_manifest.required_assets", bool(sentinel[uri_columns].notna().all(axis=1).all()))
    audit.check("sentinel_manifest.publication_timestamp", bool(sentinel[["created", "updated"]].notna().any(axis=1).all()))
    audit.check(
        "sentinel_manifest.fixed_scene_selection",
        set(sentinel["scene_selection_method"].dropna())
        == {
            "province_representative_point_fixed_grid_least_cloudy_per_period"
        },
        observed=sorted(sentinel["scene_selection_method"].dropna().unique()),
    )
    grid_count_by_zone = sentinel.groupby("zone_code")["grid_code"].nunique()
    audit.check(
        "sentinel_manifest.grid_stability",
        bool(grid_count_by_zone.eq(1).all()),
        observed={
            "maximum_grids_per_zone": int(grid_count_by_zone.max()),
            "zones_not_one": int(grid_count_by_zone.ne(1).sum()),
        },
        expected="exactly one locked MGRS grid per fixed analysis point",
    )
    audit.check(
        "sentinel_manifest.locked_grid_matches_scene",
        bool(sentinel["analysis_grid_code"].eq(sentinel["grid_code"]).all()),
    )
    satellite = read_frame(required["satellite"])
    satellite["date"] = pd.to_datetime(satellite["date"])
    audit.check("satellite.unique_scene_rows", not satellite.duplicated(["zone_code", "date"]).any())
    ok_satellite = satellite["status"].eq("ok")
    audit.check(
        "satellite.success_fraction",
        float(ok_satellite.mean()) >= args.minimum_satellite_success_fraction,
        observed=float(ok_satellite.mean()),
        expected=f">={args.minimum_satellite_success_fraction}",
    )
    usable_satellite = ok_satellite & pd.to_numeric(
        satellite.get("ndvi_mean"), errors="coerce"
    ).notna()
    audit.check(
        "satellite.usable_fraction",
        float(usable_satellite.mean()) >= args.minimum_satellite_usable_fraction,
        observed=float(usable_satellite.mean()),
        expected=f">={args.minimum_satellite_usable_fraction}",
    )
    for column, lower, upper in (
        ("ndvi_mean", -1.0, 1.0),
        ("ndwi_mean", -1.0, 1.0),
        ("evi_mean", -2.0, 2.0),
        ("valid_pixel_fraction", 0.0, 1.0),
    ):
        values = pd.to_numeric(satellite.loc[ok_satellite, column], errors="coerce").dropna()
        audit.check(
            f"satellite.range.{column}",
            bool(len(values) and values.between(lower, upper).all()),
            observed=[float(values.min()), float(values.max())] if len(values) else [],
            expected=[lower, upper],
        )

    osm_summary = read_frame(required["osm_summary"])
    osm_edges = read_frame(required["osm_edges"])
    osm_manifest = json.loads(required["osm_manifest"].read_text())
    audit.check("osm.province_rows", len(osm_summary) == 38, observed=len(osm_summary), expected=38)
    audit.check("osm.provinces", normalize_codes(osm_summary["province_code"]) == CANONICAL_PROVINCE_CODES)
    audit.check("osm.snapshot_date", set(pd.to_datetime(osm_summary["snapshot_date"]).dt.strftime("%Y-%m-%d")) == {"2026-01-01"})
    audit.check("osm.candidate_label", set(osm_edges["edge_interpretation"].dropna()) == {"candidate_structural_connectivity"})
    audit.check("osm.edges_nonempty", not osm_edges.empty, observed=len(osm_edges), expected=">0")
    pbf_path = root / "data/raw/osm/indonesia.osm.pbf"
    audit.check(
        "osm.checksum",
        pbf_path.exists()
        and pbf_path.stat().st_size == osm_manifest.get("bytes")
        and sha256(pbf_path) == osm_manifest.get("sha256"),
    )

    market_summary = read_frame(required["official_market_summary"])
    market_manifest = json.loads(required["official_market_manifest"].read_text())
    market_raw = root / str(market_manifest.get("raw_geojson", ""))
    audit.check("official_markets.features", market_manifest.get("feature_count") == 625, observed=market_manifest.get("feature_count"), expected=625)
    audit.check("official_markets.reference_provinces", len(market_summary) == 38, observed=len(market_summary), expected=38)
    audit.check("official_markets.provinces_with_points", market_manifest.get("provinces_with_points") == 37, observed=market_manifest.get("provinces_with_points"), expected=37, warning=True)
    audit.check("official_markets.dki_gap_recorded", market_manifest.get("provinces_without_points") == ["31"], observed=market_manifest.get("provinces_without_points"), expected=["31"], warning=True)
    audit.check(
        "official_markets.raw_hash",
        market_raw.exists()
        and sha256(market_raw) == market_manifest.get("raw_sha256"),
    )

    dynamic = read_frame(required["dynamic_graph"])
    dynamic["snapshot_date"] = pd.to_datetime(dynamic["snapshot_date"])
    dynamic["window_start"] = pd.to_datetime(dynamic["window_start"])
    audit.check("dynamic_graph.unique_edges", not dynamic["edge_id"].duplicated().any())
    audit.check(
        "dynamic_graph.snapshot_count",
        dynamic["snapshot_date"].nunique() == 27,
        observed=int(dynamic["snapshot_date"].nunique()),
        expected=27,
    )
    audit.check(
        "dynamic_graph.commodities",
        set(dynamic["commodity_code"].dropna()) == EXPECTED_COMMODITIES,
    )
    audit.check(
        "dynamic_graph.market_levels",
        set(dynamic["market_level"].dropna()) == EXPECTED_MARKETS,
    )
    audit.check("dynamic_graph.window_is_historical", bool((dynamic["window_start"] + pd.to_timedelta(dynamic["window_days"] - 1, unit="D")).le(dynamic["snapshot_date"]).all()))
    audit.check("dynamic_graph.interpretation", set(dynamic["edge_interpretation"].dropna()) == {"model_inferred_price_dependence"})
    audit.check("dynamic_graph.latest_snapshot", dynamic["snapshot_date"].max() <= end, observed=str(dynamic["snapshot_date"].max()), expected=f"<={end}")

    static = read_frame(required["static_graph"])
    audit.check("static_graph.nonempty", not static.empty, observed=len(static))
    audit.check("static_graph.candidate_only", bool(pd.to_numeric(static["candidate_connectivity_only"], errors="coerce").eq(1).all()))

    ready = read_frame(required["ready_all"])
    ready["date"] = pd.to_datetime(ready["date"])
    ready_province_codes = normalize_codes(ready["province_code"])
    audit.check(
        "ready.provinces_match_price_targets",
        ready_province_codes == price_province_codes,
        observed=sorted(ready_province_codes),
        expected=sorted(price_province_codes),
    )
    missing_price_provinces = sorted(CANONICAL_PROVINCE_CODES - ready_province_codes)
    audit.check(
        "ready.no_price_target_provinces_recorded",
        missing_price_provinces == ["92", "95", "96", "97"],
        observed=missing_price_provinces,
        expected=["92", "95", "96", "97"],
        warning=True,
    )
    audit.check("ready.evidence_quality_unavailable", bool(pd.to_numeric(ready["evidence_quality_score"], errors="coerce").isna().all()))
    audit.check("ready.evidence_status", set(ready["evidence_status"].dropna()) == {"not_assessed"})
    availability_columns = {
        "weather_effective_date",
        "production_effective_date",
        "satellite_effective_date",
        "transport_snapshot_date",
        "market_context_effective_date",
    }
    for column in sorted(availability_columns):
        effective_date = pd.to_datetime(ready[column], errors="coerce")
        violations = effective_date.notna() & effective_date.gt(ready["date"])
        audit.check(f"ready.no_future_context.{column}", not violations.any(), observed=int(violations.sum()), expected=0)
    masks = ["mask_price", "mask_weather", "mask_production", "mask_satellite", "mask_calendar", "mask_graph"]
    audit.check("ready.modality_masks", all(column in ready for column in masks))
    audit.check(
        "ready.modality_count_consistency",
        bool(
            pd.to_numeric(ready["available_modality_count"], errors="coerce")
            .eq(ready[masks].sum(axis=1))
            .all()
        ),
    )
    ready_metadata = json.loads(required["ready_metadata"].read_text())
    feature_columns = set(ready_metadata.get("feature_columns", []))
    forbidden_features = sorted(
        column
        for column in feature_columns
        if column.startswith(("price_t_plus_", "future_", "shock_"))
        or column == "threshold_exceeded"
    )
    audit.check("ready.no_realized_labels_in_feature_contract", not forbidden_features, observed=forbidden_features, expected=[])

    hashes = {
        name: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for name, path in required.items()
        if path.is_file() and path.suffix not in {".geojson"}
    }
    return finish_payload(audit, root, required, hashes)


def finish_payload(
    audit: Audit,
    root: Path,
    required: dict[str, Path],
    hashes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "status": "passed" if not audit.errors else "failed",
        "checks_passed": sum(item["status"] == "passed" for item in audit.checks),
        "checks_warning": sum(item["status"] == "warning" for item in audit.checks),
        "checks_failed": sum(item["status"] == "failed" for item in audit.checks),
        "errors": audit.errors,
        "warnings": audit.warnings,
        "checks": audit.checks,
        "artifact_hashes": hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2026-07-31")
    parser.add_argument("--minimum-satellite-success-fraction", type=float, default=0.80)
    parser.add_argument("--minimum-satellite-usable-fraction", type=float, default=0.80)
    parser.add_argument("--output", type=Path, default=Path("reports/multimodal_validation.json"))
    args = parser.parse_args()
    payload = validate(args)
    output = args.output if args.output.is_absolute() else args.project_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
