# Master Prompt for Codex — Implement the PasarPulse Deployment Demo

You are working in the current branch of the `ElFariss/datathon-2026` repository.

Your task is to implement a reliable competition/demo deployment for PasarPulse using the **current validated repository**, while preserving scientific integrity and the earlier paper's useful product ideas.

## Mandatory reading before coding

Read, in order:

1. root `AGENTS.md`
2. `codex/deployment-demo/README.md`
3. `codex/deployment-demo/PROJECT_CONTEXT.md`
4. `codex/deployment-demo/PRD.md`
5. `codex/deployment-demo/TECHNICAL_SPEC.md`
6. `codex/deployment-demo/SCIENTIFIC_GUARDRAILS.md`
7. `codex/deployment-demo/EXECUTION_PLAN.md`
8. `codex/deployment-demo/PAPER_CONTEXT.md`

Then inspect the actual repository and workspace before deciding which data mode can run.

## Main goal

Create a modular CPU-only Streamlit demo that tells this story:

> PasarPulse adds a leakage-safe 7-day and 14-day forward-looking monitoring layer for Indonesian horticultural prices. A historical replay shows what information was available at a forecast origin, what the model predicted, the projected price-rise warning under a transparent product rule, what evidence/context was available, and—only afterward—the realized price for retrospective evaluation.

The app must still launch in a truthful benchmark-only mode on the current committed repository when province-level forecast artifacts are absent.

## Required implementation behavior

### 1. Inspect artifacts first

Search the workspace for real versions of:

- `data/ready/model_dataset_eligible.parquet`
- `finalist_oof_predictions.csv`
- other OOF/holdout/deployment forecast exports
- serialized model bundles
- feature/SHAP attribution outputs.

Do not create fake forecast rows if these are missing.

### 2. Implement three explicit modes

- `replay`: preferred; uses real OOF/holdout predictions.
- `inference`: only if real compatible serialized models + feature snapshot exist.
- `benchmark`: fallback; uses current result CSVs and no province forecast claims.

Display the active mode prominently.

### 3. Build the app under `demo/`

Follow `TECHNICAL_SPEC.md`. Keep business/data logic outside Streamlit page code.

Required views:

- Overview
- Province Replay / Detail
- Model Performance
- Methodology & Limitations

### 4. Historical replay rules

For each forecast row, compute:

```text
projected_change_pct = (predicted_price - current_price) / current_price * 100
```

Default product warning thresholds:

```text
<5%          STABLE
5–<10%       WATCH
10–<15%      ELEVATED
>=15%        HIGH
```

These labels are product rules, not learned probabilities or regulatory thresholds.

If `target_price` exists, show it only in a section titled similar to:

> Historical evaluation — realized after the forecast origin

Never use `target_price` to calculate the warning or forecast.

### 5. Evidence behavior

Display real evidence-quality/mask/freshness fields when present.

Display model attributions only when a real attribution artifact exists.

If attributions are unavailable, say so. Do not generate pseudo-SHAP, inferred driver rankings, or confidence percentages.

### 6. Performance page rules

Load current repository metrics rather than replacing them.

Separate:

- saved A100 architecture-search results;
- compact executable finalist rerun;
- prior-fold-only meta results;
- diagnostic same-fold-weighted blend.

Do not use `FINALIST_INVERSE_MAE_BLEND` as a leakage-safe headline result because its weights use the same evaluation fold.

### 7. Methodology claims

Accurately describe the current implementation:

- LightGBM log-ratio expert;
- CatBoost scaled-delta expert;
- 7 and 14 day horizons;
- chronological rolling origins;
- training labels constrained by `date + horizon <= origin`;
- price/calendar/production/Sentinel/missingness context visible in finalist features;
- saved specialization/ensemble/meta experiments.

Do not claim that the deployed/current system uses TFT/TCN, CNN/ViT, learned missing tokens, gated multimodal fusion, dynamic GNN attention, learned shock probability, threshold-exceedance probability, propagation probability, calibrated quantile intervals, TimeSHAP, or GNNExplainer unless you actually implement and validate them during this task with real artifacts—which is **not required for the MVP**.

### 8. Reliability constraints

- no training during startup;
- no GPU requirement;
- no live dependency on upstream public-data APIs;
- no secrets in tracked files;
- no reuse/copying of credentials from old workflows;
- app must degrade to benchmark-only mode instead of crashing when replay data is absent;
- cache immutable reads;
- show actionable validation errors.

### 9. Tests

At minimum implement and run:

- warning threshold boundary tests;
- snapshot schema/date/horizon tests;
- mode-resolution tests;
- benchmark-loader test ensuring diagnostic blend is not in headline output.

### 10. Containerization

Add a CPU-only Dockerfile and concise commands for:

```bash
streamlit run demo/app.py
python -m pytest demo/tests -q
docker build -f demo/Dockerfile -t pasarpulse-demo .
docker run --rm -p 8501:8501 pasarpulse-demo
```

## Preferred scope discipline

Do not make FastAPI, an LLM, a map, external ingestion, authentication, a model registry, or cloud CI/CD prerequisites for MVP completion.

A stable historical-replay dashboard is more valuable than an ambitious but brittle architecture.

After MVP is green, you may add optional enhancements only if they do not weaken reliability or scientific clarity.

## UI narrative

The first screen should be understandable without reading the notebook. Prefer concise cards and filters over dense research tables.

Suggested demo sequence:

1. Select commodity and market level.
2. Select a historical forecast origin and 7d/14d horizon.
3. Rank provinces by projected positive movement.
4. Open one province detail.
5. Show current price -> predicted price -> product warning.
6. Show evidence availability/quality.
7. Show realized later price only as retrospective evaluation.
8. Open model performance and explain chronological validation.

## Do not ask unnecessary questions

Resolve details from the repository and these specifications whenever possible. If a genuinely required scientific artifact is absent, do not fabricate it; implement the explicit fallback and report the missing input at the end.

## Definition of done

Before stopping:

- app launches locally;
- benchmark-only mode works from committed files;
- replay mode works if a valid artifact is present/supplied;
- tests pass;
- Docker builds/starts if the environment supports Docker;
- no unsupported claims are present;
- no secrets are introduced;
- documentation includes a short 2–3 minute demo script;
- provide a completion report listing files changed, artifact source(s), commands run, tests, current data mode, limitations, and the next smallest deployment step.

Proceed with implementation now.
