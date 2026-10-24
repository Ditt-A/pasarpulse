"""Copilot orchestration: retrieve -> structure -> Gemini -> validate."""

from __future__ import annotations

from typing import Any

from ..schemas import CopilotContext, CopilotResponse
from .payload import evidence_payload
from .gemini import ask_gemini
from .validator import validate_response


class CopilotError(RuntimeError):
    """Base error surfaced when a grounded Copilot answer cannot be produced."""

    status_code = 503


class CopilotRequestError(CopilotError):
    status_code = 422


class CopilotConfigurationError(CopilotError):
    status_code = 503


class CopilotUpstreamError(CopilotError):
    status_code = 503


class CopilotValidationError(CopilotError):
    status_code = 502


class CopilotService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def _context_row(self, context: CopilotContext):
        rows = self.store.query(
            origin=context.forecast_origin,
            commodity=context.commodity_code,
            market_level=context.market_level,
            horizon=context.horizon_days,
            province_code=context.province_code,
        )
        return None if rows.empty else rows.sort_values("projected_change_pct", ascending=False).iloc[0]

    def answer(self, message: str, context: CopilotContext) -> CopilotResponse:
        row = self._context_row(context)
        if row is None:
            raise CopilotRequestError("No matching forecast snapshot is loaded for the selected context.")

        forecast_id = str(row["forecast_id"])
        raw_evidence = self.store._evidence.get(forecast_id, {})
        if not raw_evidence:
            raise CopilotRequestError("Evidence is unavailable for the selected forecast snapshot.")

        if not getattr(self.store, "llm_enabled", False):
            raise CopilotConfigurationError(
                "Gemini Copilot is not configured. Set PASARPULSE_LLM_API_KEY and restart the backend."
            )

        ranking_rows = []
        ranking_rows = [
            candidate
            for candidate, _priority in self.store.alerts(
                origin=context.forecast_origin,
                commodity=context.commodity_code,
                market_level=context.market_level,
                horizon=context.horizon_days,
            )[:5]
        ]
        payload = evidence_payload(row, raw_evidence, context, alert_rows=ranking_rows)
        known_provinces = {
            str(feature.get("properties", {}).get("province_name", "")): str(feature.get("properties", {}).get("province_code", ""))
            for feature in self.store._geojson.get("features", [])
            if feature.get("properties", {}).get("province_name")
        }
        try:
            response = ask_gemini(message, payload)
        except Exception as exc:  # fail closed; never expose a traceback to the user
            raise CopilotUpstreamError(f"Gemini Copilot request failed: {exc}") from exc

        valid, note = validate_response(response, payload, set(known_provinces.values()))
        if not valid:
            raise CopilotValidationError(f"Gemini Copilot response failed evidence validation: {note}")
        response.mode = response.mode or "Gemini structured evidence mode"
        return response
