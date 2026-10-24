import pandas as pd

from app.backend.services.artifacts import load_audited_xai_samples, load_forecast_xai


def test_audited_xai_samples_are_real_ranked_held_out_cases() -> None:
    samples = load_audited_xai_samples()

    assert {sample.case_id for sample in samples} == {
        "case_7d_late",
        "case_7d_mid",
        "case_14d_late",
    }
    assert all(sample.model == "LGBM_LOGRATIO" for sample in samples)
    assert all([driver.rank for driver in sample.drivers] == [1, 2, 3, 4, 5] for sample in samples)
    assert all("target_price" not in str(sample.model_dump()) for sample in samples)


def test_forecast_xai_requires_exactly_five_safe_drivers(tmp_path) -> None:
    path = tmp_path / "forecast_top5.csv"
    pd.DataFrame(
        [
            {
                "forecast_id": "FP-TEST",
                "rank": rank,
                "feature": f"lag_{rank}",
                "feature_value": rank,
                "contribution_logratio": rank / 100,
                "model": "LGBM_LOGRATIO__PRICE_CALENDAR",
                "horizon_days": 14,
                "forecast_origin": "2026-02-02",
            }
            for rank in range(1, 6)
        ]
    ).to_csv(path, index=False)

    explanation = load_forecast_xai("FP-TEST", path)

    assert explanation is not None
    assert [driver.rank for driver in explanation.drivers] == [1, 2, 3, 4, 5]
    assert explanation.horizon_days == 14
