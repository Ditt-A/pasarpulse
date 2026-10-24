# Technical Specification — PasarPulse Demo

## 1. Chosen MVP architecture

Use a **modular Streamlit monolith** for the first competition deployment. Keep the domain/data modules independent from Streamlit so a FastAPI service can be added later without rewriting the forecasting presentation logic.

```text
local artifacts / result CSVs
          |
          v
   loader + schema validation
          |
          v
 replay/inference domain model
          |
    +-----+----------------+
    |                      |
warning rules        evidence adapter
    |                      |
    +----------+-----------+
               |
               v
        Streamlit views
```

No training and no public-data ingestion happen on the request/runtime path.

## 2. Proposed repository layout

Codex should implement approximately this structure, adapting names only when there is a strong repository reason:

```text
demo/
  app.py
  README.md
  requirements-demo.txt
  Dockerfile
  .env.example
  pasarpulse_demo/
    __init__.py
    config.py
    schemas.py
    data.py
    mode.py
    warning.py
    evidence.py
    metrics.py
    formatting.py
    charts.py
  pages/
    1_Overview.py
    2_Province_Replay.py
    3_Model_Performance.py
    4_Methodology.py
  scripts/
    build_demo_snapshot.py
    inspect_artifacts.py
  tests/
    test_warning.py
    test_snapshot_schema.py
    test_mode_resolution.py
    test_metrics_loading.py
```

If Streamlit multipage discovery conflicts with the installed Streamlit version, keep pages in `demo/pages/` and `app.py` as the entrypoint.

## 3. Configuration

Use environment variables with sensible local defaults:

```text
PASARPULSE_DEMO_MODE=auto
PASARPULSE_REPLAY_PATH=
PASARPULSE_INFERENCE_PATH=
PASARPULSE_MODEL_DIR=
PASARPULSE_BENCHMARK_DIR=results
PASARPULSE_DEMO_TITLE=PasarPulse
```

`auto` resolution order:

1. valid explicit replay artifact;
2. known local replay artifact candidates discovered by a small deterministic list;
3. valid inference snapshot + model bundle;
4. benchmark-only mode.

Do not recursively crawl the whole machine.

## 4. Replay snapshot contract

Create a typed schema and validator for a flat table. Minimum required columns:

```text
series_id
province_code
province_name
commodity_code
commodity_name
market_level
forecast_origin
horizon_days
target_date
current_price
predicted_price
model
```

Optional but strongly supported:

```text
target_price                     # realized later; evaluation only
fold_id
evidence_quality_score
mask_price
mask_weather
mask_production
mask_satellite
mask_calendar
price_observation_age_days
satellite_observation_age_days
price_series_coverage
months_available
model_version
data_version
feature_version
top_features_json                # only real attribution values
```

Validation rules:

- parse dates explicitly;
- `horizon_days` must currently be 7 or 14;
- `target_date >= forecast_origin`;
- price columns must be finite and positive when present;
- categorical identity columns must be non-empty;
- duplicate logical keys should be rejected or deterministically resolved with a warning, never silently multiplied in the UI;
- `target_price` must never be required for the forecast path.

Canonical logical key:

```text
series_id + forecast_origin + horizon_days + model
```

## 5. Building a replay artifact

`experiments/pasarpulse_notebook_finalist.py` already writes `finalist_oof_predictions.csv` when `run_finalist_cv(...)` is executed.

`demo/scripts/build_demo_snapshot.py` should:

1. accept a path to an existing OOF/holdout prediction CSV or Parquet;
2. validate required columns;
3. optionally enrich rows from the model-ready panel using only fields whose timestamps are available at/before `forecast_origin`;
4. never recompute the prediction from `target_price`;
5. normalize dates/types/names;
6. write a compact Parquet snapshot for the demo;
7. write a small JSON manifest with source path/hash if feasible, row count, date range, models, horizons, commodities, market levels, and generation timestamp.

Do not make the snapshot builder automatically retrain models. A separate explicit research command may generate OOF predictions if the required model-ready panel exists.

## 6. Warning domain logic

Implement a pure function, for example:

```python
def projected_change_pct(current_price: float, predicted_price: float) -> float:
    ...


def classify_price_rise_warning(change_pct: float, thresholds: WarningThresholds) -> str:
    ...
```

Default thresholds:

```text
watch = 5.0
elevated = 10.0
high = 15.0
```

Rules are based on positive percentage price change only:

```text
< 5                 STABLE
>= 5 and < 10       WATCH
>= 10 and < 15      ELEVATED
>= 15               HIGH
```

The UI copy must state that these are product/demo decision thresholds, not forecast probabilities and not regulatory thresholds.

## 7. Evidence adapter

Create a neutral evidence object with fields such as:

```text
overall_score: optional float
available_modalities: list[str]
missing_modalities: list[str]
freshness: dict[str, str | number]
attributions: optional list[FeatureContribution]
```

Important behavior:

- masks indicate availability, not importance;
- observation age indicates freshness, not model contribution;
- `evidence_quality_score`, if present, is displayed as a source score; do not convert it into `% confidence`;
- feature contributions are shown only if `top_features_json` or another real attribution artifact exists.

## 8. Benchmark loader

Read benchmark information from existing files under `results/` and avoid embedding the entire metrics table in UI code.

Create a small normalization layer that can label rows into groups such as:

```text
saved_a100_search
compact_visible_rerun
prior_fold_meta
diagnostic
```

Where the exact group cannot be derived automatically from CSV columns, maintain a small transparent mapping in `metrics.py` with comments and tests.

The visible `FINALIST_INVERSE_MAE_BLEND` should be tagged `diagnostic_same_fold_weighting` and excluded from default headline cards.

## 9. Main overview behavior

When forecast rows exist:

- filters: origin, horizon, commodity, market level, model;
- aggregate/rank provinces by `projected_change_pct`;
- show counts by warning level;
- show a table with province, current price, predicted price, change %, warning;
- table sorting defaults to largest projected increase;
- clicking/selecting a province leads to detail view.

When no forecast rows exist:

- show benchmark-only empty state;
- provide detected artifact paths and a command example for `build_demo_snapshot.py`;
- still show project scope and validated metrics.

## 10. Province replay behavior

Display:

```text
Forecast as of: YYYY-MM-DD
Target date:     YYYY-MM-DD
Current price:   Rp xx.xxx/kg
Predicted price: Rp xx.xxx/kg
Projected move:  +x.x%
Warning:         WATCH/ELEVATED/HIGH/STABLE
```

If `target_price` exists:

```text
Realized later: Rp xx.xxx/kg
Absolute error: Rp x.xxx/kg
```

The actual/realized block must be titled **Historical evaluation — not available to the model at forecast time**.

A compact line or slope chart is sufficient; do not fabricate a full historical time series if only the origin and target values are available.

## 11. Methodology view

Use text grounded in current code/repo:

- LightGBM log-ratio and CatBoost scaled-delta experts;
- transformed-target reconstruction;
- seven chronological origins;
- train labels constrained by `date + horizon <= origin`;
- context and missingness features;
- limitations.

Do not present the paper's TFT/CNN/GNN architecture as current implementation.

## 12. Dependency guidance

Keep demo dependencies small. Likely packages:

```text
streamlit
pandas
pyarrow
plotly
pydantic
pytest
```

Only add `lightgbm`, `catboost`, or `shap` to the demo runtime requirements if inference/attribution actually runs inside the deployed process. A replay-only demo should not need them.

Pin compatible major/minor versions or use bounded ranges. Do not depend on Jupyter for runtime.

## 13. Docker

Build a CPU-only image. Requirements:

- non-root user if practical;
- copy only necessary repo/demo assets;
- expose Streamlit port 8501;
- healthcheck can use Streamlit's health endpoint where supported;
- startup command binds `0.0.0.0` and reads the platform-provided port only if the chosen host requires it.

A generic local command should work:

```bash
docker build -f demo/Dockerfile -t pasarpulse-demo .
docker run --rm -p 8501:8501 pasarpulse-demo
```

## 14. Testing requirements

Minimum tests:

### `test_warning.py`
- exact boundaries 4.99, 5, 9.99, 10, 14.99, 15;
- negative change;
- invalid/non-positive current price raises or returns a validated error.

### `test_snapshot_schema.py`
- valid 7d/14d rows pass;
- invalid horizon fails;
- target before origin fails;
- missing identity field fails;
- `target_price` is optional.

### `test_mode_resolution.py`
- replay beats inference when explicitly configured;
- benchmark fallback occurs when artifacts are absent;
- invalid replay file produces a clear validation failure or fallback according to config.

### `test_metrics_loading.py`
- committed results load;
- diagnostic blend is not in headline set.

## 15. Optional phase after MVP

Only after the replay demo is stable:

- FastAPI endpoint for snapshot records;
- JSON evidence export using a Pydantic schema;
- deterministic evidence-linked narrative;
- actual local inference from serialized models;
- map/GIS view;
- deployment-specific CI/CD.

Do not let these optional items delay a stable replay demo.
