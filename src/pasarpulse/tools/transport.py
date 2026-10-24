"""Direct download of the Geofabrik Indonesia OSM extract.

The PBF is retained as a raw transport-topology source. The default MVP graph
builder uses province adjacency, distance, and production similarity so the
pipeline remains lightweight; road/port parsing can be added without changing
its data contract.
"""
from __future__ import annotations

from pathlib import Path

from ..utils import build_session, md5sum, stream_download

DEFAULT_URL = "https://download.geofabrik.de/asia/indonesia-latest.osm.pbf"


def download_geofabrik(
    output: str | Path,
    *,
    url: str = DEFAULT_URL,
    verify_checksum: bool = True,
) -> Path:
    target = stream_download(url, output)
    if verify_checksum:
        response = build_session().get(url + ".md5", timeout=60)
        response.raise_for_status()
        expected = response.text.strip().split()[0].lower()
        actual = md5sum(target).lower()
        if expected != actual:
            Path(target).unlink(missing_ok=True)
            raise RuntimeError(f"Geofabrik MD5 mismatch: expected {expected}, got {actual}")
    return target
