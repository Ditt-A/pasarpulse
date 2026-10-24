"""Render paper-ready native-LightGBM XAI figures from saved CSV artifacts.

The plots intentionally use only saved A100 outputs.  ``pred_contrib`` values
are additive attributions in raw log-ratio space, not causal or rupiah effects.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def contribution_swarm(contributions: pd.DataFrame, output: Path) -> None:
    scores = contributions.groupby("feature")["contribution_logratio"].apply(
        lambda values: values.abs().mean()
    )
    features = list(scores.nlargest(12).sort_values().index)
    figure, axis = plt.subplots(figsize=(8.0, 5.3))
    colour_map = plt.get_cmap("viridis")
    for row_index, feature in enumerate(features):
        subset = contributions.loc[contributions["feature"] == feature].copy()
        values = subset["feature_value"].astype(float)
        spread = values.max() - values.min()
        colour_value = (
            np.full(len(subset), 0.5) if spread == 0 else (values - values.min()) / spread
        )
        offsets = np.linspace(-0.14, 0.14, len(subset))
        axis.scatter(
            subset["contribution_logratio"],
            row_index + offsets,
            c=colour_value,
            cmap=colour_map,
            vmin=0,
            vmax=1,
            s=48,
            edgecolor="white",
            linewidth=0.6,
            zorder=3,
        )
    axis.axvline(0, color="#404040", linewidth=0.8, zorder=1)
    axis.set_yticks(range(len(features)), features)
    axis.set_xlabel("Native LightGBM contribution (raw log-ratio)")
    axis.set_title("Local contribution swarm across three selected held-out cases")
    axis.grid(axis="x", alpha=0.22)
    mapper = plt.cm.ScalarMappable(cmap=colour_map, norm=plt.Normalize(0, 1))
    colour_bar = figure.colorbar(mapper, ax=axis, pad=0.02)
    colour_bar.set_label("Within-feature normalised value")
    figure.tight_layout()
    figure.savefig(output, dpi=240, bbox_inches="tight")
    plt.close(figure)


def waterfall(contributions: pd.DataFrame, output: Path, case_id: str) -> None:
    case = contributions.loc[contributions["case_id"] == case_id].copy()
    if case.empty:
        raise ValueError(f"Unknown case: {case_id}")
    case = case.sort_values("contribution_logratio", key=lambda values: values.abs(), ascending=False)
    top = case.head(10).copy()
    remainder = case.iloc[10:]["contribution_logratio"].sum()
    expected = float(case["expected_value_logratio"].iloc[0])
    raw_prediction = float(case["raw_prediction_logratio"].iloc[0])
    steps = [("Expected value", expected)]
    steps.extend((row.feature, float(row.contribution_logratio)) for row in top.itertuples())
    steps.append((f"Other {len(case) - len(top)} features", float(remainder)))

    labels = [label for label, _ in steps] + ["Raw prediction"]
    positions = np.arange(len(labels))
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    running = 0.0
    for position, (label, change) in enumerate(steps):
        if position == 0:
            bottom, height, colour = 0.0, change, "#4C78A8"
            running = change
        else:
            next_value = running + change
            bottom, height = min(running, next_value), abs(change)
            colour = "#2A9D8F" if change >= 0 else "#E76F51"
            running = next_value
        axis.bar(position, height, bottom=bottom, color=colour, width=0.72)
        axis.text(position, bottom + height + 0.004, f"{change:+.3f}", ha="center", fontsize=7, rotation=90)
    axis.bar(len(steps), raw_prediction, bottom=0, color="#264653", width=0.72)
    axis.axhline(0, color="#404040", linewidth=0.8)
    axis.set_xticks(positions, labels, rotation=45, ha="right", fontsize=8)
    axis.set_ylabel("Raw log-ratio prediction")
    axis.set_title(f"Native LightGBM contribution waterfall: {case_id}")
    axis.text(
        0.99,
        0.02,
        "Attributions are additive model contributions, not causal effects.",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
    )
    figure.tight_layout()
    figure.savefig(output, dpi=240, bbox_inches="tight")
    plt.close(figure)


def global_bars(global_xai: pd.DataFrame, output: Path) -> None:
    horizons = sorted(global_xai["horizon_days"].unique())
    figure, axes = plt.subplots(1, len(horizons), figsize=(10.0, 4.7), sharex=False)
    axes = np.atleast_1d(axes)
    for axis, horizon in zip(axes, horizons, strict=True):
        subset = global_xai.loc[global_xai["horizon_days"] == horizon].nlargest(
            10, "mean_abs_contribution_logratio"
        ).sort_values("mean_abs_contribution_logratio")
        axis.barh(subset["feature"], subset["mean_abs_contribution_logratio"], color="#4C78A8")
        axis.set_title(f"{horizon}-day folds")
        axis.set_xlabel("Mean |contribution|\n(raw log-ratio)")
        axis.grid(axis="x", alpha=0.22)
    figure.suptitle("Global native LightGBM contribution summaries", y=1.01)
    figure.tight_layout()
    figure.savefig(output, dpi=240, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    contributions = pd.read_csv(args.input / "xai_case_all_contributions.csv")
    global_xai = pd.read_csv(args.input / "lightgbm_native_xai_global.csv")
    contribution_swarm(contributions, args.output / "xai_local_contribution_swarm.png")
    waterfall(contributions, args.output / "xai_case_14d_late_waterfall.png", "case_14d_late")
    global_bars(global_xai, args.output / "xai_global_contribution_bars.png")


if __name__ == "__main__":
    main()
