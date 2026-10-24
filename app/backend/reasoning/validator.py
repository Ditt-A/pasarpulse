"""Post-generation validation for the grounded Copilot response contract."""

from __future__ import annotations

import math
import re
from typing import Any

from ..schemas import CopilotResponse


ALLOWED_DASHBOARD_ACTIONS = {
    "SET_PROVINCE",
    "SET_COMMODITY",
    "SET_MARKET_LEVEL",
    "SET_HORIZON",
    "SET_MAP_LAYER",
    "SET_REPLAY_ORIGIN",
    "FILTER_RISK",
    "COMPARE_PROVINCES",
    "OPEN_ALERT",
    "RESET_FILTERS",
}
ALLOWED_ANALYST_ACTIONS = {
    "VERIFY_MARKET_PRICE",
    "VERIFY_SUPPLY",
    "REVIEW_DISTRIBUTION",
    "REVIEW_LOGISTICS",
    "ESCALATE_HUMAN_REVIEW",
    "ABSTAIN",
}
# Currency labels such as ``Rp58.750`` place a letter immediately before the
# number, so a word-boundary/negative-lookbehind pattern would drop the first
# digit. The response is already schema constrained; a simple numeric token
# pattern is safer here.
NUMBER_RE = re.compile(r"[-+]?\d[\d,.]*%?")


def _numeric_values(payload: Any) -> set[float]:
    values: set[float] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            values.update(_numeric_values(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            values.update(_numeric_values(value))
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool) and math.isfinite(float(payload)):
        values.add(float(payload))
    elif isinstance(payload, str):
        for match in NUMBER_RE.findall(payload):
            raw = match.rstrip("%").replace(",", "")
            try:
                values.add(float(raw))
            except ValueError:
                continue
    return values


def _numbers_in_text(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_RE.findall(text):
        raw = match.rstrip("%").replace(",", "")
        try:
            # Indonesian IDR display commonly uses a dot as the thousands
            # separator (for example Rp58.750). Keep the decimal parse for
            # percentages and also expose the grouped-integer interpretation.
            if "." in raw and len(raw.rsplit(".", 1)[1]) == 3:
                values.append(float(raw.replace(".", "")))
            else:
                values.append(float(raw))
        except ValueError:
            continue
    return values


def _number_allowed(value: float, allowed: set[float]) -> bool:
    # Allow date fragments and the exact/rounded display form of source values.
    for candidate in allowed:
        if math.isclose(value, candidate, rel_tol=1e-5, abs_tol=1.1):
            return True
    return False


def _dashboard_action_value_allowed(action_type: str, value: Any, allowed_provinces: set[str] | None) -> bool:
    """Validate both the dashboard command name and its typed value."""

    if action_type == "SET_COMMODITY":
        return isinstance(value, str) and value in {"BM", "CMK", "CRM"}
    if action_type == "SET_MARKET_LEVEL":
        return isinstance(value, str) and value in {"producer", "wholesale", "retail"}
    if action_type == "SET_HORIZON":
        return value in {7, 14}
    if action_type == "SET_MAP_LAYER":
        return isinstance(value, str) and value in {"risk", "change", "evidence"}
    if action_type == "SET_REPLAY_ORIGIN":
        return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
    if action_type == "SET_PROVINCE":
        return isinstance(value, str) and value in (allowed_provinces or set())
    if action_type == "FILTER_RISK":
        return isinstance(value, list) and all(item in {"STABLE", "WATCH", "ELEVATED", "HIGH", "INSUFFICIENT"} for item in value)
    if action_type == "COMPARE_PROVINCES":
        return isinstance(value, list) and 2 <= len(value) <= 4 and all(isinstance(item, str) and item in (allowed_provinces or set()) for item in value)
    if action_type == "OPEN_ALERT":
        return isinstance(value, str) and bool(value)
    if action_type == "RESET_FILTERS":
        return value is None or isinstance(value, bool)
    return value is not None


def validate_response(
    response: CopilotResponse,
    evidence: dict[str, Any],
    allowed_provinces: set[str] | None = None,
) -> tuple[bool, str | None]:
    """Validate evidence IDs, whitelisted actions, and numerical fidelity."""

    evidence_items = evidence.get("items", [])
    if not evidence_items and isinstance(evidence.get("evidence_quality"), dict):
        evidence_items = evidence["evidence_quality"].get("items", [])
    if not evidence_items and isinstance(evidence.get("modalities"), list):
        evidence_items = evidence["modalities"]
    valid_ids = {str(item.get("evidence_id")) for item in evidence_items if item.get("evidence_id")}
    for reason in response.reasons:
        if not set(reason.evidence_ids).issubset(valid_ids):
            return False, "The Copilot response referenced an unknown evidence ID."
    for action in response.actions:
        if action.action_id not in ALLOWED_ANALYST_ACTIONS:
            return False, "The Copilot response proposed an unapproved analyst action."
        if not set(action.evidence_ids).issubset(valid_ids):
            return False, "An analyst action referenced an unknown evidence ID."
    for action in response.dashboard_actions:
        if action.type not in ALLOWED_DASHBOARD_ACTIONS:
            return False, "The Copilot response proposed an unapproved dashboard action."
        if not _dashboard_action_value_allowed(action.type, action.value, allowed_provinces):
            return False, "The Copilot response contained an invalid value for a dashboard action."

    allowed_numbers = _numeric_values(evidence)
    response_text = " ".join(
        [response.summary]
        + [reason.text for reason in response.reasons]
        + [str(action.value) for action in response.dashboard_actions if action.value is not None]
    )
    unknown = [number for number in _numbers_in_text(response_text) if not _number_allowed(number, allowed_numbers)]
    if unknown:
        return False, "The Copilot response contained a number not present in the loaded evidence."

    if allowed_provinces:
        # Reject an exact province-shaped token only when it is clearly named in
        # a dashboard action. Free-form text is kept conservative by the prompt
        # and the evidence-ID check, while control values are strictly checked.
        for action in response.dashboard_actions:
            if action.type in {"SET_PROVINCE", "COMPARE_PROVINCES"}:
                values = action.value if isinstance(action.value, list) else [action.value]
                for value in values:
                    if value is not None and str(value) not in allowed_provinces:
                        return False, "The Copilot response selected a province outside the loaded geography."
    return True, None
