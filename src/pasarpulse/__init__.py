"""PasarPulse-MM modular data-ingestion and feature-engineering package.

The public API intentionally exposes only the orchestration layer, configuration,
credential checks, and project paths. Individual ingestion tools live in
``src.pasarpulse.tools`` and can also be imported independently.
"""
from __future__ import annotations

from pathlib import Path

from .config import PipelineConfig, load_config
from .credentials import credential_status, load_project_credentials
from .pipeline import PasarPulsePipeline

__version__ = "0.6.0"
__author__ = "PasarPulse-MM Team"

PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_DIR.parent

__all__ = [
    "__version__",
    "__author__",
    "PACKAGE_DIR",
    "SRC_DIR",
    "PROJECT_ROOT",
    "PipelineConfig",
    "load_config",
    "PasarPulsePipeline",
    "load_project_credentials",
    "credential_status",
]
