"""Notebook-friendly orchestration of all PasarPulse-MM data stages."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import PipelineConfig
from .credentials import credential_status
from .utils import get_logger, save_frame


class PasarPulsePipeline:
    """Stateful pipeline used by ``main_data_pipeline.ipynb`` and CLI scripts."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.config.ensure_directories()
        self.logger = get_logger("pasarpulse", self.config.logs_root / "pipeline.log")
        self.frames: dict[str, pd.DataFrame] = {}
        self.paths: dict[str, Path] = {}
        self.stage_records: list[dict[str, Any]] = []
        self.errors: dict[str, str] = {}

    @property
    def fail_fast(self) -> bool:
        return bool(self.config.get("project.fail_fast", False))

    @property
    def save_csv(self) -> bool:
        return bool(self.config.get("project.save_csv", True))

    @property
    def save_parquet(self) -> bool:
        return bool(self.config.get("project.save_parquet", True))

    def _record(self, stage: str, status: str, message: str = "") -> None:
        self.stage_records.append({"stage": stage, "status": status, "message": message})
        getattr(self.logger, "error" if status == "failed" else "info")("%s | %s | %s", stage, status, message)

    def _execute(self, stage: str, function: Callable[[], Any], *, enabled: bool = True) -> Any:
        if not enabled:
            self._record(stage, "disabled", "Disabled in config.yaml")
            return None
        try:
            result = function()
            self._record(stage, "completed")
            return result
        except Exception as exc:
            self.errors[stage] = traceback.format_exc()
            self._record(stage, "failed", str(exc))
            if self.fail_fast:
                raise
            return None

    def _processed_base(self, name: str) -> Path:
        return self.config.data_root / "processed" / name

    def _ready_base(self, name: str) -> Path:
        return self.config.data_root / "ready" / name

    def _existing_frame(self, base: Path) -> pd.DataFrame:
        parquet, csv = base.with_suffix(".parquet"), base.with_suffix(".csv")
        if parquet.exists():
            return pd.read_parquet(parquet)
        if csv.exists():
            return pd.read_csv(csv)
        return pd.DataFrame()

    def preflight(self) -> pd.DataFrame:
        province_path = self.config.path("province_boundaries")
        satellite_zones = self.config.path("satellite_zones")
        events = self.config.path("calendar_events")
        inputs = self.config.get("prices.inputs", []) or []
        price_source = str(self.config.get("prices.source", "sp2kp")).casefold()
        rows = [
            {"item": "setup_credentials.py", "required_for": "ERA5 and Sentinel-2", "available": (self.config.project_root / "setup_credentials.py").exists()},
            {"item": "CDS API token", "required_for": "ERA5 download", "available": credential_status(self.config.project_root)["CDS_API_KEY"]},
            {"item": "CDSE S3 keys", "required_for": "Sentinel feature extraction", "available": credential_status(self.config.project_root)["CDSE_S3_ACCESS_KEY"] and credential_status(self.config.project_root)["CDSE_S3_SECRET_KEY"]},
            {"item": str(province_path), "required_for": "Weather aggregation and static graph", "available": bool(province_path and province_path.exists()), "auto_preparable": True},
            {"item": str(satellite_zones), "required_for": "Sentinel search/extraction", "available": bool(satellite_zones and satellite_zones.exists()), "auto_preparable": True},
            {"item": "dated Geofabrik Indonesia PBF", "required_for": "Candidate structural transport connectivity", "available": (self.config.data_root / "raw" / "osm" / "indonesia.osm.pbf").exists(), "auto_preparable": True},
            {"item": str(events), "required_for": "Official calendar events", "available": bool(events and events.exists()), "auto_preparable": False},
            {"item": f"price source: {price_source}", "required_for": "Price anchor and full merge", "available": price_source in {"sp2kp", "pihps"} or bool(inputs), "auto_preparable": price_source in {"sp2kp", "pihps"}},
        ]
        for index, spec in enumerate(inputs, start=1):
            raw = Path(spec.get("path", ""))
            path = raw if raw.is_absolute() else self.config.project_root / raw
            rows.append({"item": f"price input {index}: {path}", "required_for": "Price ingestion", "available": path.exists()})
        return pd.DataFrame(rows)

    def run_references(self) -> dict[str, Path] | None:
        def work() -> dict[str, Path]:
            from .tools.reference import prepare_reference_files
            province_path = self.config.path("province_boundaries")
            satellite_path = self.config.path("satellite_zones")
            if province_path is None or satellite_path is None:
                raise ValueError("Reference output paths are missing in config.yaml.")
            outputs = prepare_reference_files(
                province_path,
                satellite_path,
                endpoint=str(self.config.get("references.big_endpoint")),
                expected_count=int(self.config.get("references.expected_province_count", 38)),
                overwrite=bool(self.config.get("references.overwrite", False)),
            )
            self.paths.update(outputs)
            return outputs
        return self._execute("references", work, enabled=self.config.stage_enabled("references"))

    def run_prices(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.prices import audit_price_coverage, ingest_price_sources
            price_source = str(self.config.get("prices.source", "sp2kp")).casefold()
            if price_source == "sp2kp":
                from .tools.sp2kp import ingest_sp2kp
                frame, outputs, manifest, manifest_outputs = ingest_sp2kp(
                    output_base=self._processed_base("price_daily"),
                    raw_dir=self.config.data_root / "raw" / "sp2kp",
                    manifest_base=self._processed_base("sp2kp_resource_manifest"),
                    start_date=str(self.config.get("project.start_date")),
                    end_date=str(self.config.get("project.end_date")),
                    dataset_id=str(self.config.get("prices.sp2kp.dataset_id")),
                    dataset_page_url=str(self.config.get("prices.sp2kp.dataset_page_url")),
                    catalog_api_urls=list(self.config.get("prices.sp2kp.catalog_api_urls", [])),
                    overwrite_downloads=bool(self.config.get("prices.sp2kp.overwrite_downloads", False)),
                    timeout=int(self.config.get("prices.sp2kp.timeout_seconds", 180)),
                    save_csv=self.save_csv,
                    save_parquet=self.save_parquet,
                )
                self.frames["sp2kp_manifest"] = manifest
                self.paths.update({f"sp2kp_manifest_{key}": value for key, value in manifest_outputs.items()})
            elif price_source == "pihps":
                from .tools.pihps import ingest_pihps
                pihps = self.config.get("prices.pihps", {}) or {}
                commodities = pihps.get("commodities")
                market_types = pihps.get("market_types")
                if commodities:
                    commodities = {str(code): dict(spec) for code, spec in commodities.items()}
                if market_types:
                    market_types = {str(level): int(price_type_id) for level, price_type_id in market_types.items()}
                (
                    frame,
                    outputs,
                    manifest,
                    manifest_outputs,
                    mapping,
                    mapping_outputs,
                ) = ingest_pihps(
                    start_date=str(self.config.get("project.start_date")),
                    end_date=str(self.config.get("project.end_date")),
                    raw_dir=self.config.data_root / "raw" / "pihps",
                    output_base=self._processed_base("price_daily"),
                    manifest_base=self._processed_base("pihps_snapshot_manifest"),
                    mapping_base=self._processed_base("pihps_mapping_audit"),
                    endpoint=str(pihps.get("endpoint") or "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataKomoditas"),
                    page_url=str(pihps.get("page_url") or "https://www.bi.go.id/hargapangan/TabelHarga/PedagangBesarKomoditas"),
                    commodities=commodities,
                    market_types=market_types,
                    timeout=int(pihps.get("timeout_seconds", 90)),
                    overwrite_snapshots=bool(pihps.get("overwrite_snapshots", False)),
                    save_csv=self.save_csv,
                    save_parquet=self.save_parquet,
                )
                self.frames["pihps_manifest"] = manifest
                self.frames["pihps_mapping"] = mapping
                self.paths.update({f"pihps_manifest_{key}": value for key, value in manifest_outputs.items()})
                self.paths.update({f"pihps_mapping_{key}": value for key, value in mapping_outputs.items()})
            else:
                frame, outputs = ingest_price_sources(
                    self.config.get("prices.inputs", []) or [],
                    self._processed_base("price_daily"),
                    project_root=self.config.project_root,
                    save_csv=self.save_csv,
                    save_parquet=self.save_parquet,
                )
            self.frames["prices"] = frame
            self.paths.update({f"prices_{key}": value for key, value in outputs.items()})
            audit = audit_price_coverage(
                frame,
                min_months=int(self.config.get("prices.min_months", 24)),
                min_coverage=float(self.config.get("prices.min_coverage", 0.80)),
                scheduled_days=str(self.config.get("prices.scheduled_days", "business")),
            )
            audit_outputs = save_frame(
                audit,
                self._processed_base("price_coverage_audit"),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["price_coverage_audit"] = audit
            self.paths.update({f"price_audit_{key}": value for key, value in audit_outputs.items()})
            return frame
        return self._execute("prices", work, enabled=self.config.stage_enabled("prices"))

    def run_price_baselines(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.baselines import run_price_only_baselines

            prices = self.frames.get("prices")
            if prices is None or prices.empty:
                prices = self._existing_frame(self._processed_base("price_daily"))
            audit = self.frames.get("price_coverage_audit")
            if audit is None or audit.empty:
                audit = self._existing_frame(self._processed_base("price_coverage_audit"))
            metrics, prediction_outputs, metric_outputs = run_price_only_baselines(
                prices,
                audit,
                output_dir=self.config.reports_root / "tables",
                metadata_path=self.config.reports_root / "price_only_baselines.json",
                start_date=str(self.config.get("project.start_date")),
                end_date=str(self.config.get("project.end_date")),
                bounded_ffill_days=int(self.config.get("prices.bounded_ffill_days", 3)),
                shock_threshold=float(self.config.get("prices.shock_threshold", 0.10)),
                min_train_days=int(self.config.get("prices.baselines.min_train_days", 365)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["price_only_baseline_metrics"] = metrics
            self.paths.update({f"price_baseline_predictions_{key}": value for key, value in prediction_outputs.items()})
            self.paths.update({f"price_baseline_metrics_{key}": value for key, value in metric_outputs.items()})
            return metrics

        return self._execute("price_baselines", work, enabled=self.config.stage_enabled("price_baselines"))

    def run_bps(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.bps import build_annual_dataset
            frame, outputs = build_annual_dataset(
                list(map(int, self.config.get("bps.years", [2023, 2024, 2025]))),
                output_base=self._processed_base("production_annual"),
                raw_dir=self.config.data_root / "raw" / "bps",
                project_root=self.config.project_root,
                headless=bool(self.config.get("bps.headless", True)),
                timeout=int(self.config.get("bps.timeout_seconds", 60)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["production"] = frame
            self.paths.update({f"production_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("bps", work, enabled=self.config.stage_enabled("bps"))

    def run_era5_download(self) -> list[Path] | None:
        def work() -> list[Path]:
            from .tools.weather import download_era5_range
            files = download_era5_range(
                self.config.get("project.start_date"),
                self.config.get("project.end_date"),
                output_dir=self.config.data_root / "raw" / "era5_land",
                area=list(self.config.get("era5.area")),
                variables=list(self.config.get("era5.variables")),
                project_root=self.config.project_root,
            )
            for index, path in enumerate(files):
                self.paths[f"era5_month_{index}"] = path
            return files
        return self._execute("era5_download", work, enabled=self.config.stage_enabled("era5_download"))

    def run_era5_aggregate(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.weather import aggregate_era5_to_provinces
            province_path = self.config.path("province_boundaries")
            if not province_path or not province_path.exists():
                raise FileNotFoundError("Province boundary file is required for ERA5 aggregation.")
            files = sorted((self.config.data_root / "raw" / "era5_land").glob("era5_land_*.nc"))
            if not files:
                raise FileNotFoundError("No ERA5 .nc files found. Enable era5_download or upload existing files.")
            frame, outputs = aggregate_era5_to_provinces(
                files,
                provinces_path=province_path,
                province_code_col=str(self.config.get("era5.province_code_col", "province_code")),
                province_name_col=str(self.config.get("era5.province_name_col", "province_name")),
                output_base=self._processed_base("weather_daily"),
                start_date=str(self.config.get("project.start_date")),
                end_date=str(self.config.get("project.end_date")),
                metadata_path=self.config.data_root
                / "processed"
                / "weather_metadata.json",
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["weather"] = frame
            self.paths.update({f"weather_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("era5_aggregate", work, enabled=self.config.stage_enabled("era5_aggregate"))

    def run_sentinel_search(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.satellite import search_sentinel2
            zones = self.config.path("satellite_zones")
            if not zones or not zones.exists():
                raise FileNotFoundError("satellite_zones GeoJSON is required.")
            frame, outputs = search_sentinel2(
                zones,
                zone_code_col=str(self.config.get("sentinel2.zone_code_col", "province_code")),
                zone_name_col=str(self.config.get("sentinel2.zone_name_col", "province_name")),
                start_date=self.config.get("project.start_date"),
                end_date=self.config.get("project.end_date"),
                max_cloud=float(self.config.get("sentinel2.max_cloud_cover", 30.0)),
                period_days=int(self.config.get("sentinel2.period_days", 16)),
                output_base=self.config.data_root / "raw" / "sentinel2_asset_manifest",
                stac_url=str(self.config.get("sentinel2.stac_url")),
                collection=str(self.config.get("sentinel2.collection", "sentinel-2-l2a")),
                search_workers=int(self.config.get("sentinel2.search_workers", 4)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["satellite_manifest"] = frame
            self.paths.update({f"sentinel_manifest_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("sentinel_search", work, enabled=self.config.stage_enabled("sentinel_search"))

    def run_sentinel_extract(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.satellite import extract_satellite_features
            zones = self.config.path("satellite_zones")
            if not zones or not zones.exists():
                raise FileNotFoundError("satellite_zones GeoJSON is required.")
            manifest = self.frames.get("satellite_manifest")
            if manifest is None or manifest.empty:
                manifest = self._existing_frame(self.config.data_root / "raw" / "sentinel2_asset_manifest")
            if manifest.empty:
                raise FileNotFoundError("Sentinel-2 manifest not found. Run sentinel_search first.")
            frame, outputs = extract_satellite_features(
                manifest,
                zones_path=zones,
                zone_code_col=str(self.config.get("sentinel2.zone_code_col", "province_code")),
                output_base=self._processed_base("satellite_features"),
                project_root=self.config.project_root,
                valid_scl_classes=self.config.get("sentinel2.valid_scl_classes", [4, 5]),
                max_sample_pixels=int(self.config.get("sentinel2.max_sample_pixels", 262_144)),
                extract_workers=int(self.config.get("sentinel2.extract_workers", 4)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["satellite"] = frame
            self.paths.update({f"satellite_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("sentinel_extract", work, enabled=self.config.stage_enabled("sentinel_extract"))

    def run_calendar(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.calendar import build_calendar_features
            frame, outputs = build_calendar_features(
                self.config.get("project.start_date"),
                self.config.get("project.end_date"),
                events_path=self.config.path("calendar_events"),
                output_base=self._processed_base("calendar_features"),
                national_region_code=str(self.config.get("calendar.national_region_code", "NATIONAL")),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["calendar"] = frame
            self.paths.update({f"calendar_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("calendar", work, enabled=self.config.stage_enabled("calendar"))

    def run_official_markets(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.official_markets import acquire_official_markets

            provinces = self.config.path("province_boundaries")
            if not provinces or not provinces.exists():
                raise FileNotFoundError(
                    "Province boundary file is required for official market normalization."
                )
            table, summary, outputs = acquire_official_markets(
                provinces_path=provinces,
                output_dir=self.config.data_root / "processed",
                layer_url=str(self.config.get("official_markets.layer_url")),
                province_code_col=str(
                    self.config.get("era5.province_code_col", "province_code")
                ),
                province_name_col=str(
                    self.config.get("era5.province_name_col", "province_name")
                ),
                minimum_expected_features=int(
                    self.config.get("official_markets.minimum_expected_features", 600)
                ),
                nearest_join_max_km=float(
                    self.config.get("official_markets.nearest_join_max_km", 30.0)
                ),
                timeout=int(self.config.get("official_markets.timeout_seconds", 120)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["official_markets"] = table
            self.frames["official_market_summary"] = summary
            self.paths.update(
                {f"official_markets_{key}": value for key, value in outputs.items()}
            )
            return summary

        return self._execute(
            "official_markets",
            work,
            enabled=self.config.stage_enabled("official_markets"),
        )

    def run_osm_transport(self) -> dict[str, Path] | None:
        def work() -> dict[str, Path]:
            from .tools.osm import acquire_osm_transport

            provinces = self.config.path("province_boundaries")
            if not provinces or not provinces.exists():
                raise FileNotFoundError("Province boundary file is required for OSM extraction.")
            outputs = acquire_osm_transport(
                url=str(self.config.get("graph.osm_snapshot_url")),
                snapshot_date=str(self.config.get("graph.osm_snapshot_date")),
                raw_path=self.config.data_root / "raw" / "osm" / "indonesia.osm.pbf",
                provinces_path=provinces,
                output_dir=self.config.data_root / "processed",
                overwrite=bool(self.config.get("graph.osm_overwrite", False)),
                download_workers=int(self.config.get("graph.osm_download_workers", 8)),
            )
            self.paths.update({f"osm_{key}": value for key, value in outputs.items()})
            self.frames["osm_transport"] = self._existing_frame(
                self._processed_base("osm_province_transport_summary")
            )
            self.frames["osm_transport_edges"] = self._existing_frame(
                self._processed_base("osm_transport_edges")
            )
            return outputs

        return self._execute(
            "osm_transport", work, enabled=self.config.stage_enabled("osm_transport")
        )

    def run_static_graph(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.graph import build_static_graph
            provinces = self.config.path("province_boundaries")
            if not provinces or not provinces.exists():
                raise FileNotFoundError("Province boundary file is required for static graph.")
            production = self.frames.get("production")
            if production is None or production.empty:
                production = self._existing_frame(self._processed_base("production_annual"))
            transport_edges = self.frames.get("osm_transport_edges")
            if transport_edges is None or transport_edges.empty:
                transport_edges = self._existing_frame(self._processed_base("osm_transport_edges"))
            frame, outputs = build_static_graph(
                provinces,
                province_code_col=str(self.config.get("era5.province_code_col", "province_code")),
                province_name_col=str(self.config.get("era5.province_name_col", "province_name")),
                production=production,
                transport_edges=transport_edges,
                output_base=self._processed_base("province_graph_static"),
                knn=int(self.config.get("graph.static_knn", 3)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["static_graph"] = frame
            self.paths.update({f"static_graph_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("static_graph", work, enabled=self.config.stage_enabled("static_graph"))

    def run_dynamic_graph(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.graph import build_dynamic_price_graph
            prices = self.frames.get("prices")
            if prices is None or prices.empty:
                prices = self._existing_frame(self._processed_base("price_daily"))
            if prices.empty:
                raise FileNotFoundError("Price data is required for dynamic graph.")
            frame, outputs = build_dynamic_price_graph(
                prices,
                output_base=self._processed_base("province_graph_dynamic"),
                window_days=int(self.config.get("graph.dynamic_window_days", 90)),
                snapshot_freq=str(self.config.get("graph.dynamic_snapshot_freq", "MS")),
                max_lag_days=int(self.config.get("graph.dynamic_max_lag_days", 7)),
                min_overlap=int(self.config.get("graph.dynamic_min_overlap", 30)),
                top_k=int(self.config.get("graph.dynamic_top_k", 5)),
                bounded_ffill_days=int(self.config.get("prices.bounded_ffill_days", 3)),
                shock_threshold=float(self.config.get("prices.shock_threshold", 0.10)),
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["dynamic_graph"] = frame
            self.paths.update({f"dynamic_graph_{key}": value for key, value in outputs.items()})
            return frame
        return self._execute("dynamic_graph", work, enabled=self.config.stage_enabled("dynamic_graph"))

    def run_merge(self) -> pd.DataFrame | None:
        def work() -> pd.DataFrame:
            from .tools.merge import build_model_ready_dataset
            prices = self.frames.get("prices")
            if prices is None or prices.empty:
                prices = self._existing_frame(self._processed_base("price_daily"))
            audit = self.frames.get("price_coverage_audit")
            if audit is None or audit.empty:
                audit = self._existing_frame(self._processed_base("price_coverage_audit"))
            weather = self.frames.get("weather")
            if weather is None or weather.empty:
                weather = self._existing_frame(self._processed_base("weather_daily"))
            production = self.frames.get("production")
            if production is None or production.empty:
                production = self._existing_frame(self._processed_base("production_annual"))
            satellite = self.frames.get("satellite")
            if satellite is None or satellite.empty:
                satellite = self._existing_frame(self._processed_base("satellite_features"))
            calendar = self.frames.get("calendar")
            if calendar is None or calendar.empty:
                calendar = self._existing_frame(self._processed_base("calendar_features"))
            transport = self.frames.get("osm_transport")
            if transport is None or transport.empty:
                transport = self._existing_frame(
                    self._processed_base("osm_province_transport_summary")
                )
            official_markets = self.frames.get("official_market_summary")
            if official_markets is None or official_markets.empty:
                official_markets = self._existing_frame(
                    self._processed_base("official_market_province_summary")
                )
            thresholds_path = self.config.path("official_thresholds")
            thresholds = pd.read_csv(thresholds_path) if thresholds_path and thresholds_path.exists() else pd.DataFrame()
            all_frame, eligible, all_outputs, eligible_outputs = build_model_ready_dataset(
                prices,
                coverage_audit=audit,
                weather=weather,
                production=production,
                satellite=satellite,
                calendar=calendar,
                transport=transport,
                official_markets=official_markets,
                thresholds=thresholds,
                start_date=self.config.get("project.start_date"),
                end_date=self.config.get("project.end_date"),
                bounded_price_ffill_days=int(self.config.get("prices.bounded_ffill_days", 3)),
                satellite_max_carry_days=int(self.config.get("sentinel2.max_carry_days", 24)),
                satellite_publication_lag_days=int(
                    self.config.get("merge.satellite_publication_lag_days", 1)
                ),
                weather_publication_lag_days=int(
                    self.config.get("merge.weather_publication_lag_days", 5)
                ),
                weather_max_carry_days=int(
                    self.config.get("merge.weather_max_carry_days", 10)
                ),
                production_max_age_years=int(self.config.get("merge.production_max_age_years", 3)),
                shock_threshold=float(self.config.get("prices.shock_threshold", 0.10)),
                output_all_base=self._ready_base("model_dataset_all"),
                output_eligible_base=self._ready_base("model_dataset_eligible"),
                metadata_path=self.config.data_root / "ready" / "model_dataset_metadata.json",
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            self.frames["ready_all"] = all_frame
            self.frames["ready_eligible"] = eligible
            self.paths.update({f"ready_all_{key}": value for key, value in all_outputs.items()})
            self.paths.update({f"ready_eligible_{key}": value for key, value in eligible_outputs.items()})

            static_graph = self.frames.get("static_graph")
            if static_graph is None or static_graph.empty:
                static_graph = self._existing_frame(self._processed_base("province_graph_static"))
            if not static_graph.empty:
                from .tools.graph import build_multilevel_graph

                nodes, edges, node_outputs, edge_outputs = build_multilevel_graph(
                    prices,
                    static_graph,
                    output_nodes_base=self._ready_base("graph_nodes"),
                    output_edges_base=self._ready_base("graph_edges_static_multilevel"),
                    save_csv=self.save_csv,
                    save_parquet=self.save_parquet,
                )
                self.frames["graph_nodes"] = nodes
                self.frames["graph_edges_static_multilevel"] = edges
                self.paths.update({f"graph_nodes_{key}": value for key, value in node_outputs.items()})
                self.paths.update({f"graph_edges_{key}": value for key, value in edge_outputs.items()})
            return eligible if bool(self.config.get("merge.eligible_only_default", True)) else all_frame
        return self._execute("merge", work, enabled=self.config.stage_enabled("merge"))

    def run_quality(self) -> dict[str, Any] | None:
        def work() -> dict[str, Any]:
            from .tools.quality import build_quality_artifacts
            if "ready_all" not in self.frames:
                self.frames["ready_all"] = self._existing_frame(self._ready_base("model_dataset_all"))
            artifacts = build_quality_artifacts(
                self.frames,
                ready_dataset_name="ready_all",
                reports_tables_dir=self.config.reports_root / "tables",
                manifest_path=self.config.reports_root / "data_manifest.json",
                source_files={key: value for key, value in self.paths.items()},
                save_csv=self.save_csv,
                save_parquet=self.save_parquet,
            )
            return artifacts
        return self._execute("quality", work, enabled=self.config.stage_enabled("quality"))

    def run_visualization(self, *, close_figures: bool = False) -> dict[str, Any] | None:
        def work() -> dict[str, Any]:
            from .tools.visualization import create_pipeline_figures
            ready = self.frames.get("ready_all")
            if ready is None or ready.empty:
                ready = self._existing_frame(self._ready_base("model_dataset_all"))
            audit = self.frames.get("price_coverage_audit")
            if audit is None or audit.empty:
                audit = self._existing_frame(self._processed_base("price_coverage_audit"))
            production = self.frames.get("production")
            if production is None or production.empty:
                production = self._existing_frame(self._processed_base("production_annual"))
            if ready.empty:
                raise FileNotFoundError("Ready dataset is required for visualizations.")
            return create_pipeline_figures(
                ready=ready,
                coverage_audit=audit,
                production=production,
                output_dir=self.config.reports_root / "figures",
                example_province=str(self.config.get("visualization.example_province", "")),
                example_commodity=str(self.config.get("visualization.example_commodity", "CRM")),
                example_market_level=str(self.config.get("visualization.example_market_level", "retail")),
                top_n_production=int(self.config.get("visualization.top_n_production", 12)),
                close_figures=close_figures,
            )
        return self._execute("visualization", work, enabled=self.config.stage_enabled("visualization"))

    def run_all(self, *, close_figures: bool = False) -> pd.DataFrame:
        self.run_references()
        self.run_prices()
        self.run_price_baselines()
        self.run_bps()
        self.run_era5_download()
        self.run_era5_aggregate()
        self.run_sentinel_search()
        self.run_sentinel_extract()
        self.run_calendar()
        self.run_official_markets()
        self.run_osm_transport()
        self.run_static_graph()
        self.run_dynamic_graph()
        self.run_merge()
        self.run_quality()
        self.run_visualization(close_figures=close_figures)
        return self.status()

    def status(self) -> pd.DataFrame:
        return pd.DataFrame(self.stage_records)
