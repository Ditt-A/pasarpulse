"""Fit and export the validated PasarPulse LightGBM log-ratio experts.

The exported files are deployable LightGBM Booster models.  A separate booster
is fit for each forecast horizon because the supervised target is horizon
specific.  The feature order and categorical label mappings are written to the
same output directory and must be used at inference time.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder


PARAMS = {
    "n_estimators": 700,
    "learning_rate": 0.025,
    "num_leaves": 47,
    "min_child_samples": 50,
    "max_bin": 127,
    "reg_alpha": 0.05,
    "reg_lambda": 2.5,
    "colsample_bytree": 0.9,
}


def load_core(path: Path):
    spec = importlib.util.spec_from_file_location("pasarpulse_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load core module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_list(core, frame: pd.DataFrame) -> list[str]:
    requested = (
        list(core.PRICE_BASE)
        + list(core.CALENDAR)
        + list(core.GRAPH)
        + list(core.CATEGORICAL)
        + ["target_dow", "target_month", "target_doy_sin", "target_doy_cos"]
    )
    return [name for name in requested if name in frame.columns]


def category_manifest(core, frame: pd.DataFrame, features: list[str]) -> dict:
    manifest = {}
    for column in core.CATEGORICAL:
        if column not in features:
            continue
        values = frame[column].astype(str).fillna("missing")
        encoder = LabelEncoder().fit(values)
        manifest[column] = {
            "feature_index": features.index(column),
            "classes": encoder.classes_.tolist(),
        }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument(
        "--panel-parquet",
        type=Path,
        help="Reuse an already-built panel from the validated run.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    started = time.time()
    args.output.mkdir(parents=True, exist_ok=True)
    core = load_core(args.core)
    if args.panel_parquet:
        panel = pd.read_parquet(args.panel_parquet)
    else:
        raw = pd.read_csv(
            args.price_csv, parse_dates=["date"], dtype={"province_code": str}
        )
        if "price" not in raw.columns and "price_idr_per_kg" in raw.columns:
            raw["price"] = raw["price_idr_per_kg"]
        if "price" not in raw.columns:
            raise ValueError("Input price CSV must contain price or price_idr_per_kg")
        panel = core.build_panel(raw)
    summary_rows = []
    manifest = {
        "model_family": "LightGBM",
        "model_name": "expert_lgb_logratio",
        "target": "target_logratio",
        "prediction_reconstruction": "clip(current_price * exp(prediction), 1000, 500000)",
        "input_price_csv": str(args.price_csv),
        "input_price_csv_sha256": sha256(args.price_csv),
        "input_panel_parquet": str(args.panel_parquet) if args.panel_parquet else None,
        "input_panel_parquet_sha256": sha256(args.panel_parquet)
        if args.panel_parquet
        else None,
        "parameters": PARAMS,
        "horizons": {},
        "software": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
        },
    }

    for horizon in (7, 14):
        supervised = core.create_supervised(panel, horizon)
        valid = (
            (supervised["observed"] == 1)
            & (supervised["target_observed"] == 1)
            & supervised["target_price"].notna()
            & supervised["price_filled"].notna()
            & np.isfinite(supervised["target_logratio"])
        )
        train = supervised.loc[valid].copy()
        counts = train.groupby("series_id", observed=True).size()
        eligible = counts[counts >= 240].index
        train = train[train["series_id"].isin(eligible)].copy()
        features = feature_list(core, train)
        if not features or train.empty:
            raise RuntimeError(f"No training rows/features for horizon {horizon}")

        # The final fit uses the latest date represented by the target, which
        # is the natural forecast origin after all available labels are used.
        final_origin = train["date"].max() + pd.Timedelta(days=horizon)
        sample_weight = core.recent_weights(train["date"], final_origin)
        probe = train.iloc[[0]].copy()
        _, model = core.fit_predict_lgb(
            train,
            probe,
            features,
            "target_logratio",
            sample_weight,
            PARAMS,
        )

        model_path = args.output / f"expert_lgb_logratio_{horizon}d.txt"
        model.booster_.save_model(str(model_path))

        # Verify that the serialized Booster reproduces the in-memory model.
        from lightgbm import Booster

        train_encoded, probe_encoded = core.encode_frame(train, probe, features)
        original_prediction = model.predict(probe_encoded)
        restored_prediction = Booster(model_file=str(model_path)).predict(probe_encoded)
        max_abs_diff = float(np.max(np.abs(original_prediction - restored_prediction)))
        if max_abs_diff > 1e-8:
            raise RuntimeError(
                f"Serialized model check failed for {horizon}d: {max_abs_diff}"
            )

        manifest["horizons"][str(horizon)] = {
            "model_file": model_path.name,
            "feature_order": features,
            "categorical_mappings": category_manifest(core, train, features),
            "rows": int(len(train)),
            "series": int(train["series_id"].nunique()),
            "date_min": str(train["date"].min().date()),
            "date_max": str(train["date"].max().date()),
            "forecast_origin": str(final_origin.date()),
            "sample_weight": "recent_weights(date, final_origin)",
            "serialized_model_sha256": sha256(model_path),
            "serialized_model_bytes": model_path.stat().st_size,
            "serialization_max_abs_prediction_diff": max_abs_diff,
        }
        summary_rows.append(
            {
                "model": "expert_lgb_logratio",
                "horizon_days": horizon,
                "rows": len(train),
                "series": train["series_id"].nunique(),
                "date_min": train["date"].min().date(),
                "date_max": train["date"].max().date(),
                "forecast_origin": final_origin.date(),
                "model_file": model_path.name,
                "model_bytes": model_path.stat().st_size,
                "sha256": sha256(model_path),
            }
        )
        print(
            f"horizon={horizon} rows={len(train)} series={train['series_id'].nunique()} "
            f"model={model_path} bytes={model_path.stat().st_size} "
            f"serialization_max_abs_diff={max_abs_diff}",
            flush=True,
        )

    manifest["runtime_seconds"] = time.time() - started
    (args.output / "model_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    pd.DataFrame(summary_rows).to_csv(args.output / "training_summary.csv", index=False)
    print(json.dumps({"output": str(args.output), "runtime_seconds": manifest["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
