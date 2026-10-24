# A100 artifact audit

This audit was executed through the existing JupyterHub kernel API on 2026-08-09.
The remote session reported:

```text
workspace: <PROJECT_ROOT>
user: <REDACTED_USER>
GPU: NVIDIA A100-SXM4-80GB
```

No credentials are stored in this document.

## Methodology source

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `PasarPulse_MM_AI_Product_Concept_Paper.docx` | 123,913 | `9a5ced7d9aff7c93aa9818c941850a14f627db5c1c8080798d08c5a11e7752ed` |

The extracted methodology is transcribed in [METHODOLOGY.md](METHODOLOGY.md).

## Remote source-data audit

| Artifact | Rows | Coverage / status | SHA-256 |
|---|---:|---|---|
| `data/processed/price_daily.csv` | 181,177 | 2024-02-01 to 2026-07-31; 34 provinces; BM/CMK/CRM; producer/wholesale/retail | `5852923c64029214352b99cd8c292d12ad8df0549e98609871004d2c5f3cc4dc` |
| `data/processed/production_annual.csv` | 342 | 38 provinces; BM/CMK/CRM; annual structural context | `e2e265769ff547fc422f2cf93bb6593210f55a17d179fd70acae3e61421517ed` |
| `data/manual/calendar_events.csv` | 131 | Official calendar events | `9b02a2da80ade00f755205bb14bc9b0f8c4af12fd43cae00c864c6733dbff709` |
| `data/reference/indonesia_provinces.geojson` | 38 features | Canonical province geometry | `f8e158195cfd5e3ac28b254ed1c1cb79987a832b82e1605b5559cd3b5351e94e` |

The earlier satellite-zone gap is resolved. The checked-in
`data/reference/satellite_zones.geojson` contains 38 documented province
fallback zones. The deployed replay now consumes the validated multimodal
winner per horizon; satellite context is surfaced with its real freshness and
missingness state, without being relabeled as attribution.

## Completed multimodal research artifacts

| Artifact | Rows | Coverage / semantics | SHA-256 |
|---|---:|---|---|
| `data/raw/sentinel2_asset_manifest.parquet` | 786 | 38 provinces; fixed interior point and one locked MGRS grid per province | `cb6e8514b4e2c10e505bac1e2e887e1b0c478779fdf3139a79941f27f1697df7` |
| `data/processed/satellite_features.parquet` | 786 | 786 usable NDVI/EVI/NDWI rows; five flagged low-valid-pixel scenes | `ec8e7ee6c2329816c7a96958ff590cc73c889e7b83228ab36280967fa6d06a24` |
| `data/processed/osm_province_transport_summary.parquet` | 38 | Dated road/ferry/port/market context for every province | `2ef8a2022788f75f432603672fc3af3bab2eea0f5ffdb99fa12387a5e01dfc9b` |
| `data/processed/osm_transport_edges.parquet` | 70 | Candidate structural connectivity; not shipments | `809a759d17ce27edda0c0e8bfa1eb3d126b5f995d8a93514e702065bb722cb4f` |
| `data/processed/province_graph_static.parquet` | 73 | Candidate adjacency/KNN/OSM graph | `21823ec368158ddc15aa01925ce0caeed038f56dbe4191ebedee3b1210be27b0` |
| `data/processed/province_graph_dynamic.parquet` | 37,485 | 27 historical rolling snapshots; model-inferred price dependence | `2a028217608d5b7fd99c5c65b080cd98dca0e1d1290fcfa9be69a11c6baf243b` |
| `data/processed/official_markets.parquet` | 625 | 37 provinces with source points; DKI source gap retained | `62b7dad2cc52245a42b7cec2d23d272dba270fa1aa148c04aac6ed3f2ccb9851` |
| `data/processed/weather_daily.parquet` | 35,834 | 38 provinces; 2024-01-01 to 2026-07-31; zero duplicate or missing province-days | `8ff2234927bb1a437dbd795da5dc3a5d15498427148f31938fce88b92aeaba08` |

The weather aggregate contains ERA5-Land temperature, accumulated rainfall,
layer-1 soil moisture, and surface solar radiation. Its metadata records 35
source files and the accumulation convention
`next_day_00utc_previous_24h`. The June 2026 source was received as a ZIP with
two aligned NetCDF members; it was normalized into one canonical NetCDF while
retaining each variable's source `expver` timeline. The original ZIP and the
normalization report remain on the A100 acquisition workspace.

The checksum-verified OSM source is the 2026-01-01 Geofabrik Indonesia
snapshot: 1,686,629,405 bytes, SHA-256
`4c290085dc779e8a85248c70c341b52a3920e1657b60fb3b54a75785d1c11746`.
The raw PBF remains on the A100 and outside Git; normalized tables and source
hashes are portable.

## Remote model-output audit

| Artifact | SHA-256 |
|---|---|
| `proposed_model_run/results/oof_predictions.csv` | `735f7c71886633e164153c93f0d87bc8550ef17656348336b901c710d6050855` |
| `proposed_model_run/results/pooled_metrics.csv` | `7496a5a4ab8be5a94449a2746d902c9f3ccf72c70d749c404f5129c88247e116` |
| `proposed_gpu_v2/results/oof_predictions.csv` | `2738977a88344127d88c60a8399daf0c2a583dec6fe995ee2d44ad936fad8757` |
| `proposed_gpu_run/results/oof_predictions.csv` | `0be07e918d527dfa0810fdb7f4b739ddbf82b06f0d4f169ecac3f32eaf2b51db` |
| `architecture_sweep_50/results/evaluations.csv` | `c43f62938506c03fb5d8cfdc8e95b61e7237ce92151931b636a19ec229f0476c` |
| `best_model_weights/expert_lgb_logratio_7d.txt` | `5262e0bd101a88628955b846bbd9452aa2284de65d30ca7d80f0439b95702fc5` |
| `best_model_weights/expert_lgb_logratio_14d.txt` | `b84b4904fccd38dfa559afca75ab6ac392b5133143e72f8459e11b9f2939b0e8` |

These hashes match the corresponding committed local archive files.

## Price-file discrepancy resolution

The remote and local `price_daily.csv` files have the same size and all
semantic coverage checks, but their raw hashes differ because
`extraction_timestamp` is generated when the normalized snapshot is written.
The remote first-row timestamp was `2026-08-04T09:56:19.008693+00:00`; the
local archive was written at `2026-08-04T09:53:25.916174+00:00`.

After replacing only that run-generated column with an empty value, both files
produce this canonical SHA-256:

```text
9bc2069453efd96dfd7ddab4fb72f8af135a1e5235e5866ef31a576673d3066b
```

Therefore the difference is provenance timestamp metadata, not a price,
identifier, date, market-level, commodity, or revision-content discrepancy.

## Completed multimodal experiment

The full A100 run used the eligible merged panel with the static and dynamic
graph tables above. It ran seven origins (`2026-02-02` through `2026-07-17`),
both 7-day and 14-day targets, and 10 executable models per horizon. The
remote runtime was 6,199.52 seconds. The panel, graph, and result hashes are
recorded in `results/multimodal_ablation/run_manifest.json`.

| Horizon | Selected model | Variant | MAE | Rows | Folds |
|---:|---|---|---:|---:|---:|
| 7 days | LightGBM log-ratio | All modalities + dynamic graph | 3,538.489570 | 1,946 | 7 |
| 14 days | LightGBM log-ratio | Price + calendar | 5,308.467050 | 1,947 | 7 |

The all-modality dynamic-graph result at 14 days is Rp5,660.109323/kg, so it
is retained as an ablation row but not promoted as the best 14-day result. The
result validator passed 25 checks with zero failures. No same-fold ensemble,
future target, or post-origin modality observation was used to select these
rows.
