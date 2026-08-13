from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.flight_data_catalog import compare_null_cohorts, discover_monthly_flights


class FlightDataCatalogTests(unittest.TestCase):
    def test_monthly_folder_wins_without_losing_legacy_only_month(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "202106").mkdir()
            (root / "flights").mkdir()
            (root / "202106" / "Flights_20210601_20210630.csv.gz").touch()
            (root / "flights" / "Flights_20210601_20210630.csv.gz").touch()
            (root / "flights" / "Flights_20221201_20221231.csv.gz").touch()
            records = discover_monthly_flights(root)
            self.assertEqual([item.month for item in records], ["202106", "202212"])
            self.assertEqual(records[0].source, "monthly_folder")

    def test_null_comparison_is_row_weighted(self):
        profile = pd.DataFrame(
            [
                {"month": "old", "column": "x", "rows": 100, "nulls": 10, "null_pct": 10},
                {"month": "new", "column": "x", "rows": 200, "nulls": 40, "null_pct": 20},
            ]
        )
        result = compare_null_cohorts(profile, ["old"], ["new"])
        self.assertEqual(result.iloc[0]["delta_null_pp"], 10)
        self.assertTrue(result.iloc[0]["material_change"])


if __name__ == "__main__":
    unittest.main()
