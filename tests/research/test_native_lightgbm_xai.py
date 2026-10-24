from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.pasarpulse_notebook_finalist import (
    summarize_lightgbm_native_contributions,
)


class FakeContributionModel:
    """Minimal LightGBM-compatible predictor for XAI contract testing."""

    def predict(self, matrix, pred_contrib=False):
        values = matrix.to_numpy(dtype=float)
        if pred_contrib:
            # Two feature contributions plus the expected-value column.
            return np.column_stack([values[:, 0], 2.0 * values[:, 1], np.ones(len(values))])
        return values[:, 0] + 2.0 * values[:, 1] + 1.0


def test_native_lightgbm_contributions_are_additive_and_ranked():
    test_x = pd.DataFrame({"lag_1": [2.0, -1.0], "calendar": [3.0, 4.0]})
    fitted_models = {
        ("LGBM_LOGRATIO", 7, 1): {
            "model": FakeContributionModel(),
            "prep": (pd.DataFrame(), test_x, [], "CPU"),
            "test_rows": pd.DataFrame(
                {
                    "series_id": ["11|BM|retail", "12|CRM|producer"],
                    "date": pd.to_datetime(["2026-02-02", "2026-02-02"]),
                }
            ),
        }
    }

    global_xai, local_xai, audit = summarize_lightgbm_native_contributions(
        fitted_models, top_k=1
    )

    assert audit.loc[0, "max_abs_additivity_error"] == 0.0
    assert audit.loc[0, "rows_explained"] == 2
    assert list(global_xai["feature"]) == ["calendar", "lag_1"]
    assert len(local_xai) == 2
    assert set(local_xai["feature"]) == {"calendar"}
    assert np.allclose(local_xai["expected_value_logratio"], 1.0)
