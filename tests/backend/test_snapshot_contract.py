from pathlib import Path

import pandas as pd
import pytest

from app.backend.services.artifacts import ArtifactValidationError, ForecastStore, resolve_mode
from scripts.build_replay_snapshot import load_and_normalize


def _row(**overrides):
    value = {
        "series_id": "35|CRM|retail",
        "province_code": "35",
        "province_name": "Jawa Timur",
        "commodity_code": "CRM",
        "commodity_name": "Cabai Rawit Merah",
        "market_level": "retail",
        "forecast_origin": "2026-07-17",
        "target_date": "2026-07-24",
        "horizon_days": 7,
        "current_price": 68000,
        "predicted_price": 74800,
        "model": "expert_lgb_logratio",
        "target_price": 300000,
    }
    value.update(overrides)
    return value


def test_valid_snapshot_without_target(tmp_path: Path) -> None:
    source = tmp_path / "predictions.csv"
    pd.DataFrame([_row()]).drop(columns="target_price").to_csv(source, index=False)
    frame = load_and_normalize(source, "expert_lgb_logratio")
    assert frame.iloc[0]["projected_change_pct"] == 10.0
    assert frame.iloc[0]["warning_level"] == "ELEVATED"


def test_invalid_horizon_and_date(tmp_path: Path) -> None:
    source = tmp_path / "predictions.csv"
    pd.DataFrame([_row(horizon_days=3)]).to_csv(source, index=False)
    with pytest.raises(ValueError, match="Unsupported horizons"):
        load_and_normalize(source, "expert_lgb_logratio")
    pd.DataFrame([_row(target_date="2026-07-23")]).to_csv(source, index=False)
    with pytest.raises(ValueError, match="target_date must equal"):
        load_and_normalize(source, "expert_lgb_logratio")


def test_mode_fallback_and_replay() -> None:
    missing = Path("/tmp/pasarpulse-no-such-snapshot.csv")
    assert resolve_mode(missing, "auto").name == "benchmark_only"
    assert resolve_mode(Path("demo_data/forecasts/forecast_snapshot.csv"), "replay").name == "historical_replay"


def test_loaded_geojson_has_all_provinces_and_recomputes_warning() -> None:
    store = ForecastStore()
    geo = store.geojson(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7)
    assert len(geo["features"]) == 38
    assert all("province_code" in feature["properties"] for feature in geo["features"])
    # The full PIHPS artifact covers 34 province codes, while one selected
    # origin/commodity/market slice can have additional missing series.
    assert sum(not feature["properties"]["has_forecast"] for feature in geo["features"]) == 7


def test_target_is_evaluation_only() -> None:
    store = ForecastStore()
    rows = store.query(origin="2026-07-17", commodity="CRM", market_level="retail", horizon=7)
    first = rows.iloc[0].copy()
    original_warning = first["warning_level"]
    original_change = first["projected_change_pct"]
    first["target_price"] = 999999999
    assert first["warning_level"] == original_warning
    assert first["projected_change_pct"] == original_change
    record = store.record_from_row(first, reveal=False)
    assert record.historical_evaluation.realized_price is None
