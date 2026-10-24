"""ERA5-Land monthly download and province-day aggregation."""
from __future__ import annotations

import calendar
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

import cdsapi
import geopandas as gpd
import numpy as np
import pandas as pd
import regionmask
import xarray as xr

from ..credentials import load_project_credentials
from ..utils import save_frame, save_json

DEFAULT_VARIABLES = [
    "2m_temperature",
    "total_precipitation",
    "volumetric_soil_water_layer_1",
    "surface_solar_radiation_downwards",
]


def _normalize_netcdf_payload(path: Path) -> bool:
    """Replace a CDS ZIP response with its sole NetCDF member in place.

    CDS occasionally returns a ZIP container even when ``unarchived`` NetCDF
    is requested.  The target still receives a ``.nc`` suffix, so relying on
    that suffix can publish an unreadable raw artifact.  Return ``True`` when
    normalization was required.
    """
    if not zipfile.is_zipfile(path):
        return False
    unpacked = path.with_suffix(path.suffix + ".unpacked")
    unpacked.unlink(missing_ok=True)
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.namelist()
            if not member.endswith("/") and member.lower().endswith(".nc")
        ]
        if not members:
            raise ValueError(f"No NetCDF member found in {path}")
        if len(members) == 1:
            with archive.open(members[0]) as source, unpacked.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
        else:
            # CDS can split requested variables into multiple aligned NetCDF
            # members (for example soil moisture in one member and the other
            # fields in another).  Merge only disjoint variables on exactly
            # matching time/spatial coordinates; never concatenate or align
            # approximately.
            with tempfile.TemporaryDirectory(dir=path.parent) as directory:
                member_paths: list[Path] = []
                for index, member in enumerate(sorted(members)):
                    member_path = Path(directory) / f"member_{index}.nc"
                    with archive.open(member) as source, member_path.open("wb") as destination:
                        shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
                    member_paths.append(member_path)
                datasets: list[xr.Dataset] = []
                seen_variables: set[str] = set()
                try:
                    for member_path in member_paths:
                        dataset = xr.open_dataset(member_path)
                        source_variables = list(dataset.data_vars)
                        duplicate = seen_variables.intersection(source_variables)
                        if duplicate:
                            raise ValueError(
                                f"Duplicate variables in CDS ZIP members: {sorted(duplicate)}"
                            )
                        seen_variables.update(source_variables)
                        if "expver" in dataset.coords:
                            # Variable groups can legitimately move from final
                            # (0001) to preliminary (0005) data at different
                            # timestamps.  Preserve that exact per-time
                            # provenance beside each source variable rather
                            # than overriding a conflicting shared coordinate.
                            expver = dataset.coords["expver"]
                            dataset = dataset.drop_vars("expver")
                            for variable in source_variables:
                                dataset[f"source_expver_{variable}"] = (
                                    expver.dims,
                                    expver.values,
                                )
                        datasets.append(dataset)
                    merged = xr.merge(datasets, join="exact", compat="identical")
                    merged.to_netcdf(unpacked, engine="netcdf4")
                finally:
                    for dataset in datasets:
                        dataset.close()
    unpacked.replace(path)
    return True


def _valid_netcdf(path: Path, *, minimum_timestamps: int) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with xr.open_dataset(path) as dataset:
            coordinate = "valid_time" if "valid_time" in dataset.coords else "time"
            return bool(
                coordinate in dataset.coords
                and dataset[coordinate].size >= int(minimum_timestamps)
                and len(dataset.data_vars) > 0
            )
    except Exception:
        return False


def build_cds_client(project_root: str | Path) -> cdsapi.Client:
    settings = load_project_credentials(required=("CDS_API_KEY",), project_root=project_root)
    return cdsapi.Client(
        url=settings.get("CDS_API_URL") or "https://cds.climate.copernicus.eu/api",
        key=settings["CDS_API_KEY"],
    )


def month_range(start_date: str, end_date: str) -> list[pd.Period]:
    return list(pd.period_range(pd.Timestamp(start_date).to_period("M"), pd.Timestamp(end_date).to_period("M"), freq="M"))


def download_era5_month(
    period: pd.Period,
    *,
    output_dir: str | Path,
    area: list[float],
    variables: list[str],
    project_root: str | Path,
    overwrite: bool = False,
) -> Path:
    output = Path(output_dir) / f"era5_land_{period.year}_{period.month:02d}.nc"
    output.parent.mkdir(parents=True, exist_ok=True)
    expected_timestamps = calendar.monthrange(period.year, period.month)[1] * 24
    if _valid_netcdf(output, minimum_timestamps=expected_timestamps) and not overwrite:
        return output
    days = [f"{day:02d}" for day in range(1, calendar.monthrange(period.year, period.month)[1] + 1)]
    request = {
        "variable": variables,
        "year": str(period.year),
        "month": f"{period.month:02d}",
        "day": days,
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [float(value) for value in area],
    }
    temporary = output.with_suffix(output.suffix + ".download")
    temporary.unlink(missing_ok=True)
    build_cds_client(project_root).retrieve(
        "reanalysis-era5-land", request, str(temporary)
    )
    _normalize_netcdf_payload(temporary)
    if not _valid_netcdf(temporary, minimum_timestamps=expected_timestamps):
        raise ValueError(f"CDS returned an incomplete ERA5-Land month: {period}")
    temporary.replace(output)
    return output


def download_era5_range(
    start_date: str,
    end_date: str,
    *,
    output_dir: str | Path,
    area: list[float],
    variables: list[str] | None,
    project_root: str | Path,
    overwrite: bool = False,
) -> list[Path]:
    files = [
        download_era5_month(
            period,
            output_dir=output_dir,
            area=area,
            variables=variables or DEFAULT_VARIABLES,
            project_root=project_root,
            overwrite=overwrite,
        )
        for period in month_range(start_date, end_date)
    ]
    # ERA5-Land accumulations stamped at 00:00 contain the total for the
    # previous UTC day.  Fetch one boundary record so the final requested day
    # has precipitation and radiation values without downloading another month.
    boundary_date = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    boundary = Path(output_dir) / f"era5_land_boundary_{boundary_date:%Y_%m_%d}.nc"
    if not _valid_netcdf(boundary, minimum_timestamps=1):
        request = {
            "variable": variables or DEFAULT_VARIABLES,
            "year": f"{boundary_date.year:04d}",
            "month": f"{boundary_date.month:02d}",
            "day": [f"{boundary_date.day:02d}"],
            "time": ["00:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": [float(value) for value in area],
        }
        temporary = boundary.with_suffix(boundary.suffix + ".download")
        temporary.unlink(missing_ok=True)
        build_cds_client(project_root).retrieve(
            "reanalysis-era5-land", request, str(temporary)
        )
        _normalize_netcdf_payload(temporary)
        if not _valid_netcdf(temporary, minimum_timestamps=1):
            raise ValueError(
                f"CDS returned an incomplete ERA5-Land boundary: {boundary_date.date()}"
            )
        temporary.replace(boundary)
    files.append(boundary)
    return files


def _normalize_dimensions(dataset: xr.Dataset) -> xr.Dataset:
    rename: dict[str, str] = {}
    if "valid_time" in dataset.dims or "valid_time" in dataset.coords:
        rename["valid_time"] = "time"
    if "latitude" in dataset.dims or "latitude" in dataset.coords:
        rename["latitude"] = "lat"
    if "longitude" in dataset.dims or "longitude" in dataset.coords:
        rename["longitude"] = "lon"
    if rename:
        dataset = dataset.rename(rename)
    if "expver" in dataset.dims:
        dataset = dataset.max("expver", skipna=True)
    if float(dataset.lat.values[0]) > float(dataset.lat.values[-1]):
        dataset = dataset.sortby("lat")
    return dataset


def _find_var(dataset: xr.Dataset, candidates: list[str]) -> xr.DataArray:
    for name in candidates:
        if name in dataset:
            return dataset[name]
    raise KeyError(f"Variables {candidates} unavailable. Found: {list(dataset.data_vars)}")


def daily_weather_dataset(
    dataset: xr.Dataset, *, accumulations_only: bool = False
) -> xr.Dataset:
    ds = _normalize_dimensions(dataset)
    temperature = _find_var(ds, ["t2m", "2m_temperature"])
    precipitation = _find_var(ds, ["tp", "total_precipitation"])
    soil = _find_var(ds, ["swvl1", "volumetric_soil_water_layer_1"])
    radiation = _find_var(ds, ["ssrd", "surface_solar_radiation_downwards"])

    def previous_day_accumulation(values: xr.DataArray) -> xr.DataArray:
        midnight = values.where(values.time.dt.hour == 0, drop=True)
        return midnight.assign_coords(time=midnight.time - np.timedelta64(1, "D"))

    result = xr.Dataset(
        {
            "temperature_c_mean": temperature.resample(time="1D").mean() - 273.15,
            "temperature_c_min": temperature.resample(time="1D").min() - 273.15,
            "temperature_c_max": temperature.resample(time="1D").max() - 273.15,
            "rainfall_mm_sum": previous_day_accumulation(precipitation) * 1000.0,
            "soil_moisture_layer1_mean": soil.resample(time="1D").mean(),
            "solar_radiation_mj_m2_sum": previous_day_accumulation(radiation)
            / 1_000_000.0,
        }
    )
    if accumulations_only:
        # A segment-boundary file contains only the next day's 00:00 record.
        # That record completes the previous day's accumulated precipitation
        # and radiation, but it cannot represent a full daily temperature or
        # soil-moisture statistic.  Keep only the two scientifically valid
        # prior-day accumulations from such files.
        for variable in (
            "temperature_c_mean",
            "temperature_c_min",
            "temperature_c_max",
            "soil_moisture_layer1_mean",
        ):
            result[variable] = xr.full_like(result[variable], np.nan)
    return result


def aggregate_era5_to_provinces(
    netcdf_paths: list[str | Path],
    *,
    provinces_path: str | Path,
    province_code_col: str,
    province_name_col: str,
    output_base: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
    metadata_path: str | Path | None = None,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    provinces = gpd.read_file(provinces_path).to_crs(4326).reset_index(drop=True)
    required = {province_code_col, province_name_col}
    missing = required.difference(provinces.columns)
    if missing:
        raise ValueError(f"Province boundary file misses columns: {sorted(missing)}")
    provinces[province_code_col] = provinces[province_code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)

    masks = None
    weights = None
    rows: list[pd.DataFrame] = []
    for path in sorted(map(Path, netcdf_paths)):
        with xr.open_dataset(path) as raw:
            daily = daily_weather_dataset(
                raw,
                accumulations_only=path.name.startswith("era5_land_boundary_"),
            ).load()
        if masks is None:
            masks = regionmask.mask_3D_geopandas(provinces, daily.lon, daily.lat)
            weights = np.cos(np.deg2rad(daily.lat))
        month_frame: pd.DataFrame | None = None
        for variable in daily.data_vars:
            data = daily[variable]
            numerator = (data * masks * weights).sum(dim=("lat", "lon"), skipna=True)
            denominator = (masks * weights).where(data.notnull()).sum(dim=("lat", "lon"), skipna=True)
            regional = (numerator / denominator).to_dataframe(name=variable).reset_index()
            # ERA5 NetCDFs may expose scalar coordinates such as ``number``
            # and ``expver``.  They are provenance coordinates, not join
            # keys; carrying them into every variable frame creates duplicate
            # columns on the second/third merge under modern pandas.
            regional = regional[["time", "region", variable]]
            month_frame = regional if month_frame is None else month_frame.merge(regional, on=["time", "region"], how="outer")
        assert month_frame is not None
        month_frame["province_code"] = month_frame["region"].map(lambda i: str(provinces.iloc[int(i)][province_code_col]).zfill(2))
        month_frame["province_name"] = month_frame["region"].map(lambda i: str(provinces.iloc[int(i)][province_name_col]))
        month_frame = month_frame.rename(columns={"time": "date"}).drop(columns=["region"])
        month_frame["weather_grid_coverage"] = month_frame[[
            "temperature_c_mean", "rainfall_mm_sum", "soil_moisture_layer1_mean", "solar_radiation_mj_m2_sum"
        ]].notna().mean(axis=1)
        rows.append(month_frame)

    result = pd.concat(rows, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    value_columns = [
        "temperature_c_mean",
        "temperature_c_min",
        "temperature_c_max",
        "rainfall_mm_sum",
        "soil_moisture_layer1_mean",
        "solar_radiation_mj_m2_sum",
    ]
    # Instantaneous fields and prior-day accumulations can arrive from
    # adjacent monthly files on separate rows. Consolidate them deterministically.
    result = (
        result.groupby(
            ["province_code", "province_name", "date"], as_index=False, dropna=False
        )[[column for column in value_columns if column in result]]
        .first()
        .sort_values(["province_code", "date"])
        .reset_index(drop=True)
    )
    if start_date:
        result = result[result["date"].ge(pd.Timestamp(start_date).normalize())]
    if end_date:
        result = result[result["date"].le(pd.Timestamp(end_date).normalize())]
    result = result.reset_index(drop=True)
    result["weather_grid_coverage"] = result[[
        "temperature_c_mean",
        "rainfall_mm_sum",
        "soil_moisture_layer1_mean",
        "solar_radiation_mj_m2_sum",
    ]].notna().mean(axis=1)
    result["weather_status"] = np.where(result["weather_grid_coverage"].ge(0.75), "ok", "partial")
    result["weather_source"] = "ERA5-Land hourly data"
    result["weather_day_timezone"] = "UTC"
    result["accumulation_convention"] = "next_day_00utc_previous_24h"
    result["spatial_aggregation"] = "latitude_cosine_area_weighted_province_mean"
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    if metadata_path is not None:
        project_root = Path(output_base).resolve().parents[2]
        files = []
        for path in sorted(map(Path, netcdf_paths)):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            files.append(
                {
                    "path": (
                        str(path.resolve().relative_to(project_root))
                        if path.resolve().is_relative_to(project_root)
                        else str(path.resolve())
                    ),
                    "bytes": path.stat().st_size,
                    "sha256": digest.hexdigest(),
                }
            )
        metadata_output = Path(metadata_path)
        save_json(
            {
                "source": "ERA5-Land hourly data",
                "date_range": [
                    str(result["date"].min().date()),
                    str(result["date"].max().date()),
                ],
                "rows": len(result),
                "province_count": int(result["province_code"].nunique()),
                "accumulation_convention": "next_day_00utc_previous_24h",
                "weather_day_timezone": "UTC",
                "spatial_aggregation": "latitude_cosine_area_weighted_province_mean",
                "source_files": files,
            },
            metadata_output,
        )
        outputs["metadata"] = metadata_output
    return result, outputs
