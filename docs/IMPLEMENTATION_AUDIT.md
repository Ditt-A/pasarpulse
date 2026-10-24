# PasarPulse implementation audit

Generated for the semifinal product layer on 2026-08-10. This document is the
truth table for the application. It deliberately separates artifacts that are
implemented and evaluated from components described only in the PasarPulse-MM
proposal.

## Product/runtime decision

The repository now contains a deployable Next.js + FastAPI product layer. The
runtime loads prepared local snapshots and never trains a model. The primary
demo mode is **Historical Replay** from the validated multimodal OOF winners:
the 7-day all-modalities/dynamic-graph LightGBM row and the 14-day
price/calendar LightGBM row. If the snapshot is absent, the API falls back to
**Benchmark Only** and still serves the methodology and benchmark pages.

The older `codex/deployment-demo/` packet describes a Streamlit MVP. That was a
useful scientific guardrail, but the semifinal product request explicitly
requires a browser application and API service, so this implementation keeps
the same domain rules while using Next.js and FastAPI.

## Evidence and model truth table

| Capability | Status | Source / product treatment |
|---|---|---|
| Province × commodity × market forecast rows | Implemented | `results/multimodal_ablation/oof_predictions.csv`, selected by validated horizon winner |
| 7-day and 14-day horizons | Implemented | Seven chronological origins from 2026-02-02 through 2026-07-17 |
| 34 observed provinces | Implemented | OOF artifact and PIHPS snapshot |
| 38-province national geometry | Implemented | `data/reference/indonesia_provinces.geojson` (BIG-sourced geometry) |
| LightGBM log-ratio expert | Implemented/evaluated | `models/weights/expert_lgb_logratio_{7d,14d}.txt` and research metrics |
| CatBoost specialist | Evaluated offline | Reported in benchmark files; not the default replay model |
| Six-modality tree ablation | Implemented/evaluated/deployed for replay | `results/multimodal_ablation/`; seven origins, 7-day and 14-day horizons, zero availability violations |
| ERA5-Land daily context | Implemented/evaluated | 35,834 complete province-days; bounded publication-lag gating |
| Sentinel-2 vegetation context | Implemented/evaluated | 786 scenes/features across 38 province proxy zones; five low-valid scenes retained with flags |
| Static and dynamic graph context | Implemented/evaluated as tabular features | 73 static candidate edges and 37,485 rolling price-dependence rows; not a deployed GNN or shipment graph |
| Historical realized target | Evaluation-only | OOF `actual_price` becomes `target_price`; never used for warning/ranking |
| Product warning rule | Implemented | Configurable movement thresholds: 5%, 10%, 15%; not a probability or regulatory threshold |
| Price, calendar, weather, production, satellite, market/static, and dynamic graph evidence | Available | `results/multimodal_ablation/replay_context.csv` plus graph summaries; shown with status, age, source, and feature-contract membership |
| Production/BPS metadata | Available | `data/processed/production_annual.csv`; annual structural context, not daily supply |
| Satellite metadata | Available in replay context when usable | Cloud-aware Sentinel-2 context is surfaced; stale/missing observations remain explicit |
| `evidence_quality_score` | Preserved only when present | UI shows “Not available for this forecast artifact” rather than deriving confidence when null |
| SHAP / feature attribution | Not available for replay rows | UI explicitly abstains from model-driver claims |
| TimeSHAP | Not available | Proposal/roadmap only |
| GNN explanation / GNN deployment | Not available | Proposal/roadmap only; tree/relational features are not a deployed GNN |
| Shock probability | Not available | Projected movement and warning label are shown instead |
| Threshold-exceedance probability | Not available | No probability displayed |
| Propagation probability/path | Not available | Propagation tab is disabled with an explanation |
| Uncertainty interval | Not available for winning replay artifact | No fabricated band or confidence interval |
| Inference snapshot | Not bundled | Product defaults to Historical Replay; no claim of real-time operation |

## Forecast artifact coverage

The selected multimodal OOF source contains 38,930 rows across ten model
variants. The product snapshot selects two validated winners, yielding 3,893
rows (seven origins × two horizons with some series unavailable at individual
origins), 279 eligible series, 34 province codes, three commodities, and three
market levels. The seven origins are:

```text
2026-02-02, 2026-03-02, 2026-03-30, 2026-04-27,
2026-05-25, 2026-06-22, 2026-07-17
```

The canonical BIG GeoJSON has 38 provinces. Codes `92`, `95`, `96`, and `97`
are absent from the PIHPS snapshot and therefore remain visible as
`INSUFFICIENT EVIDENCE` on the national map when no forecast row exists.

## Validated benchmark provenance

The saved architecture-search benchmark reports LightGBM log-ratio pooled MAE
of Rp3,275.46/kg at 7 days and Rp4,882.06/kg at 14 days over seven origins.
The model-page loader reads the repository CSVs rather than hard-coding these
values. The same-fold inverse-MAE blend is not a leakage-safe headline result
and is excluded from headline cards.

The completed multimodal ablation is the source of the deployed replay
selection. Its best rows are Rp3,538.49/kg at 7 days (all modalities plus
dynamic graph) and Rp5,308.47/kg at 14 days (price plus calendar). The full
ablation table remains available as research benchmark rows; it is not
presented as the deployed TFT/CNN/GNN proposal.

## Explicitly unavailable claims

The proposal describes TFT/TCN sequence encoders, CNN/ViT satellite encoders,
learned missing tokens, gated multimodal fusion, dynamic heterogeneous graph
attention, calibrated quantiles, shock/propagation heads, and specialized XAI.
None of those proposal components is presented as deployed by this product.
The product may show them on the Model page as research architecture / roadmap
only.

## Methodology source alignment

The A100 workspace contains the current concept-paper reference at
`PasarPulse_MM_AI_Product_Concept_Paper.docx`. Its methodology defines the
North Sumatra district/city pilot, asynchronous price/weather/satellite/
production/calendar alignment, missing-modality handling, dynamic multi-level
graph learning, multi-task calibrated outputs, and the B0–B5 baseline ladder.
Those details are transcribed in [METHODOLOGY.md](METHODOLOGY.md), and the
remote hashes and coverage checks are recorded in
[A100_ARTIFACT_AUDIT.md](A100_ARTIFACT_AUDIT.md).

The national semifinal product intentionally does not relabel its province-level
tree ablation as the proposed multimodal neural system. The concept paper
remains the research direction; the selected feature contracts and artifact
truth table above remain the deployment contract.

## Security and leakage boundary

The Gemini API key supplied during development is not stored in this repository
or in Docker images. Copilot reads `PASARPULSE_LLM_API_KEY` at runtime and
returns an explicit configuration error when the variable is absent. In
replay mode, `target_price` and historical error are retained only for the
explicit reveal/evaluation panel; forecast severity, ranking, evidence
summary, and Copilot context are built without them.
