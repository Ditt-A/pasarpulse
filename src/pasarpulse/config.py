"""YAML-backed configuration for the PasarPulse-MM data pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


DEFAULTS: dict[str, Any] = {
    "project": {
        "start_date": "2023-01-01",
        "end_date": "2026-07-31",
        "timezone": "Asia/Jakarta",
        "fail_fast": False,
        "save_csv": True,
        "save_parquet": True,
        "random_seed": 42,
    },
    "stages": {
        "references": True,
        "prices": True,
        "price_baselines": True,
        "bps": True,
        "era5_download": False,
        "era5_aggregate": True,
        "sentinel_search": False,
        "sentinel_extract": False,
        "calendar": True,
        "official_markets": True,
        "osm_transport": False,
        "static_graph": True,
        "dynamic_graph": True,
        "merge": True,
        "quality": True,
        "visualization": True,
    },
    "paths": {
        "data_root": "data",
        "reports_root": "reports",
        "logs_root": "logs",
        "province_boundaries": "data/reference/indonesia_provinces.geojson",
        "satellite_zones": "data/reference/satellite_zones.geojson",
        "calendar_events": "data/manual/calendar_events.csv",
        "official_thresholds": "data/manual/official_thresholds.csv",
    },
    "references": {
        "big_endpoint": "https://geoservices.big.go.id/rbi/rest/services/BATASWILAYAH/BATAS_WILAYAH/MapServer/12/query",
        "expected_province_count": 38,
        "overwrite": False,
    },
    "prices": {
        "source": "sp2kp",
        "inputs": [],
        "sp2kp": {
            "dataset_id": "6ea910f4-4b55-422b-80d7-8346c2aae076",
            "dataset_page_url": "https://data.go.id/dataset/dataset/tingkat-harga-daerah",
            "catalog_api_urls": [
                "https://katalog.data.go.id/api/3/action/package_show",
                "https://katalog.data.go.id/api/action/package_show",
                "https://data.go.id/api/3/action/package_show",
            ],
            "overwrite_downloads": False,
            "timeout_seconds": 180,
        },
        "pihps": {
            "endpoint": "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataKomoditas",
            "page_url": "https://www.bi.go.id/hargapangan/TabelHarga/PedagangBesarKomoditas",
            "timeout_seconds": 90,
            "overwrite_snapshots": False,
            "commodities": {
                "BM": {"source_id": "com_11", "source_name": "Bawang Merah"},
                "CMK": {"source_id": "com_14", "source_name": "Cabai Merah Keriting"},
                "CRM": {"source_id": "com_16", "source_name": "Cabai Rawit Merah"},
            },
            "market_types": {"retail": 1, "wholesale": 3, "producer": 4},
        },
        "baselines": {
            "min_train_days": 365,
        },
        "min_months": 24,
        "min_coverage": 0.80,
        "scheduled_days": "business",
        "bounded_ffill_days": 3,
        "shock_threshold": 0.10,
    },
    "bps": {
        "years": [2023, 2024, 2025],
        "headless": True,
        "timeout_seconds": 60,
    },
    "era5": {
        "area": [6.5, 94.0, -11.5, 141.5],
        "variables": [
            "2m_temperature",
            "total_precipitation",
            "volumetric_soil_water_layer_1",
            "surface_solar_radiation_downwards",
        ],
        "province_code_col": "province_code",
        "province_name_col": "province_name",
    },
    "sentinel2": {
        "stac_url": "https://stac.dataspace.copernicus.eu/v1/",
        "collection": "sentinel-2-l2a",
        "zone_code_col": "province_code",
        "zone_name_col": "province_name",
        "max_cloud_cover": 30.0,
        "search_workers": 4,
        "extract_workers": 4,
        "period_days": 16,
        "max_carry_days": 24,
        "max_sample_pixels": 262144,
        "valid_scl_classes": [4, 5],
    },
    "calendar": {
        "national_region_code": "NATIONAL",
    },
    "official_markets": {
        "layer_url": "https://kspservices.big.go.id/satupeta/rest/services/PUBLIK/SARANA_PRASARANA/MapServer/28",
        "minimum_expected_features": 600,
        "nearest_join_max_km": 30.0,
        "timeout_seconds": 120,
    },
    "graph": {
        "osm_snapshot_url": "https://download.geofabrik.de/asia/indonesia-260101.osm.pbf",
        "osm_snapshot_date": "2026-01-01",
        "osm_overwrite": False,
        "osm_download_workers": 8,
        "static_knn": 3,
        "dynamic_window_days": 90,
        "dynamic_snapshot_freq": "MS",
        "dynamic_max_lag_days": 7,
        "dynamic_min_overlap": 30,
        "dynamic_top_k": 5,
    },
    "merge": {
        "eligible_only_default": True,
        "production_max_age_years": 3,
        "weather_publication_lag_days": 5,
        "weather_max_carry_days": 10,
        "satellite_publication_lag_days": 1,
    },
    "visualization": {
        "example_province": "",
        "example_commodity": "CRM",
        "example_market_level": "retail",
        "top_n_production": 12,
    },
}


@dataclass(slots=True)
class PipelineConfig:
    """Resolved pipeline configuration.

    ``raw`` keeps the complete nested configuration while ``project_root`` is
    used to resolve every relative file path consistently in notebooks, scripts,
    and VM sessions.
    """

    raw: dict[str, Any]
    project_root: Path
    config_path: Path | None = None
    _resolved_cache: dict[str, Path] = field(default_factory=dict, init=False)

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        if not isinstance(value, dict):
            raise TypeError(f"Configuration section '{name}' must be a mapping.")
        return value

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def stage_enabled(self, name: str) -> bool:
        return bool(self.get(f"stages.{name}", False))

    def resolve(self, value: str | Path | None) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (self.project_root / path).resolve()

    @property
    def data_root(self) -> Path:
        return self.resolve(self.get("paths.data_root", "data"))  # type: ignore[return-value]

    @property
    def reports_root(self) -> Path:
        return self.resolve(self.get("paths.reports_root", "reports"))  # type: ignore[return-value]

    @property
    def logs_root(self) -> Path:
        return self.resolve(self.get("paths.logs_root", "logs"))  # type: ignore[return-value]

    def path(self, key: str, default: str | None = None) -> Path | None:
        return self.resolve(self.get(f"paths.{key}", default))

    def ensure_directories(self) -> None:
        directories = [
            self.data_root / "raw",
            self.data_root / "interim",
            self.data_root / "processed",
            self.data_root / "ready",
            self.data_root / "manual",
            self.data_root / "reference",
            self.reports_root / "figures",
            self.reports_root / "tables",
            self.logs_root,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def redacted_dict(self) -> dict[str, Any]:
        """Return configuration safe to display; credentials are never stored here."""
        return self.raw


def load_config(path: str | Path = "config.yaml", *, project_root: str | Path | None = None) -> PipelineConfig:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        base = Path(project_root).expanduser().resolve() if project_root else Path.cwd().resolve()
        config_path = (base / config_path).resolve()
    else:
        base = Path(project_root).expanduser().resolve() if project_root else config_path.parent.resolve()

    user_config: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise TypeError("config.yaml must contain a top-level mapping.")
        user_config = loaded

    merged = _deep_merge(DEFAULTS, user_config)
    config = PipelineConfig(raw=merged, project_root=base, config_path=config_path if config_path.exists() else None)
    config.ensure_directories()
    return config
