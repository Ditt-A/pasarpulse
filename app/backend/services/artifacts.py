"""Read-only artifact repository for replay, evidence, geography, and metadata."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..config import (
    BENCHMARK_PATH,
    EVIDENCE_PATH,
    FORECAST_PATH,
    GEOGRAPHY_PATH,
    MANIFEST_PATH,
    MODE,
    REPO_ROOT,
    SCHEMA_VERSION,
    SUPPORTED_HORIZONS,
    THRESHOLDS,
    XAI_CASE_TOP5_PATH,
    XAI_FORECAST_TOP5_PATH,
)
from ..rules import classify_warning, projected_change_pct, warning_rank
from ..schemas import (
    EvidenceItem,
    EvidenceResponse,
    ForecastRecord,
    HistoricalEvaluation,
    AuditedXaiSample,
    ForecastXai,
    XaiDriver,
)


def _safe_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clean_code(value: Any) -> str:
    match = re.search(r"\d+", str(value))
    return match.group(0).zfill(2) if match else str(value).strip()


def _json_load(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def load_audited_xai_samples(path: Path = XAI_CASE_TOP5_PATH) -> list[AuditedXaiSample]:
    """Load saved held-out native-LightGBM samples without attributing replay rows."""

    required = {
        "case_id", "model", "horizon_days", "rank", "feature", "feature_value",
        "contribution_logratio", "province_name", "commodity_name", "market_level", "date",
    }
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return []
    if required - set(frame.columns):
        return []

    manifest = _json_load(path.with_name("xai_run_manifest.json"), {})
    selection_rule = str(manifest.get("selection_rule", "Held-out native LightGBM attribution sample."))
    samples: list[AuditedXaiSample] = []
    for case_id, group in frame.groupby("case_id", sort=False):
        ranked = group.sort_values("rank").head(5)
        first = ranked.iloc[0]
        try:
            drivers = [
                XaiDriver(
                    rank=int(row["rank"]),
                    feature=str(row["feature"]),
                    feature_value=row["feature_value"],
                    contribution_logratio=float(row["contribution_logratio"]),
                )
                for _, row in ranked.iterrows()
            ]
            samples.append(
                AuditedXaiSample(
                    case_id=str(case_id),
                    selection_rule=selection_rule,
                    model=str(first["model"]),
                    horizon_days=int(first["horizon_days"]),
                    forecast_origin=str(first["date"]),
                    province_name=str(first["province_name"]),
                    commodity_name=str(first["commodity_name"]),
                    market_level=str(first["market_level"]),
                    drivers=drivers,
                )
            )
        except (TypeError, ValueError):
            continue
    return samples


def load_forecast_xai(forecast_id: str, path: Path = XAI_FORECAST_TOP5_PATH) -> ForecastXai | None:
    """Load a verified native contribution set for one replay forecast only."""

    required = {
        "forecast_id", "rank", "feature", "feature_value", "contribution_logratio",
        "model", "horizon_days", "forecast_origin",
    }
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if required - set(frame.columns):
        return None
    rows = frame.loc[frame["forecast_id"].astype(str).eq(forecast_id)].sort_values("rank")
    if len(rows) != 5 or rows["rank"].tolist() != [1, 2, 3, 4, 5]:
        return None
    forbidden_names = {
        "target_price", "target_logratio", "target_scaled_delta", "target_delta", "threshold_exceeded",
    }
    if rows["feature"].astype(str).isin(forbidden_names).any() or rows["feature"].astype(str).str.startswith("future_").any():
        return None
    first = rows.iloc[0]
    try:
        drivers = [
            XaiDriver(
                rank=int(row["rank"]),
                feature=str(row["feature"]),
                feature_value=row["feature_value"],
                contribution_logratio=float(row["contribution_logratio"]),
            )
            for _, row in rows.iterrows()
        ]
        return ForecastXai(
            forecast_id=forecast_id,
            model=str(first["model"]),
            horizon_days=int(first["horizon_days"]),
            forecast_origin=str(first["forecast_origin"]),
            drivers=drivers,
        )
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RuntimeMode:
    name: str
    label: str
    forecast_available: bool
    detail: str


def resolve_mode(forecast_path: Path = FORECAST_PATH, configured: str = MODE) -> RuntimeMode:
    """Resolve one explicit product mode without requiring a live data source."""

    normalized = configured.lower().strip()
    if normalized in {"benchmark", "benchmark_only"}:
        return RuntimeMode("benchmark_only", "BENCHMARK ONLY", False, "Forecast snapshot was disabled by configuration.")
    if normalized in {"replay", "historical_replay"}:
        if forecast_path.exists():
            return RuntimeMode("historical_replay", "HISTORICAL REPLAY", True, "Forecast-as-of replay from a saved chronological evaluation artifact.")
        return RuntimeMode("benchmark_only", "BENCHMARK ONLY", False, "Configured replay artifact is unavailable.")
    inference_path = os.getenv("PASARPULSE_INFERENCE_PATH", "").strip()
    if normalized in {"inference", "inference_snapshot"} or (normalized == "auto" and inference_path):
        candidate = Path(inference_path).expanduser() if inference_path else forecast_path
        if candidate.exists():
            return RuntimeMode("inference_snapshot", "INFERENCE SNAPSHOT", True, "Loaded from a prepared inference artifact; no training occurs at runtime.")
        return RuntimeMode("benchmark_only", "BENCHMARK ONLY", False, "Inference snapshot is unavailable.")
    if forecast_path.exists():
        return RuntimeMode("historical_replay", "HISTORICAL REPLAY", True, "Forecast-as-of replay from a saved chronological evaluation artifact.")
    return RuntimeMode("benchmark_only", "BENCHMARK ONLY", False, "No forecast snapshot is available; benchmark and methodology views remain active.")


class ArtifactValidationError(ValueError):
    pass


class ForecastStore:
    """Immutable in-memory read model. It never reads target values for alerts."""

    def __init__(
        self,
        forecast_path: Path = FORECAST_PATH,
        evidence_path: Path = EVIDENCE_PATH,
        geography_path: Path = GEOGRAPHY_PATH,
        manifest_path: Path = MANIFEST_PATH,
    ) -> None:
        self.forecast_path = Path(forecast_path)
        self.evidence_path = Path(evidence_path)
        self.geography_path = Path(geography_path)
        self.manifest_path = Path(manifest_path)
        self.mode = resolve_mode(self.forecast_path)
        self.llm_enabled = False
        self._frame = self._load_forecasts()
        self._evidence = self._load_evidence()
        self._geojson = self._load_geojson()
        self.manifest = _json_load(self.manifest_path, {})

    @property
    def available(self) -> bool:
        return not self._frame.empty

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy()

    def _load_forecasts(self) -> pd.DataFrame:
        if not self.forecast_path.exists():
            return pd.DataFrame()
        try:
            frame = pd.read_parquet(self.forecast_path) if self.forecast_path.suffix in {".parquet", ".pq"} else pd.read_csv(self.forecast_path)
        except Exception as exc:  # pragma: no cover - exact parser errors differ by engine
            raise ArtifactValidationError(f"Forecast snapshot could not be loaded: {exc}") from exc
        required = {
            "forecast_id", "series_id", "province_code", "province_name", "commodity_code",
            "commodity_name", "market_level", "forecast_origin", "target_date", "horizon_days",
            "current_price", "predicted_price", "model",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ArtifactValidationError(f"Forecast snapshot is missing fields: {missing}")
        frame = frame.copy()
        frame["province_code"] = frame["province_code"].map(_clean_code)
        frame["forecast_origin"] = pd.to_datetime(frame["forecast_origin"], errors="raise").dt.strftime("%Y-%m-%d")
        frame["target_date"] = pd.to_datetime(frame["target_date"], errors="raise").dt.strftime("%Y-%m-%d")
        frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="raise").astype(int)
        if set(frame["horizon_days"]) - set(SUPPORTED_HORIZONS):
            raise ArtifactValidationError("Forecast snapshot contains an unsupported horizon")
        if (pd.to_datetime(frame["target_date"]) < pd.to_datetime(frame["forecast_origin"])).any():
            raise ArtifactValidationError("target_date precedes forecast_origin")
        if ((pd.to_datetime(frame["target_date"]) - pd.to_datetime(frame["forecast_origin"])).dt.days != frame["horizon_days"]).any():
            raise ArtifactValidationError("target_date does not equal forecast_origin + horizon_days")
        for column in ["current_price", "predicted_price"]:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
            if (~frame[column].map(math.isfinite)).any():
                raise ArtifactValidationError(f"{column} contains non-finite values")
        if (frame["current_price"] <= 0).any() or (frame["predicted_price"] < 0).any():
            raise ArtifactValidationError("Forecast prices must be non-negative and current_price must be positive")
        key_columns = ["series_id", "forecast_origin", "horizon_days", "model"]
        if frame.duplicated(key_columns).any():
            raise ArtifactValidationError("Forecast snapshot contains duplicate logical keys")

        # Recompute product fields from forecast-time inputs. This protects the
        # API if someone edits a derived CSV column and also proves target_price
        # is not part of alert/ranking logic.
        frame["projected_change"] = frame.apply(lambda row: row["predicted_price"] - row["current_price"], axis=1)
        frame["projected_change_pct"] = [
            projected_change_pct(current, predicted)
            for current, predicted in zip(frame["current_price"], frame["predicted_price"])
        ]
        frame["warning_level"] = [classify_warning(value, THRESHOLDS) for value in frame["projected_change_pct"]]
        frame["actual_available"] = frame.get("target_price", pd.Series(index=frame.index, dtype=float)).notna()
        frame["province_code"] = frame["province_code"].astype(str)
        return frame.sort_values(["forecast_origin", "horizon_days", "province_code", "commodity_code", "market_level"]).reset_index(drop=True)

    def _load_evidence(self) -> dict[str, dict[str, Any]]:
        raw = _json_load(self.evidence_path, [])
        if isinstance(raw, dict):
            raw = raw.get("records", [])
        return {str(item.get("forecast_id")): item for item in raw if isinstance(item, dict) and item.get("forecast_id")}

    def _load_geojson(self) -> dict[str, Any]:
        payload = _json_load(self.geography_path, {"type": "FeatureCollection", "features": []})
        if payload.get("type") != "FeatureCollection":
            raise ArtifactValidationError("Province geography must be a GeoJSON FeatureCollection")
        features = payload.get("features", [])
        if features and len(features) != 38:
            raise ArtifactValidationError(f"Expected 38 province geometries, found {len(features)}")
        return payload

    def origins(self) -> list[str]:
        return sorted(self._frame["forecast_origin"].unique().tolist(), reverse=True) if self.available else []

    def latest_origin(self) -> str | None:
        return self.origins()[0] if self.origins() else None

    def query(
        self,
        origin: str | None = None,
        commodity: str | None = None,
        market_level: str | None = None,
        horizon: int | None = None,
        province_code: str | None = None,
        model: str | None = None,
    ) -> pd.DataFrame:
        frame = self._frame.copy()
        if frame.empty:
            return frame
        if origin in {None, "", "latest"}:
            origin = self.latest_origin()
        if origin:
            frame = frame.loc[frame["forecast_origin"].eq(str(origin))]
        if commodity:
            frame = frame.loc[frame["commodity_code"].eq(str(commodity))]
        if market_level:
            frame = frame.loc[frame["market_level"].eq(str(market_level))]
        if horizon:
            frame = frame.loc[frame["horizon_days"].eq(int(horizon))]
        if province_code:
            frame = frame.loc[frame["province_code"].eq(_clean_code(province_code))]
        if model:
            frame = frame.loc[frame["model"].eq(str(model))]
        return frame.copy()

    def _model_version(self, row: pd.Series) -> str | None:
        value = row.get("model_version")
        return None if pd.isna(value) else str(value)

    def record_from_row(self, row: pd.Series, reveal: bool = False) -> ForecastRecord:
        target = _safe_float(row.get("target_price")) if reveal else None
        historical = HistoricalEvaluation(
            available=bool(row.get("actual_available", False)),
            realized_price=target,
            absolute_error=abs(target - float(row["predicted_price"])) if target is not None else None,
        )
        return ForecastRecord(
            forecast_id=str(row["forecast_id"]),
            series_id=str(row["series_id"]),
            province_code=str(row["province_code"]),
            province_name=str(row["province_name"]),
            commodity_code=str(row["commodity_code"]),
            commodity_name=str(row["commodity_name"]),
            market_level=str(row["market_level"]),
            forecast_origin=str(row["forecast_origin"]),
            target_date=str(row["target_date"]),
            horizon_days=int(row["horizon_days"]),
            current_price=float(row["current_price"]),
            predicted_price=float(row["predicted_price"]),
            projected_change=float(row["projected_change"]),
            projected_change_pct=float(row["projected_change_pct"]),
            warning_level=str(row["warning_level"]),
            model=str(row["model"]),
            model_version=self._model_version(row),
            data_version=self._model_version(pd.Series({"model_version": row.get("data_version")})),
            feature_version=self._model_version(pd.Series({"model_version": row.get("feature_version")})),
            evidence_status="AVAILABLE_CONTEXT",
            evidence_quality_score=_safe_float(row.get("evidence_quality_score")),
            attribution_available=bool(row.get("attribution_available", False)),
            interval_available=bool(row.get("interval_available", False)),
            shock_probability_available=bool(row.get("shock_probability_available", False)),
            propagation_available=bool(row.get("propagation_available", False)),
            abstention_required=bool(row.get("abstention_required", False)),
            historical_evaluation=historical,
        )

    def records(self, **filters: Any) -> list[ForecastRecord]:
        reveal = bool(filters.pop("reveal", False))
        return [self.record_from_row(row, reveal=reveal) for _, row in self.query(**filters).iterrows()]

    def by_id(self, forecast_id: str, reveal: bool = False) -> ForecastRecord | None:
        if self._frame.empty:
            return None
        match = self._frame.loc[self._frame["forecast_id"].eq(forecast_id)]
        if match.empty:
            return None
        return self.record_from_row(match.iloc[0], reveal=reveal)

    def row_by_id(self, forecast_id: str) -> pd.Series | None:
        if self._frame.empty:
            return None
        match = self._frame.loc[self._frame["forecast_id"].eq(forecast_id)]
        return None if match.empty else match.iloc[0]

    def evidence_for(self, forecast_id: str) -> EvidenceResponse:
        raw = self._evidence.get(forecast_id, {})
        items = [EvidenceItem(**item) for item in raw.get("items", [])]
        return EvidenceResponse(
            forecast_id=forecast_id,
            evidence_quality_score=_safe_float(raw.get("evidence_quality_score")),
            evidence_quality_label="Source quality score not available for this forecast artifact" if raw.get("evidence_quality_score") is None else "Source quality metadata",
            items=items,
            attribution_available=bool(raw.get("attribution_available", False)),
            attribution_note=str(raw.get("attribution_note", "Model attribution is not available for this snapshot.")),
            abstention_required=bool(raw.get("abstention_required", False)),
            abstention_reason=raw.get("abstention_reason"),
            model=raw.get("model"),
            model_feature_contract=raw.get("model_feature_contract"),
            model_modalities=[str(value) for value in raw.get("model_modalities", [])],
        )

    def geojson(self, **filters: Any) -> dict[str, Any]:
        payload = json.loads(json.dumps(self._geojson))
        summary = self.query(**filters)
        by_province: dict[str, pd.Series] = {}
        if not summary.empty:
            # One selected commodity/market/horizon should normally yield one
            # row per province. Keep the largest projected movement if a caller
            # intentionally requests several commodities.
            for code, group in summary.groupby("province_code"):
                by_province[str(code)] = group.sort_values("projected_change_pct", ascending=False).iloc[0]
        for feature in payload.get("features", []):
            props = feature.setdefault("properties", {})
            code = _clean_code(props.get("province_code", props.get("code", "")))
            row = by_province.get(code)
            props["province_code"] = code
            props["has_forecast"] = row is not None
            if row is None:
                props.update({"warning_level": "INSUFFICIENT", "projected_change_pct": None, "forecast_id": None, "evidence_status": "INSUFFICIENT"})
            else:
                props.update(
                    {
                        "province_name": str(row["province_name"]),
                        "has_forecast": True,
                        "warning_level": str(row["warning_level"]),
                        "projected_change_pct": float(row["projected_change_pct"]),
                        "forecast_id": str(row["forecast_id"]),
                        "evidence_status": "AVAILABLE_CONTEXT",
                    }
                )
        return payload

    def metadata(self) -> dict[str, Any]:
        frame = self._frame
        return {
            "app": "PasarPulse",
            "subtitle": "National Food Price Early-Warning Intelligence",
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode.name,
            "mode_label": self.mode.label,
            "mode_detail": self.mode.detail,
            "forecast_available": self.available,
            "forecast_path": str(self.forecast_path),
            "evidence_path": str(self.evidence_path),
            "geography_path": str(self.geography_path),
            "forecast_origins": self.origins(),
            "latest_origin": self.latest_origin(),
            "horizons": sorted(int(value) for value in frame["horizon_days"].unique()) if self.available else [],
            "commodities": self.options("commodity_code", "commodity_name"),
            "market_levels": sorted(frame["market_level"].unique().tolist()) if self.available else [],
            "models": sorted(frame["model"].unique().tolist()) if self.available else [],
            "province_count_in_forecast": int(frame["province_code"].nunique()) if self.available else 0,
            "province_count_in_geometry": len(self._geojson.get("features", [])),
            "warning_thresholds": {"watch": THRESHOLDS.watch, "elevated": THRESHOLDS.elevated, "high": THRESHOLDS.high},
            "warning_note": "Product warning thresholds; not model probabilities or regulatory thresholds.",
            "unsupported_outputs": [
                "shock_probability",
                "propagation_probability",
                "SHAP / TimeSHAP / GNN explanations",
                "uncertainty intervals",
            ],
            "manifest": self.manifest,
        }

    def options(self, code_column: str, name_column: str) -> list[dict[str, str]]:
        if self._frame.empty:
            return []
        pairs = self._frame[[code_column, name_column]].drop_duplicates().sort_values(code_column)
        return [{"code": str(row[code_column]), "name": str(row[name_column])} for _, row in pairs.iterrows()]

    def alerts(self, **filters: Any) -> list[tuple[pd.Series, int]]:
        frame = self.query(**filters)
        if frame.empty:
            return []
        frame = frame.assign(_warning_rank=frame["warning_level"].map(warning_rank))
        frame = frame.sort_values(["_warning_rank", "projected_change_pct"], ascending=[False, False])
        return [(row, index + 1) for index, (_, row) in enumerate(frame.iterrows())]

    def alert_id(self, row: pd.Series) -> str:
        return "ALT-{origin}-{province}-{commodity}-{market}-{horizon}".format(
            origin=str(row["forecast_origin"]).replace("-", ""),
            province=str(row["province_code"]),
            commodity=str(row["commodity_code"]),
            market=str(row["market_level"]).upper(),
            horizon=int(row["horizon_days"]),
        )

    def geometry_component(self) -> dict[str, Any]:
        path = self.geography_path if self.geography_path.exists() else None
        status = "healthy" if path and len(self._geojson.get("features", [])) == 38 else "partial"
        return {"status": status, "path": str(path) if path else None, "detail": "Canonical 38-province BIG GeoJSON" if path else "Province geometry unavailable"}


def benchmark_paths() -> Iterable[Path]:
    if not BENCHMARK_PATH.exists():
        return []
    return [
        BENCHMARK_PATH / "summary_metrics.csv",
        BENCHMARK_PATH / "finalist_pooled_metrics.csv",
        BENCHMARK_PATH / "meta_metrics.csv",
        BENCHMARK_PATH / "proposed_model_run" / "pooled_metrics.csv",
        BENCHMARK_PATH / "multimodal_ablation" / "pooled_metrics.csv",
        BENCHMARK_PATH / "clean_metrics" / "early_warning_metrics.csv",
    ]
