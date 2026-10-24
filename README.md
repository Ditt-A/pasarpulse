# PasarPulse — Datathon RISTEK UI 2026

PasarPulse is an uncertainty-aware early-warning system for high-value horticultural commodity prices.

## Dashboard

A focused workspace for national price monitoring, province-level forecasts,
source evidence, regional comparisons, and validated model results.

![PasarPulse national market overview](docs/images/dashboard-overview.png)

The preview uses the real **2 February 2026** historical snapshot for
**Cabai Rawit Merah · retail · 7 days**. The application defaults to the latest
available forecast origin. All prices and warning levels come from the saved
replay artifacts; no model is loaded or trained to display the dashboard.

<details>
<summary>Province detail and mobile preview</summary>

![Province forecast, evidence, and historical evaluation](docs/images/dashboard-province.png)

[View the mobile dashboard](docs/images/dashboard-mobile.png).

</details>

See [local and Docker setup](README_DEPLOYMENT.md) and the
[dashboard interaction guide](docs/DASHBOARD_UX.md).

## Main notebook

- `notebooks/PasarPulse_A100_Research_Notebook.ipynb`

The notebook is executed and follows the research-paper structure from title page
through references. Its model section includes the actual feature construction,
chronological split logic, LightGBM and CatBoost training functions, seven-origin
finalist execution, fold metrics, explainability checks, and deployment-shaped
export. The larger 120-configuration search is reported from its saved A100
artifacts.

The compact finalist source is also checked in at
`experiments/pasarpulse_notebook_finalist.py`; its implementation is expanded into
the visible model subsections when the notebook is built.

## Data and model archive

The repository includes the complete reproducibility archive used by the A100
runs:

- `data/`: raw PIHPS/SP2KP/BPS inputs, processed price/calendar/production
  tables, ready model panels, and GeoJSON reference layers.
- `reports/` and `results/`: baseline, architecture-search, specialist,
  meta-router, OOF, feature-importance, and holdout artifacts.
- `models/`, `experiments/`, `pipeline/`, and `src/`: model and acquisition
  source code.
- `models/weights/`: deployable full-data LightGBM boosters for the winning
  seven-day and fourteen-day log-ratio experts, with their feature and
  categorical-mapping manifest.
- `model_runs/`: full parent-run outputs and architecture-sweep artifacts.

The two large ready-panel CSVs and the 75 MB model feature panel use Git LFS.
Credentials, virtual environments, caches, and temporary process files are
not included.

## Experiment summary

- 120 architecture configurations screened
- 7 chronological rolling forecast origins
- 7-day and 14-day horizons
- commodities: Bawang Merah, Cabai Merah Keriting, Cabai Rawit Merah
- market levels: producer, wholesale, retail

## Validated headline results

| Model | Horizon | MAE | WAPE |
|---|---:|---:|---:|
| ARIMA reference | 7 days | Rp3,731.69/kg | — |
| Raw CatBoost GPU log-ratio | 7 days | Rp3,581.00/kg | — |
| Leakage-safe commodity × market grid blend | 7 days | Rp3,454.11/kg | — |
| LightGBM log-ratio | 7 days | Rp3,275.46/kg | — |
| CatBoost commodity × market specialist | 7 days | Rp3,371.66/kg | 7.27% |
| CatBoost commodity × market specialist | 14 days | Rp4,858.38/kg | 10.44% |
| Prior-fold-only soft-error meta blend | 7 days | Rp3,495.79/kg | — |
| Prior-fold-only error router | 14 days | Rp4,952.64/kg | — |
| Best late-origin ensemble | 7 days | Rp3,642.35/kg | — |
| Best late-origin ensemble | 14 days | Rp5,004.57/kg | — |

The executed compact finalist check in the notebook produced LightGBM log-ratio
MAE Rp3,638.02/kg at 7 days and Rp5,464.92/kg at 14 days over the same seven
origins. The notebook also reports the visible CatBoost and inverse-MAE blend
outputs in `results/finalist_pooled_metrics.csv`. These values are a
reproducibility check for the visible training loop, not a replacement for the
stronger saved A100 architecture-search scores above.

## Completed six-modality A100 ablation

The repository also contains a separate, fully executed chronological ablation
using the merged price, calendar, ERA5-Land weather, BPS production, Sentinel-2
vegetation, official-market/static-graph, and rolling price-dependence graph
features. It evaluates the implemented tree models only; the proposed
TFT/CNN/GNN architecture is not claimed to be trained.

| Result | Horizon | Pooled MAE | Rows | Origins |
|---|---:|---:|---:|---:|
| Best ablation: LightGBM log-ratio + all modalities + dynamic graph | 7 days | Rp3,538.49/kg | 1,946 | 7 |
| Best ablation: LightGBM log-ratio + price + calendar | 14 days | Rp5,308.47/kg | 1,947 | 7 |
| Persistence reference | 7 days | Rp3,689.08/kg | 1,946 | 7 |
| Persistence reference | 14 days | Rp5,780.25/kg | 1,947 | 7 |

Against the matching persistence rows, the best ablation improves pooled MAE by
4.08% at 7 days and 8.16% at 14 days. The all-modality dynamic-graph variant is
best at 7 days, but not at 14 days; the 14-day result is therefore selected by
the validation table rather than assumed from the richer feature set. The full
fold, OOF, feature-contract, availability audit, and result validation files
are in `results/multimodal_ablation/`.

## Scope

The 120-model sweep and the finalist retraining ran as GPU Python jobs on an
NVIDIA A100. The notebook does not falsely claim to retrain every search
configuration interactively; it does show and execute the finalist training loop.

## Operational semifinal demo

The repository also contains the deployable PasarPulse product layer: a Next.js
command center backed by FastAPI and read-only local replay artifacts. It does
not train at runtime or call upstream data APIs.

```bash
docker compose up --build
```

Then open `http://localhost:3000`. The default mode is `HISTORICAL REPLAY` over
the seven leakage-safe origins in `demo_data/`. Set `PASARPULSE_LLM_API_KEY` in
a local, uncommitted `.env` to enable Gemini Copilot. Without it, the product
remains usable but Copilot returns an explicit configuration error; no canned
answer is generated.

The product intentionally reports unavailable scientific outputs as unavailable:
the current finalist artifact has no shock probabilities, propagation scores,
attribution values, or uncertainty intervals. See `README_DEPLOYMENT.md`,
`docs/IMPLEMENTATION_AUDIT.md`, `docs/METHODOLOGY.md`,
`docs/A100_ARTIFACT_AUDIT.md`, and `docs/DEMO_SCRIPT.md` for deployment,
artifact truth, methodology alignment, A100 provenance, and the semifinal
story.
