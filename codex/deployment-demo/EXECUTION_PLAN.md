# Execution Plan — PasarPulse Demo

This plan is written for a coding assistant working directly in the repository. Execute in order. Do not skip the artifact/data inspection phase.

## Phase 0 — Inspect before coding

1. Read all files in `codex/deployment-demo/` and root `AGENTS.md`.
2. Inspect:
   - `README.md`
   - `experiments/pasarpulse_notebook_finalist.py`
   - `results/*.csv`
   - `data/dataset_summary.csv`
   - relevant notebook cells/outputs if needed.
3. Search the workspace, including untracked files if accessible, for:
   - `model_dataset_eligible.parquet`
   - `finalist_oof_predictions.csv`
   - deployment-shaped forecast exports
   - serialized LightGBM/CatBoost models
   - SHAP/feature-contribution artifacts.
4. Record what is actually available in a short implementation note or console output.
5. Never substitute synthetic forecast rows for missing real artifacts.

**Exit condition:** choose initial runtime mode: replay, inference, or benchmark-only.

## Phase 1 — Scaffold a deployable CPU-only app

Create the `demo/` structure from `TECHNICAL_SPEC.md`.

Minimum first commit should include:

- Streamlit entrypoint;
- domain modules;
- requirements;
- `.env.example` with no secrets;
- tests skeleton;
- demo README.

The initial app should launch in benchmark-only mode using the currently committed repository.

**Exit condition:** `streamlit run demo/app.py` works without province forecast artifacts.

## Phase 2 — Implement benchmark and project-context views

1. Load committed result CSVs from `results/`.
2. Build normalized benchmark rows.
3. Distinguish saved A100 search, compact rerun, prior-fold meta, and diagnostic rows.
4. Exclude same-fold inverse-MAE blend from headline cards.
5. Build Methodology & Limitations page grounded in current code.
6. Show project scope from `data/dataset_summary.csv` where practical.

**Exit condition:** a judge can understand the current research even with no replay artifact.

## Phase 3 — Implement replay snapshot contract

1. Add Pydantic/dataclass schema and dataframe validation.
2. Implement mode resolver.
3. Add `build_demo_snapshot.py`.
4. Support CSV and Parquet inputs.
5. Create a JSON manifest for generated snapshots.
6. Add unit tests for required fields, dates, horizons, prices, and duplicates.

If a real `finalist_oof_predictions.csv` exists, build a replay snapshot from it.

If it does not exist but the model-ready panel exists and the environment can reasonably run the research code, the assistant may provide an **explicit separate command** for generating OOF predictions. Do not make that command run on app startup, Docker build, or deployment startup.

**Exit condition:** valid replay files are loadable without changing application code.

## Phase 4 — Implement Overview and Province Replay

### Overview

- filters: forecast origin, horizon, commodity, market level, model;
- warning summary counts;
- province ranking by projected positive price movement;
- current price, predicted price, projected change, warning badge;
- no fake map requirement.

### Province Replay

- forecast-as-of card;
- target date;
- predicted price;
- product warning;
- evidence metadata;
- optional later realized price and replay error;
- explicit retrospective label around target actuals.

**Exit condition:** at least one valid real replay row produces a coherent 7d/14d detail view when a real artifact is supplied.

## Phase 5 — Warning and evidence layer

1. Implement deterministic percentage-change calculation.
2. Implement configurable `STABLE/WATCH/ELEVATED/HIGH` thresholds.
3. Test exact boundary behavior.
4. Implement neutral evidence adapter.
5. Only show real attribution data.
6. If no attribution exists, show evidence availability/freshness instead of invented SHAP.

**Exit condition:** no UI text implies a learned probability or calibrated confidence without supporting artifacts.

## Phase 6 — Polish for competition demo

Improve the first-screen narrative:

- one-line problem statement;
- mode/as-of badge;
- focused selectors;
- 3–4 headline cards at most;
- clear warning labels;
- concise methodology trust callout;
- clean IDR formatting;
- responsive layout.

Add a short `Demo script` section to `demo/README.md` describing a 2–3 minute presentation flow.

Do not add visual complexity that creates runtime instability.

## Phase 7 — Containerize and test

1. Build CPU-only Docker image.
2. Run Streamlit in the container.
3. Run all unit tests.
4. Verify benchmark-only mode on a clean clone-like environment.
5. Verify replay mode with a valid snapshot if available.
6. Verify app behavior when snapshot path is invalid.
7. Confirm no network call is required for normal runtime.
8. Confirm no credentials/secrets are present in new tracked files.

Suggested commands:

```bash
python -m pytest demo/tests -q
streamlit run demo/app.py

docker build -f demo/Dockerfile -t pasarpulse-demo .
docker run --rm -p 8501:8501 pasarpulse-demo
```

## Phase 8 — Deployment handoff

The coding assistant should leave platform-neutral deployment artifacts and instructions.

Do not create external cloud resources or publish credentials unless the user explicitly provides/authorizes a platform and secret mechanism.

Recommended output at handoff:

- local launch command;
- Docker launch command;
- required environment variables;
- replay snapshot generation command;
- detected demo mode;
- test summary;
- known remaining limitations.

## Optional Phase 9 — Only if MVP is stable

Potential additions:

- Indonesia map using a properly licensed/static province geometry asset;
- JSON evidence export;
- FastAPI endpoint;
- serialized-model inference adapter;
- deterministic evidence-linked narrative;
- CI for tests/container build.

Do not start these until Phases 0–8 are green.

## Stop / escalation conditions

Stop and surface the issue instead of inventing a workaround when:

- only target/actual prices exist but no forecast predictions exist;
- model artifacts have incompatible feature schemas;
- a replay row cannot be tied to a legitimate forecast origin;
- a requested confidence/probability metric has no validated source;
- a source requires committing a secret;
- the only way to create a desired screenshot is to fabricate data.

## Final completion report expected from Codex

At the end, report:

1. files added/changed;
2. active data modes implemented;
3. exact source artifacts used for replay/inference;
4. commands run;
5. tests passed/failed;
6. Docker status;
7. claims intentionally omitted because they remain proposal-only;
8. next smallest step required for a public hosted URL, if not already authorized.
