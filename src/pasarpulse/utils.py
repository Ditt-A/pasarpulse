"""Shared IO, logging, hashing, and HTTP utilities."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def ensure_parent(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def get_logger(name: str = "pasarpulse", log_file: str | Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_file:
        target = ensure_parent(log_file)
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def build_session(user_agent: str = "PasarPulse-MM/0.5 academic-research") -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": user_agent})
    return session


def stream_download(url: str, output: str | Path, chunk_size: int = 1024 * 1024) -> Path:
    target = ensure_parent(output)
    with build_session().get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    handle.write(chunk)
    return target


def md5sum(path: str | Path) -> str:
    digest = hashlib.md5()  # nosec B324: checksum verification only
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(data: Any, path: str | Path) -> Path:
    target = ensure_parent(path)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def save_frame(
    frame: pd.DataFrame,
    base_path: str | Path,
    *,
    save_csv: bool = True,
    save_parquet: bool = True,
    index: bool = False,
) -> dict[str, Path]:
    """Save a dataframe to CSV and/or Parquet using one extensionless base path."""
    base = Path(base_path)
    if base.suffix:
        base = base.with_suffix("")
    outputs: dict[str, Path] = {}
    if save_csv:
        csv_path = ensure_parent(base.with_suffix(".csv"))
        frame.to_csv(csv_path, index=index)
        outputs["csv"] = csv_path
    if save_parquet:
        parquet_path = ensure_parent(base.with_suffix(".parquet"))
        try:
            frame.to_parquet(parquet_path, index=index)
            outputs["parquet"] = parquet_path
        except ImportError:
            # CSV remains the portable primary artifact when a runtime does
            # not ship pyarrow/fastparquet.  Remote VM environments can still
            # enable Parquet without changing the pipeline code.
            pass
    return outputs


def read_table(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path, **kwargs)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, **kwargs)
    return pd.read_csv(path, **kwargs)


def first_existing(*paths: str | Path | None) -> Path | None:
    for raw in paths:
        if raw is None:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None
