from __future__ import annotations

from pathlib import Path
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.transform import from_bounds
from shapely.geometry import box, mapping

from experiments.pasarpulse_multimodal_ablation import (
    FULL_PERIOD_AUDIT_COLUMNS,
    PRICE_FEATURES,
)
from src.pasarpulse.tools.graph import (
    _best_lead_lag,
    _best_lead_lag_matrix,
    build_static_graph,
)
from src.pasarpulse.tools.merge import (
    _merge_production,
    _merge_official_markets,
    _merge_satellite,
    _merge_transport,
    _merge_weather,
)
from src.pasarpulse.tools.satellite import (
    _add_leakage_safe_anomalies,
    _compute_indices,
)
from src.pasarpulse.tools.official_markets import parse_operating_days_per_week
from src.pasarpulse.tools.weather import (
    _normalize_netcdf_payload,
    daily_weather_dataset,
)


def test_full_period_coverage_is_not_a_replay_feature() -> None:
    assert FULL_PERIOD_AUDIT_COLUMNS.isdisjoint(PRICE_FEATURES)


def test_era5_land_accumulations_use_following_midnight() -> None:
    times = pd.date_range("2024-01-01", periods=48, freq="h")
    shape = (len(times), 1, 1)
    precipitation = np.zeros(shape, dtype="float32")
    radiation = np.zeros(shape, dtype="float32")
    precipitation[0, 0, 0] = 0.011  # Dec 31 total, not Jan 1.
    precipitation[24, 0, 0] = 0.020  # Jan 1 total, stamped Jan 2 00:00.
    radiation[24, 0, 0] = 18_000_000.0
    dataset = xr.Dataset(
        {
            "t2m": (("time", "lat", "lon"), np.full(shape, 300.0)),
            "tp": (("time", "lat", "lon"), precipitation),
            "swvl1": (("time", "lat", "lon"), np.full(shape, 0.3)),
            "ssrd": (("time", "lat", "lon"), radiation),
        },
        coords={"time": times, "lat": [-6.0], "lon": [106.8]},
    )

    daily = daily_weather_dataset(dataset)

    assert float(daily["rainfall_mm_sum"].sel(time="2024-01-01").item()) == 20.0
    assert float(daily["solar_radiation_mj_m2_sum"].sel(time="2024-01-01").item()) == 18.0

    boundary = daily_weather_dataset(dataset, accumulations_only=True)
    assert bool(boundary["temperature_c_mean"].isnull().all())
    assert bool(boundary["soil_moisture_layer1_mean"].isnull().all())
    assert float(boundary["rainfall_mm_sum"].sel(time="2024-01-01").item()) == 20.0
    assert float(boundary["solar_radiation_mj_m2_sum"].sel(time="2024-01-01").item()) == 18.0


def test_cds_zip_payload_is_normalized_to_netcdf(tmp_path: Path) -> None:
    source_a = tmp_path / "source_a.nc"
    source_b = tmp_path / "source_b.nc"
    payload = tmp_path / "target.nc"
    coordinates = {
        "time": [pd.Timestamp("2026-06-01")],
        "lat": [0.0],
        "lon": [0.0],
    }
    xr.Dataset(
        {"t2m": (("time", "lat", "lon"), np.ones((1, 1, 1)))},
        coords={**coordinates, "expver": ("time", ["0001"])},
    ).to_netcdf(source_a)
    xr.Dataset(
        {"swvl1": (("time", "lat", "lon"), np.full((1, 1, 1), 0.3))},
        coords={**coordinates, "expver": ("time", ["0005"])},
    ).to_netcdf(source_b)
    with zipfile.ZipFile(payload, "w") as archive:
        archive.write(source_a, "data_0.nc")
        archive.write(source_b, "data_1.nc")

    assert _normalize_netcdf_payload(payload)
    assert not zipfile.is_zipfile(payload)
    with xr.open_dataset(payload) as dataset:
        assert dataset.sizes["time"] == 1
        assert set(dataset.data_vars) == {
            "t2m",
            "swvl1",
            "source_expver_t2m",
            "source_expver_swvl1",
        }
        assert dataset["source_expver_t2m"].item() == "0001"
        assert dataset["source_expver_swvl1"].item() == "0005"


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    value_scale: float = 1.0,
    value_offset: float = 0.0,
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        crs="EPSG:4326",
        transform=from_bounds(0, 0, 1, 1, values.shape[1], values.shape[0]),
    ) as dataset:
        dataset.write(values, 1)
        dataset.scales = (value_scale,)
        dataset.offsets = (value_offset,)


def test_satellite_reads_bounded_calibrated_sample(tmp_path: Path) -> None:
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    green = tmp_path / "green.tif"
    scl = tmp_path / "scl.tif"
    _write_raster(red, np.full((100, 100), 1_000, dtype="uint16"), value_scale=0.0001, value_offset=-0.1)
    _write_raster(nir, np.full((100, 100), 2_000, dtype="uint16"), value_scale=0.0001, value_offset=-0.1)
    _write_raster(green, np.full((100, 100), 1_500, dtype="uint16"), value_scale=0.0001, value_offset=-0.1)
    _write_raster(scl, np.full((100, 100), 4, dtype="uint8"))

    result = _compute_indices(
        str(red),
        str(nir),
        str(green),
        str(red),
        str(scl),
        mapping(box(0, 0, 1, 1)),
        {4, 5},
        max_sample_pixels=400,
    )

    assert result["source_window_pixels"] == 10_000
    assert result["sample_pixel_count"] <= 400
    assert np.isclose(result["ndvi_mean"], 1.0, atol=1e-5)
    assert np.isclose(result["evi_mean"], 2.5 / 11.0, atol=1e-5)
    assert result["valid_pixel_fraction"] == 1.0


def test_osm_context_is_unavailable_before_snapshot() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "date": pd.to_datetime(["2025-12-31", "2026-01-02"]),
        }
    )
    transport = pd.DataFrame(
        {
            "province_code": ["01"],
            "snapshot_date": ["2026-01-01"],
            "major_road_length_km": [123.0],
            "ferry_length_km": [4.0],
            "ferry_terminal_count": [1],
            "port_count": [2],
            "marketplace_count": [3],
        }
    )

    merged = _merge_transport(panel, transport).sort_values("date")

    assert merged.iloc[0]["graph_status"] == "missing"
    assert pd.isna(merged.iloc[0]["major_road_length_km"])
    assert merged.iloc[1]["graph_status"] == "available"
    assert merged.iloc[1]["major_road_length_km"] == 123.0


def test_official_market_context_respects_service_effective_date() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "date": pd.to_datetime(["2024-07-03", "2024-07-04"]),
        }
    )
    context = pd.DataFrame(
        {
            "province_code": ["01"],
            "market_context_effective_date": np.array(
                ["2024-07-04"], dtype="datetime64[ms]"
            ),
            "official_market_count": [12],
            "official_market_days_per_week_mean": [5.0],
        }
    )
    merged = _merge_official_markets(panel, context)

    assert merged.iloc[0]["official_market_context_status"] == "missing"
    assert merged.iloc[1]["official_market_context_status"] == "available"
    assert merged.iloc[1]["official_market_count"] == 12


def test_official_market_frequency_parser_is_conservative() -> None:
    assert parse_operating_days_per_week("Setiap Hari") == 7
    assert parse_operating_days_per_week("2 Hari Seminggu") == 2
    assert np.isnan(parse_operating_days_per_week("06.00 - 16.00"))


def test_weather_respects_publication_lag() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
        }
    )
    weather = pd.DataFrame(
        {
            "province_code": ["01"],
            "date": ["2026-01-01"],
            "temperature_c_mean": [27.0],
            "rainfall_mm_sum": [2.0],
            "soil_moisture_layer1_mean": [0.3],
            "solar_radiation_mj_m2_sum": [18.0],
        }
    )

    merged = _merge_weather(panel, weather, publication_lag_days=5, max_carry_days=10)

    assert merged.iloc[0]["weather_status"] == "missing"
    assert pd.isna(merged.iloc[0]["temperature_c_mean"])
    assert merged.iloc[1]["weather_status"] == "fresh"
    assert merged.iloc[1]["weather_observation_age_days"] == 5


def test_production_respects_official_release_date() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "commodity_code": ["CRM", "CRM"],
            "date": pd.to_datetime(["2026-06-11", "2026-06-12"]),
        }
    )
    production = pd.DataFrame(
        {
            "province_code": ["01"],
            "commodity_code": ["CRM"],
            "year": [2025],
            "production_effective_date": ["2026-06-12"],
            "production_kg": [1_000.0],
            "harvested_area_ha": [10.0],
            "productivity_kg_per_ha": [100.0],
            "quality_flag": ["ok"],
        }
    )

    merged = _merge_production(panel, production, max_age_years=3)

    assert merged.iloc[0]["production_status"] == "missing"
    assert pd.isna(merged.iloc[0]["production_kg"])
    assert merged.iloc[1]["production_status"] == "fresh"
    assert merged.iloc[1]["production_kg"] == 1_000.0


def test_satellite_scene_is_not_available_at_acquisition_instant() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        }
    )
    satellite = pd.DataFrame(
        {
            "zone_code": ["01"],
            "date": ["2026-01-01"],
            "status": ["ok"],
            "satellite_quality": ["ok"],
            "ndvi_mean": [0.5],
            "evi_mean": [0.3],
            "ndwi_mean": [-0.1],
        }
    )

    merged = _merge_satellite(
        panel, satellite, max_carry_days=24, publication_lag_days=1
    )

    assert merged.iloc[0]["satellite_status"] == "missing"
    assert pd.isna(merged.iloc[0]["ndvi_mean"])
    assert merged.iloc[1]["satellite_status"] == "fresh"


def test_satellite_prefers_stac_publication_timestamp() -> None:
    panel = pd.DataFrame(
        {
            "province_code": ["01", "01"],
            "date": pd.to_datetime(["2026-01-02", "2026-01-03"]),
        }
    )
    satellite = pd.DataFrame(
        {
            "zone_code": ["01"],
            "date": ["2026-01-01"],
            "created": ["2026-01-03T02:00:00Z"],
            "status": ["ok"],
            "satellite_quality": ["ok"],
            "ndvi_mean": [0.5],
        }
    )

    merged = _merge_satellite(
        panel, satellite, max_carry_days=24, publication_lag_days=1
    )

    assert merged.iloc[0]["satellite_status"] == "missing"
    assert merged.iloc[1]["satellite_status"] == "fresh"


def test_satellite_anomaly_does_not_use_future_scenes() -> None:
    base = pd.DataFrame(
        {
            "zone_code": ["01", "01", "01"],
            "item_id": ["a", "b", "c"],
            "datetime": pd.to_datetime(
                ["2024-01-01", "2025-01-01", "2026-01-01"], utc=True
            ),
            "month": [1, 1, 1],
            "status": ["ok", "ok", "ok"],
            "ndvi_mean": [0.2, 0.4, 0.9],
        }
    )
    without_future = _add_leakage_safe_anomalies(base.iloc[:2]).iloc[-1]
    with_future = _add_leakage_safe_anomalies(base).iloc[1]

    assert pd.isna(with_future["ndvi_anomaly"])
    assert pd.isna(without_future["ndvi_anomaly"])
    # Once two prior January scenes exist, only those two define 2026.
    complete = _add_leakage_safe_anomalies(base).iloc[2]
    assert np.isclose(complete["ndvi_monthly_baseline"], 0.3)


def test_osm_edge_augments_static_candidate_graph(tmp_path: Path) -> None:
    provinces = gpd.GeoDataFrame(
        {
            "province_code": ["01", "02"],
            "province_name": ["Alpha", "Beta"],
            "geometry": [box(0, 0, 1, 1), box(3, 0, 4, 1)],
        },
        crs="EPSG:4326",
    )
    province_path = tmp_path / "provinces.geojson"
    provinces.to_file(province_path, driver="GeoJSON")
    transport_edges = pd.DataFrame(
        {
            "source_province_code": ["01"],
            "target_province_code": ["02"],
            "edge_type": ["ferry_connection"],
            "segment_count": [2],
            "length_km": [50.0],
            "snapshot_date": ["2026-01-01"],
        }
    )

    graph, _ = build_static_graph(
        province_path,
        province_code_col="province_code",
        province_name_col="province_name",
        production=pd.DataFrame(),
        transport_edges=transport_edges,
        output_base=tmp_path / "graph",
        knn=0,
        save_csv=True,
        save_parquet=False,
    )

    assert len(graph) == 1
    assert graph.iloc[0]["edge_type"] == "osm_transport_candidate"
    assert graph.iloc[0]["osm_transport_connection"] == 1
    assert graph.iloc[0]["osm_ferry_length_km"] == 50.0
    assert graph.iloc[0]["candidate_connectivity_only"] == 1


def test_vectorized_lead_lag_matches_reference() -> None:
    rng = np.random.default_rng(2026)
    source = rng.normal(size=90)
    target = np.concatenate([np.full(3, np.nan), source[:-3]])
    noise = rng.normal(size=90)
    values = np.column_stack([source, target, noise])

    lag_matrix, corr_matrix, overlap_matrix = _best_lead_lag_matrix(
        values, max_lag=7, min_overlap=30
    )
    for source_index in range(values.shape[1]):
        for target_index in range(values.shape[1]):
            if source_index == target_index:
                continue
            lag, corr, overlap = _best_lead_lag(
                pd.Series(values[:, source_index]),
                pd.Series(values[:, target_index]),
                max_lag=7,
                min_overlap=30,
            )
            assert lag_matrix[source_index, target_index] == lag
            assert np.isclose(corr_matrix[source_index, target_index], corr)
            assert overlap_matrix[source_index, target_index] == overlap
