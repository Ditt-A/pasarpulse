#!/usr/bin/env python3
"""Validate and copy the canonical 38-province GeoJSON into demo artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/reference/indonesia_provinces.geojson"))
    parser.add_argument("--output", type=Path, default=Path("demo_data/geography/indonesia_provinces.geojson"))
    args = parser.parse_args()
    payload = json.loads(args.source.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if len(features) != 38:
        raise SystemExit(f"Expected 38 province features, found {len(features)}")
    codes = [str(feature.get("properties", {}).get("province_code", "")).zfill(2) for feature in features]
    if len(set(codes)) != 38 or any(not code.isdigit() for code in codes):
        raise SystemExit("GeoJSON province_code properties are not unique canonical codes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.source, args.output)
    print(f"validated {len(features)} provinces -> {args.output}")


if __name__ == "__main__":
    main()
