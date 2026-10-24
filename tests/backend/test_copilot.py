import pytest

from app.backend.reasoning.payload import evidence_payload
from app.backend.reasoning.service import CopilotConfigurationError, CopilotService, CopilotValidationError
from app.backend.reasoning.validator import validate_response
from app.backend.schemas import AnalystAction, CopilotContext, CopilotReason, CopilotResponse
from app.backend.services.artifacts import ForecastStore


def test_evidence_payload_is_target_free() -> None:
    store = ForecastStore()
    row = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7).iloc[0]
    raw = store._evidence[row["forecast_id"]]
    context = CopilotContext(province_code=row["province_code"], commodity_code="CRM", market_level="retail", horizon_days=7, forecast_origin="2026-07-17")
    payload = evidence_payload(row, raw, context)
    serialized = str(payload)
    assert "target_price" not in serialized


def test_copilot_requires_gemini_instead_of_using_a_canned_answer() -> None:
    store = ForecastStore()
    store.llm_enabled = False
    row = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7).iloc[0]
    context = CopilotContext(
        province_code=row["province_code"],
        commodity_code="CRM",
        market_level="retail",
        horizon_days=7,
        forecast_origin="2026-07-17",
    )
    with pytest.raises(CopilotConfigurationError, match="PASARPULSE_LLM_API_KEY"):
        CopilotService(store).answer("Why?", context)


def test_validator_rejects_unknown_number_and_evidence() -> None:
    store = ForecastStore()
    row = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7).iloc[0]
    raw = store._evidence[row["forecast_id"]]
    context = CopilotContext(province_code=row["province_code"], commodity_code="CRM", market_level="retail", horizon_days=7, forecast_origin="2026-07-17")
    payload = evidence_payload(row, raw, context)
    response = CopilotResponse(summary="The verified price is 999999 IDR.", actions=[AnalystAction(action_id="ABSTAIN")])
    valid, note = validate_response(response, payload)
    assert not valid
    assert "number" in (note or "")
    response = CopilotResponse(summary="Why?", reasons=[CopilotReason(text="Reason", evidence_ids=["EV-NOT-REAL"])])
    valid, note = validate_response(response, payload)
    assert not valid
    assert "evidence ID" in (note or "")


def test_copilot_reads_multimodal_contract_and_keeps_targets_out() -> None:
    store = ForecastStore()
    for horizon, expected_contract, expected_weather_membership in [
        (7, "ALL_MODALITIES_DYNAMIC_GRAPH", True),
        (14, "PRICE_CALENDAR", False),
    ]:
        row = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=horizon).iloc[0]
        raw = store._evidence[row["forecast_id"]]
        context = CopilotContext(
            province_code=row["province_code"],
            commodity_code="CRM",
            market_level="retail",
            horizon_days=horizon,
            forecast_origin="2026-07-17",
        )
        payload = evidence_payload(row, raw, context)
        modalities = {item["modality"]: item for item in raw["items"]}
        assert raw["model_feature_contract"] == expected_contract
        assert modalities["Weather"]["available"]
        assert modalities["Weather"]["used_by_model"] is expected_weather_membership
        assert "target_price" not in str(payload)
        response = CopilotResponse(summary="The selected evidence is available.", actions=[AnalystAction(action_id="ABSTAIN")])
        valid, note = validate_response(response, payload)
        assert valid, note


def test_invalid_gemini_response_is_an_error_not_a_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ForecastStore()
    store.llm_enabled = True
    row = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7).iloc[0]
    context = CopilotContext(
        province_code=row["province_code"],
        commodity_code="CRM",
        market_level="retail",
        horizon_days=7,
        forecast_origin="2026-07-17",
    )
    monkeypatch.setattr(
        "app.backend.reasoning.service.ask_gemini",
        lambda _message, _payload: CopilotResponse(summary="Unsupported price 999999", actions=[AnalystAction(action_id="ABSTAIN")]),
    )
    with pytest.raises(CopilotValidationError, match="evidence validation"):
        CopilotService(store).answer("Why?", context)
