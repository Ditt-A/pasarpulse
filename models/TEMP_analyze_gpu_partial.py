from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PREDICTION_PATH = Path("proposed_gpu_v2/results/oof_predictions.csv")
OUTPUT_DIRECTORY = PREDICTION_PATH.parent
EXPERTS = [
    "CAT_GPU_V2_delta",
    "CAT_GPU_V2_logratio",
    "CAT_GPU_V2_level",
    "CAT_GPU_V2_last_price",
]
KEYS = [
    "series_id",
    "province_code",
    "commodity_code",
    "market_level",
    "forecast_origin",
    "target_date",
    "horizon_days",
    "fold_id",
    "actual_price",
]


def mae(actual, prediction):
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(prediction))))


def expert_pivot(frame):
    return (
        frame[frame["model"].isin(EXPERTS)]
        .pivot_table(
            index=KEYS,
            columns="model",
            values="predicted_price",
            aggfunc="first",
        )
        .reset_index()
    )


def sequential_bias_predictions(frame, group_columns=None, shrinkage=20.0):
    outputs = []
    for _, horizon_frame in frame.groupby("horizon_days", observed=True):
        for _, model_frame in horizon_frame.groupby("model", observed=True):
            model_frame = model_frame.sort_values(["fold_id", "series_id"]).copy()
            for fold_id in sorted(model_frame["fold_id"].unique()):
                current = model_frame[model_frame["fold_id"] == fold_id].copy()
                prior = model_frame[model_frame["fold_id"] < fold_id].copy()
                if prior.empty:
                    current["calibrated_prediction"] = current["predicted_price"]
                else:
                    prior = prior.assign(
                        residual=prior["actual_price"] - prior["predicted_price"]
                    )
                    global_bias = float(prior["residual"].median())
                    if group_columns:
                        grouped = (
                            prior.groupby(group_columns, observed=True)["residual"]
                            .agg(["median", "count"])
                            .reset_index()
                            .rename(
                                columns={
                                    "median": "group_bias",
                                    "count": "group_count",
                                }
                            )
                        )
                        current = current.merge(grouped, on=group_columns, how="left")
                        count = current["group_count"].fillna(0.0).to_numpy(float)
                        group_bias = current["group_bias"].fillna(global_bias).to_numpy(float)
                        weight = count / (count + shrinkage)
                        bias = weight * group_bias + (1.0 - weight) * global_bias
                    else:
                        bias = np.full(len(current), global_bias, dtype=float)
                    current["calibrated_prediction"] = np.clip(
                        current["predicted_price"].to_numpy(float)
                        + np.clip(bias, -5000.0, 5000.0),
                        1000.0,
                        500000.0,
                    )
                outputs.append(current)
    return pd.concat(outputs, ignore_index=True)


def blend_grid():
    grid = []
    for delta_weight in np.arange(0.0, 1.01, 0.1):
        remaining = round(1.0 - delta_weight, 10)
        for log_weight in np.arange(0.0, remaining + 0.001, 0.1):
            for level_weight in np.arange(0.0, remaining - log_weight + 0.001, 0.1):
                last_weight = 1.0 - delta_weight - log_weight - level_weight
                if last_weight < -1e-9:
                    continue
                weights = np.array(
                    [delta_weight, log_weight, level_weight, max(0.0, last_weight)]
                )
                grid.append(weights / weights.sum())
    return np.unique(np.round(np.asarray(grid), 8), axis=0)


def chronological_grid_blend(frame):
    pivot = expert_pivot(frame)
    rows = []
    grid = blend_grid()
    anchor = np.array([0.6, 0.1, 0.0, 0.3])
    for _, horizon_frame in pivot.groupby("horizon_days", observed=True):
        horizon_frame = horizon_frame.sort_values(["fold_id", "series_id"])
        for fold_id in sorted(horizon_frame["fold_id"].unique()):
            current = horizon_frame[horizon_frame["fold_id"] == fold_id].copy()
            prior = horizon_frame[horizon_frame["fold_id"] < fold_id].copy()
            if prior.empty:
                weights = np.array([1.0, 0.0, 0.0, 0.0])
            else:
                prior_matrix = prior[EXPERTS].to_numpy(float)
                prior_y = prior["actual_price"].to_numpy(float)
                scores = np.mean(
                    np.abs(prior_y[:, None] - prior_matrix @ grid.T), axis=0
                )
                regularization = 30.0 * np.sum((grid - anchor) ** 2, axis=1)
                weights = grid[np.argmin(scores + regularization)]
            current["predicted_price"] = np.clip(
                current[EXPERTS].to_numpy(float) @ weights, 1000.0, 500000.0
            )
            current["model"] = "CHRONOLOGICAL_REGULARIZED_GRID_BLEND"
            current["weights"] = ",".join(f"{value:.2f}" for value in weights)
            rows.append(current)
    return pd.concat(rows, ignore_index=True)


def chronological_global_selector(frame):
    pivot = expert_pivot(frame)
    rows = []
    for _, horizon_frame in pivot.groupby("horizon_days", observed=True):
        horizon_frame = horizon_frame.sort_values(["fold_id", "series_id"])
        for fold_id in sorted(horizon_frame["fold_id"].unique()):
            current = horizon_frame[horizon_frame["fold_id"] == fold_id].copy()
            prior = horizon_frame[horizon_frame["fold_id"] < fold_id]
            if prior.empty:
                selected = "CAT_GPU_V2_delta"
            else:
                scores = {
                    expert: mae(prior["actual_price"], prior[expert])
                    for expert in EXPERTS
                }
                selected = min(scores, key=scores.get)
            current["predicted_price"] = current[selected]
            current["model"] = "CHRONOLOGICAL_GLOBAL_EXPERT_SELECTOR"
            current["selected_expert"] = selected
            rows.append(current)
    return pd.concat(rows, ignore_index=True)


def chronological_group_selector(frame, minimum_rows=20, shrinkage=30.0):
    pivot = expert_pivot(frame)
    rows = []
    groups = ["commodity_code", "market_level"]
    for _, horizon_frame in pivot.groupby("horizon_days", observed=True):
        horizon_frame = horizon_frame.sort_values(["fold_id", "series_id"])
        for fold_id in sorted(horizon_frame["fold_id"].unique()):
            current = horizon_frame[horizon_frame["fold_id"] == fold_id].copy()
            prior = horizon_frame[horizon_frame["fold_id"] < fold_id].copy()
            if prior.empty:
                current["predicted_price"] = current["CAT_GPU_V2_delta"]
                current["selected_expert"] = "CAT_GPU_V2_delta"
            else:
                global_scores = {
                    expert: mae(prior["actual_price"], prior[expert])
                    for expert in EXPERTS
                }
                outputs = []
                for group_values, current_group in current.groupby(groups, observed=True):
                    mask = np.ones(len(prior), dtype=bool)
                    for column, value in zip(groups, group_values):
                        mask &= prior[column].to_numpy() == value
                    prior_group = prior.loc[mask]
                    scores = {}
                    for expert in EXPERTS:
                        local = (
                            mae(prior_group["actual_price"], prior_group[expert])
                            if len(prior_group) >= minimum_rows
                            else global_scores[expert]
                        )
                        weight = len(prior_group) / (len(prior_group) + shrinkage)
                        scores[expert] = (
                            weight * local + (1.0 - weight) * global_scores[expert]
                        )
                    selected = min(scores, key=scores.get)
                    current_group = current_group.copy()
                    current_group["predicted_price"] = current_group[selected]
                    current_group["selected_expert"] = selected
                    outputs.append(current_group)
                current = pd.concat(outputs, ignore_index=True)
            current["model"] = "CHRONOLOGICAL_COMMODITY_MARKET_SELECTOR"
            rows.append(current)
    return pd.concat(rows, ignore_index=True)


def chronological_group_grid_blend(frame, minimum_rows=20, shrinkage=30.0):
    pivot = expert_pivot(frame)
    grid = blend_grid()
    rows = []
    groups = ["commodity_code", "market_level"]
    anchor = np.array([0.5, 0.1, 0.0, 0.4])
    for _, horizon_frame in pivot.groupby("horizon_days", observed=True):
        horizon_frame = horizon_frame.sort_values(["fold_id", "series_id"])
        for fold_id in sorted(horizon_frame["fold_id"].unique()):
            current = horizon_frame[horizon_frame["fold_id"] == fold_id].copy()
            prior = horizon_frame[horizon_frame["fold_id"] < fold_id].copy()
            if prior.empty:
                current["predicted_price"] = current["CAT_GPU_V2_delta"]
                current["weights"] = "1.00,0.00,0.00,0.00"
            else:
                prior_matrix = prior[EXPERTS].to_numpy(float)
                prior_y = prior["actual_price"].to_numpy(float)
                global_scores = np.mean(
                    np.abs(prior_y[:, None] - prior_matrix @ grid.T), axis=0
                )
                outputs = []
                for group_values, current_group in current.groupby(groups, observed=True):
                    mask = np.ones(len(prior), dtype=bool)
                    for column, value in zip(groups, group_values):
                        mask &= prior[column].to_numpy() == value
                    prior_group = prior.loc[mask]
                    if len(prior_group) >= minimum_rows:
                        local_matrix = prior_group[EXPERTS].to_numpy(float)
                        local_y = prior_group["actual_price"].to_numpy(float)
                        local_scores = np.mean(
                            np.abs(local_y[:, None] - local_matrix @ grid.T), axis=0
                        )
                    else:
                        local_scores = global_scores
                    weight = len(prior_group) / (len(prior_group) + shrinkage)
                    scores = weight * local_scores + (1.0 - weight) * global_scores
                    scores += 20.0 * np.sum((grid - anchor) ** 2, axis=1)
                    selected_weights = grid[np.argmin(scores)]
                    current_group = current_group.copy()
                    current_group["predicted_price"] = np.clip(
                        current_group[EXPERTS].to_numpy(float) @ selected_weights,
                        1000.0,
                        500000.0,
                    )
                    current_group["weights"] = ",".join(
                        f"{value:.2f}" for value in selected_weights
                    )
                    outputs.append(current_group)
                current = pd.concat(outputs, ignore_index=True)
            current["model"] = "CHRONOLOGICAL_COMMODITY_MARKET_GRID_BLEND"
            rows.append(current)
    return pd.concat(rows, ignore_index=True)


def summarize(frame, label):
    rows = []
    for (model, horizon), group in frame.groupby(
        ["model", "horizon_days"], observed=True
    ):
        rows.append(
            {
                "candidate": label,
                "model": model,
                "horizon_days": int(horizon),
                "folds": int(group["fold_id"].nunique()),
                "rows": len(group),
                "mae": mae(group["actual_price"], group["predicted_price"]),
                "mean_error": float(
                    np.mean(group["predicted_price"] - group["actual_price"])
                ),
            }
        )
    return pd.DataFrame(rows)


def main():
    if not PREDICTION_PATH.exists():
        print("No GPU V2 predictions yet")
        return
    frame = pd.read_csv(PREDICTION_PATH)
    summaries = [summarize(frame, "raw")]
    postprocessed = []

    global_calibrated = sequential_bias_predictions(frame).rename(
        columns={"predicted_price": "raw_prediction"}
    )
    global_calibrated["predicted_price"] = global_calibrated["calibrated_prediction"]
    summaries.append(summarize(global_calibrated, "prior_global_median_bias"))

    hierarchical = sequential_bias_predictions(
        frame,
        group_columns=["commodity_code", "market_level"],
        shrinkage=20.0,
    ).rename(columns={"predicted_price": "raw_prediction"})
    hierarchical["predicted_price"] = hierarchical["calibrated_prediction"]
    summaries.append(
        summarize(hierarchical, "prior_commodity_market_bias_shrink20")
    )

    candidates = [
        (chronological_grid_blend(frame), "chronological_regularized_grid"),
        (chronological_global_selector(frame), "chronological_global_selector"),
        (
            chronological_group_selector(frame),
            "chronological_commodity_market_selector",
        ),
        (
            chronological_group_grid_blend(frame),
            "chronological_commodity_market_grid",
        ),
    ]
    for candidate, label in candidates:
        candidate = candidate.copy()
        candidate["candidate"] = label
        summaries.append(summarize(candidate, label))
        postprocessed.append(candidate)

    summary = pd.concat(summaries, ignore_index=True).sort_values(
        ["horizon_days", "mae", "candidate", "model"]
    )
    summary.to_csv(OUTPUT_DIRECTORY / "postprocessing_metrics.csv", index=False)
    if postprocessed:
        pd.concat(postprocessed, ignore_index=True).to_csv(
            OUTPUT_DIRECTORY / "postprocessed_predictions.csv", index=False
        )

    print("=== Leakage-safe post-processing diagnostics ===")
    print(summary.to_string(index=False))

    print("=== Per-fold raw GPU V2 MAE ===")
    per_fold_rows = []
    for (model, horizon, fold_id), group in frame.groupby(
        ["model", "horizon_days", "fold_id"], observed=True
    ):
        per_fold_rows.append(
            {
                "model": model,
                "horizon_days": int(horizon),
                "fold_id": int(fold_id),
                "mae": mae(group["actual_price"], group["predicted_price"]),
                "mean_error": float(
                    np.mean(group["predicted_price"] - group["actual_price"])
                ),
            }
        )
    per_fold = pd.DataFrame(per_fold_rows).sort_values(
        ["horizon_days", "fold_id", "mae"]
    )
    per_fold.to_csv(OUTPUT_DIRECTORY / "per_fold_raw_metrics.csv", index=False)
    print(per_fold.to_string(index=False))


if __name__ == "__main__":
    main()
