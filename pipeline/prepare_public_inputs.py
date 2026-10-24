"""Prepare public, credential-free inputs for PasarPulse-MM.

Examples:
    python prepare_public_inputs.py
    python prepare_public_inputs.py --references-only
    python prepare_public_inputs.py --prices-only
    python prepare_public_inputs.py --markets-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pasarpulse import PasarPulsePipeline, load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--references-only", action="store_true")
    group.add_argument("--prices-only", action="store_true")
    group.add_argument("--markets-only", action="store_true")
    args = parser.parse_args()

    project_root = ROOT
    config = load_config(project_root / "config.yaml", project_root=project_root)
    # The public-input helper reports all attempted stages in one run.  The
    # full research orchestrator may still opt into fail-fast behavior.
    config.raw["project"]["fail_fast"] = False
    pipeline = PasarPulsePipeline(config)

    if not args.prices_only and not args.markets_only:
        print("Preparing BIG boundaries and province-fallback Sentinel zones...")
        result = pipeline.run_references()
        if result:
            for name, path in result.items():
                print(f"  {name}: {path}")
        else:
            print("  FAILED. See logs/pipeline.log")

    if not args.references_only and not args.markets_only:
        print("Downloading and parsing public SP2KP resources...")
        prices = pipeline.run_prices()
        if prices is not None:
            print(f"  canonical price rows: {len(prices):,}")
            print(prices.head())
        else:
            print("  FAILED. See data/processed/sp2kp_resource_manifest.csv and logs/pipeline.log")

    if not args.references_only and not args.prices_only:
        print("Preparing official market locations and operating-frequency metadata...")
        markets = pipeline.run_official_markets()
        if markets is not None and len(markets) == 38:
            source_gaps = int(
                markets.get(
                    "official_market_province_coverage_status",
                    markets["official_market_count"].notna().map(
                        {True: "observed", False: "no_points_in_source"}
                    ),
                )
                .ne("available")
                .sum()
            )
            print(f"  normalized province rows: {len(markets):,}; explicit source gaps: {source_gaps}")
        else:
            print("  FAILED. See logs/pipeline.log")

    status = pipeline.status()
    print("\nStage status:")
    print(status.to_string(index=False))
    return 1 if (status["status"] == "failed").any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
