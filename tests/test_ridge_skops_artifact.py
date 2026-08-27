"""Regression checks for the safely persisted dashboard Ridge model."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd
import skops.io as sio


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_ROOT = PROJECT_ROOT / "streamlit_app"
if str(STREAMLIT_ROOT) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_ROOT))

from dashboard.ridge_inference import (
    RIDGE_MODEL_PATH,
    load_ridge_artifact,
    predict_arrival_delay_minutes,
)


class RidgeSkopsArtifactTests(unittest.TestCase):
    def test_artifact_contains_no_untrusted_types(self) -> None:
        self.assertEqual(sio.get_untrusted_types(file=RIDGE_MODEL_PATH), [])

    def test_reference_prediction_is_stable(self) -> None:
        routes = pd.read_csv(
            STREAMLIT_ROOT / "public_data" / "routes" / "route_metrics.csv"
        )
        route = routes[
            routes["scope_id"].eq("all_flights")
            & routes["ADEP"].eq("ENGM")
            & routes["ADES"].eq("ENVA")
        ].iloc[0]
        load_ridge_artifact.clear()
        prediction = predict_arrival_delay_minutes(route, "ZZZ", 6, 2, 8)
        self.assertAlmostEqual(prediction, 3.6294924148076455, places=10)


if __name__ == "__main__":
    unittest.main()
