"""Publication rules shared by aggregate generation and dashboard loading."""

from __future__ import annotations

import pandas as pd


MIN_PUBLIC_AGGREGATE_FLIGHTS = 20


def suppress_small_aggregates(frame: pd.DataFrame) -> pd.DataFrame:
    """Exclude rows containing a non-empty aggregate below the public minimum."""

    count_columns = [
        column
        for column in frame.columns
        if column == "flight_count" or column.endswith("_flight_count")
    ]
    if not count_columns:
        return frame

    publishable = pd.Series(True, index=frame.index)
    for column in count_columns:
        counts = pd.to_numeric(frame[column], errors="coerce")
        publishable &= counts.isna() | counts.eq(0) | counts.ge(
            MIN_PUBLIC_AGGREGATE_FLIGHTS
        )
    return frame.loc[publishable].copy()
