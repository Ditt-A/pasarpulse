"""FastAPI service for the PasarPulse operational intelligence demo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_NAME, APP_SUBTITLE, LLM_API_KEY, REPO_ROOT, THRESHOLDS
from .reasoning.service import CopilotError, CopilotService
from .schemas import (
    AlertRecord,
    AuditedXaiSample,
    ForecastXai,
    CopilotQuery,
    CopilotResponse,
    ForecastRecord,
    HealthComponent,
    HealthResponse,
    ProvinceList,
)
from .services.artifacts import ArtifactValidationError, ForecastStore, load_audited_xai_samples, load_forecast_xai
from .services.benchmarks import load_benchmarks


startup_error: str | None = None
try:
    store = ForecastStore()
except Exception as exc:  # fail into benchmark-only instead of blocking the UI
    startup_error = str(exc)
    store = ForecastStore(forecast_path=Path("/__pasarpulse_missing_forecast_snapshot.csv"))
store.llm_enabled = bool(LLM_API_KEY)
copilot = CopilotService(store)

app = FastAPI(
    title=f"{APP_NAME} API",
    description=f"{APP_SUBTITLE}. Offline artifact serving and grounded analyst interaction.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _filters(
    origin: str | None,
    commodity: str | None,
    market_level: str | None,
    horizon: int | None,
    province_code: str | None,
    model: str | None,
) -> dict[str, Any]:
    return {
        "origin": origin,
        "commodity": commodity,
        "market_level": market_level,
        "horizon": horizon,
        "province_code": province_code,
        "model": model,
    }


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    forecast_status = "healthy" if store.available else "missing"
    evidence_status = "healthy" if store.evidence_path.exists() else "missing"
    geo = store.geometry_component()
    if startup_error:
        forecast_detail = f"Forecast snapshot unavailable; benchmark-only fallback active. {startup_error}"
    elif store.available:
        forecast_detail = f"{len(store._frame):,} replay rows loaded without runtime training."
    else:
        forecast_detail = "Forecast snapshot unavailable; benchmark-only fallback active."
    return HealthResponse(
        app="healthy",
        mode=store.mode.name,
        forecast_artifact=HealthComponent(status=forecast_status, path=str(store.forecast_path), detail=forecast_detail),
        evidence_artifact=HealthComponent(status=evidence_status, path=str(store.evidence_path), detail="Structured availability/freshness evidence" if evidence_status == "healthy" else "Evidence artifact unavailable"),
        geography=HealthComponent(status=geo["status"], path=geo["path"], detail=geo["detail"]),
        reasoning_service=HealthComponent(
            status="healthy" if LLM_API_KEY else "disabled",
            detail="Gemini structured mode configured; no answer fallback is enabled."
            if LLM_API_KEY
            else "Gemini key not configured; Copilot requests return an explicit configuration error.",
        ),
    )


@app.get("/metadata")
def metadata() -> dict[str, Any]:
    payload = store.metadata()
    payload["benchmarks_available"] = len(load_benchmarks()) > 0
    payload["startup_warning"] = startup_error
    payload["product_identity"] = {"name": APP_NAME, "subtitle": APP_SUBTITLE, "tagline": "From monitoring what happened to anticipating what may happen next."}
    return payload


@app.get("/origins")
def origins() -> dict[str, Any]:
    return {"origins": store.origins(), "latest_origin": store.latest_origin()}


@app.get("/forecasts", response_model=list[ForecastRecord])
def forecasts(
    origin: str | None = None,
    commodity: str | None = None,
    market_level: str | None = None,
    horizon: int | None = Query(default=None, ge=1, le=365),
    province_code: str | None = None,
    model: str | None = None,
    reveal: bool = False,
) -> list[ForecastRecord]:
    return store.records(**_filters(origin, commodity, market_level, horizon, province_code, model), reveal=reveal)


@app.get("/forecasts/{forecast_id}", response_model=ForecastRecord)
def forecast_detail(forecast_id: str, reveal: bool = False) -> ForecastRecord:
    record = store.by_id(forecast_id, reveal=reveal)
    if record is None:
        raise HTTPException(status_code=404, detail="Forecast snapshot unavailable for this forecast ID.")
    return record


@app.get("/provinces", response_model=ProvinceList)
def provinces(
    origin: str | None = None,
    commodity: str | None = None,
    market_level: str | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    return store.geojson(origin=origin, commodity=commodity, market_level=market_level, horizon=horizon)


@app.get("/commodities")
def commodities() -> list[dict[str, str]]:
    return store.options("commodity_code", "commodity_name")


@app.get("/alerts", response_model=list[AlertRecord])
def alerts(
    origin: str | None = None,
    commodity: str | None = None,
    market_level: str | None = None,
    horizon: int | None = None,
    province_code: str | None = None,
    risk: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AlertRecord]:
    rows = store.alerts(**_filters(origin, commodity, market_level, horizon, province_code, None))
    wanted = {item.upper() for item in risk}
    output: list[AlertRecord] = []
    for row, priority in rows:
        if wanted and str(row["warning_level"]).upper() not in wanted:
            continue
        record = store.record_from_row(row)
        data = _dump(record)
        data["alert_id"] = store.alert_id(row)
        data["priority"] = priority
        output.append(AlertRecord(**data))
        if len(output) >= limit:
            break
    return output


@app.get("/alerts/{alert_id}", response_model=AlertRecord)
def alert_detail(alert_id: str) -> AlertRecord:
    for row, priority in store.alerts():
        if store.alert_id(row) == alert_id:
            record = store.record_from_row(row)
            data = _dump(record)
            data["alert_id"] = alert_id
            data["priority"] = priority
            return AlertRecord(**data)
    raise HTTPException(status_code=404, detail="Alert unavailable for this snapshot.")


@app.get("/evidence/{forecast_id}")
def evidence(forecast_id: str) -> dict[str, Any]:
    if store.row_by_id(forecast_id) is None:
        raise HTTPException(status_code=404, detail="Evidence unavailable for this forecast ID.")
    return _dump(store.evidence_for(forecast_id))


@app.get("/xai/audited-samples", response_model=list[AuditedXaiSample])
def audited_xai_samples() -> list[AuditedXaiSample]:
    """Saved held-out attribution samples, intentionally separate from replay rows."""

    return load_audited_xai_samples()


@app.get("/xai/forecasts/{forecast_id}", response_model=ForecastXai)
def forecast_xai(forecast_id: str) -> ForecastXai:
    if store.row_by_id(forecast_id) is None:
        raise HTTPException(status_code=404, detail="Forecast snapshot unavailable for this forecast ID.")
    explanation = load_forecast_xai(forecast_id)
    if explanation is None:
        raise HTTPException(status_code=404, detail="Verified XAI is not available for this forecast yet.")
    return explanation


@app.get("/benchmarks")
def benchmarks() -> dict[str, Any]:
    rows = load_benchmarks()
    return {
        "rows": rows,
        "headline_rows": [row for row in rows if row["headline_eligible"]],
        "excluded_rows": [row for row in rows if not row["headline_eligible"]],
        "note": "Lower MAE is better. Diagnostic same-fold weighting is excluded from headline claims.",
    }


@app.get("/graph")
def graph() -> dict[str, Any]:
    return {"available": False, "edges": [], "message": "Candidate structural connectivity / model-inferred price dependence is not available for this forecast artifact."}


@app.get("/propagation/{forecast_id}")
def propagation(forecast_id: str) -> dict[str, Any]:
    if store.row_by_id(forecast_id) is None:
        raise HTTPException(status_code=404, detail="Propagation context unavailable for this forecast ID.")
    return {"available": False, "forecast_id": forecast_id, "edges": [], "message": "Propagation outputs are not available for this forecast artifact."}


@app.post("/copilot/query", response_model=CopilotResponse)
def copilot_query(query: CopilotQuery) -> CopilotResponse:
    try:
        return copilot.answer(query.message, query.context)
    except CopilotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
