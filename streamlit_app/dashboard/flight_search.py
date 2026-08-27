"""Reusable aggregate statistics for flight search."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class FlightSearchStats:
    """Aggregated evidence for one route, operator and departure hour."""

    route_delay_pct: float
    route_flights: int
    operator_delay_pct: float
    operator_flights: int
    origin_hour_delay_pct: float | None
    origin_hour_flights: int
    destination_hour_delay_pct: float | None
    destination_hour_flights: int


def weighted_hourly_delay_rate(
    heatmap: pd.DataFrame,
    airport_code: str,
    movement_type: str,
    hour: int,
) -> tuple[float | None, int]:
    """Combine weekday cells into one flight-weighted hourly delay rate."""

    cells = heatmap[
        heatmap["airport_code"].eq(airport_code)
        & heatmap["movement_type"].eq(movement_type)
        & heatmap["hour"].eq(hour)
        & heatmap["scope_id"].eq("all_flights")
    ]
    volume = int(cells["flight_count"].sum())
    if cells.empty or volume == 0:
        return None, 0
    delayed_flights = (cells["flight_count"] * cells["delay_over_15_pct"] / 100).sum()
    return float(100 * delayed_flights / volume), volume


def build_search_stats(
    route: pd.Series,
    operator: pd.Series,
    heatmap: pd.DataFrame,
    departure_hour: int,
) -> FlightSearchStats:
    """Build historical statistics without exposing flight-level records."""

    origin_rate, origin_volume = weighted_hourly_delay_rate(
        heatmap, str(route["ADEP"]), "departure", departure_hour
    )
    arrival_hour = int(
        (departure_hour + float(route["median_scheduled_duration_min"]) / 60) % 24
    )
    destination_rate, destination_volume = weighted_hourly_delay_rate(
        heatmap, str(route["ADES"]), "arrival", arrival_hour
    )
    return FlightSearchStats(
        route_delay_pct=float(route["delay_over_15_pct"]),
        route_flights=int(route["flight_count"]),
        operator_delay_pct=float(operator["delay_over_15_pct"]),
        operator_flights=int(operator["flight_count"]),
        origin_hour_delay_pct=origin_rate,
        origin_hour_flights=origin_volume,
        destination_hour_delay_pct=destination_rate,
        destination_hour_flights=destination_volume,
    )

