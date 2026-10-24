"""Run three held-out LightGBM XAI cases on an A100-compatible workspace.

The selected rows are chosen by absolute forecast movement, not by the realised
target or error.  Actual prices are exported only as evaluation metadata.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


CASE_SPECS = (
    ("case_7d_late", 7, "2026-07-17"),
    ("case_7d_mid", 7, "2026-06-22"),
    ("case_14d_late", 14, "2026-07-17"),
)
IDENTITY_COLUMNS = [
    "series_id",
    "province_code",
    "province_name",
    "commodity_code",
    "commodity_name",
    "market_level",
    "date",
    "current_price",
]


def load_finalist_source(root: Path):
    source = Path(
        os.environ.get(
            "PASARPULSE_XAI_SOURCE",
            root / "experiments" / "pasarpulse_notebook_finalist.py",
        )
    )
    spec = importlib.util.spec_from_file_location("pasarpulse_xai_finalist", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load finalist source: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, source


def main() -> None:
    root = Path(os.environ.get("PASARPULSE_ROOT", Path(__file__).resolve().parents[1]))
    output = Path(
        os.environ.get("PASARPULSE_XAI_OUTPUT", root / "results" / "xai_validation")
    )
    output.mkdir(parents=True, exist_ok=True)
    core, source = load_finalist_source(root)
    frame = core.load_panel(root)
    if frame.empty:
        raise RuntimeError("The eligible model panel is unavailable or empty")

    features = core.feature_columns(frame)
    fitted_models = {}
    selected_cases = []
    for fold_id, (case_id, horizon, origin_text) in enumerate(CASE_SPECS, start=1):
        origin = pd.Timestamp(origin_text)
        train, test = core.make_origin_split(frame, horizon, origin)
        if train.empty or test.empty:
            raise RuntimeError(f"No train/test rows for {case_id}")
        prediction, model, prep = core.fit_lightgbm(
            train,
            test,
            features,
            "target_logratio",
            core.FINALIST_SEED + fold_id,
        )
        test_rows = test[IDENTITY_COLUMNS].reset_index(drop=True).copy()
        test_rows["test_row_position"] = np.arange(len(test_rows), dtype=int)
        fitted_models[("LGBM_LOGRATIO", horizon, fold_id)] = {
            "model": model,
            "prep": prep,
            "features": features,
            "test_rows": test_rows,
        }

        ranked = test.reset_index(drop=True).copy()
        ranked["predicted_price"] = prediction
        ranked["forecast_movement_pct"] = (
            ranked["predicted_price"] / ranked["current_price"] - 1.0
        )
        # Selection deliberately excludes target_price and every error metric.
        selected_position = int(
            ranked.assign(
                absolute_forecast_movement=ranked["forecast_movement_pct"].abs()
            )
            .sort_values(
                ["absolute_forecast_movement", "series_id"],
                ascending=[False, True],
                kind="mergesort",
            )
            .index[0]
        )
        selected = ranked.iloc[selected_position]
        selected_cases.append(
            {
                "case_id": case_id,
                "selection_rule": "largest absolute forecast movement within held-out fold",
                "model": "LGBM_LOGRATIO",
                "horizon_days": horizon,
                "fold_id": fold_id,
                "forecast_origin": origin.date().isoformat(),
                "test_row_position": selected_position,
                "series_id": selected["series_id"],
                "province_code": selected["province_code"],
                "province_name": selected["province_name"],
                "commodity_code": selected["commodity_code"],
                "commodity_name": selected["commodity_name"],
                "market_level": selected["market_level"],
                "current_price": float(selected["current_price"]),
                "predicted_price": float(selected["predicted_price"]),
                "forecast_movement_pct": float(selected["forecast_movement_pct"]),
                "actual_price_evaluation_only": float(selected["target_price"]),
            }
        )

    # Request the full feature contract once, then retain both paper-ready
    # top-five rows and complete selected-case rows for faithful waterfalls.
    global_xai, local_xai, audit = core.summarize_lightgbm_native_contributions(
        fitted_models, top_k=len(features)
    )
    cases = pd.DataFrame(selected_cases)
    all_case_contributions = local_xai.merge(
        cases[
            ["case_id", "horizon_days", "fold_id", "test_row_position"]
        ],
        on=["horizon_days", "fold_id", "test_row_position"],
        how="inner",
        validate="many_to_one",
    ).sort_values(["case_id", "rank"])
    local_cases = all_case_contributions.loc[
        all_case_contributions["rank"] <= 5
    ].copy()

    cases.to_csv(output / "xai_case_summary.csv", index=False)
    local_cases.to_csv(output / "xai_case_top5.csv", index=False)
    all_case_contributions.to_csv(
        output / "xai_case_all_contributions.csv", index=False
    )
    global_xai.to_csv(output / "lightgbm_native_xai_global.csv", index=False)
    audit.to_csv(output / "lightgbm_native_xai_audit.csv", index=False)
    (output / "xai_run_manifest.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "case_specs": CASE_SPECS,
                "selection_rule": "largest absolute forecast movement; target excluded",
                "xai_method": "LightGBM native pred_contrib additive log-ratio contributions",
                "case_contribution_file": "xai_case_all_contributions.csv",
                "claims_excluded": [
                    "causal effects",
                    "rupiah-space contributions",
                    "confidence or probability",
                    "commodity-flow evidence",
                ],
                "max_abs_additivity_error": float(
                    audit["max_abs_additivity_error"].max()
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(cases.to_string(index=False))
    print(audit.to_string(index=False))
    print(f"Wrote XAI artifacts to {output}")


if __name__ == "__main__":
    main()
