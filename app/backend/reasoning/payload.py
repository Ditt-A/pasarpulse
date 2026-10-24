"""Build the structured, target-free evidence object sent to Gemini."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..schemas import CopilotContext


def evidence_payload(
    row: pd.Series | None,
    evidence: dict[str, Any],
    context: CopilotContext,
    alert_rows: list[pd.Series] | None = None,
) -> dict[str, Any]:
    """Build the exact structured payload sent to the LLM.

    Realized/target prices are intentionally absent. The payload is the only
    source Gemini is allowed to use for a response.
    """

    forecast: dict[str, Any] = {}
    if row is not None:
        forecast = {
            "forecast_id": str(row["forecast_id"]),
            "province_code": str(row["province_code"]),
            "province_name": str(row["province_name"]),
            "commodity_code": str(row["commodity_code"]),
            "commodity_name": str(row["commodity_name"]),
            "market_level": str(row["market_level"]),
            "forecast_origin": str(row["forecast_origin"]),
            "target_date": str(row["target_date"]),
            "horizon_days": int(row["horizon_days"]),
            "current_price": float(row["current_price"]),
            "predicted_price": float(row["predicted_price"]),
            "projected_change": float(row["projected_change"]),
            "projected_change_pct": float(row["projected_change_pct"]),
            "warning_level": str(row["warning_level"]),
            "model": str(row["model"]),
            "model_version": str(row.get("model_version", "")),
            "data_version": str(row.get("data_version", "")),
            "feature_version": str(row.get("feature_version", "")),
            "unsupported_outputs": [
                "shock_probability",
                "propagation_probability",
                "SHAP / TimeSHAP / GNN explanations",
                "uncertainty intervals",
            ],
        }

    items = evidence.get("items", [])
    graph_item = next(
        (item for item in items if item.get("modality") == "Dynamic price dependence graph"),
        {},
    )
    ranking_context = []
    for alert in alert_rows or []:
        ranking_context.append(
            {
                "province_code": str(alert.get("province_code", "")),
                "province_name": str(alert.get("province_name", "")),
                "commodity_code": str(alert.get("commodity_code", "")),
                "market_level": str(alert.get("market_level", "")),
                "forecast_id": str(alert.get("forecast_id", "")),
                "projected_change_pct": float(alert.get("projected_change_pct", 0.0)),
                "warning_level": str(alert.get("warning_level", "")),
                "predicted_price": float(alert.get("predicted_price", 0.0)),
            }
        )

    safe_evidence = {
        "evidence_quality_score": evidence.get("evidence_quality_score"),
        "items": items,
        "attribution_available": bool(evidence.get("attribution_available", False)),
        "attribution_note": evidence.get("attribution_note", "Model attribution is not available for this snapshot."),
        "abstention_required": bool(evidence.get("abstention_required", False)),
        "abstention_reason": evidence.get("abstention_reason"),
        "model": evidence.get("model", forecast.get("model")),
        "model_feature_contract": evidence.get("model_feature_contract", forecast.get("feature_version")),
        "model_modalities": evidence.get("model_modalities", []),
        "ranking_context": ranking_context,
    }
    return {
        "context": context.model_dump() if hasattr(context, "model_dump") else context.dict(),
        "forecast": forecast,
        "evidence_quality": safe_evidence,
        "modalities": safe_evidence["items"],
        "dominant_evidence": [],
        "graph_paths": graph_item.get("values", {}).get("edges", []),
        "abstention": {
            "required": safe_evidence["abstention_required"],
            "reason": safe_evidence["abstention_reason"] or "",
        },
    }
