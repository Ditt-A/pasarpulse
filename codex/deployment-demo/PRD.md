# PRD — PasarPulse Competition Deployment Demo

## 1. Product objective

Build a reliable, judge-friendly web demo that makes the current PasarPulse forecasting work understandable in 2–3 minutes without overstating what the research has validated.

The MVP must answer four questions clearly:

1. **What may happen?** — projected price at +7 and/or +14 days.
2. **Where?** — province, commodity, and market level.
3. **How large is the projected movement?** — percentage change from the forecast-origin price.
4. **What evidence is available?** — data coverage/freshness/context and, when real model-attribution artifacts exist, actual feature drivers.

## 2. Primary users

### Competition judge / evaluator
Needs a fast, credible demonstration of research value, validation discipline, and product usability.

### Analyst / monitoring operator
Needs to prioritize province × commodity × market combinations for verification or closer monitoring.

### Research reviewer
Needs to distinguish empirical model results from product heuristics and from proposal-only future work.

## 3. Core user journey

### A. Landing / national overview

The user sees:

- PasarPulse title and one-line positioning;
- active data mode: `Historical Replay`, `Inference Snapshot`, or `Benchmark Only`;
- forecast-as-of date when available;
- commodity selector;
- market-level selector;
- horizon selector: 7d / 14d;
- ranked province table by projected price increase/warning severity when forecast rows are available;
- clear empty state if province-level forecasts are unavailable.

A map is optional. Do not block MVP completion on GIS assets. A ranked, sortable province table plus a compact bar chart is sufficient.

### B. Province drill-down

For a selected province × commodity × market level, display when real data exists:

- price at forecast origin;
- predicted price at target date;
- projected absolute change in IDR/kg;
- projected percentage change;
- warning level from the product rule;
- forecast origin and target date;
- model identifier/version if available;
- evidence-quality value/status if present in source data;
- modality availability/freshness indicators if present.

In historical replay mode, the later realized target price may be shown as a separate retrospective evaluation card/chart. It must be visually labeled **Realized later / evaluation only** so it is obvious that the model did not have access to it at the forecast origin.

### C. Why this warning?

When actual feature-attribution output exists for the selected row, show ranked drivers with their true signed contributions.

If attribution output does not exist, show:

- context/evidence availability;
- recent price-state features if they are directly observable;
- a message such as `Model attribution is not available for this snapshot.`

Never synthesize SHAP or pretend availability masks are causal feature importance.

### D. Model performance

Load benchmark data from committed result CSVs and/or README-derived structured files.

The page must separate:

1. saved A100 architecture-search results;
2. compact executable finalist rerun;
3. diagnostic results that should not be used as headline leakage-safe claims.

The default table should include ARIMA and the main validated tree-model results. Add a note that lower MAE is better.

### E. Methodology / trust page

Explain in plain language:

- 7 and 14 day horizons;
- chronological rolling-origin evaluation;
- training labels must be known by forecast origin (`date + horizon <= origin`);
- three commodities and three market levels;
- model family: LightGBM/CatBoost with transformed targets;
- public contextual features and missingness/evidence handling;
- product limitations and non-causal interpretation.

## 4. Data modes

The application resolves exactly one mode at startup.

### Replay mode

Use a real out-of-fold/holdout prediction artifact. Required minimum fields are defined in `TECHNICAL_SPEC.md`.

This is the preferred competition mode because it demonstrates the historical forecast while preserving leakage-safe evaluation.

### Inference mode

Use only when serialized models, preprocessing metadata, and a feature snapshot with compatible schema exist. No training is permitted at runtime.

### Benchmark-only mode

Use when no province-level forecast artifact exists. The app still launches and shows project overview, methodology, validated benchmarks, artifact readiness, and instructions for generating a replay snapshot.

Do not bundle fake province predictions merely to avoid this mode.

## 5. Warning rule

The model predicts price. The initial warning classification is a **configurable product heuristic** based on projected positive price movement, not a learned shock probability.

Suggested default:

```text
projected_change_pct < 5%     -> STABLE
5% to <10%                    -> WATCH
10% to <15%                   -> ELEVATED
>=15%                          -> HIGH
```

Negative or flat projected movements remain `STABLE` in the price-rise warning view; the UI may separately show the signed percentage change.

The 10% boundary is aligned with the earlier paper's candidate shock modeling choice, but this warning ladder itself is a demo/product rule, not a regulatory threshold.

Store thresholds in configuration, not scattered through UI code.

## 6. Evidence-quality behavior

If `evidence_quality_score` is present, display the numeric score as source metadata without inventing probabilistic semantics.

If modality masks/ages are present, display each modality as available/missing and fresh/stale only where those statuses can be derived from actual fields/configured rules.

If evidence fields are absent, do not reverse-engineer an arbitrary confidence percentage. Show `Evidence detail unavailable in this artifact`.

## 7. Required pages / views

MVP pages:

1. **Overview**
2. **Province Detail / Replay**
3. **Model Performance**
4. **Methodology & Limitations**

Optional after MVP:

- lightweight Indonesia map;
- export selected forecast/evidence as JSON;
- deterministic evidence-linked narrative;
- FastAPI serving layer;
- authenticated analyst mode.

## 8. Visual requirements

- Default language may be Bahasa Indonesia, but keep metric/model names unambiguous.
- Use a restrained dashboard style suitable for a research/decision-support demo.
- Use consistent IDR/kg formatting.
- Use warning badges with text labels in addition to color.
- Every forecast card must show the as-of/origin date.
- Every historical actual must be labeled as later realized/evaluation data.
- Show an explicit `DEMO / HISTORICAL REPLAY` badge when applicable.
- Avoid dense notebook-like tables on the first screen.

## 9. Non-functional requirements

### Reliability

- No GPU required.
- No upstream API calls required during runtime.
- App launches even when replay/inference artifacts are missing.
- Errors become actionable UI messages rather than stack traces.

### Performance

- Cold start target: under ~15 seconds on a modest hosted CPU where feasible.
- Normal filter interactions should feel immediate; cache immutable data reads.

### Reproducibility

- Display artifact/model/data identifiers when available.
- Do not mutate source benchmark CSVs.
- Snapshot-building scripts must be deterministic given the same inputs.

### Security

- No credentials committed in new code.
- New deployment tokens/secrets only through environment variables/platform secret stores.
- Do not reuse credentials found in historical workflows.

## 10. Acceptance criteria

The PRD is satisfied when all of the following are true:

- [ ] `streamlit run demo/app.py` succeeds on a clean Python environment after installing demo requirements.
- [ ] The app selects and displays its data mode.
- [ ] Benchmark-only mode works on the current committed repository.
- [ ] If a valid replay artifact is supplied, province ranking and drill-down work without code changes.
- [ ] 7d and 14d rows are handled correctly.
- [ ] Warning classification is deterministic and unit-tested.
- [ ] IDR and percentage formatting are tested or centralized.
- [ ] Realized values are never used to compute the displayed forecast/warning in replay mode.
- [ ] Same-fold inverse-MAE blend is not presented as a leakage-safe headline model.
- [ ] A100-search and compact-rerun metrics are visibly distinguished.
- [ ] Missing attribution data does not produce fake explanations.
- [ ] Docker build/start instructions are included.
- [ ] No runtime dependency on external public-data APIs exists.
