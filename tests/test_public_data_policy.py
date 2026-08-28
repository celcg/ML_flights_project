"""Regression tests for the public aggregate disclosure threshold."""

from __future__ import annotations

import csv
from pathlib import Path
import unittest

import pandas as pd

from streamlit_app.data_policy import (
    MIN_PUBLIC_AGGREGATE_FLIGHTS,
    suppress_small_aggregates,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA_ROOT = PROJECT_ROOT / "streamlit_app" / "public_data"


class PublicDataPolicyTests(unittest.TestCase):
    """Ensure small aggregate cells cannot enter published dashboard data."""

    def test_suppress_small_aggregates_filters_below_threshold(self) -> None:
        frame = pd.DataFrame(
            {
                "flight_count": [20, 20, 20, 21],
                "arrival_flight_count": [0, 19, 20, 21],
                "delay_rate": [0.0, 1.0, 2.0, 3.0],
            }
        )

        published = suppress_small_aggregates(frame)

        self.assertEqual(published.index.tolist(), [0, 2, 3])

    def test_published_csvs_respect_minimum_flight_count(self) -> None:
        violations: list[str] = []
        checked_files = 0

        for path in sorted(PUBLIC_DATA_ROOT.rglob("*.csv")):
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle), [])
            count_columns = [
                column
                for column in header
                if column == "flight_count" or column.endswith("_flight_count")
            ]
            if not count_columns:
                continue

            checked_files += 1
            counts = pd.read_csv(path, usecols=count_columns)
            for column in count_columns:
                small_groups = counts[column].between(
                    1, MIN_PUBLIC_AGGREGATE_FLIGHTS - 1
                )
                if small_groups.any():
                    minimum = counts.loc[small_groups, column].min()
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT)} has minimum "
                        f"{column}={minimum:g}"
                    )

        self.assertGreater(checked_files, 0, "No aggregate CSVs were checked.")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
