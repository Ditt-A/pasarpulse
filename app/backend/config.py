"""Runtime configuration for the offline-first PasarPulse API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WarningThresholds:
    """Product warning thresholds, expressed as positive percentage movement."""

    watch: float = 5.0
    elevated: float = 10.0
    high: float = 15.0


THRESHOLDS = WarningThresholds(
    watch=float(os.getenv("PASARPULSE_WARNING_WATCH", "5")),
    elevated=float(os.getenv("PASARPULSE_WARNING_ELEVATED", "10")),
    high=float(os.getenv("PASARPULSE_WARNING_HIGH", "15")),
)


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser() if value else default


FORECAST_PATH = _env_path(
    "PASARPULSE_FORECAST_PATH", REPO_ROOT / "demo_data" / "forecasts" / "forecast_snapshot.csv"
)
EVIDENCE_PATH = _env_path(
    "PASARPULSE_EVIDENCE_PATH", REPO_ROOT / "demo_data" / "evidence" / "evidence_snapshot.json"
)
BENCHMARK_PATH = _env_path("PASARPULSE_BENCHMARK_PATH", REPO_ROOT / "results")
GEOGRAPHY_PATH = _env_path(
    "PASARPULSE_GEOGRAPHY_PATH", REPO_ROOT / "demo_data" / "geography" / "indonesia_provinces.geojson"
)
MANIFEST_PATH = _env_path(
    "PASARPULSE_MANIFEST_PATH", REPO_ROOT / "demo_data" / "manifests" / "forecast_manifest.json"
)
XAI_CASE_TOP5_PATH = _env_path(
    "PASARPULSE_XAI_CASE_TOP5_PATH", REPO_ROOT / "results" / "xai_validation" / "xai_case_top5.csv"
)
XAI_FORECAST_TOP5_PATH = _env_path(
    "PASARPULSE_XAI_FORECAST_TOP5_PATH", REPO_ROOT / "results" / "dashboard_xai" / "forecast_top5.csv"
)

MODE = os.getenv("PASARPULSE_MODE", "auto").strip().lower()
LLM_API_KEY = os.getenv("PASARPULSE_LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("PASARPULSE_LLM_MODEL", "gemini-3.5-flash-lite").strip()
LLM_THINKING_LEVEL = os.getenv("PASARPULSE_GEMINI_THINKING_LEVEL", "high").strip().lower()
LLM_TIMEOUT_SECONDS = float(os.getenv("PASARPULSE_LLM_TIMEOUT_SECONDS", "20"))

SUPPORTED_HORIZONS = (7, 14)
APP_NAME = "PasarPulse"
APP_SUBTITLE = "National Food Price Early-Warning Intelligence"
SCHEMA_VERSION = "pasarpulse-demo-v1"
