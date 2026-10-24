"""Run all enabled pipeline stages outside Jupyter."""
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
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--close-figures", action="store_true")
    args = parser.parse_args()
    root = ROOT
    config = load_config(root / args.config, project_root=root)
    pipeline = PasarPulsePipeline(config)
    print(pipeline.preflight().to_string(index=False))
    status = pipeline.run_all(close_figures=args.close_figures)
    print("\nPipeline status:\n", status.to_string(index=False))
    if pipeline.errors:
        print("\nFailed stages:", ", ".join(pipeline.errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
