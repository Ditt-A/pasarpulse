#!/usr/bin/env python3
"""Run one resumable PasarPulse data stage with a machine-readable status."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STAGES = {
    "references": "run_references",
    "bps": "run_bps",
    "era5_download": "run_era5_download",
    "era5_aggregate": "run_era5_aggregate",
    "sentinel_search": "run_sentinel_search",
    "sentinel_extract": "run_sentinel_extract",
    "calendar": "run_calendar",
    "official_markets": "run_official_markets",
    "osm_transport": "run_osm_transport",
    "static_graph": "run_static_graph",
    "dynamic_graph": "run_dynamic_graph",
    "merge": "run_merge",
    "quality": "run_quality",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=tuple(STAGES))
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--satellite-provider",
        choices=("configured", "cdse", "earth-search"),
        default="configured",
    )
    parser.add_argument("--status-output", type=Path)
    args = parser.parse_args()

    from src.pasarpulse import PasarPulsePipeline, load_config

    project_root = args.project_root.resolve()
    config_path = args.config if args.config.is_absolute() else project_root / args.config
    config = load_config(config_path, project_root=project_root)
    config.raw.setdefault("stages", {})[args.stage] = True
    if args.start_date:
        config.raw["project"]["start_date"] = args.start_date
    if args.end_date:
        config.raw["project"]["end_date"] = args.end_date
    if args.satellite_provider == "cdse":
        config.raw["sentinel2"].update(
            {
                "stac_url": "https://stac.dataspace.copernicus.eu/v1/",
                "collection": "sentinel-2-l2a",
            }
        )
    elif args.satellite_provider == "earth-search":
        config.raw["sentinel2"].update(
            {
                "stac_url": "https://earth-search.aws.element84.com/v1/",
                "collection": "sentinel-2-c1-l2a",
            }
        )

    pipeline = PasarPulsePipeline(config)
    result = getattr(pipeline, STAGES[args.stage])()
    record = pipeline.stage_records[-1] if pipeline.stage_records else {
        "stage": args.stage,
        "status": "failed",
        "message": "No stage status was recorded.",
    }
    payload = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage,
        "status": record,
        "paths": {key: str(value) for key, value in pipeline.paths.items()},
        "result_type": type(result).__name__,
        "errors": pipeline.errors,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.status_output:
        output = (
            args.status_output
            if args.status_output.is_absolute()
            else project_root / args.status_output
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if record.get("status") == "completed" else 1)


if __name__ == "__main__":
    main()
