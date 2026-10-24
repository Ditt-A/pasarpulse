# Paper Context — Original PasarPulse-MM Proposal

This document summarizes the earlier `PasarPulse.pdf` supplied by the project owner. It is **context for intent and product direction**, not a claim that every proposed component exists in the current repository.

## 1. Original paper identity

Original title:

> **PasarPulse-MM: Missing-Modality-Aware Multimodal Graph Learning for National Horticultural Price-Shock Forecasting in Indonesia**

The proposal framed PasarPulse-MM as a national early-warning and decision-support product for 7-day and 14-day horticultural price shocks across Indonesia's 38 provinces, focusing on bird's-eye chili, red/curly chili, and shallots, with producer/wholesale/retail market levels.

The paper's core problem statement remains useful: public systems are good at describing prices that have already moved, while decision makers need earlier signals about **what may happen next, where, and with what evidence quality**.

## 2. Proposal data philosophy that should be retained

The original paper proposed six public-data routes:

- price data from Bapanas / PIHPS;
- ERA5-Land weather;
- Sentinel-2 regional vegetation proxies;
- BPS annual production / harvested area / productivity;
- OSM/Geofabrik structural connectivity;
- calendar/holiday/seasonal information.

Important responsible interpretations from the paper should remain in the product language:

- Sentinel-2 vegetation anomalies are regional supply-side proxies, not direct measurements of chili/shallot production;
- annual production is structural context, not daily realized supply;
- road/port/ferry/adjacency links are candidate connectivity, not observed commodity flow;
- predictive evidence is not a causal guarantee;
- warnings should trigger verification/review rather than automatic intervention.

## 3. Original proposed scientific architecture

The proposal described:

- TFT or TCN encoders for price/calendar/weather sequences;
- CNN or ViT encoders for Sentinel-2 sequences;
- MLP encoding for annual production/static province features;
- asynchronous alignment across update frequencies;
- missingness masks, learned missing tokens, bounded carry-forward, modality dropout, and learned fusion gates;
- a dynamic heterogeneous province × commodity × market graph;
- structural edges from adjacency, roads, ports/ferries, distance, market layers, and production similarity;
- dynamic edges from rolling correlation, lead-lag, shock co-occurrence, and seasonal similarity;
- dynamic graph attention;
- multi-task heads for price quantiles, shock probability, official-threshold exceedance probability, and propagation probability;
- quantile/conformal uncertainty;
- SHAP, TimeSHAP/temporal perturbation, modality deletion, and GNNExplainer/influential-edge masking.

### Status relative to the current repo

Treat the above as **proposal/future-research context** unless direct code and validated artifacts exist.

The current semifinal implementation instead centers on LightGBM/CatBoost tabular panel forecasting with transformed targets, chronological rolling-origin evaluation, contextual/missingness features, specialization, and saved ensemble/meta-model experiments.

Therefore the deployment demo must not visually imply that a dynamic GNN or multi-task probabilistic model is serving the forecast.

## 4. Original evaluation plan

The paper proposed a broad evaluation matrix including:

- MAE, sMAPE, pinball loss, interval coverage;
- PR-AUC, recall, false-negative rate, lead time;
- Brier score / expected calibration error;
- edge/node propagation PR-AUC;
- rolling-origin evaluation;
- leave-one-province-out and leave-one-island-group-out validation;
- regional subgroup tests;
- missing-modality stress tests;
- XAI deletion/fidelity tests.

The deployment demo may mention these as **original research hypotheses/roadmap only** unless they are actually present in current saved results.

The current validated story should focus on the metrics and validation present in the repository.

## 5. Product architecture ideas from the paper worth keeping

The paper's deployment section contains several ideas that remain highly relevant even after the modeling approach changed.

### Offline training separated from inference

This is fully aligned with the deployment PRD. The demo should load approved artifacts/snapshots, not train models on user requests.

### Evidence-first output

The paper proposed an Evidence JSON structure carrying:

- forecast identity;
- region/commodity/market;
- forecast values;
- evidence quality;
- modality freshness/availability;
- dominant evidence IDs;
- graph paths where applicable;
- abstention state;
- model/data/schema versions.

For the current implementation, simplify the schema so it only contains fields genuinely available from tree-model/replay artifacts.

A truthful current-version evidence object might look conceptually like:

```json
{
  "forecast_id": "...",
  "region": {"code": "...", "name": "..."},
  "commodity": {"code": "...", "name": "..."},
  "market_level": "retail",
  "forecast": {
    "origin": "YYYY-MM-DD",
    "horizon_days": 7,
    "current_price_idr_per_kg": 0,
    "predicted_price_idr_per_kg": 0,
    "projected_change_pct": 0,
    "warning_rule": "STABLE"
  },
  "evidence_quality": {
    "overall_score": null,
    "available_modalities": [],
    "missing_modalities": []
  },
  "attributions": null,
  "versions": {
    "model": null,
    "data": null,
    "schema": "demo-v1"
  }
}
```

Do not populate null/unknown scientific fields with invented numbers just to mimic the older paper schema.

### Schema validation and action control

The paper proposed validating evidence and restricting downstream actions to safe decision-support IDs such as:

- verify market price;
- verify supply;
- review distribution;
- review logistics;
- escalate human review;
- abstain.

This is a strong future extension for the demo. If implemented, recommendations must remain deterministic/evidence-linked or schema-validated and must never create unsupported causal claims.

### Optional reasoning/LLM layer

The paper positioned the LLM as an interpretation layer after forecasting, not the forecasting model itself. That separation is good architecture.

However, the original benchmark table explicitly left reasoning-model results TBD. Therefore do not add an LLM to the MVP merely to claim AI sophistication. A deterministic evidence summary is preferable until the core replay demo is stable.

## 6. Original data-quality/abstention principle

The paper proposed that insufficient coverage/freshness should remain visible and that the system should abstain instead of aggressively imputing long gaps.

This principle should survive the architecture change:

- missing replay artifact -> benchmark-only mode, not fake forecast;
- missing evidence detail -> explicit unavailable state, not fake confidence;
- invalid schema -> reject/fallback, not silently repair into a publishable number.

## 7. How to describe evolution from paper to project

A defensible narrative for judges/reviewers is:

> The initial research proposal hypothesized a missing-modality-aware multimodal dynamic graph architecture. After building the national panel and performing architecture/model search, the semifinal implementation prioritized leakage-safe gradient-boosted tree experts with transformed targets, contextual/relational features, and commodity-market specialization because they offered a stronger practical trade-off between accuracy, auditability, robustness, and limited validation origins. The product vision—forward-looking warning, evidence quality, abstention, and human decision support—remains intact.

This narrative treats the difference between proposal and implementation as the result of empirical research, not as something to hide.

## 8. What the deployment demo may borrow from the paper now

Safe to use now:

- early-warning framing;
- 7d / 14d horizon framing;
- province × commodity × market-level unit;
- evidence quality/freshness concept;
- offline training vs inference separation;
- historical replay / auditability;
- explicit limitations;
- abstention / insufficient-evidence state;
- optional structured evidence export;
- decision-support-only framing.

Keep as roadmap unless newly implemented and validated:

- TFT/TCN/CNN/ViT multimodal encoders;
- learned missing tokens/modality dropout/gated fusion;
- dynamic GNN attention;
- learned shock probability;
- threshold-exceedance probability;
- propagation probability/path prediction;
- calibrated quantile intervals;
- TimeSHAP/GNNExplainer claims;
- leave-one-province/island results;
- LLM benchmark superiority.

## 9. Source note

This file is derived from the original 12-page PasarPulse-MM proposal supplied by the project owner. Keep it as context. When a final paper is revised, update the paper to match validated implementation rather than changing the implementation merely to recreate proposal-only claims.
