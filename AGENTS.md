# AGENTS.md — PasarPulse

This repository contains the PasarPulse Datathon RISTEK UI 2026 research project.

Before implementing or changing the deployment demo, read these files in order:

1. `codex/deployment-demo/README.md`
2. `codex/deployment-demo/PROJECT_CONTEXT.md`
3. `codex/deployment-demo/PRD.md`
4. `codex/deployment-demo/TECHNICAL_SPEC.md`
5. `codex/deployment-demo/SCIENTIFIC_GUARDRAILS.md`
6. `codex/deployment-demo/EXECUTION_PLAN.md`
7. `codex/deployment-demo/PAPER_CONTEXT.md`
8. `codex/deployment-demo/CODEX_PROMPT.md`

## Repository-wide instructions

- Treat the current repository and saved result files as the source of truth for what was actually implemented and validated.
- The earlier PasarPulse-MM paper is proposal context, not proof that every proposed component exists in the current codebase.
- Do not rewrite validated metric CSVs, notebook outputs, or research claims merely to make the demo look better.
- Do not retrain models during application startup or on user interaction.
- Prefer a precomputed historical replay/snapshot for the competition demo. Add live inference only when real model artifacts and a compatible feature snapshot are available.
- Never fabricate province forecasts, SHAP values, confidence percentages, prediction intervals, shock probabilities, threshold-exceedance probabilities, or graph-propagation probabilities.
- Do not present the visible `FINALIST_INVERSE_MAE_BLEND` as a leakage-safe benchmark. Its weights are computed from the same evaluation fold. Exclude it from the default demo benchmark or label it explicitly as diagnostic only.
- Keep saved A100 architecture-search scores distinct from the compact executable finalist rerun.
- Product warning levels derived from forecast percentage movement are configurable decision rules, not learned probabilities or regulatory thresholds.
- Preserve the decision-support framing: PasarPulse supports monitoring and verification; it does not automatically set prices or dispatch supply.
- Satellite features are regional vegetation proxies, not direct commodity-production observations. Annual production is structural context, not realized daily supply. Relational/graph-derived features are not observed commodity flows.
- Never copy, expose, or reuse hard-coded credentials from existing repository files. New secrets must be supplied via environment variables or deployment-platform secret stores.
- Do not add a new external network dependency to the runtime path unless the application has a deterministic cached/offline fallback.
- New demo code must have tests for data contracts and warning logic and must run without GPU.

## Preferred implementation boundary

The MVP is a modular Streamlit application backed by precomputed local artifacts/Parquet/CSV. Keep a clean domain layer so FastAPI can be added later, but do not make a separate API service a prerequisite for the first deployable demo.
