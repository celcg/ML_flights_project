"""Publication rules shared by aggregate generation and dashboard loading."""

from __future__ import annotations

import pandas as pd


MIN_PUBLIC_AGGREGATE_FLIGHTS = 20


def suppress_small_aggregates(frame: pd.DataFrame) -> pd.DataFrame:
    """Exclude aggregate cells backed by fewer than the publication minimum."""

    if "flight_count" not in frame.columns:
        return frame
    return frame.loc[
        frame["flight_count"].ge(MIN_PUBLIC_AGGREGATE_FLIGHTS)
    ].copy()
