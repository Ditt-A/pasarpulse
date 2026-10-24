"""Pydantic contracts exposed by the PasarPulse API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class HistoricalEvaluation(BaseModel):
    available: bool
    realized_price: Optional[float] = None
    absolute_error: Optional[float] = None
    label: str = "Historical evaluation — not available to the model at forecast time"


class ForecastRecord(BaseModel):
    forecast_id: str
    series_id: str
    province_code: str
    province_name: str
    commodity_code: str
    commodity_name: str
    market_level: str
    forecast_origin: str
    target_date: str
    horizon_days: int
    current_price: float
    predicted_price: float
    projected_change: float
    projected_change_pct: float
    warning_level: str
    model: str
    model_version: Optional[str] = None
    data_version: Optional[str] = None
    feature_version: Optional[str] = None
    evidence_status: str = "DETAIL_UNAVAILABLE"
    evidence_quality_score: Optional[float] = None
    attribution_available: bool = False
    interval_available: bool = False
    shock_probability_available: bool = False
    propagation_available: bool = False
    abstention_required: bool = False
    historical_evaluation: HistoricalEvaluation


class MapFeature(BaseModel):
    type: str = "Feature"
    properties: dict[str, Any]
    geometry: dict[str, Any]


class ProvinceList(BaseModel):
    type: str = "FeatureCollection"
    features: list[MapFeature]


class EvidenceItem(BaseModel):
    evidence_id: str
    modality: str
    status: str
    available: bool
    observation_date: Optional[str] = None
    observation_age_days: Optional[float] = None
    source: Optional[str] = None
    note: Optional[str] = None
    is_model_attribution: bool = False
    # This is feature-contract membership, not feature importance.  Keep the
    # distinction explicit in the API so the UI and Copilot cannot turn
    # availability masks into attribution claims.
    used_by_model: bool = False
    values: dict[str, Any] = Field(default_factory=dict)


class EvidenceResponse(BaseModel):
    forecast_id: str
    evidence_quality_score: Optional[float] = None
    evidence_quality_label: str = "Not available for this forecast artifact"
    items: list[EvidenceItem]
    attribution_available: bool = False
    attribution_note: str = "Model attribution is not available for this snapshot."
    abstention_required: bool = False
    abstention_reason: Optional[str] = None
    model: Optional[str] = None
    model_feature_contract: Optional[str] = None
    model_modalities: list[str] = Field(default_factory=list)


class XaiDriver(BaseModel):
    rank: int
    feature: str
    feature_value: str | float | int | None = None
    contribution_logratio: float


class AuditedXaiSample(BaseModel):
    """A saved, held-out LightGBM explanation; not an attribution for replay rows."""

    case_id: str
    selection_rule: str
    model: str
    horizon_days: int
    forecast_origin: str
    province_name: str
    commodity_name: str
    market_level: str
    drivers: list[XaiDriver]


class ForecastXai(BaseModel):
    """Native LightGBM prediction drivers for one deployed replay forecast."""

    forecast_id: str
    model: str
    horizon_days: int
    forecast_origin: str
    drivers: list[XaiDriver]


class AlertRecord(ForecastRecord):
    alert_id: str
    priority: int


class CopilotContext(BaseModel):
    province_code: Optional[str] = None
    province_name: Optional[str] = None
    commodity_code: Optional[str] = None
    commodity_name: Optional[str] = None
    market_level: Optional[str] = None
    horizon_days: Optional[int] = None
    forecast_origin: Optional[str] = None


class CopilotQuery(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: CopilotContext = Field(default_factory=CopilotContext)


class CopilotReason(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


AllowedAnalystAction = Literal[
    "VERIFY_MARKET_PRICE",
    "VERIFY_SUPPLY",
    "REVIEW_DISTRIBUTION",
    "REVIEW_LOGISTICS",
    "ESCALATE_HUMAN_REVIEW",
    "ABSTAIN",
]


class AnalystAction(BaseModel):
    action_id: AllowedAnalystAction
    evidence_ids: list[str] = Field(default_factory=list)


class DashboardAction(BaseModel):
    type: str
    value: Any = None


class CopilotResponse(BaseModel):
    summary: str
    reasons: list[CopilotReason] = Field(default_factory=list)
    actions: list[AnalystAction] = Field(default_factory=list)
    dashboard_actions: list[DashboardAction] = Field(default_factory=list)
    abstained: bool = False
    mode: str = "Gemini structured evidence mode"
    validation_note: Optional[str] = None


class HealthComponent(BaseModel):
    status: Literal["healthy", "partial", "missing", "disabled"]
    path: Optional[str] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    app: str
    mode: str
    forecast_artifact: HealthComponent
    evidence_artifact: HealthComponent
    geography: HealthComponent
    reasoning_service: HealthComponent
