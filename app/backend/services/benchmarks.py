"""Transparent benchmark loading from committed research result files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import benchmark_paths


def _group_for(path: Path, model: str) -> tuple[str, bool, str]:
    name = path.as_posix()
    if "summary_metrics" in name:
        return "saved_a100_search", True, "Saved validated architecture-search / headline results"
    if "finalist_pooled_metrics" in name:
        if "INVERSE_MAE_BLEND" in model:
            return "diagnostic_same_fold_weighting", False, "Same-fold inverse-MAE weighting; not leakage-safe"
        return "compact_visible_rerun", True, "Compact executable finalist rerun"
    if "meta_metrics" in name:
        return "prior_fold_meta", True, "Prior-fold-only meta experiment"
    if "multimodal_ablation" in name:
        return (
            "multimodal_ablation",
            False,
            "A100 leakage-safe modality ablation; research result, not the deployed replay headline",
        )
    if "proposed_model_run" in name:
        if model.startswith("PROPOSED_"):
            return "proposal_named_tree_variant", False, "Tree approximation with proposal naming; not a deployed GNN"
        return "a100_experiment", True, "Saved A100 executable experiment"
    if "early_warning" in name:
        return "early_warning_diagnostic", True, "Derived early-warning diagnostic in repository"
    return "research_result", True, "Repository result artifact"


def load_benchmarks(root: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in benchmark_paths():
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        for record in frame.to_dict(orient="records"):
            model = str(record.get("model", record.get("metric", "unknown")))
            group, headline, note = _group_for(path, model)
            horizon = record.get("horizon_days")
            mae = record.get("mae_idr_per_kg", record.get("mae"))
            if mae is None or pd.isna(mae):
                continue
            rows.append(
                {
                    "model": model,
                    "horizon_days": int(horizon) if horizon is not None and not pd.isna(horizon) else None,
                    "mae_idr_per_kg": float(mae),
                    "rmse_idr_per_kg": _number(record.get("rmse_idr_per_kg", record.get("rmse"))),
                    "wape_percent": _number(record.get("wape")),
                    "smape_percent": _number(record.get("smape_percent", record.get("smape"))),
                    "rows_scored": _number(record.get("rows_scored", record.get("rows")), integer=True),
                    "folds_scored": _number(record.get("folds_scored", record.get("folds")), integer=True),
                    "group": group,
                    "headline_eligible": headline,
                    "note": note,
                    "source_file": str(path),
                }
            )
    # stable order with best eligible result first by horizon
    return sorted(rows, key=lambda item: (item["horizon_days"] is None, item["horizon_days"] or 0, not item["headline_eligible"], item["mae_idr_per_kg"]))


def _number(value: Any, integer: bool = False) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    result = float(value)
    return int(result) if integer else result
