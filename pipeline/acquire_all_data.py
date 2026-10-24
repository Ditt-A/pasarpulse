#!/usr/bin/env python3
"""Acquire every public input required by PasarPulse-MM.

Required, no account:
  * BIG 38-province GeoJSON
  * PIHPS province × commodity × market-level daily snapshots from 2024-02 through 2026-07
  * SP2KP monthly workbooks from 2024-02 through 2026-07
  * BPS production and harvested-area tables for 2023-2025
  * official market locations and declared operating-frequency metadata
  * calendar events and official thresholds (already bundled)

Full multimodal acquisition, disabled by default because it is large:
  * ERA5-Land
  * Sentinel-2 L2A
  * dated Geofabrik OpenStreetMap transport snapshot
  * static and rolling price-dependence graph features
  * leakage-gated model-ready merge and quality artifacts

The command is resumable: existing non-empty files are kept unless --overwrite is used.
A machine-readable status report is always written to data/acquisition/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_status(rows: list[dict[str, Any]]) -> None:
    out = ROOT / "data" / "acquisition"
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "download_status.csv", index=False)
    payload = {
        "generated_at_utc": utc_now(),
        "host": {"python": sys.version, "platform": platform.platform()},
        "summary": frame["status"].value_counts(dropna=False).to_dict() if not frame.empty else {},
        "items": rows,
    }
    (out / "download_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def record(rows: list[dict[str, Any]], stage: str, status: str, detail: str = "", outputs: list[Path] | None = None) -> None:
    outputs = outputs or []
    rows.append({
        "checked_at_utc": utc_now(),
        "stage": stage,
        "status": status,
        "detail": detail,
        "outputs": ";".join(str(p.relative_to(ROOT)) if p.is_absolute() and ROOT in p.parents else str(p) for p in outputs),
    })
    save_status(rows)


def parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:
        return False


def expected_sp2kp_resources(start_date: str, end_date: str) -> pd.DataFrame:
    months = pd.date_range(pd.Timestamp(start_date).to_period("M").to_timestamp(), pd.Timestamp(end_date).to_period("M").to_timestamp(), freq="MS")
    return pd.DataFrame([
        {
            "resource_id": f"official-direct-{d:%Y-%m}",
            "name": f"Harga Komoditas Bahan Pokok SP2KP {d:%Y-%m}",
            "url": f"https://api-sp2kp.kemendag.go.id/kld/api/list-harga-harian/{d.year:04d}/{d.month:02d}",
            "format": "XLSX",
            "last_modified": None,
            "size": None,
            "year": d.year,
            "month": d.month,
            "period": d,
            "last_modified_parsed": pd.NaT,
            "size_numeric": pd.NA,
            "discovery_source": "official_direct_pattern",
        }
        for d in months
    ])


def acquire_references(rows: list[dict[str, Any]], overwrite: bool) -> bool:
    try:
        from src.pasarpulse.tools.reference import prepare_reference_files
        outputs = prepare_reference_files(
            ROOT / "data/reference/indonesia_provinces.geojson",
            ROOT / "data/reference/satellite_zones.geojson",
            endpoint="https://geoservices.big.go.id/rbi/rest/services/BATASWILAYAH/BATAS_WILAYAH/MapServer/12/query",
            expected_count=38,
            overwrite=overwrite,
        )
        paths = list(outputs.values())
        record(rows, "BIG province boundaries", "complete", "Downloaded and validated 38 province polygons; derived province-fallback satellite zones.", paths)
        return True
    except Exception as exc:
        record(rows, "BIG province boundaries", "failed", f"{type(exc).__name__}: {exc}")
        return False


def acquire_sp2kp(rows: list[dict[str, Any]], start_date: str, end_date: str, overwrite: bool, timeout: int) -> bool:
    from src.pasarpulse.tools.sp2kp import download_sp2kp_resources, parse_sp2kp_file
    from src.pasarpulse.utils import save_frame

    resources = expected_sp2kp_resources(start_date, end_date)
    manifest_rows: list[dict[str, Any]] = []
    parts: list[pd.DataFrame] = []
    raw_dir = ROOT / "data/raw/sp2kp"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for _, item in resources.iterrows():
        row = dict(item)
        try:
            downloaded = download_sp2kp_resources(pd.DataFrame([row]), raw_dir, overwrite=overwrite, timeout=timeout)
            local_path = Path(str(downloaded.iloc[0]["local_path"]))
            parsed = parse_sp2kp_file(local_path, year=int(item.year), month=int(item.month))
            parts.append(parsed)
            row.update({
                "local_path": str(local_path),
                "download_status": str(downloaded.iloc[0]["download_status"]),
                "parse_status": "parsed",
                "bytes": local_path.stat().st_size,
                "sha256": sha256(local_path),
            })
        except Exception as exc:
            row.update({"download_status": "failed", "parse_status": f"failed: {type(exc).__name__}: {exc}"})
        manifest_rows.append(row)
        pd.DataFrame(manifest_rows).to_csv(ROOT / "data/processed/sp2kp_resource_manifest.csv", index=False)

    manifest = pd.DataFrame(manifest_rows)
    if parquet_available():
        manifest.to_parquet(ROOT / "data/processed/sp2kp_resource_manifest.parquet", index=False)
    succeeded = manifest["parse_status"].eq("parsed").sum()
    expected = len(resources)
    if parts:
        result = pd.concat(parts, ignore_index=True)
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
        result = result[result["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
        keys = ["date", "province_code", "commodity_code", "market_level", "source"]
        result = result.sort_values(keys + ["source_version"]).drop_duplicates(keys, keep="last")
        result = result.sort_values(["province_code", "commodity_code", "market_level", "date"]).reset_index(drop=True)
        outputs = save_frame(result, ROOT / "data/processed/price_daily", save_csv=True, save_parquet=parquet_available())
        output_paths = list(outputs.values()) + [ROOT / "data/processed/sp2kp_resource_manifest.csv"]
    else:
        output_paths = [ROOT / "data/processed/sp2kp_resource_manifest.csv"]
    status = "complete" if succeeded == expected else ("partial" if succeeded else "failed")
    record(rows, "SP2KP prices", status, f"Parsed {succeeded}/{expected} expected monthly resources.", output_paths)
    return succeeded == expected


def acquire_pihps(rows: list[dict[str, Any]], start_date: str, end_date: str, overwrite: bool, timeout: int) -> bool:
    try:
        from src.pasarpulse.tools.pihps import ingest_pihps

        frame, outputs, manifest, manifest_outputs, mapping, mapping_outputs = ingest_pihps(
            start_date=start_date,
            end_date=end_date,
            raw_dir=ROOT / "data/raw/pihps",
            output_base=ROOT / "data/processed/price_daily",
            manifest_base=ROOT / "data/processed/pihps_snapshot_manifest",
            mapping_base=ROOT / "data/processed/pihps_mapping_audit",
            timeout=timeout,
            overwrite_snapshots=overwrite,
            save_csv=True,
            save_parquet=parquet_available(),
        )
        failed = int(manifest["status"].eq("failed").sum()) if not manifest.empty else 0
        outputs_all = list(outputs.values()) + list(manifest_outputs.values()) + list(mapping_outputs.values())
        status = "complete" if failed == 0 else "partial"
        record(
            rows,
            "PIHPS prices",
            status,
            f"Canonical rows: {len(frame):,}; snapshots: {len(manifest):,}; failed snapshots: {failed}.",
            outputs_all,
        )
        return failed == 0
    except Exception as exc:
        record(rows, "PIHPS prices", "failed", f"{type(exc).__name__}: {exc}")
        return False


def acquire_bps(rows: list[dict[str, Any]], years: list[int], overwrite: bool, timeout: int) -> bool:
    # The public BPS tables expose the rendered data in the page's Next.js
    # payload.  The direct parser avoids a browser/token dependency and keeps
    # this acquisition command usable on the A100 runtime as well as locally.
    existing_csv = ROOT / "data/processed/production_annual.csv"
    existing_manifest = ROOT / "data/processed/bps_acquisition_manifest.csv"
    expected_raw = [
        ROOT / "data/raw/bps" / f"{measure}_{year}_{suffix}"
        for year in years
        for measure in ("production", "harvested_area")
        for suffix in ("rendered.csv", "page.html")
    ]
    if not overwrite and existing_csv.exists() and existing_csv.stat().st_size > 0 and all(
        path.exists() and path.stat().st_size > 0 for path in expected_raw
    ):
        try:
            existing = pd.read_csv(existing_csv)
            available_years = set(pd.to_numeric(existing["year"], errors="coerce").dropna().astype(int))
            if set(years).issubset(available_years):
                outputs = [existing_csv]
                existing_parquet = ROOT / "data/processed/production_annual.parquet"
                if existing_parquet.exists() and existing_parquet.stat().st_size > 0:
                    outputs.append(existing_parquet)
                if existing_manifest.exists() and existing_manifest.stat().st_size > 0:
                    outputs.append(existing_manifest)
                record(rows, "BPS production", "complete", f"Reused validated panel for years: {sorted(available_years)}.", outputs)
                return True
        except Exception:
            pass

    from src.pasarpulse.tools.bps import build_annual_dataset
    yearly: list[pd.DataFrame] = []
    successful_years: list[int] = []
    for year in years:
        yearly_csv = ROOT / f"data/interim/bps_{year}.csv"
        if yearly_csv.exists() and yearly_csv.stat().st_size > 0 and not overwrite:
            try:
                yearly.append(pd.read_csv(yearly_csv))
                successful_years.append(year)
                continue
            except Exception:
                pass
        try:
            frame, _ = build_annual_dataset(
                [year], output_base=ROOT / f"data/interim/bps_{year}", raw_dir=ROOT / "data/raw/bps",
                project_root=ROOT, headless=True, timeout=timeout, save_csv=True, save_parquet=parquet_available(),
            )
            frame.to_csv(yearly_csv, index=False)
            yearly.append(frame)
            successful_years.append(year)
        except Exception as exc:
            (ROOT / "logs" / f"bps_{year}_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")

    outputs: list[Path] = []
    if yearly:
        result = pd.concat(yearly, ignore_index=True)
        result = result.sort_values(["year", "province_code", "commodity_code"], na_position="last").reset_index(drop=True)
        result.to_csv(ROOT / "data/processed/production_annual.csv", index=False)
        outputs.append(ROOT / "data/processed/production_annual.csv")
        if parquet_available():
            result.to_parquet(ROOT / "data/processed/production_annual.parquet", index=False)
            outputs.append(ROOT / "data/processed/production_annual.parquet")
    status = "complete" if set(successful_years) == set(years) else ("partial" if successful_years else "failed")
    record(rows, "BPS production", status, f"Completed years: {successful_years}; expected: {years}.", outputs)
    return set(successful_years) == set(years)


def build_calendar(rows: list[dict[str, Any]], start_date: str, end_date: str) -> bool:
    try:
        from src.pasarpulse.tools.calendar import build_calendar_features
        frame, outputs = build_calendar_features(
            start_date, end_date,
            events_path=ROOT / "data/manual/calendar_events.csv",
            output_base=ROOT / "data/processed/calendar_features",
            national_region_code="NATIONAL", save_csv=True, save_parquet=parquet_available(),
        )
        record(rows, "Calendar features", "complete", f"Generated {len(frame):,} daily rows.", list(outputs.values()))
        return True
    except Exception as exc:
        record(rows, "Calendar features", "failed", f"{type(exc).__name__}: {exc}")
        return False


def verify_included(rows: list[dict[str, Any]]) -> bool:
    required = [ROOT / "data/manual/calendar_events.csv", ROOT / "data/manual/official_thresholds.csv"]
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        record(rows, "Bundled official tables", "failed", f"Missing: {missing}")
        return False
    record(rows, "Bundled official tables", "complete", "Calendar source events and official threshold table are included.", required)
    return True


def acquire_official_market_data(rows: list[dict[str, Any]]) -> bool:
    """Acquire the official BIG/Kemendag market layer and normalize all provinces."""
    try:
        from src.pasarpulse import PasarPulsePipeline, load_config

        config = load_config(ROOT / "config.yaml", project_root=ROOT)
        config.raw["project"]["fail_fast"] = True
        config.raw["stages"]["official_markets"] = True
        pipeline = PasarPulsePipeline(config)
        summary = pipeline.run_official_markets()
        outputs = [
            path
            for key, path in pipeline.paths.items()
            if key.startswith("official_markets_")
        ]
        complete = summary is not None and len(summary) == 38
        record(
            rows,
            "Official market metadata",
            "complete" if complete else "failed",
            (
                f"Normalized {0 if summary is None else len(summary)}/38 province rows. "
                "A missing province in the source remains an explicit source gap, not a zero."
            ),
            outputs,
        )
        return complete
    except Exception as exc:
        record(rows, "Official market metadata", "failed", f"{type(exc).__name__}: {exc}")
        return False


def multimodal_inputs(rows: list[dict[str, Any]]) -> bool:
    """Run every large methodology stage in dependency order.

    The stages are deliberately resumable.  A failed source is recorded and
    later independent stages still run, which makes partial-source failures
    auditable instead of silently disappearing.
    """
    from src.pasarpulse import PasarPulsePipeline, load_config

    config = load_config(ROOT / "config.yaml", project_root=ROOT)
    config.raw["project"]["fail_fast"] = False
    stage_specs = [
        ("ERA5-Land download", "era5_download", "run_era5_download"),
        ("ERA5-Land province aggregation", "era5_aggregate", "run_era5_aggregate"),
        ("Sentinel-2 catalog search", "sentinel_search", "run_sentinel_search"),
        ("Sentinel-2 regional vegetation extraction", "sentinel_extract", "run_sentinel_extract"),
        ("Dated OSM transport snapshot", "osm_transport", "run_osm_transport"),
        ("Candidate static graph", "static_graph", "run_static_graph"),
        ("Rolling price-dependence graph", "dynamic_graph", "run_dynamic_graph"),
        ("Leakage-gated model-ready merge", "merge", "run_merge"),
        ("Multimodal quality artifacts", "quality", "run_quality"),
    ]
    pipeline = PasarPulsePipeline(config)
    all_complete = True
    for label, stage, method in stage_specs:
        config.raw["stages"][stage] = True
        before = set(pipeline.paths)
        try:
            result = getattr(pipeline, method)()
            stage_record = pipeline.stage_records[-1]
            complete = stage_record["status"] == "completed" and result is not None
            detail = stage_record.get("message", "")
        except Exception as exc:  # defensive: fail_fast is disabled above
            complete = False
            detail = f"{type(exc).__name__}: {exc}"
        outputs = [
            value for key, value in pipeline.paths.items() if key not in before
        ]
        record(
            rows,
            label,
            "complete" if complete else "failed",
            detail,
            outputs,
        )
        all_complete &= complete
    return all_complete


def write_checksums(rows: list[dict[str, Any]]) -> Path:
    targets = []
    for base in [ROOT / "data/manual", ROOT / "data/reference", ROOT / "data/raw", ROOT / "data/processed"]:
        if base.exists():
            targets.extend(p for p in base.rglob("*") if p.is_file() and p.name != ".gitkeep")
    checksum_path = ROOT / "data/acquisition/SHA256SUMS.txt"
    checksum_path.write_text("".join(f"{sha256(p)}  {p.relative_to(ROOT)}\n" for p in sorted(targets)), encoding="utf-8")
    record(rows, "Checksums", "complete", f"Recorded {len(targets)} files.", [checksum_path])
    return checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Redownload existing files.")
    parser.add_argument(
        "--include-multimodal",
        action="store_true",
        help="Acquire and integrate ERA5, Sentinel-2, dated OSM, and both graph layers.",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Deprecated alias for --include-multimodal.",
    )
    parser.add_argument("--skip-bps", action="store_true")
    parser.add_argument("--skip-sp2kp", action="store_true")
    parser.add_argument("--skip-pihps", action="store_true")
    parser.add_argument("--skip-boundaries", action="store_true")
    parser.add_argument("--skip-official-markets", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    start_date = str(cfg["project"]["start_date"])
    end_date = str(cfg["project"]["end_date"])
    years = [int(y) for y in cfg["bps"]["years"]]
    rows: list[dict[str, Any]] = []

    required_ok = verify_included(rows)
    required_ok &= build_calendar(rows, start_date, end_date)
    if not args.skip_boundaries:
        required_ok &= acquire_references(rows, args.overwrite)
    if not args.skip_pihps:
        required_ok &= acquire_pihps(rows, start_date, end_date, args.overwrite, args.timeout)
    if not args.skip_sp2kp:
        required_ok &= acquire_sp2kp(rows, start_date, end_date, args.overwrite, args.timeout)
    if not args.skip_bps:
        required_ok &= acquire_bps(rows, years, args.overwrite, min(args.timeout, 120))
    if not args.skip_official_markets:
        required_ok &= acquire_official_market_data(rows)
    if args.include_multimodal or args.include_optional:
        required_ok &= multimodal_inputs(rows)
    write_checksums(rows)
    save_status(rows)

    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nStatus report: {ROOT / 'data/acquisition/download_status.csv'}")
    if not required_ok:
        print("\nOne or more required remote inputs are incomplete. Fix the reported environment/network issue and rerun; completed files are reused.", file=sys.stderr)
        return 1
    print("\nAll requested public inputs are complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
