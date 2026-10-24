# PasarPulse Copilot contract

Copilot is an interpretation and dashboard-control layer after retrieval. It
is not a forecaster.

## Pipeline

```text
user message
  → context resolver
  → forecast/evidence retrieval
  → structured Evidence JSON
  → Gemini JSON response
  → numerical/evidence/action validator
  → UI or explicit error
```

The payload excludes `target_price` and includes only the selected forecast,
forecast-specific availability/freshness records, actual modality values,
selected feature-contract membership, a target-free ranking context, explicit
unsupported-output flags, and current dashboard context. Evidence strings are
untrusted data and cannot override the system instruction or schema. Gemini is
the only answer generator; missing configuration, upstream failure, or failed
validation is returned as an explicit error rather than a canned response.

Approved analyst actions:

```text
VERIFY_MARKET_PRICE
VERIFY_SUPPLY
REVIEW_DISTRIBUTION
REVIEW_LOGISTICS
ESCALATE_HUMAN_REVIEW
ABSTAIN
```

Approved dashboard actions are a separate whitelist:
`SET_PROVINCE`, `SET_COMMODITY`, `SET_MARKET_LEVEL`, `SET_HORIZON`,
`SET_MAP_LAYER`, `SET_REPLAY_ORIGIN`, `FILTER_RISK`, `COMPARE_PROVINCES`,
`OPEN_ALERT`, and `RESET_FILTERS`.

The Gemini route defaults to `gemini-3.5-flash-lite` with a configured high
thinking level. Structured output is required. If a returned number is not
represented in the evidence JSON, an evidence ID is unknown, or an action is
not whitelisted, the response is rejected with an error and is not shown.
