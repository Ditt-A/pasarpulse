"""Sentinel-2 L2A discovery and vegetation-anomaly feature extraction."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from rasterio.enums import Resampling
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import reproject, transform_geom
from tqdm.auto import tqdm

from ..credentials import load_project_credentials
from ..utils import save_frame

DEFAULT_STAC_URL = "https://stac.dataspace.copernicus.eu/v1/"


def _choose_asset(assets: dict[str, Any], candidates: list[str]) -> str | None:
    lowered = {key.casefold(): value for key, value in assets.items()}
    for candidate in candidates:
        asset = assets.get(candidate) or lowered.get(candidate.casefold())
        if asset:
            href = asset.get("href") if isinstance(asset, dict) else getattr(asset, "href", None)
            if href:
                return str(href)
    return None


def search_sentinel2(
    zones_path: str | Path,
    *,
    zone_code_col: str,
    zone_name_col: str,
    start_date: str,
    end_date: str,
    max_cloud: float,
    period_days: int,
    output_base: str | Path,
    stac_url: str = DEFAULT_STAC_URL,
    collection: str = "sentinel-2-l2a",
    search_workers: int = 1,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    zones = gpd.read_file(zones_path).to_crs(4326)
    missing = {zone_code_col, zone_name_col}.difference(zones.columns)
    if missing:
        raise ValueError(f"Satellite zone file misses columns: {sorted(missing)}")
    def search_zone(zone: pd.Series) -> list[dict[str, Any]]:
        # Bound every remote call.  A stalled STAC page must fail visibly and
        # resumably instead of holding the national acquisition indefinitely.
        catalog = Client.open(
            stac_url,
            stac_io=StacApiIO(timeout=(30.0, 180.0), max_retries=5),
        )
        catalog.add_conforms_to("ITEM_SEARCH")
        zone_rows: list[dict[str, Any]] = []
        analysis_point = zone.geometry.representative_point()
        analysis_geometry = analysis_point.__geo_interface__
        range_start = pd.Timestamp(start_date).normalize()
        range_end = pd.Timestamp(end_date).normalize()
        anchor_search = catalog.search(
            collections=[collection],
            datetime=f"{start_date}/{end_date}",
            intersects=analysis_geometry,
            query={"eo:cloud_cover": {"lte": float(max_cloud)}},
            sortby=[
                {
                    "field": "properties.eo:cloud_cover",
                    "direction": "asc",
                }
            ],
            max_items=1,
        )
        anchor_item = next(anchor_search.items(), None)
        if anchor_item is None:
            return zone_rows
        analysis_grid_code = anchor_item.properties.get("grid:code")
        if not analysis_grid_code:
            raise ValueError(
                f"Sentinel anchor scene does not expose grid:code for zone "
                f"{zone[zone_code_col]}"
            )
        period_starts = pd.date_range(
            range_start, range_end, freq=f"{int(period_days)}D"
        )
        # Query exactly the one least-cloudy scene required by each period.
        # Fetching every intersecting tile before deduplication is unbounded for
        # multi-island provinces such as Maluku and needlessly stresses the
        # public catalog.
        for period_start in period_starts:
            period_end = min(
                period_start + pd.Timedelta(days=int(period_days) - 1),
                range_end,
            )
            search = catalog.search(
                collections=[collection],
                datetime=(
                    f"{period_start.date().isoformat()}/"
                    f"{period_end.date().isoformat()}"
                ),
                intersects=analysis_geometry,
                query={
                    "eo:cloud_cover": {"lte": float(max_cloud)},
                    "grid:code": {"eq": analysis_grid_code},
                },
                sortby=[
                    {
                        "field": "properties.eo:cloud_cover",
                        "direction": "asc",
                    }
                ],
                max_items=1,
            )
            item = next(search.items(), None)
            if item is None:
                continue
            assets = {key: value.to_dict() for key, value in item.assets.items()}
            zone_rows.append(
                {
                    "zone_code": str(zone[zone_code_col]),
                    "zone_name": str(zone[zone_name_col]),
                    "zone_method": zone.get("zone_method", "unspecified"),
                    "zone_source": zone.get("zone_source", "unspecified"),
                    "zone_version": zone.get("zone_version", "unspecified"),
                    "scene_selection_method": (
                        "province_representative_point_fixed_grid_"
                        "least_cloudy_per_period"
                    ),
                    "analysis_longitude": float(analysis_point.x),
                    "analysis_latitude": float(analysis_point.y),
                    "analysis_grid_code": str(analysis_grid_code),
                    "stac_url": stac_url,
                    "stac_collection": collection,
                    "item_id": item.id,
                    "datetime": item.properties.get("datetime"),
                    "created": item.properties.get("created"),
                    "updated": item.properties.get("updated"),
                    "cloud_cover": item.properties.get("eo:cloud_cover"),
                    "grid_code": item.properties.get("grid:code"),
                    "platform": item.properties.get("platform"),
                    "red_uri": _choose_asset(assets, ["B04_10m", "B04", "red", "red-jp2"]),
                    "nir_uri": _choose_asset(assets, ["B08_10m", "B08", "nir", "nir08", "nir-jp2"]),
                    "green_uri": _choose_asset(assets, ["B03_10m", "B03", "green", "green-jp2"]),
                    "blue_uri": _choose_asset(assets, ["B02_10m", "B02", "blue", "blue-jp2"]),
                    "scl_uri": _choose_asset(assets, ["SCL_20m", "SCL", "scl", "classification"]),
                    "product_uri": _choose_asset(assets, ["Product", "product", "visual"]),
                }
            )
        return zone_rows

    zone_records = [zone for _, zone in zones.iterrows()]
    checkpoint = Path(output_base).with_name(
        Path(output_base).name + "_checkpoint.parquet"
    )
    state_path = Path(output_base).with_name(
        Path(output_base).name + "_checkpoint.json"
    )
    valid_zone_codes = {str(zone[zone_code_col]) for zone in zone_records}
    completed_codes: set[str] = set()
    rows: list[dict[str, Any]] = []
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        completed_codes = set(map(str, state.get("completed_zone_codes", [])))
        completed_codes.intersection_update(valid_zone_codes)
    if checkpoint.exists() and checkpoint.stat().st_size > 0:
        checkpoint_frame = pd.read_parquet(checkpoint)
        checkpoint_frame = checkpoint_frame[
            checkpoint_frame["zone_code"].astype(str).isin(valid_zone_codes)
        ]
        rows = checkpoint_frame.to_dict("records")

    def write_search_checkpoint() -> None:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        if rows:
            temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
            pd.DataFrame(rows).to_parquet(temporary, index=False)
            temporary.replace(checkpoint)
        temporary_state = state_path.with_suffix(state_path.suffix + ".tmp")
        temporary_state.write_text(
            json.dumps(
                {"completed_zone_codes": sorted(completed_codes)}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_state.replace(state_path)

    pending = [
        zone for zone in zone_records if str(zone[zone_code_col]) not in completed_codes
    ]
    worker_count = max(1, min(int(search_workers), len(pending) or 1))
    failures: dict[str, str] = {}
    progress = tqdm(
        total=len(zone_records),
        initial=len(completed_codes),
        desc="STAC zones",
    )
    try:
        if worker_count == 1:
            for zone in pending:
                code = str(zone[zone_code_col])
                try:
                    rows.extend(search_zone(zone))
                    completed_codes.add(code)
                    write_search_checkpoint()
                except Exception as exc:
                    failures[code] = repr(exc)
                progress.update(1)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(search_zone, zone): str(zone[zone_code_col])
                    for zone in pending
                }
                for future in as_completed(futures):
                    code = futures[future]
                    try:
                        rows.extend(future.result())
                        completed_codes.add(code)
                        write_search_checkpoint()
                    except Exception as exc:
                        failures[code] = repr(exc)
                    progress.update(1)
    finally:
        progress.close()
    if failures:
        raise RuntimeError(
            "Sentinel STAC search failed for zones; rerun to resume: "
            + json.dumps(failures, ensure_ascii=False)
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
        origin = pd.Timestamp(start_date, tz="UTC")
        frame["period_index"] = ((frame["datetime"] - origin).dt.days // int(period_days)).astype("Int64")
        frame["period_start"] = origin + pd.to_timedelta(frame["period_index"] * int(period_days), unit="D")
        frame = (
            frame.sort_values(["zone_code", "period_start", "cloud_cover", "datetime"])
            .drop_duplicates(["zone_code", "period_start"], keep="first")
            .reset_index(drop=True)
        )
    outputs = save_frame(frame, output_base, save_csv=save_csv, save_parquet=save_parquet)
    checkpoint.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    return frame, outputs


def configure_cdse_s3(project_root: str | Path) -> dict[str, str]:
    settings = load_project_credentials(
        required=("CDSE_S3_ACCESS_KEY", "CDSE_S3_SECRET_KEY"),
        project_root=project_root,
    )
    endpoint = (settings.get("CDSE_S3_ENDPOINT") or "https://eodata.dataspace.copernicus.eu").rstrip("/")
    endpoint_host = endpoint.removeprefix("https://").removeprefix("http://")
    os.environ.update(
        {
            "AWS_S3_ENDPOINT": endpoint_host,
            "AWS_ENDPOINT_URL": endpoint,
            "AWS_ACCESS_KEY_ID": settings["CDSE_S3_ACCESS_KEY"],
            "AWS_SECRET_ACCESS_KEY": settings["CDSE_S3_SECRET_KEY"],
            "AWS_HTTPS": "YES",
            "AWS_VIRTUAL_HOSTING": "FALSE",
            "AWS_DEFAULT_REGION": "default",
            "GDAL_HTTP_TCP_KEEPALIVE": "YES",
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        }
    )
    return settings


def configure_asset_access(project_root: str | Path, scenes: pd.DataFrame) -> str:
    """Configure only the access mode required by the selected asset URIs."""
    os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "30")
    os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")
    os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
    os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "5")
    uri_columns = [column for column in scenes if column.endswith("_uri")]
    uris = [
        str(value)
        for column in uri_columns
        for value in scenes[column].dropna().tolist()
        if str(value).strip()
    ]
    if any(uri.startswith("s3://eodata/") for uri in uris):
        configure_cdse_s3(project_root)
        return "cdse_authenticated_s3"
    if any(uri.startswith("s3://") for uri in uris):
        os.environ["AWS_NO_SIGN_REQUEST"] = "YES"
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
        os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
        return "public_anonymous_s3"
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    return "public_https"


def _raster_uri(uri: str) -> str:
    if uri.startswith("s3://"):
        return "/vsis3/" + uri.removeprefix("s3://")
    if uri.startswith("https://") or uri.startswith("http://"):
        return "/vsicurl/" + uri
    return uri


def _read_masked_band(
    uri: str,
    geometry_4326: dict,
    *,
    resampling: Resampling,
    max_sample_pixels: int,
    apply_scale_offset: bool,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a bounded regional sample without materializing an entire S2 tile.

    Sentinel-2 L2A assets are 10/20 metre rasters.  A province can intersect
    hundreds of millions of source pixels, so reading the native-resolution
    crop is both unnecessary for a regional proxy and unsafe on shared
    compute.  The source window is reduced to a deterministic maximum pixel
    budget while preserving its footprint.  This is a regional sample, not a
    parcel-level crop map, and the output records the applied scale explicitly.
    """
    with rasterio.open(_raster_uri(uri)) as src:
        geometry = transform_geom("EPSG:4326", src.crs, geometry_4326)
        try:
            window = geometry_window(src, [geometry]).round_offsets().round_lengths()
        except WindowError as exc:
            raise ValueError("Analysis zone does not overlap the selected Sentinel-2 asset.") from exc
        source_pixels = max(1, int(window.width) * int(window.height))
        sampling_scale = max(
            1.0, float(np.sqrt(source_pixels / max(1, int(max_sample_pixels))))
        )
        out_width = max(1, int(np.ceil(window.width / sampling_scale)))
        out_height = max(1, int(np.ceil(window.height / sampling_scale)))
        array = src.read(
            1,
            window=window,
            out_shape=(out_height, out_width),
            masked=True,
            resampling=resampling,
        )
        band = array.astype("float32").filled(np.nan)
        value_scale = float(src.scales[0]) if src.scales else 1.0
        offset = float(src.offsets[0]) if src.offsets else 0.0
        if apply_scale_offset and (value_scale != 1.0 or offset != 0.0):
            band = band * value_scale + offset
        transform = src.window_transform(window) * Affine.scale(
            float(window.width) / out_width,
            float(window.height) / out_height,
        )
        inside = geometry_mask(
            [geometry], out_shape=(out_height, out_width), transform=transform,
            invert=True, all_touched=False,
        )
        band[~inside] = np.nan
        return band, {
            "transform": transform,
            "crs": src.crs,
            "height": band.shape[0],
            "width": band.shape[1],
            "source_window_pixels": source_pixels,
            "sample_pixels": int(band.size),
            "sampling_scale": sampling_scale,
            "raster_value_scale": value_scale,
            "raster_value_offset": offset,
        }


def _compute_indices(
    red_uri: str,
    nir_uri: str,
    green_uri: str | None,
    blue_uri: str | None,
    scl_uri: str,
    geometry_4326: dict,
    valid_scl_classes: set[int],
    max_sample_pixels: int,
) -> dict[str, float]:
    red, profile = _read_masked_band(
        red_uri, geometry_4326, resampling=Resampling.bilinear,
        max_sample_pixels=max_sample_pixels,
        apply_scale_offset=True,
    )
    nir, nir_profile = _read_masked_band(
        nir_uri, geometry_4326, resampling=Resampling.bilinear,
        max_sample_pixels=max_sample_pixels,
        apply_scale_offset=True,
    )
    if nir.shape != red.shape or nir_profile["transform"] != profile["transform"]:
        aligned_nir = np.full(red.shape, np.nan, dtype="float32")
        reproject(
            source=nir, destination=aligned_nir,
            src_transform=nir_profile["transform"], src_crs=nir_profile["crs"],
            dst_transform=profile["transform"], dst_crs=profile["crs"],
            resampling=Resampling.bilinear,
            dst_nodata=np.nan,
        )
        nir = aligned_nir
    scl, scl_profile = _read_masked_band(
        scl_uri, geometry_4326, resampling=Resampling.nearest,
        max_sample_pixels=max_sample_pixels,
        apply_scale_offset=False,
    )
    green = None
    if green_uri:
        green, green_profile = _read_masked_band(
            green_uri, geometry_4326, resampling=Resampling.bilinear,
            max_sample_pixels=max_sample_pixels,
            apply_scale_offset=True,
        )
        if green.shape != red.shape or green_profile["transform"] != profile["transform"]:
            aligned_green = np.full(red.shape, np.nan, dtype="float32")
            reproject(
                source=green,
                destination=aligned_green,
                src_transform=green_profile["transform"],
                src_crs=green_profile["crs"],
                dst_transform=profile["transform"],
                dst_crs=profile["crs"],
                resampling=Resampling.bilinear,
                dst_nodata=np.nan,
            )
            green = aligned_green
    blue = None
    if blue_uri:
        blue, blue_profile = _read_masked_band(
            blue_uri,
            geometry_4326,
            resampling=Resampling.bilinear,
            max_sample_pixels=max_sample_pixels,
            apply_scale_offset=True,
        )
        if blue.shape != red.shape or blue_profile["transform"] != profile["transform"]:
            aligned_blue = np.full(red.shape, np.nan, dtype="float32")
            reproject(
                source=blue,
                destination=aligned_blue,
                src_transform=blue_profile["transform"],
                src_crs=blue_profile["crs"],
                dst_transform=profile["transform"],
                dst_crs=profile["crs"],
                resampling=Resampling.bilinear,
                dst_nodata=np.nan,
            )
            blue = aligned_blue
    if scl.shape != red.shape or scl_profile["transform"] != profile["transform"]:
        aligned_scl = np.full(red.shape, np.nan, dtype="float32")
        reproject(
            source=scl,
            destination=aligned_scl,
            src_transform=scl_profile["transform"],
            src_crs=scl_profile["crs"],
            dst_transform=profile["transform"],
            dst_crs=profile["crs"],
            resampling=Resampling.nearest,
            dst_nodata=np.nan,
        )
        scl = aligned_scl

    scl_codes = np.where(np.isfinite(scl), scl, -9999).astype("int16")
    valid = np.isfinite(red) & np.isfinite(nir) & np.isin(scl_codes, list(valid_scl_classes))
    denominator = nir + red
    valid &= np.abs(denominator) > 1e-6
    ndvi = np.where(valid, (nir - red) / denominator, np.nan)
    ndwi = None
    if green is not None:
        ndwi_denominator = green + nir
        ndwi_valid = valid & np.isfinite(green) & (np.abs(ndwi_denominator) > 1e-6)
        ndwi = np.where(ndwi_valid, (green - nir) / ndwi_denominator, np.nan)
    evi = None
    if blue is not None:
        evi_denominator = nir + 6.0 * red - 7.5 * blue + 1.0
        evi_valid = valid & np.isfinite(blue) & (np.abs(evi_denominator) > 1e-6)
        evi = np.where(evi_valid, 2.5 * (nir - red) / evi_denominator, np.nan)

    analysis_pixels = np.isfinite(red) & np.isfinite(nir)
    valid_count = int(np.isfinite(ndvi).sum())
    total_count = int(analysis_pixels.sum())
    if valid_count == 0:
        return {
            "ndvi_mean": np.nan, "ndvi_std": np.nan, "ndvi_p10": np.nan,
            "ndvi_p90": np.nan, "ndwi_mean": np.nan,
            "evi_mean": np.nan, "evi_std": np.nan,
            "valid_pixel_fraction": 0.0, "sample_pixel_count": total_count,
            "source_window_pixels": int(profile["source_window_pixels"]),
            "sampling_scale": float(profile["sampling_scale"]),
        }
    return {
        "ndvi_mean": float(np.nanmean(ndvi)),
        "ndvi_std": float(np.nanstd(ndvi)),
        "ndvi_p10": float(np.nanpercentile(ndvi, 10)),
        "ndvi_p90": float(np.nanpercentile(ndvi, 90)),
        "ndwi_mean": float(np.nanmean(ndwi)) if ndwi is not None and np.isfinite(ndwi).any() else np.nan,
        "evi_mean": float(np.nanmean(evi)) if evi is not None and np.isfinite(evi).any() else np.nan,
        "evi_std": float(np.nanstd(evi)) if evi is not None and np.isfinite(evi).any() else np.nan,
        "valid_pixel_fraction": valid_count / total_count if total_count else 0.0,
        "sample_pixel_count": total_count,
        "source_window_pixels": int(profile["source_window_pixels"]),
        "sampling_scale": float(profile["sampling_scale"]),
    }


def _add_leakage_safe_anomalies(frame: pd.DataFrame) -> pd.DataFrame:
    """Add vegetation anomalies using only earlier observations.

    A full-sample monthly climatology would let a scene observed after a
    forecast origin alter an older feature.  The baseline below is therefore
    an expanding zone-by-calendar-month statistic shifted by one scene.
    """
    result = frame.sort_values(["zone_code", "datetime", "item_id"]).copy()
    ok = result["status"].eq("ok")
    for prefix in ("ndvi", "evi"):
        value_column = f"{prefix}_mean"
        if value_column not in result:
            continue
        observed = pd.to_numeric(result[value_column], errors="coerce").where(ok)
        grouped = observed.groupby(
            [result["zone_code"], result["month"]], sort=False
        )
        baseline_mean = grouped.transform(
            lambda values: values.shift(1).expanding(min_periods=2).mean()
        )
        baseline_std = grouped.transform(
            lambda values: values.shift(1).expanding(min_periods=2).std()
        )
        result[f"{prefix}_monthly_baseline"] = baseline_mean
        result[f"{prefix}_monthly_baseline_std"] = baseline_std
        result[f"{prefix}_anomaly"] = result[value_column] - baseline_mean
        result[f"{prefix}_zscore"] = result[f"{prefix}_anomaly"] / baseline_std.replace(
            0, np.nan
        )
    return result.sort_index()


def extract_satellite_features(
    manifest: pd.DataFrame | str | Path,
    *,
    zones_path: str | Path,
    zone_code_col: str,
    output_base: str | Path,
    project_root: str | Path,
    valid_scl_classes: list[int] | set[int] = (4, 5),
    max_sample_pixels: int = 262_144,
    extract_workers: int = 1,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    scenes = manifest.copy() if isinstance(manifest, pd.DataFrame) else (
        pd.read_parquet(manifest) if Path(manifest).suffix == ".parquet" else pd.read_csv(manifest)
    )
    access_mode = configure_asset_access(project_root, scenes)
    zones = gpd.read_file(zones_path).to_crs(4326)
    if zone_code_col not in zones:
        raise ValueError(f"Zone file does not contain {zone_code_col}")
    zone_map = {str(row[zone_code_col]): row.geometry.__geo_interface__ for _, row in zones.iterrows()}
    valid_classes = set(map(int, valid_scl_classes))

    def process_record(record: dict[str, Any]) -> dict[str, Any]:
        code = str(record["zone_code"])
        geometry = zone_map.get(code)
        if geometry is None:
            return {**record, "status": "missing_zone_geometry"}
        required = [record.get("red_uri"), record.get("nir_uri"), record.get("scl_uri")]
        if any(pd.isna(value) or not value for value in required):
            return {**record, "status": "missing_asset"}
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                features = _compute_indices(
                    str(record["red_uri"]), str(record["nir_uri"]),
                    None if pd.isna(record.get("green_uri")) else str(record.get("green_uri")),
                    None if pd.isna(record.get("blue_uri")) else str(record.get("blue_uri")),
                    str(record["scl_uri"]), geometry, valid_classes,
                    int(max_sample_pixels),
                )
                return {
                    **record,
                    **features,
                    "asset_access_mode": access_mode,
                    "extraction_attempts": attempt,
                    "status": "ok",
                }
            except Exception as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(min(8, 2 ** attempt))
        return {
            **record,
            "asset_access_mode": access_mode,
            "extraction_attempts": 4,
            "status": "error",
            "error": repr(last_error),
        }

    records = scenes.to_dict("records")
    checkpoint = Path(output_base).with_name(
        Path(output_base).name + "_checkpoint.parquet"
    )
    rows: list[dict[str, Any]] = []
    completed: set[tuple[str, str]] = set()
    expected = {
        (str(record.get("zone_code")), str(record.get("item_id")))
        for record in records
    }
    if checkpoint.exists() and checkpoint.stat().st_size > 0:
        checkpoint_frame = pd.read_parquet(checkpoint).drop_duplicates(
            ["zone_code", "item_id"], keep="last"
        )
        rows = [
            row
            for row in checkpoint_frame.to_dict("records")
            if (str(row.get("zone_code")), str(row.get("item_id"))) in expected
            and str(row.get("status")) != "error"
        ]
        completed = {
            (str(row.get("zone_code")), str(row.get("item_id"))) for row in rows
        }
    pending = [
        record
        for record in records
        if (str(record.get("zone_code")), str(record.get("item_id"))) not in completed
    ]
    worker_count = max(1, min(int(extract_workers), len(pending) or 1))

    def write_checkpoint() -> None:
        if not rows:
            return
        temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
        pd.DataFrame(rows).to_parquet(temporary, index=False)
        temporary.replace(checkpoint)

    progress = tqdm(
        total=len(records),
        initial=len(rows),
        desc="Sentinel-2 features",
    )
    try:
        if worker_count == 1:
            for index, record in enumerate(pending, start=1):
                rows.append(process_record(record))
                progress.update(1)
                if index % 20 == 0:
                    write_checkpoint()
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(process_record, record) for record in pending]
                for index, future in enumerate(as_completed(futures), start=1):
                    rows.append(future.result())
                    progress.update(1)
                    if index % 20 == 0:
                        write_checkpoint()
        write_checkpoint()
    finally:
        progress.close()

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce", utc=True)
        frame["date"] = frame["datetime"].dt.tz_convert(None).dt.normalize()
        frame["month"] = frame["datetime"].dt.month
        frame = _add_leakage_safe_anomalies(frame)
        frame["satellite_quality"] = np.select(
            [frame["status"].ne("ok"), frame["valid_pixel_fraction"].lt(0.25)],
            [frame["status"], "low_valid_pixels"],
            default="ok",
        )
        frame = frame.sort_values(
            ["zone_code", "date", "item_id"], na_position="last"
        ).reset_index(drop=True)
    outputs = save_frame(frame, output_base, save_csv=save_csv, save_parquet=save_parquet)
    checkpoint.unlink(missing_ok=True)
    return frame, outputs
