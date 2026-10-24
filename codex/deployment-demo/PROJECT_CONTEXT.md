# Project Context — Current PasarPulse Repository

## 1. What PasarPulse is now

PasarPulse is an uncertainty/evidence-aware early-warning project for Indonesian horticultural commodity prices. The current repository focuses on **point forecasts for 7-day and 14-day horizons** over province × commodity × market-level panel series.

Current scope reported by the repository:

- 254,448 model-ready rows;
- 95 model-ready columns;
- 3 commodities: Bawang Merah, Cabai Merah Keriting, Cabai Rawit Merah;
- 3 market levels: producer, wholesale, retail;
- 7 chronological rolling forecast origins;
- forecasting targets: `price_t_plus_7` and `price_t_plus_14`.

Primary implementation references:

- `README.md`
- `notebooks/PasarPulse_A100_Research_Notebook.ipynb`
- `experiments/pasarpulse_notebook_finalist.py`
- `results/summary_metrics.csv`
- `results/finalist_pooled_metrics.csv`
- `results/meta_metrics.csv`
- `data/dataset_summary.csv`

## 2. Actual model family

The current visible finalist is a tabular/global forecasting system, not the multimodal GNN proposed in the original paper.

### LightGBM expert

The visible finalist uses `LGBMRegressor(objective="l1")` and predicts the transformed target:

```text
target_logratio = log(target_price / current_price)
```

The prediction is reconstructed to IDR/kg using the current price.

### CatBoost expert

The visible finalist uses `CatBoostRegressor(loss_function="MAE")` and predicts:

```text
target_scaled_delta = (target_price - current_price) / current_price
```

The code tries GPU first and falls back to CPU.

### Feature families visible in the finalist

- categorical: province, commodity, market level;
- price state: current price, observation status/age, historical coverage;
- price lags: 1/7/14/28/56 days;
- rolling means/median/std and price deltas;
- calendar/seasonality and holiday-event distance features;
- production, harvested area, productivity and production age;
- Sentinel-derived NDVI/NDWI statistics, anomaly/z-score, cloud cover and observation age;
- modality availability masks;
- `evidence_quality_score`.

The wider research notebook/saved architecture search also discusses relational/graph/context feature sets and specialization. These are tabular/relational features in the validated semifinal approach, not proof of a deployed GNN.

## 3. Leakage-safe chronological split

For horizon `h` and forecast origin `t`, the visible split uses training rows whose labels are known by the origin:

```text
date < origin
and date + horizon <= origin
```

The test set uses rows at `date == origin`. A series must have at least 240 eligible historical training rows at that origin in the visible finalist code.

This chronological construction is central to the product story and should be made visible in the demo through a historical **forecast-as-of** replay.

## 4. Validated headline metrics currently reported

The repository README reports the following saved/validated headline results:

| Model | Horizon | MAE | WAPE |
|---|---:|---:|---:|
| ARIMA reference | 7d | Rp3,731.69/kg | — |
| Raw CatBoost GPU log-ratio | 7d | Rp3,581.00/kg | — |
| Leakage-safe commodity × market grid blend | 7d | Rp3,454.11/kg | — |
| LightGBM log-ratio | 7d | Rp3,275.46/kg | — |
| CatBoost commodity × market specialist | 7d | Rp3,371.66/kg | 7.27% |
| CatBoost commodity × market specialist | 14d | Rp4,858.38/kg | 10.44% |
| Prior-fold-only soft-error meta blend | 7d | Rp3,495.79/kg | — |
| Prior-fold-only error router | 14d | Rp4,952.64/kg | — |
| Best late-origin ensemble | 7d | Rp3,642.35/kg | — |
| Best late-origin ensemble | 14d | Rp5,004.57/kg | — |

The compact visible finalist rerun is a separate reproducibility check. The README reports LightGBM log-ratio MAE of approximately Rp3,638.02/kg at 7 days and Rp5,464.92/kg at 14 days over the seven visible origins.

**Do not merge these two result families into one claim.** Saved A100 architecture-search results and compact visible rerun results must be labeled separately.

## 5. Known evaluation caveat

The visible `FINALIST_INVERSE_MAE_BLEND` computes inverse-MAE weights from the **same test fold** and then evaluates the blend on that fold. That makes it unsuitable as a leakage-safe headline benchmark.

For the demo:

- do not select it as the default model;
- do not call it leakage-safe;
- either hide it from the main benchmark table or mark it `diagnostic / same-fold-weighted`;
- prefer base-model results and prior-fold-only meta results for claims.

## 6. Current remote-repository data limitation

The visible finalist expects:

```text
data/ready/model_dataset_eligible.parquet
```

The file is not currently committed in the GitHub repository. The committed `data/` directory exposes only lightweight summary information. The committed `results/` directory contains metric CSVs, not province-level forecast rows.

Therefore the deployment code must not assume a model-ready panel is available on a clean clone.

Codex must first inspect the actual execution workspace for untracked/local artifacts. If no real replay/inference artifact exists, build a truthful benchmark-only mode and a deterministic snapshot builder. Do not fabricate province-level price histories or predictions.

## 7. Product positioning

The demo should frame PasarPulse as:

> a leakage-safe, multi-horizon early-warning decision-support system that turns historical prices and contextual public-data signals into a forward-looking monitoring priority.

It should **not** frame the system as:

- an exact price oracle;
- a causal supply-chain model;
- an automatic intervention engine;
- a calibrated probability-of-shock model unless such a classifier/calibration artifact is actually added later;
- a deployed dynamic GNN.

## 8. Suggested deployment interpretation

The most defensible competition demo is a retrospective replay using a validated origin:

```text
information available as of forecast origin
        -> model prediction at +7/+14 days
        -> product warning rule
        -> evidence availability / quality
        -> later realized price shown only as retrospective evaluation
```

This gives judges a concrete experience while preserving the scientific evaluation boundary.
