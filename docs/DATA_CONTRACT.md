# PasarPulse data contract

The application consumes a prepared snapshot, not arbitrary research CSVs.
`scripts/build_multimodal_replay_snapshot.py` is the current normalization
boundary. `scripts/build_replay_snapshot.py` remains available for the older
single-model artifact.

## Forecast row

Required identity and forecast fields:

```text
forecast_id, series_id, province_code, province_name,
commodity_code, commodity_name, market_level,
forecast_origin, target_date, horizon_days,
current_price, predicted_price, model
```

The snapshot also carries product-derived fields (`projected_change`,
`projected_change_pct`, `warning_level`) and lineage fields. The API recomputes
the product-derived fields on load from `current_price` and `predicted_price`.

`target_price` is optional and evaluation-only. It is never used for map color,
warning level, alert sorting, evidence context, or Copilot context. A client
must request `reveal=true` to receive it in the historical evaluation object.

## Geography

`data/reference/indonesia_provinces.geojson` is the canonical BIG-sourced
38-province geometry. Forecast rows join on `province_code`; display names are
not used as the primary key. A province without a matching forecast remains on
the map with `INSUFFICIENT` evidence status.

## Evidence

Evidence records describe availability, source, observation date, age, and the
selected model feature contract. `used_by_model` means that a modality belongs
to the selected tree model's declared feature set; it does not mean feature
importance or attribution. `evidence_quality_score` is preserved when the
source provides it and remains null otherwise. The product never converts it
into an AI confidence percentage.

The multimodal replay selects `LGBM_LOGRATIO__ALL_MODALITIES_DYNAMIC_GRAPH`
for 7 days and `LGBM_LOGRATIO__PRICE_CALENDAR` for 14 days. Therefore weather,
production, satellite, market/static, and dynamic-graph records can be
available context-only for a 14-day forecast without being claimed as model
drivers.

## Unsupported outputs

The current snapshot does not contain shock probability, propagation
probability, SHAP/TimeSHAP/GNN explanations, or uncertainty intervals. API
responses expose availability flags and the UI renders an explicit unavailable
state instead of filling those fields.
