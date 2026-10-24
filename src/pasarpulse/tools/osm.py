"""Leakage-safe OSM transport and market context for the province graph.

The extractor intentionally uses a dated Geofabrik snapshot.  It summarizes
major roads, ferries, ports, ferry terminals, and marketplaces by province and
records only candidate structural connectivity.  These data do not establish
observed commodity shipments or causal propagation.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Geod
from shapely.geometry import Point

from ..utils import ensure_parent, save_frame, save_json

GEOD = Geod(ellps="WGS84")
MAJOR_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary",
    "primary_link", "secondary", "secondary_link",
}
POI_TAGS = {
    ("amenity", "ferry_terminal"): "ferry_terminal",
    ("amenity", "marketplace"): "marketplace",
    ("industrial", "port"): "port",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec B324: upstream transport checksum only
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_geofabrik_snapshot(
    url: str,
    output_path: str | Path,
    *,
    md5_url: str | None = None,
    overwrite: bool = False,
    timeout: int = 180,
    workers: int = 1,
) -> tuple[Path, dict[str, Any]]:
    """Download a dated PBF resumably and verify the published checksum."""
    output = Path(output_path)
    ensure_parent(output)
    expected_md5: str | None = None
    checksum_url = md5_url or f"{url}.md5"
    checksum_response = requests.get(checksum_url, timeout=timeout)
    if checksum_response.ok:
        token = checksum_response.text.strip().split()[0]
        if len(token) == 32:
            expected_md5 = token.casefold()

    if output.exists() and output.stat().st_size > 0 and not overwrite:
        actual_md5 = _md5(output)
        if expected_md5 and actual_md5 != expected_md5:
            raise ValueError(f"Existing Geofabrik snapshot failed MD5 verification: {output}")
        return output, {
            "source_url": url,
            "md5_url": checksum_url,
            "expected_md5": expected_md5,
            "actual_md5": actual_md5,
            "sha256": _sha256(output),
            "bytes": output.stat().st_size,
            "download_status": "reused",
        }

    if int(workers) > 1:
        head = requests.head(url, allow_redirects=True, timeout=timeout)
        head.raise_for_status()
        total_bytes = int(head.headers.get("Content-Length", 0))
        accepts_ranges = "bytes" in head.headers.get("Accept-Ranges", "").casefold()
        if total_bytes <= 0 or not accepts_ranges:
            raise RuntimeError("Geofabrik server did not provide a ranged content length.")
        parts_dir = output.parent / f"{output.name}.parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        worker_count = max(1, min(int(workers), 32))
        chunk_size = math.ceil(total_bytes / worker_count)
        legacy_partial = output.with_suffix(output.suffix + ".part")
        first_part = parts_dir / "part-00000"
        if legacy_partial.exists() and not first_part.exists():
            if legacy_partial.stat().st_size <= chunk_size:
                legacy_partial.replace(first_part)

        ranges: list[tuple[int, int, Path]] = []
        for index in range(worker_count):
            start = index * chunk_size
            end = min(total_bytes - 1, (index + 1) * chunk_size - 1)
            if start <= end:
                ranges.append((start, end, parts_dir / f"part-{index:05d}"))

        def fetch_range(spec: tuple[int, int, Path]) -> Path:
            start, end, part = spec
            expected = end - start + 1
            for attempt in range(1, 6):
                existing = part.stat().st_size if part.exists() else 0
                if existing == expected:
                    return part
                if existing > expected:
                    raise ValueError(f"Range part exceeds expected size: {part}")
                request_start = start + existing
                try:
                    with requests.get(
                        url,
                        stream=True,
                        timeout=timeout,
                        headers={"Range": f"bytes={request_start}-{end}"},
                    ) as response:
                        if response.status_code != 206:
                            raise RuntimeError(
                                f"Range request returned HTTP {response.status_code}."
                            )
                        content_range = response.headers.get("Content-Range", "")
                        if not content_range.startswith(f"bytes {request_start}-{end}/"):
                            raise RuntimeError(
                                f"Unexpected Content-Range for {part.name}: {content_range}"
                            )
                        with part.open("ab") as handle:
                            for block in response.iter_content(chunk_size=1024 * 1024):
                                if block:
                                    handle.write(block)
                    if part.stat().st_size == expected:
                        return part
                except Exception:
                    if attempt >= 5:
                        raise
                    time.sleep(min(30, 2 ** attempt))
            raise RuntimeError(f"Failed to download range for {part}")

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            completed = list(executor.map(fetch_range, ranges))
        assembling = output.with_suffix(output.suffix + ".assembling")
        with assembling.open("wb") as destination:
            for part in completed:
                with part.open("rb") as source:
                    for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
                        destination.write(block)
        if assembling.stat().st_size != total_bytes:
            raise ValueError("Assembled Geofabrik snapshot has the wrong byte size.")
        actual_md5 = _md5(assembling)
        if expected_md5 and actual_md5 != expected_md5:
            raise ValueError("Assembled Geofabrik snapshot failed its published MD5 checksum.")
        assembling.replace(output)
        return output, {
            "source_url": url,
            "md5_url": checksum_url,
            "expected_md5": expected_md5,
            "actual_md5": actual_md5,
            "sha256": _sha256(output),
            "bytes": output.stat().st_size,
            "download_status": "downloaded_parallel_ranges",
            "download_workers": worker_count,
        }

    partial = output.with_suffix(output.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as response:
        response.raise_for_status()
        append = bool(offset and response.status_code == 206)
        mode = "ab" if append else "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    handle.write(chunk)
    actual_md5 = _md5(partial)
    if expected_md5 and actual_md5 != expected_md5:
        raise ValueError("Downloaded Geofabrik snapshot failed its published MD5 checksum.")
    partial.replace(output)
    return output, {
        "source_url": url,
        "md5_url": checksum_url,
        "expected_md5": expected_md5,
        "actual_md5": actual_md5,
        "sha256": _sha256(output),
        "bytes": output.stat().st_size,
        "download_status": "downloaded",
    }


class _FerryRelations:
    def __init__(self) -> None:
        import osmium

        class Handler(osmium.SimpleHandler):
            def __init__(self, owner: _FerryRelations) -> None:
                super().__init__()
                self.owner = owner

            def relation(self, relation: Any) -> None:
                if relation.tags.get("type") == "route" and relation.tags.get("route") == "ferry":
                    self.owner.relation_count += 1
                    self.owner.way_ids.update(member.ref for member in relation.members if member.type == "w")

        self.way_ids: set[int] = set()
        self.relation_count = 0
        self.handler = Handler(self)


class _InfrastructureHandler:
    def __init__(self, provinces: gpd.GeoDataFrame, ferry_way_ids: set[int]) -> None:
        import osmium

        owner = self

        class Handler(osmium.SimpleHandler):
            def node(self, node: Any) -> None:
                owner.node(node)

            def way(self, way: Any) -> None:
                owner.way(way)

        self.handler = Handler()
        self.provinces = provinces.reset_index(drop=True)
        self.sindex = self.provinces.sindex
        self.ferry_way_ids = ferry_way_ids
        self.poi_rows: list[dict[str, Any]] = []
        self.edge_accumulator: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(
            lambda: {"segment_count": 0.0, "length_km": 0.0}
        )
        self.summary: dict[str, dict[str, Any]] = {}
        for row in self.provinces.itertuples():
            code = str(row.province_code).zfill(2)
            self.summary[code] = {
                "province_code": code,
                "province_name": str(row.province_name),
                "major_road_length_km": 0.0,
                "major_road_segment_count": 0,
                "ferry_length_km": 0.0,
                "ferry_segment_count": 0,
                "ferry_terminal_count": 0,
                "port_count": 0,
                "marketplace_count": 0,
            }

    @lru_cache(maxsize=2_000_000)
    def _province(self, lon: float, lat: float) -> str | None:
        point = Point(float(lon), float(lat))
        candidates = list(self.sindex.query(point, predicate="intersects"))
        if not candidates:
            return None
        return str(self.provinces.iloc[int(candidates[0])]["province_code"]).zfill(2)

    @staticmethod
    def _poi_type(tags: Any) -> str | None:
        for (key, value), label in POI_TAGS.items():
            if tags.get(key) == value:
                return label
        if tags.get("harbour") not in {None, "", "no"}:
            return "port"
        return None

    def _record_poi(self, osm_type: str, osm_id: int, lon: float, lat: float, tags: Any) -> None:
        poi_type = self._poi_type(tags)
        if not poi_type:
            return
        code = self._province(lon, lat)
        if code is None:
            return
        self.summary[code][f"{poi_type}_count"] += 1
        self.poi_rows.append(
            {
                "osm_type": osm_type,
                "osm_id": int(osm_id),
                "feature_type": poi_type,
                "province_code": code,
                "province_name": self.summary[code]["province_name"],
                "name": tags.get("name"),
                "operator": tags.get("operator"),
                "longitude": float(lon),
                "latitude": float(lat),
            }
        )

    def node(self, node: Any) -> None:
        try:
            if node.location.valid():
                self._record_poi("node", node.id, node.location.lon, node.location.lat, node.tags)
        except Exception:
            return

    def way(self, way: Any) -> None:
        highway = way.tags.get("highway")
        is_road = highway in MAJOR_HIGHWAYS
        is_ferry = int(way.id) in self.ferry_way_ids or way.tags.get("route") == "ferry" or bool(way.tags.get("ferry"))
        poi_type = self._poi_type(way.tags)
        if not (is_road or is_ferry or poi_type):
            return
        coordinates: list[tuple[float, float]] = []
        try:
            for node in way.nodes:
                if node.location.valid():
                    coordinates.append((float(node.location.lon), float(node.location.lat)))
        except Exception:
            return
        if not coordinates:
            return
        if poi_type:
            middle = coordinates[len(coordinates) // 2]
            self._record_poi("way", way.id, middle[0], middle[1], way.tags)
        if len(coordinates) < 2:
            return

        mode = "ferry" if is_ferry else "road"
        edge_type = "ferry_connection" if is_ferry else "road_crossing"
        road_class = "ferry" if is_ferry else str(highway)
        province_codes = [self._province(lon, lat) for lon, lat in coordinates]
        for segment_index, ((lon1, lat1), (lon2, lat2)) in enumerate(
            zip(coordinates, coordinates[1:])
        ):
            _, _, distance_m = GEOD.inv(lon1, lat1, lon2, lat2)
            if not math.isfinite(distance_m) or distance_m <= 0:
                continue
            source = province_codes[segment_index]
            target = province_codes[segment_index + 1]
            # Almost every short road segment lies wholly within one province.
            # Reuse the endpoint classification and reserve an extra spatial
            # lookup for actual boundary/coverage ambiguity.
            midpoint_code = (
                source
                if source is not None and source == target
                else self._province((lon1 + lon2) / 2.0, (lat1 + lat2) / 2.0)
            )
            if midpoint_code:
                if mode == "road":
                    self.summary[midpoint_code]["major_road_length_km"] += distance_m / 1000.0
                    self.summary[midpoint_code]["major_road_segment_count"] += 1
                else:
                    self.summary[midpoint_code]["ferry_length_km"] += distance_m / 1000.0
                    self.summary[midpoint_code]["ferry_segment_count"] += 1
            if source and target and source != target:
                first, second = sorted((source, target))
                key = (first, second, edge_type, road_class)
                self.edge_accumulator[key]["segment_count"] += 1
                self.edge_accumulator[key]["length_km"] += distance_m / 1000.0


def extract_osm_transport(
    pbf_path: str | Path,
    *,
    provinces_path: str | Path,
    output_dir: str | Path,
    snapshot_date: str,
    source_url: str,
    save_parquet: bool = True,
) -> dict[str, Path]:
    """Extract province summaries and candidate transport edges from a PBF."""
    import osmium

    pbf = Path(pbf_path)
    provinces = gpd.read_file(provinces_path).to_crs(4326)
    required = {"province_code", "province_name"}
    missing = required.difference(provinces.columns)
    if missing:
        raise ValueError(f"Province geometry misses fields: {sorted(missing)}")
    provinces["province_code"] = provinces["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    provinces = provinces[["province_code", "province_name", "geometry"]].dropna(subset=["geometry"])
    provinces["geometry"] = provinces.geometry.make_valid()

    ferry_relations = _FerryRelations()
    ferry_relations.handler.apply_file(str(pbf))
    infrastructure = _InfrastructureHandler(provinces, ferry_relations.way_ids)
    infrastructure.handler.apply_file(str(pbf), locations=True, idx="flex_mem")

    generated = datetime.now(timezone.utc).isoformat()
    summary = pd.DataFrame(infrastructure.summary.values()).sort_values("province_code")
    summary["snapshot_date"] = snapshot_date
    summary["source"] = "OpenStreetMap via Geofabrik"
    summary["source_url"] = source_url
    summary["candidate_connectivity_only"] = 1
    pois = pd.DataFrame(infrastructure.poi_rows)
    if not pois.empty:
        pois["snapshot_date"] = snapshot_date
        pois["source"] = "OpenStreetMap via Geofabrik"
    edge_rows: list[dict[str, Any]] = []
    for (source, target, edge_type, road_class), values in infrastructure.edge_accumulator.items():
        edge_rows.append(
            {
                "source_province_code": source,
                "target_province_code": target,
                "edge_type": edge_type,
                "road_class": road_class,
                "segment_count": int(values["segment_count"]),
                "length_km": values["length_km"],
                "snapshot_date": snapshot_date,
                "edge_interpretation": "candidate_structural_connectivity",
                "source": "OpenStreetMap via Geofabrik",
                "source_url": source_url,
            }
        )
    edges = pd.DataFrame(edge_rows)
    if not edges.empty:
        edges = edges.sort_values(["source_province_code", "target_province_code", "edge_type", "road_class"])

    out = Path(output_dir)
    summary_outputs = save_frame(summary, out / "osm_province_transport_summary", save_csv=True, save_parquet=save_parquet)
    poi_outputs = save_frame(pois, out / "osm_infrastructure_points", save_csv=True, save_parquet=save_parquet)
    edge_outputs = save_frame(edges, out / "osm_transport_edges", save_csv=True, save_parquet=save_parquet)
    metadata_path = out / "osm_transport_metadata.json"
    save_json(
        {
            "created_at": generated,
            "snapshot_date": snapshot_date,
            "source_url": source_url,
            "source_sha256": _sha256(pbf),
            "source_bytes": pbf.stat().st_size,
            "province_rows": len(summary),
            "poi_rows": len(pois),
            "edge_rows": len(edges),
            "ferry_route_relations": ferry_relations.relation_count,
            "ferry_member_ways": len(ferry_relations.way_ids),
            "province_lookup_cache": {
                "hits": infrastructure._province.cache_info().hits,
                "misses": infrastructure._province.cache_info().misses,
                "current_size": infrastructure._province.cache_info().currsize,
            },
            "interpretation": "Candidate structural connectivity; not confirmed commodity shipments.",
        },
        metadata_path,
    )
    return {
        **{f"summary_{key}": value for key, value in summary_outputs.items()},
        **{f"points_{key}": value for key, value in poi_outputs.items()},
        **{f"edges_{key}": value for key, value in edge_outputs.items()},
        "metadata": metadata_path,
    }


def acquire_osm_transport(
    *,
    url: str,
    snapshot_date: str,
    raw_path: str | Path,
    provinces_path: str | Path,
    output_dir: str | Path,
    overwrite: bool = False,
    download_workers: int = 1,
) -> dict[str, Path]:
    pbf, download_metadata = download_geofabrik_snapshot(
        url,
        raw_path,
        overwrite=overwrite,
        workers=download_workers,
    )
    manifest_path = Path(output_dir) / "osm_download_manifest.json"
    save_json({**download_metadata, "snapshot_date": snapshot_date}, manifest_path)
    outputs = extract_osm_transport(
        pbf,
        provinces_path=provinces_path,
        output_dir=output_dir,
        snapshot_date=snapshot_date,
        source_url=url,
    )
    outputs["download_manifest"] = manifest_path
    return outputs
