import pytest
from fastapi import HTTPException

from app.backend.main import alerts, copilot, copilot_query, forecasts, provinces
from app.backend.schemas import CopilotContext, CopilotQuery


def test_overview_to_copilot_vertical_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = forecasts(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7)
    assert rows
    selected = rows[0]

    geojson = provinces(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7)
    assert len(geojson["features"]) == 38
    map_feature = next(item for item in geojson["features"] if item["properties"]["province_code"] == selected.province_code)
    assert map_feature["properties"]["forecast_id"] == selected.forecast_id
    assert map_feature["properties"]["warning_level"] == selected.warning_level

    queue = alerts(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7, risk=[], limit=100)
    assert queue
    assert {item.alert_id for item in queue} >= {f"ALT-20260717-{selected.province_code}-CRM-RETAIL-7"}

    monkeypatch.setattr(copilot.store, "llm_enabled", False)
    with pytest.raises(HTTPException) as error:
        copilot_query(
            CopilotQuery(
                message="Why is this province elevated?",
                context=CopilotContext(
                    province_code=selected.province_code,
                    commodity_code="CRM",
                    market_level="retail",
                    horizon_days=7,
                    forecast_origin="2026-07-17",
                ),
            )
        )
    assert error.value.status_code == 503
    assert "PASARPULSE_LLM_API_KEY" in str(error.value.detail)
