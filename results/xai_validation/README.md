# Native LightGBM XAI validation

These artifacts were generated on the AI Centre A100 from the current
PasarPulse finalist LightGBM log-ratio pipeline. They cover three held-out
cases, selected deterministically as the largest absolute *predicted* movement
within their designated fold; the realized target was excluded from selection.

| Case | Horizon | Origin | Series | Forecast movement | Largest local contribution |
| --- | ---: | --- | --- | ---: | --- |
| `case_7d_late` | 7d | 2026-07-17 | North Sulawesi / Cabai Rawit Merah / wholesale | -9.24% | `province_code` = -0.02194 |
| `case_7d_mid` | 7d | 2026-06-22 | North Sulawesi / Cabai Rawit Merah / wholesale | -10.32% | `current_price` = -0.04045 |
| `case_14d_late` | 14d | 2026-07-17 | Gorontalo / Cabai Rawit Merah / producer | -24.76% | `current_price` = -0.05124 |

The contribution audit covers 832 held-out rows across the three fitted folds.
The worst raw-prediction reconstruction error is `5.273559366969494e-16`.
`pred_contrib` values are additive contributions in raw log-ratio space: they
are not causal effects, rupiah allocations, confidence values, or probabilities.

Files:

- `xai_case_summary.csv` — selected case identities and evaluation-only targets.
- `xai_case_top5.csv` — five largest absolute local contributions per case.
- `xai_case_all_contributions.csv` — all 69 native contributions for each selected case; used for the waterfall figure.
- `lightgbm_native_xai_global.csv` — fold-aggregated mean absolute/signed contributions.
- `lightgbm_native_xai_audit.csv` — additive reconstruction checks.
- `xai_run_manifest.json` — method, selection rule, and excluded claims.
- `figures/` — contribution swarm, 14-day local waterfall, and global contribution-summary figures rendered solely from these CSV files.
