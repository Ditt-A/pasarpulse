# Scientific Guardrails for the Deployment Demo

This file exists to prevent product polish from turning into scientific overclaiming.

## 1. Current implementation beats proposal wording

The current repository is the source of truth for what has been implemented. The earlier PasarPulse-MM paper proposed a substantially more complex system including TFT/TCN sequence encoders, CNN/ViT satellite encoders, learned missing tokens and gated fusion, dynamic heterogeneous graph attention, multi-task shock/threshold/propagation heads, calibrated intervals, and GNN-specific explanations.

Those proposal components must not be described as implemented unless corresponding code/artifacts are added and validated later.

For the current demo, describe the primary forecasting implementation as:

> leakage-safe, multi-horizon panel forecasting with LightGBM/CatBoost experts, transformed targets, contextual features, missingness/evidence metadata, specialization, and saved ensemble/meta-model experiments.

## 2. Keep result families separate

### Saved A100 architecture search

The repository README reports stronger headline scores from the saved 120-configuration A100 search, including:

- LightGBM log-ratio 7d MAE: Rp3,275.46/kg;
- CatBoost commodity × market specialist 7d MAE: Rp3,371.66/kg;
- CatBoost commodity × market specialist 14d MAE: Rp4,858.38/kg.

These may be shown as **saved validated architecture-search results**.

### Compact visible finalist rerun

The executable finalist code/notebook rerun is a separate reproducibility check with different pooled scores. Label it `compact executable finalist rerun` or equivalent.

Never imply that opening the demo retrains the 120-model search or reproduces the saved A100 headline scores live.

## 3. Same-fold inverse-MAE blend caveat

In the visible finalist, `FINALIST_INVERSE_MAE_BLEND` computes each expert's MAE on the evaluation fold, converts those errors into weights, then evaluates the blend on that same fold.

That makes the blend inappropriate as a leakage-safe headline benchmark.

Demo rule:

- exclude it from headline performance cards;
- if displayed for research transparency, label it `diagnostic: same-fold error-weighted blend`;
- do not use those same-fold weights for a deployed forecast.

A prior-fold-only router/blend is conceptually acceptable if its weights/decision logic are learned only from earlier folds and the saved result is clearly identified.

## 4. Historical replay must preserve the as-of boundary

In replay mode:

- `current_price` is information at the forecast origin;
- `predicted_price` comes from the out-of-fold/holdout model output;
- `target_price` is later realized data used only for retrospective evaluation.

Never calculate warning severity from `target_price`.

Never use the later actual value to fill missing forecast-time context.

Any enrichment from the model-ready panel must use fields available at or before the origin according to their timestamps/age semantics.

## 5. No invented probability language

The current primary model is a price regressor. Therefore do not display:

- `87% probability of price shock`;
- `93% model confidence`;
- `74% threshold-exceedance probability`;
- calibrated prediction intervals;

unless those values come from a separately implemented and validated artifact.

Allowed wording:

- `Projected +12.4% price increase in 14 days`;
- `Warning: ELEVATED (product rule)`;
- `Evidence quality score: 0.84` when the source field really exists;
- `Historical absolute error: Rp.../kg` in replay mode.

## 6. Warning levels are product rules

The initial `STABLE/WATCH/ELEVATED/HIGH` ladder is a configurable decision-support heuristic over projected price movement.

It is:

- not a classifier output;
- not a probability;
- not an official regulatory threshold;
- not a causal policy trigger.

The earlier paper uses a ≥10% seven-day rise as a candidate shock modeling choice. This may motivate the `ELEVATED` boundary, but the full warning ladder must still be labeled as a product/demo rule.

## 7. Evidence is not causality

Feature importance/SHAP, when available, should be described as **model contribution / predictive evidence**, not proof that a factor caused the future price movement.

Do not write statements such as:

- `NDVI caused the price increase`;
- `neighbor province X transmitted the shock`;
- `production decline caused retail price inflation`.

Prefer:

- `This feature pushed the model forecast upward`;
- `The model used this relational context`;
- `Regional vegetation proxy was consistent with higher/lower forecast risk`.

## 8. Satellite and production semantics

Keep the original paper's responsible-data interpretation:

- Sentinel-derived NDVI/NDWI are regional vegetation/supply-side proxies, not direct observations of chili/shallot production;
- annual production, harvested area, and productivity are structural context, not daily realized supply;
- cloud cover and observation age describe satellite data quality/freshness.

## 9. Graph / relational semantics

The paper proposed dynamic heterogeneous graph learning. The current validated semifinal system should be described more conservatively as using relational/graph-derived/context features where applicable.

Do not claim:

- a deployed GNN;
- observed commodity-flow edges;
- learned propagation probabilities;
- verified cross-province causal transmission paths;

unless those artifacts are added later.

Structural connectivity should be described as candidate connectivity/context, not ground-truth flow.

## 10. Weather wording

The paper treats weather as a major modality. The visible compact finalist feature list includes `mask_weather` but does not visibly include a rich set of substantive weather variables in the same way it includes price, production, and Sentinel context.

Therefore the demo should say that PasarPulse research considers multimodal public context, but it should not assert that the displayed compact finalist forecast is materially driven by weather unless the selected model/artifact actually contains those variables and attribution evidence.

## 11. Missingness and evidence quality

Availability masks are useful evidence metadata but are not learned modality gates in the current tree implementation.

Do not describe current masks as `learned missing tokens`, `modality dropout`, or `gated multimodal fusion`.

If evidence is insufficient, a truthful empty state/abstention is better than a fabricated forecast.

## 12. Deployment claims

The demo may truthfully implement:

- offline artifact generation;
- replay/inference snapshot loading;
- warning/evidence formatting;
- dashboard delivery;
- schema validation;
- deterministic evidence JSON export if built.

The paper's optional reasoning router, LLM service, model registry, authenticated API, cache, monitoring logs, and post-generation validator remain roadmap items unless Codex actually implements them.

## 13. Security

Do not repeat or expose any credential encountered in an existing workflow. Do not copy it into docs, examples, `.env`, Docker build args, Streamlit secrets, or CI.

All new secrets must be externalized.

## 14. Recommended UI footnote

A concise footer can say:

> PasarPulse is a decision-support prototype. Forecasts are predictive estimates, not causal guarantees or automatic policy instructions. Historical replay uses chronological evaluation; later realized prices are shown only for retrospective assessment.
