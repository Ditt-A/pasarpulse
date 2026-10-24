from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("<PROJECT_ROOT>")
ORIGINAL = ROOT / "TEMP_pasarpulse_sweep50.py"


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def coordinate_points(value):
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
            yield float(value[0]), float(value[1])
        else:
            for item in value:
                yield from coordinate_points(item)


def patched_geo(panel, root):
    candidates = list(Path(root).rglob("*province*.geojson")) + list(Path(root).rglob("*provinces*.json"))
    if not candidates:
        print("Geo patch: no province GeoJSON found", flush=True)
        return panel, []
    geo_path = sorted(set(candidates), key=lambda path: ("reference" not in str(path), len(str(path))))[0]
    payload = json.loads(geo_path.read_text(encoding="utf-8"))
    aliases = {
        "dki jakarta": "jakarta",
        "daerah khusus ibukota jakarta": "jakarta",
        "di yogyakarta": "yogyakarta",
        "daerah istimewa yogyakarta": "yogyakarta",
        "kep bangka belitung": "kepulauan bangka belitung",
        "kep riau": "kepulauan riau",
    }
    lookup = {}
    for code, name in panel[["province_code", "province_name"]].drop_duplicates().itertuples(index=False, name=None):
        key = aliases.get(norm(name), norm(name))
        lookup[key] = (str(code).zfill(2), str(name))
    rows = []
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        matched = None
        for value in properties.values():
            key = aliases.get(norm(value), norm(value))
            if key in lookup:
                matched = lookup[key]
                break
        if matched is None:
            continue
        points = list(coordinate_points((feature.get("geometry") or {}).get("coordinates", [])))
        if not points:
            continue
        rows.append(
            {
                "province_code": matched[0],
                "geo_longitude": float(np.mean([point[0] for point in points])),
                "geo_latitude": float(np.mean([point[1] for point in points])),
            }
        )
    centroids = pd.DataFrame(rows).drop_duplicates("province_code")
    print(f"Geo patch matched {len(centroids)} province centroids from {geo_path}", flush=True)
    if len(centroids) < 20:
        print("Geo patch disabled: fewer than 20 provinces matched", flush=True)
        return panel, []

    def distance_km(lat1, lon1, lat2, lon2):
        radius = 6371.0088
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        value = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2.0 * radius * math.asin(min(1.0, math.sqrt(value)))

    edge_rows = []
    records = list(centroids.itertuples(index=False))
    for current in records:
        distances = []
        for neighbor in records:
            if current.province_code == neighbor.province_code:
                continue
            distances.append(
                (
                    distance_km(current.geo_latitude, current.geo_longitude, neighbor.geo_latitude, neighbor.geo_longitude),
                    neighbor.province_code,
                )
            )
        for distance, neighbor_code in sorted(distances)[:4]:
            edge_rows.append(
                {
                    "province_code": str(current.province_code).zfill(2),
                    "neighbor_code": str(neighbor_code).zfill(2),
                    "geo_neighbor_distance_km": distance,
                    "geo_neighbor_weight": 1.0 / (25.0 + distance),
                }
            )
    edges = pd.DataFrame(edge_rows)
    source = panel[["date", "province_code", "commodity_code", "market_level", "price_filled"]].copy()
    source["province_code"] = source["province_code"].astype(str).str.zfill(2)
    source = source.rename(columns={"province_code": "neighbor_code", "price_filled": "geo_neighbor_price"})
    expanded = edges.merge(source, on="neighbor_code", how="left")
    expanded = expanded[expanded["geo_neighbor_price"].notna()].copy()
    expanded["geo_weighted_price"] = expanded["geo_neighbor_price"] * expanded["geo_neighbor_weight"]
    keys = ["date", "province_code", "commodity_code", "market_level"]
    neighbor = (
        expanded.groupby(keys, observed=True)
        .agg(
            geo_weighted_price=("geo_weighted_price", "sum"),
            geo_weight_sum=("geo_neighbor_weight", "sum"),
            geo_neighbor_std=("geo_neighbor_price", "std"),
            geo_neighbor_min=("geo_neighbor_price", "min"),
            geo_neighbor_max=("geo_neighbor_price", "max"),
            geo_mean_neighbor_distance_km=("geo_neighbor_distance_km", "mean"),
        )
        .reset_index()
    )
    neighbor["geo_neighbor_mean"] = neighbor["geo_weighted_price"] / neighbor["geo_weight_sum"].replace(0.0, np.nan)
    keep = keys + [
        "geo_neighbor_mean",
        "geo_neighbor_std",
        "geo_neighbor_min",
        "geo_neighbor_max",
        "geo_mean_neighbor_distance_km",
    ]
    output = panel.copy()
    output["province_code"] = output["province_code"].astype(str).str.zfill(2)
    output = output.merge(centroids, on="province_code", how="left")
    output = output.merge(neighbor[keep], on=keys, how="left")
    output["geo_neighbor_gap"] = output["price_filled"] - output["geo_neighbor_mean"]
    output["geo_neighbor_ratio"] = output["price_filled"] / output["geo_neighbor_mean"] - 1.0
    output = output.sort_values(["province_code", "commodity_code", "market_level", "date"])
    group = output.groupby(["province_code", "commodity_code", "market_level"], observed=True, sort=False)
    output["geo_neighbor_delta_7"] = output["geo_neighbor_mean"] - group["geo_neighbor_mean"].shift(7)
    output["geo_neighbor_delta_14"] = output["geo_neighbor_mean"] - group["geo_neighbor_mean"].shift(14)
    features = [
        "geo_longitude",
        "geo_latitude",
        "geo_neighbor_mean",
        "geo_neighbor_std",
        "geo_neighbor_min",
        "geo_neighbor_max",
        "geo_mean_neighbor_distance_km",
        "geo_neighbor_gap",
        "geo_neighbor_ratio",
        "geo_neighbor_delta_7",
        "geo_neighbor_delta_14",
    ]
    return output.replace([np.inf, -np.inf], np.nan), features


if not ORIGINAL.exists():
    raise FileNotFoundError(ORIGINAL)
spec = importlib.util.spec_from_file_location("sweep_module", ORIGINAL)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["sweep_module"] = module
spec.loader.exec_module(module)
module.add_geo_neighbor_features = patched_geo
sys.argv = [
    str(ORIGINAL),
    "--core", "TEMP_pasarpulse_optimizer.py",
    "--panel", "proposed_model_run/panel_features.parquet",
    "--root", str(ROOT),
    "--outdir", "architecture_sweep_50/results",
]
module.main()
