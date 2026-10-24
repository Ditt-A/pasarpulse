#!/usr/bin/env python3
"""Verify credentialed multimodal sources without exposing credentials.

The checks intentionally request only metadata (CDSE STAC/S3) or one tiny
ERA5-Land sample.  They are suitable as a preflight before launching the
resumable bulk acquisition jobs on the A100 host.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_cdse(project_root: Path, zones_path: Path) -> dict[str, Any]:
    import boto3
    import geopandas as gpd
    from botocore.config import Config
    from pystac_client import Client

    from src.pasarpulse.credentials import load_project_credentials

    settings = load_project_credentials(
        required=("CDSE_S3_ACCESS_KEY", "CDSE_S3_SECRET_KEY"),
        project_root=project_root,
        force_reload=True,
    )
    zones = gpd.read_file(zones_path).to_crs(4326)
    if zones.empty:
        raise ValueError("Satellite zone file is empty.")
    point = zones.geometry.iloc[0].representative_point()
    epsilon = 0.02
    bbox = [point.x - epsilon, point.y - epsilon, point.x + epsilon, point.y + epsilon]
    catalog = Client.open("https://stac.dataspace.copernicus.eu/v1/")
    catalog.add_conforms_to("ITEM_SEARCH")
    items = list(
        catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime="2024-01-01/2024-01-31",
            query={"eo:cloud_cover": {"lte": 30.0}},
            max_items=2,
        ).items()
    )
    endpoint = (settings.get("CDSE_S3_ENDPOINT") or "https://eodata.dataspace.copernicus.eu").rstrip("/")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings["CDSE_S3_ACCESS_KEY"],
        aws_secret_access_key=settings["CDSE_S3_SECRET_KEY"],
        region_name="default",
        config=Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 1}),
    )
    listing = client.list_objects_v2(
        Bucket="eodata", Prefix="Sentinel-2/MSI/L2A/2024/01/", MaxKeys=1
    )
    return {
        "source": "Copernicus Data Space Ecosystem",
        "checked_at_utc": _utc_now(),
        "stac_reachable": True,
        "stac_item_count": len(items),
        "sample_item_ids": [item.id for item in items],
        "sample_asset_keys": sorted(items[0].assets) if items else [],
        "s3_reachable": True,
        "s3_object_count": int(listing.get("KeyCount", 0)),
        "credentials_present": True,
    }


def check_earth_search(zones_path: Path) -> dict[str, Any]:
    import geopandas as gpd
    import rasterio
    from pystac_client import Client
    from rasterio.windows import Window

    zones = gpd.read_file(zones_path).to_crs(4326)
    if zones.empty:
        raise ValueError("Satellite zone file is empty.")
    point = zones.geometry.iloc[0].representative_point()
    epsilon = 0.02
    bbox = [point.x - epsilon, point.y - epsilon, point.x + epsilon, point.y + epsilon]
    catalog = Client.open("https://earth-search.aws.element84.com/v1/")
    items = list(
        catalog.search(
            collections=["sentinel-2-c1-l2a"],
            bbox=bbox,
            datetime="2024-01-01/2024-01-31",
            query={"eo:cloud_cover": {"lte": 30.0}},
            max_items=2,
        ).items()
    )
    if not items:
        raise RuntimeError("Earth Search returned no January 2024 sample scene.")
    asset = items[0].assets.get("red")
    if asset is None:
        raise RuntimeError("Earth Search sample is missing the red COG asset.")
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(asset.href) as dataset:
            sample = dataset.read(1, window=Window(0, 0, 1, 1))
            raster_driver = dataset.driver
            raster_crs = str(dataset.crs)
    return {
        "source": "Earth Search / AWS Registry of Open Data",
        "checked_at_utc": _utc_now(),
        "stac_reachable": True,
        "collection": "sentinel-2-c1-l2a",
        "stac_item_count": len(items),
        "sample_item_ids": [item.id for item in items],
        "sample_asset_keys": sorted(items[0].assets),
        "public_cog_readable": bool(sample.size),
        "raster_driver": raster_driver,
        "raster_crs": raster_crs,
        "credentials_required": False,
    }


def check_cds(project_root: Path) -> dict[str, Any]:
    import cdsapi

    from src.pasarpulse.credentials import load_project_credentials

    settings = load_project_credentials(
        required=("CDS_API_URL", "CDS_API_KEY"),
        project_root=project_root,
        force_reload=True,
    )
    with tempfile.TemporaryDirectory(prefix="pasarpulse-cds-smoke-") as directory:
        target = Path(directory) / "era5_land_smoke.nc"
        client = cdsapi.Client(
            url=settings["CDS_API_URL"], key=settings["CDS_API_KEY"], quiet=True
        )
        client.retrieve(
            "reanalysis-era5-land",
            {
                "variable": ["2m_temperature"],
                "year": "2024",
                "month": "01",
                "day": ["01"],
                "time": ["00:00"],
                "area": [0.2, 106.6, -0.2, 107.0],
                "data_format": "netcdf",
                "download_format": "unarchived",
            },
            str(target),
        )
        if not target.exists() or target.stat().st_size == 0:
            raise RuntimeError("CDS returned no ERA5-Land sample.")
        size = target.stat().st_size
    return {
        "source": "Copernicus Climate Data Store",
        "checked_at_utc": _utc_now(),
        "dataset": "reanalysis-era5-land",
        "sample_retrieved": True,
        "sample_bytes": size,
        "credentials_present": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--zones", type=Path, default=Path("data/reference/satellite_zones.geojson"))
    parser.add_argument(
        "--source", choices=("all", "cdse", "earth-search", "cds"), default="all"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    zones_path = args.zones if args.zones.is_absolute() else project_root / args.zones
    checks: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, callback in (
        ("cdse", lambda: check_cdse(project_root, zones_path)),
        ("earth-search", lambda: check_earth_search(zones_path)),
        ("cds", lambda: check_cds(project_root)),
    ):
        if args.source not in {"all", name}:
            continue
        try:
            checks[name] = callback()
        except Exception as exc:  # Preserve a machine-readable preflight result.
            errors[name] = f"{type(exc).__name__}: {exc}"
    payload = {
        "checked_at_utc": _utc_now(),
        "checks": checks,
        "errors": errors,
        "ok": not errors,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output if args.output.is_absolute() else project_root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
