# PasarPulse-MM methodology alignment

This document records the methodology in the A100 concept paper and maps it to
what is actually implemented in the repository.

## Source of truth

The source reference is:

```text
<PROJECT_ROOT>/PasarPulse_MM_AI_Product_Concept_Paper.docx
```

The concept paper is the reference for the proposed research architecture. The
current product and replay artifact remain the reference for implemented
capabilities. A proposed component is not described as deployed unless a
trained artifact and validation output exist.

## 1. Product objective

PasarPulse-MM is a decision-support system for anticipating seven- and
fourteen-day horticultural price shocks in Indonesia. Its intended outputs are:

- point and quantile price forecasts;
- probability of an abrupt increase and, where applicable, reference-price
  exceedance;
- possible propagation to connected regions or market levels;
- calibrated uncertainty and evidence quality; and
- ranked locations for verification, monitoring, or supply-coordination review.

The system recommends questions for human analysts. It does not set prices,
dispatch food, or make autonomous market interventions.

## 2. Proposed data strategy

The concept paper defines a pilot focused on North Sumatra, initially covering
bird's-eye chili, red/curly chili, and shallots over a proposed January 2023 to
July 2026 period, subject to completeness auditing. The target spatial unit is
district/city, while producer, wholesale, and retail levels represent distinct
price-formation stages.

The proposed modalities are:

| Modality | Source | Intended role | Important limitation |
|---|---|---|---|
| Price | Bapanas / PIHPS | Daily target, lags, spreads, revisions | Coverage, units, and revisions require audit |
| Weather | ERA5-Land | Rain, temperature, soil moisture, radiation | Hourly data must be aggregated to the modeling day |
| Satellite | Sentinel-2 L2A | NDVI/EVI/NDWI and crop-condition context | Clouds and revisit gaps require missingness handling |
| Production | BPS | Annual structural supply, area, productivity | Not a real-time supply measurement |
| Calendar | Official calendars | Ramadan, Eid, holidays, market-day and seasonal effects | Effective dates and revisions must be versioned |
| Graph | OSM / boundaries | Adjacency, road travel, and market connectivity | Candidate connectivity is not confirmed commodity flow |

Satellite summaries are intended to be computed over cropland or known
production areas. The methodology does not treat every vegetated pixel as the
target commodity.

## 3. Proposed model architecture

### 3.1 Modality-specific encoders

- A Temporal Fusion Transformer or Temporal Convolutional Network encodes price
  history, calendar, and aggregated weather.
- A compact CNN or vision transformer encodes cloud-filtered Sentinel-2
  sequences.
- An MLP encodes production and static regional features.

Each modality is converted into date- and region-indexed embeddings.

### 3.2 Asynchronous alignment and missing modalities

Price and weather are aligned daily. Satellite features may be carried forward
only within a bounded validity window and must include observation age and cloud
quality. Missingness masks, learned missing tokens, and modality dropout prevent
missing observations from being interpreted as zero values. Fusion gates learn
how much evidence to use for a region and date.

### 3.3 Dynamic multi-level graph

A node represents a district–commodity–market-level combination. Candidate edges
encode geographic adjacency, estimated road travel time,
producer–wholesale–retail links, and rolling lead–lag price relationships.
Dynamic graph attention is intended to propagate useful information between
connected nodes.

Any product visualization must label these as **model-inferred price
dependence** or **candidate structural connectivity** unless observed shipment
data support a stronger interpretation.

### 3.4 Multi-task outputs

The proposed heads jointly predict median and quantile prices, a seven-day
increase above a candidate threshold, reference-price exceedance where
applicable, and propagation likelihood to connected nodes. Quantile loss or
conformal calibration produces intervals. Proposed explanations include
temporal attention, modality-gate weights, tabular SHAP values, and influential
graph edges.

The paper's candidate shock label is a **10% or greater increase within seven
days**. This is a modeling choice, not a regulatory threshold. HAP/HET labels
are separate reference-price targets and must not be conflated with the
product's warning heuristic.

## 4. Training and evaluation protocol

The proposal requires chronological rolling-origin splits to avoid future
leakage and a leave-region-out test for spatial generalization. The proposed
baseline ladder is:

| ID | Baseline / variant |
|---|---|
| B0 | Last-value or seasonal-naive forecast |
| B1 | ARIMA |
| B2 | Price-only LSTM/GRU |
| B3 | Price-only TFT |
| B4 | Price plus weather |
| B5 | All modalities without graph |
| Proposed | All modalities with dynamic graph and missing-aware fusion |

Evaluation should report price MAE, sMAPE, pinball loss, interval coverage and
width; shock PR-AUC, recall, false-negative rate and lead time; Brier score and
expected calibration error; propagation edge/node PR-AUC and earliest correct
warning; rolling-origin and leave-region-out performance; and missing-data,
modality-ablation, and progressive-system variants.

## 5. Implemented repository status

The semifinal product currently serves a real national province-level replay
artifact, not the full proposed model:

- validated multimodal tree winners: 7-day all-modalities/dynamic-graph and
  14-day price/calendar LightGBM log-ratio;
- province × commodity × market-level rows;
- 7-day and 14-day endpoint forecasts over seven chronological origins;
- offline fitted weights and OOF predictions;
- configurable product warning rules at 5%, 10%, and 15%;
- 38-province geometry with explicit insufficient-evidence coverage;
- historical replay with realized prices kept evaluation-only; and
- validated Gemini Copilot interpretation; unavailable when the API key is absent.

The product snapshot is built from the national, leakage-gated contextual
ablation around those executable tree models. This is not a claim that the
product serves the proposed multimodal neural model. Its inputs and timing
rules are:

| Input | Implemented representation | Replay-time availability rule |
|---|---|---|
| Price | PIHPS daily province × commodity × market panel and lag/rolling features | Observation date; bounded three-day fill only |
| Calendar | Official holidays, Ramadan/Eid, day/week/month seasonality, and official market operating-frequency context | Known calendar/version; no realized target values |
| Weather | ERA5-Land hourly fields aggregated to UTC province-day means/totals | Observation date plus five days; maximum age ten days |
| Production | BPS annual production, harvested area, and derived productivity | Official publication date for each statistical year |
| Satellite | Sentinel-2 C1 L2A NDVI/EVI/NDWI samples selected from one locked MGRS grid at a fixed interior representative point per province, clipped to province overlap, with SCL mask | STAC publication timestamp, then bounded 24-day carry |
| Static graph | BIG adjacency/centroid geometry plus dated OSM road, ferry, port, and market summaries | OSM snapshot date 2026-01-01 |
| Dynamic graph | Rolling 90-day lead-lag, shock co-occurrence, and seasonal-similarity summaries | Snapshot uses only its trailing window |

For accumulated ERA5-Land fields, the next-day 00:00 UTC value is assigned to
the preceding UTC day. One-record segment-boundary files are used only to close
precipitation and radiation totals; they are never interpreted as full-day
temperature or soil-moisture observations.

The official market layer contributes declared market availability and
operating-frequency context. Availability masks are passed as features, but
they are never presented as model importance or confidence.

The implemented progressive tree experiment evaluates:

1. persistence;
2. price-only LightGBM;
3. price + calendar;
4. price + calendar + weather;
5. price + calendar + weather + BPS production;
6. the same inputs plus Sentinel-2;
7. all modalities plus candidate static graph context; and
8. all modalities plus the rolling price-dependence graph.

LightGBM is evaluated for every progressive variant. CatBoost GPU log-ratio
and scaled-delta experts are evaluated for the final all-modality variant.
Every model uses the same seven chronological origins and separate seven- and
fourteen-day endpoint targets. A training label is admitted only when its
target date is on or before that fold's forecast origin. No test-fold metric is
used to fit an ensemble weight or routing rule. Full-period price coverage and
`months_available` define the archived evaluation cohort only; those summaries
are excluded from the model feature contract because they include observations
after early replay origins.

The completed A100 run is recorded in
`results/multimodal_ablation/pooled_metrics.csv`. It contains 10 model rows per
horizon (persistence, seven LightGBM modality variants, and two all-modality
GPU CatBoost targets), seven folds per model, and 1,946 / 1,947 pooled rows for
the 7-day / 14-day horizons. The best pooled MAE is Rp3,538.49/kg at 7 days
for LightGBM with all modalities and the dynamic graph, and Rp5,308.47/kg at
14 days for LightGBM with price plus calendar. The matching persistence
references are Rp3,689.08/kg and Rp5,780.25/kg. These are research ablation
scores, not a claim that every modality improves every horizon. The selected
OOF winners are the replay artifact; modality membership is still not model
attribution.

The A100 result contract (`pipeline/validate_multimodal_results.py`) checks all
14 folds, finite predictions and metrics, target-date alignment, one forecast
per model/series/fold/date key, OOF row counts, zero future-availability
violations, and a feature contract without realized labels. The executed
validation report contains 25 passed checks and zero failures.

The following remain proposal/roadmap components and are not claimed as
deployed: TFT/TCN encoders, Sentinel-2 CNN/ViT encoders, learned missing
tokens, gated multimodal fusion, dynamic GNN propagation, shock or propagation
probabilities, calibrated intervals, SHAP/TimeSHAP/GNN explanations, and
leave-region-out results for the multimodal architecture. The implemented
rolling graph is a tabular contextual feature source, not a trained GNN.

This separation is intentional: the product can communicate the research
direction without fabricating scientific outputs that are absent from the
current artifact.

## 6. Deployment and decision boundary

The product layer is an offline artifact-serving application. Runtime does not
train models or call upstream data APIs. A warning routes an analyst to verify
market prices, supply, distribution, or logistics and to escalate human review
when appropriate. It does not autonomously intervene in food markets.
