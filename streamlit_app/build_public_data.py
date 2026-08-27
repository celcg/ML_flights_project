"""Build reusable, flight-anonymous CSVs for the Streamlit introduction page."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
OUTPUT_ROOT = APP_ROOT / "public_data" / "introduction"
ROUTES_OUTPUT_ROOT = APP_ROOT / "public_data" / "routes"
AIRLINES_OUTPUT_ROOT = APP_ROOT / "public_data" / "airlines"
AIRPORTS_OUTPUT_ROOT = APP_ROOT / "public_data" / "airports"
ANALYSIS_YEAR = 2022
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.flight_data_catalog import discover_monthly_flights
from streamlit_app.data_policy import suppress_small_aggregates


USE_COLUMNS = [
    "ADEP",
    "ADES",
    "ADEP Latitude",
    "ADEP Longitude",
    "ADES Latitude",
    "ADES Longitude",
    "FILED OFF BLOCK TIME",
    "FILED ARRIVAL TIME",
    "ACTUAL OFF BLOCK TIME",
    "ACTUAL ARRIVAL TIME",
    "AC Operator",
    "ICAO Flight Type",
    "Requested FL",
    "Actual Distance Flown (nm)",
]
TIME_COLUMNS = [
    "FILED OFF BLOCK TIME",
    "FILED ARRIVAL TIME",
    "ACTUAL OFF BLOCK TIME",
    "ACTUAL ARRIVAL TIME",
]
SCOPE_LABELS = {
    "all_flights": "All scheduled flights",
    "scheduled_duration_under_3h": "Scheduled duration under 3 hours",
}
ROUTE_SCOPE_LABELS = {
    "all_flights": "All scheduled flights",
    "scheduled_duration_under_3h": "Under 3 hours",
    "scheduled_duration_3h_or_more": "3 hours or more",
}
ROUTE_MIN_FLIGHTS = 500
ROUTE_MIN_PERIODS = 3
AIRLINE_MIN_FLIGHTS = 500
AIRLINE_MIN_PERIODS = 3
AIRPORT_MIN_FLIGHTS = 500
AIRPORT_MIN_PERIODS = 3
UNKNOWN_OPERATOR_CODES = {"ZZZ", "UNK", "UNKNOWN"}


def write_aggregate_csv(table: pd.DataFrame, path: Path) -> None:
    """Write only aggregate cells meeting the public minimum sample size."""

    suppress_small_aggregates(table).round(4).to_csv(path, index=False)


def load_airport_dimension() -> pd.DataFrame:
    """Return one reusable airport-name record per ICAO code."""

    path = PROJECT_ROOT / "data" / "raw" / "icao" / "airports.csv"
    airports = pd.read_csv(
        path,
        usecols=["ICAO", "Airport name", "City", "Country"],
        dtype="string",
        low_memory=False,
    )
    airports["ICAO"] = airports["ICAO"].str.strip().str.upper()
    airports = airports.dropna(subset=["ICAO"])
    airports = airports[airports["ICAO"].ne("")]
    return airports.drop_duplicates("ICAO", keep="first").set_index("ICAO")


def load_airline_dimension() -> pd.DataFrame:
    """Return one reusable company record per three-letter ICAO operator code."""

    path = PROJECT_ROOT / "data" / "raw" / "icao" / "airlines.csv"
    airlines = pd.read_csv(
        path,
        usecols=["3Ltr", "Company", "Country"],
        dtype="string",
        low_memory=False,
    )
    airlines["3Ltr"] = airlines["3Ltr"].str.strip().str.upper()
    airlines = airlines.dropna(subset=["3Ltr"])
    airlines = airlines[airlines["3Ltr"].ne("")]
    return airlines.drop_duplicates("3Ltr", keep="first").set_index("3Ltr")


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Return a 95% Wilson interval as percentages."""

    if total == 0:
        return np.nan, np.nan
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = (proportion + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z**2 / (4 * total**2)
    ) / denominator
    return 100 * (centre - margin), 100 * (centre + margin)


def clean_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Apply the same core aviation-quality rules used by notebook 10."""

    frame = chunk.copy()
    for column in TIME_COLUMNS:
        frame[column] = pd.to_datetime(
            frame[column], format="%d-%m-%Y %H:%M:%S", errors="coerce"
        )
    arrival_delay = (
        frame["ACTUAL ARRIVAL TIME"] - frame["FILED ARRIVAL TIME"]
    ).dt.total_seconds() / 60.0
    departure_delay = (
        frame["ACTUAL OFF BLOCK TIME"] - frame["FILED OFF BLOCK TIME"]
    ).dt.total_seconds() / 60.0
    mask = frame["ICAO Flight Type"].eq("S")
    mask &= arrival_delay.isna() | arrival_delay.ge(-120)
    mask &= departure_delay.isna() | departure_delay.ge(-120)
    mask &= frame["Requested FL"].isna() | frame["Requested FL"].between(0, 500)
    mask &= (
        frame["Actual Distance Flown (nm)"].isna()
        | frame["Actual Distance Flown (nm)"].gt(0)
    )
    for column in ("ADEP Latitude", "ADES Latitude"):
        mask &= frame[column].isna() | frame[column].between(-90, 90)
    for column in ("ADEP Longitude", "ADES Longitude"):
        mask &= frame[column].isna() | frame[column].between(-180, 180)

    result = pd.DataFrame({
        "ADEP": frame.loc[mask, "ADEP"].astype("string"),
        "ADES": frame.loc[mask, "ADES"].astype("string"),
        "origin_latitude": pd.to_numeric(frame.loc[mask, "ADEP Latitude"], errors="coerce"),
        "origin_longitude": pd.to_numeric(frame.loc[mask, "ADEP Longitude"], errors="coerce"),
        "destination_latitude": pd.to_numeric(frame.loc[mask, "ADES Latitude"], errors="coerce"),
        "destination_longitude": pd.to_numeric(frame.loc[mask, "ADES Longitude"], errors="coerce"),
        "operator_code": (
            frame.loc[mask, "AC Operator"].astype("string").str.strip().str.upper()
        ),
        "period": frame.loc[mask, "FILED OFF BLOCK TIME"].dt.to_period("M").astype(str),
        "arrival_delay_min": arrival_delay.loc[mask],
        "departure_delay_min": departure_delay.loc[mask],
        "filed_departure_hour": frame.loc[mask, "FILED OFF BLOCK TIME"].dt.hour,
        "filed_departure_weekday": frame.loc[mask, "FILED OFF BLOCK TIME"].dt.dayofweek,
        "filed_arrival_hour": frame.loc[mask, "FILED ARRIVAL TIME"].dt.hour,
        "filed_arrival_weekday": frame.loc[mask, "FILED ARRIVAL TIME"].dt.dayofweek,
        "scheduled_duration_min": (
            frame.loc[mask, "FILED ARRIVAL TIME"]
            - frame.loc[mask, "FILED OFF BLOCK TIME"]
        ).dt.total_seconds() / 60.0,
    })
    return result.dropna(subset=["period", "arrival_delay_min"]).reset_index(drop=True)


def load_population(year: int) -> tuple[pd.DataFrame, list[str]]:
    """Read one year's available snapshots without retaining flight identifiers."""

    catalog = [
        item for item in discover_monthly_flights(PROJECT_ROOT / "data" / "raw")
        if item.month.startswith(str(year))
    ]
    if not catalog:
        raise FileNotFoundError(f"No canonical {year} flight snapshots were discovered")
    parts: list[pd.DataFrame] = []
    for item in catalog:
        for chunk in pd.read_csv(
            item.path, usecols=USE_COLUMNS, chunksize=200_000, low_memory=False
        ):
            parts.append(clean_chunk(chunk))
    population = pd.concat(parts, ignore_index=True)
    return population, [item.month for item in catalog]


def scope_frames(population: pd.DataFrame) -> dict[str, pd.DataFrame]:
    duration = population["scheduled_duration_min"]
    return {
        "all_flights": population,
        "scheduled_duration_under_3h": population[(duration > 0) & (duration < 180)],
    }


def route_scope_frames(population: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return the duration scopes used by the Routes dashboard page."""

    duration = population["scheduled_duration_min"]
    return {
        "all_flights": population,
        "scheduled_duration_under_3h": population[(duration > 0) & (duration < 180)],
        "scheduled_duration_3h_or_more": population[duration >= 180],
    }


def build_route_metrics(population: pd.DataFrame) -> pd.DataFrame:
    """Build reusable route aggregates without publishing flight-level records."""

    airports = load_airport_dimension()
    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(subset=["ADEP", "ADES", "arrival_delay_min"]).copy()
        valid = valid[valid["ADEP"].ne("") & valid["ADES"].ne("")]
        valid["delayed_over_15"] = valid["arrival_delay_min"].gt(15)
        valid["positive_delay_min"] = valid["arrival_delay_min"].clip(lower=0)
        grouped = valid.groupby(["ADEP", "ADES"], observed=True).agg(
            flight_count=("arrival_delay_min", "size"),
            periods_active=("period", "nunique"),
            delayed_over_15_count=("delayed_over_15", "sum"),
            mean_arrival_delay_min=("arrival_delay_min", "mean"),
            median_arrival_delay_min=("arrival_delay_min", "median"),
            p90_arrival_delay_min=("arrival_delay_min", lambda values: values.quantile(0.90)),
            total_positive_delay_min=("positive_delay_min", "sum"),
            median_scheduled_duration_min=("scheduled_duration_min", "median"),
            origin_latitude=("origin_latitude", "median"),
            origin_longitude=("origin_longitude", "median"),
            destination_latitude=("destination_latitude", "median"),
            destination_longitude=("destination_longitude", "median"),
        ).reset_index()
        grouped["scope_id"] = scope_id
        grouped["scope_label"] = ROUTE_SCOPE_LABELS[scope_id]
        grouped["route"] = grouped["ADEP"].astype(str) + " → " + grouped["ADES"].astype(str)
        for prefix, code_column in (("origin", "ADEP"), ("destination", "ADES")):
            grouped[f"{prefix}_airport_name"] = grouped[code_column].map(airports["Airport name"])
            grouped[f"{prefix}_city"] = grouped[code_column].map(airports["City"])
            grouped[f"{prefix}_country"] = grouped[code_column].map(airports["Country"])
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["executive_eligible"] = (
            grouped["flight_count"].ge(ROUTE_MIN_FLIGHTS)
            & grouped["periods_active"].ge(ROUTE_MIN_PERIODS)
        )
        # Two historical flights remove one-off route records while retaining a reusable table.
        rows.append(grouped[grouped["flight_count"].ge(2)])
    return pd.concat(rows, ignore_index=True)


def build_route_scope_summary(population: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(subset=["ADEP", "ADES", "arrival_delay_min"])
        rows.append({
            "scope_id": scope_id,
            "scope_label": ROUTE_SCOPE_LABELS[scope_id],
            "flight_count": len(valid),
            "route_count": valid[["ADEP", "ADES"]].drop_duplicates().shape[0],
            "delay_over_15_pct": 100 * valid["arrival_delay_min"].gt(15).mean(),
            "median_arrival_delay_min": valid["arrival_delay_min"].median(),
        })
    return pd.DataFrame(rows)


def build_route_monthly_metrics(
    population: pd.DataFrame,
    route_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Build monthly OTP15 trends for executive-eligible directional routes."""

    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(subset=["ADEP", "ADES", "period", "arrival_delay_min"]).copy()
        valid["delayed_over_15"] = valid["arrival_delay_min"].gt(15)
        grouped = valid.groupby(["ADEP", "ADES", "period"], observed=True).agg(
            flight_count=("arrival_delay_min", "size"),
            delayed_over_15_count=("delayed_over_15", "sum"),
            median_arrival_delay_min=("arrival_delay_min", "median"),
        ).reset_index()
        eligible = route_metrics[
            route_metrics["scope_id"].eq(scope_id)
            & route_metrics["executive_eligible"].eq(True)
        ][["ADEP", "ADES"]].drop_duplicates()
        grouped = grouped.merge(eligible, on=["ADEP", "ADES"], how="inner")
        grouped["scope_id"] = scope_id
        grouped["route"] = grouped["ADEP"].astype(str) + " → " + grouped["ADES"].astype(str)
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def build_route_operator_metrics(
    population: pd.DataFrame,
    route_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate operating companies for every executive-eligible route."""

    airlines = load_airline_dimension()
    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(
            subset=["ADEP", "ADES", "operator_code", "arrival_delay_min"]
        ).copy()
        valid = valid[valid["operator_code"].ne("")]
        valid["delayed_over_15"] = valid["arrival_delay_min"].gt(15)
        grouped = valid.groupby(
            ["ADEP", "ADES", "operator_code"], observed=True
        ).agg(
            flight_count=("arrival_delay_min", "size"),
            delayed_over_15_count=("delayed_over_15", "sum"),
            median_arrival_delay_min=("arrival_delay_min", "median"),
        ).reset_index()
        eligible = route_metrics[
            route_metrics["scope_id"].eq(scope_id)
            & route_metrics["executive_eligible"].eq(True)
        ][["ADEP", "ADES"]].drop_duplicates()
        grouped = grouped.merge(eligible, on=["ADEP", "ADES"], how="inner")
        grouped["scope_id"] = scope_id
        grouped["route"] = grouped["ADEP"].astype(str) + " → " + grouped["ADES"].astype(str)
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["operator_name"] = grouped["operator_code"].map(airlines["Company"])
        grouped["operator_country"] = grouped["operator_code"].map(airlines["Country"])
        grouped["operator_name"] = grouped["operator_name"].fillna(
            grouped["operator_code"].map(lambda value: f"Unknown operator ({value})")
        )
        unknown_operator = grouped["operator_code"].isin(
            ["ZZZ", "UNK", "UNKNOWN"]
        )
        grouped.loc[unknown_operator, "operator_name"] = "Unknown / not identified"
        grouped.loc[unknown_operator, "operator_country"] = pd.NA
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def build_airline_metrics(population: pd.DataFrame) -> pd.DataFrame:
    """Build exact airline aggregates for dashboard rankings and profiles."""

    airlines = load_airline_dimension()
    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(
            subset=["operator_code", "arrival_delay_min", "scheduled_duration_min"]
        ).copy()
        valid = valid[
            valid["operator_code"].ne("")
            & ~valid["operator_code"].isin(UNKNOWN_OPERATOR_CODES)
            & valid["scheduled_duration_min"].gt(0)
        ]
        valid["delayed_over_15"] = valid["arrival_delay_min"].gt(15)
        valid["route"] = valid["ADEP"].astype(str) + " → " + valid["ADES"].astype(str)
        grouped = valid.groupby("operator_code", observed=True).agg(
            flight_count=("arrival_delay_min", "size"),
            periods_active=("period", "nunique"),
            route_count=("route", "nunique"),
            delayed_over_15_count=("delayed_over_15", "sum"),
            median_arrival_delay_min=("arrival_delay_min", "median"),
            median_scheduled_duration_min=("scheduled_duration_min", "median"),
        ).reset_index()
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["scope_id"] = scope_id
        grouped["scope_label"] = ROUTE_SCOPE_LABELS[scope_id]
        grouped["operator_name"] = grouped["operator_code"].map(airlines["Company"])
        grouped["operator_country"] = grouped["operator_code"].map(airlines["Country"])
        grouped["operator_name"] = grouped["operator_name"].fillna(
            grouped["operator_code"].map(lambda value: f"Unknown operator ({value})")
        )
        grouped["executive_eligible"] = (
            grouped["flight_count"].ge(AIRLINE_MIN_FLIGHTS)
            & grouped["periods_active"].ge(AIRLINE_MIN_PERIODS)
        )
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def build_airline_monthly_metrics(
    population: pd.DataFrame,
    airline_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Build exact monthly airline aggregates for eligible dashboard airlines."""

    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        valid = frame.dropna(
            subset=["operator_code", "period", "arrival_delay_min"]
        ).copy()
        valid = valid[
            valid["operator_code"].ne("")
            & ~valid["operator_code"].isin(UNKNOWN_OPERATOR_CODES)
        ]
        valid["delayed_over_15"] = valid["arrival_delay_min"].gt(15)
        grouped = valid.groupby(["operator_code", "period"], observed=True).agg(
            flight_count=("arrival_delay_min", "size"),
            delayed_over_15_count=("delayed_over_15", "sum"),
            median_arrival_delay_min=("arrival_delay_min", "median"),
            median_scheduled_duration_min=("scheduled_duration_min", "median"),
        ).reset_index()
        eligible = airline_metrics[
            airline_metrics["scope_id"].eq(scope_id)
            & airline_metrics["executive_eligible"].eq(True)
        ][["operator_code", "operator_name", "operator_country"]]
        grouped = grouped.merge(eligible, on="operator_code", how="inner")
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["scope_id"] = scope_id
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def write_airline_public_data(population: pd.DataFrame) -> None:
    """Write reusable airline-level public aggregates only."""

    AIRLINES_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    airline_metrics = build_airline_metrics(population)
    write_aggregate_csv(
        airline_metrics, AIRLINES_OUTPUT_ROOT / "airline_metrics.csv"
    )
    write_aggregate_csv(
        build_airline_monthly_metrics(population, airline_metrics),
        AIRLINES_OUTPUT_ROOT / "airline_monthly_metrics.csv",
    )
    pd.DataFrame([{
        "minimum_flights": AIRLINE_MIN_FLIGHTS,
        "minimum_periods": AIRLINE_MIN_PERIODS,
        "ranking_unit": "Identified ICAO airline operator",
        "delay_threshold": "Arrival delay greater than 15 minutes",
    }]).to_csv(AIRLINES_OUTPUT_ROOT / "airline_ranking_methodology.csv", index=False)


def _airport_movement_metrics(
    frame: pd.DataFrame,
    *,
    airport_column: str,
    delay_column: str,
    prefix: str,
) -> pd.DataFrame:
    """Aggregate one arrival/departure side before combining airport metrics."""

    valid = frame.dropna(subset=[airport_column, delay_column]).copy()
    valid = valid[valid[airport_column].ne("")]
    delayed_column = f"{prefix}_delayed_over_15"
    valid[delayed_column] = valid[delay_column].gt(15)
    return valid.groupby(airport_column, observed=True).agg(
        **{
            f"{prefix}_flight_count": (delay_column, "size"),
            f"{prefix}_delayed_over_15_count": (delayed_column, "sum"),
            f"median_{prefix}_delay_min": (delay_column, "median"),
            f"{prefix}_periods_active": ("period", "nunique"),
        }
    ).reset_index().rename(columns={airport_column: "airport_code"})


def build_airport_metrics(population: pd.DataFrame) -> pd.DataFrame:
    """Build exact arrival, departure and combined metrics per airport."""

    airports = load_airport_dimension()
    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        arrivals = _airport_movement_metrics(
            frame,
            airport_column="ADES",
            delay_column="arrival_delay_min",
            prefix="arrival",
        )
        departures = _airport_movement_metrics(
            frame,
            airport_column="ADEP",
            delay_column="departure_delay_min",
            prefix="departure",
        )
        grouped = arrivals.merge(departures, on="airport_code", how="outer")
        count_columns = [
            "arrival_flight_count",
            "arrival_delayed_over_15_count",
            "arrival_periods_active",
            "departure_flight_count",
            "departure_delayed_over_15_count",
            "departure_periods_active",
        ]
        grouped[count_columns] = grouped[count_columns].fillna(0).astype(int)
        grouped["flight_count"] = (
            grouped["arrival_flight_count"] + grouped["departure_flight_count"]
        )
        grouped["delayed_over_15_count"] = (
            grouped["arrival_delayed_over_15_count"]
            + grouped["departure_delayed_over_15_count"]
        )
        grouped["arrival_delay_over_15_pct"] = (
            100
            * grouped["arrival_delayed_over_15_count"]
            / grouped["arrival_flight_count"].replace(0, np.nan)
        )
        grouped["departure_delay_over_15_pct"] = (
            100
            * grouped["departure_delayed_over_15_count"]
            / grouped["departure_flight_count"].replace(0, np.nan)
        )
        grouped["combined_delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["periods_active"] = grouped[
            ["arrival_periods_active", "departure_periods_active"]
        ].max(axis=1)
        grouped["scope_id"] = scope_id
        grouped["scope_label"] = ROUTE_SCOPE_LABELS[scope_id]
        grouped["airport_name"] = grouped["airport_code"].map(airports["Airport name"])
        grouped["city"] = grouped["airport_code"].map(airports["City"])
        grouped["country"] = grouped["airport_code"].map(airports["Country"])
        grouped["latitude"] = grouped["airport_code"].map(
            frame.groupby("ADEP", observed=True)["origin_latitude"].median()
                .combine_first(frame.groupby("ADES", observed=True)["destination_latitude"].median())
        )
        grouped["longitude"] = grouped["airport_code"].map(
            frame.groupby("ADEP", observed=True)["origin_longitude"].median()
                .combine_first(frame.groupby("ADES", observed=True)["destination_longitude"].median())
        )
        grouped["executive_eligible"] = (
            grouped["flight_count"].ge(AIRPORT_MIN_FLIGHTS)
            & grouped["periods_active"].ge(AIRPORT_MIN_PERIODS)
        )
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def _airport_period_metrics(
    frame: pd.DataFrame,
    *,
    airport_column: str,
    delay_column: str,
    prefix: str,
) -> pd.DataFrame:
    valid = frame.dropna(subset=[airport_column, "period", delay_column]).copy()
    valid = valid[valid[airport_column].ne("")]
    valid["delayed_over_15"] = valid[delay_column].gt(15)
    return valid.groupby([airport_column, "period"], observed=True).agg(
        **{
            f"{prefix}_flight_count": (delay_column, "size"),
            f"{prefix}_delayed_over_15_count": ("delayed_over_15", "sum"),
        }
    ).reset_index().rename(columns={airport_column: "airport_code"})


def build_airport_monthly_metrics(
    population: pd.DataFrame,
    airport_metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for scope_id, frame in route_scope_frames(population).items():
        arrivals = _airport_period_metrics(
            frame,
            airport_column="ADES",
            delay_column="arrival_delay_min",
            prefix="arrival",
        )
        departures = _airport_period_metrics(
            frame,
            airport_column="ADEP",
            delay_column="departure_delay_min",
            prefix="departure",
        )
        grouped = arrivals.merge(
            departures, on=["airport_code", "period"], how="outer"
        )
        count_columns = [
            "arrival_flight_count",
            "arrival_delayed_over_15_count",
            "departure_flight_count",
            "departure_delayed_over_15_count",
        ]
        grouped[count_columns] = grouped[count_columns].fillna(0).astype(int)
        grouped["flight_count"] = (
            grouped["arrival_flight_count"] + grouped["departure_flight_count"]
        )
        grouped["arrival_delay_over_15_pct"] = (
            100 * grouped["arrival_delayed_over_15_count"]
            / grouped["arrival_flight_count"].replace(0, np.nan)
        )
        grouped["departure_delay_over_15_pct"] = (
            100 * grouped["departure_delayed_over_15_count"]
            / grouped["departure_flight_count"].replace(0, np.nan)
        )
        grouped["combined_delay_over_15_pct"] = (
            100
            * (grouped["arrival_delayed_over_15_count"] + grouped["departure_delayed_over_15_count"])
            / grouped["flight_count"]
        )
        eligible = airport_metrics[
            airport_metrics["scope_id"].eq(scope_id)
            & airport_metrics["executive_eligible"].eq(True)
        ][["airport_code"]]
        grouped = grouped.merge(eligible, on="airport_code", how="inner")
        grouped["scope_id"] = scope_id
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def build_airport_heatmap_metrics(
    population: pd.DataFrame,
    airport_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Build airport delay rates by scheduled local snapshot weekday and hour."""

    rows: list[pd.DataFrame] = []
    movement_specs = [
        ("arrival", "ADES", "arrival_delay_min", "filed_arrival_hour", "filed_arrival_weekday"),
        ("departure", "ADEP", "departure_delay_min", "filed_departure_hour", "filed_departure_weekday"),
    ]
    for scope_id, frame in route_scope_frames(population).items():
        eligible_codes = set(
            airport_metrics.loc[
                airport_metrics["scope_id"].eq(scope_id)
                & airport_metrics["executive_eligible"].eq(True),
                "airport_code",
            ]
        )
        movement_frames: list[pd.DataFrame] = []
        for movement_type, airport_col, delay_col, hour_col, weekday_col in movement_specs:
            movement = frame[[airport_col, delay_col, hour_col, weekday_col]].dropna().copy()
            movement = movement[movement[airport_col].isin(eligible_codes)]
            movement = movement.rename(columns={
                airport_col: "airport_code",
                delay_col: "delay_min",
                hour_col: "hour",
                weekday_col: "weekday_order",
            })
            movement["movement_type"] = movement_type
            movement_frames.append(movement)
        combined = pd.concat(movement_frames, ignore_index=True)
        both = combined.copy()
        both["movement_type"] = "both"
        combined = pd.concat([combined, both], ignore_index=True)
        combined["delayed_over_15"] = combined["delay_min"].gt(15)
        grouped = combined.groupby(
            ["airport_code", "movement_type", "weekday_order", "hour"],
            observed=True,
        ).agg(
            flight_count=("delay_min", "size"),
            delayed_over_15_count=("delayed_over_15", "sum"),
        ).reset_index()
        grouped["delay_over_15_pct"] = (
            100 * grouped["delayed_over_15_count"] / grouped["flight_count"]
        )
        grouped["weekday"] = grouped["weekday_order"].map(
            dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
        )
        grouped["scope_id"] = scope_id
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def write_airport_public_data(population: pd.DataFrame) -> None:
    """Write airport-level aggregate datasets without flight-level records."""

    AIRPORTS_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    airport_metrics = build_airport_metrics(population)
    write_aggregate_csv(
        airport_metrics, AIRPORTS_OUTPUT_ROOT / "airport_metrics.csv"
    )
    write_aggregate_csv(
        build_airport_monthly_metrics(population, airport_metrics),
        AIRPORTS_OUTPUT_ROOT / "airport_monthly_metrics.csv",
    )
    heatmap_metrics = build_airport_heatmap_metrics(population, airport_metrics)
    write_aggregate_csv(
        heatmap_metrics[
            [
                "airport_code",
                "movement_type",
                "hour",
                "flight_count",
                "delay_over_15_pct",
                "weekday",
                "scope_id",
            ]
        ],
        AIRPORTS_OUTPUT_ROOT / "airport_heatmap_metrics.csv",
    )


def summarise_scope(scope_id: str, frame: pd.DataFrame) -> dict[str, float | int | str]:
    delay = frame["arrival_delay_min"].to_numpy(dtype=float)
    delayed_0 = delay > 0
    delayed_15 = delay > 15
    delayed_60 = delay > 60
    low, high = wilson_interval(int(delayed_15.sum()), len(delay))
    positive = np.clip(delay, 0, None)
    return {
        "scope_id": scope_id,
        "scope_label": SCOPE_LABELS[scope_id],
        "flight_count": len(delay),
        "delay_over_0_count": int(delayed_0.sum()),
        "delay_over_0_pct": 100 * delayed_0.mean(),
        "delay_over_15_count": int(delayed_15.sum()),
        "delay_over_15_pct": 100 * delayed_15.mean(),
        "delay_over_15_wilson_low": low,
        "delay_over_15_wilson_high": high,
        "delay_over_60_pct": 100 * delayed_60.mean(),
        "median_arrival_delay_min": float(np.median(delay)),
        "median_delayed_only_min": (
            float(np.median(delay[delayed_15])) if delayed_15.any() else np.nan
        ),
        "p90_arrival_delay_min": float(np.quantile(delay, 0.90)),
        "total_positive_delay_hours": float(positive.sum() / 60),
    }


def build_overview(population: pd.DataFrame) -> pd.DataFrame:
    airports = load_airport_dimension()
    enriched = population.assign(
        origin_country=population["ADEP"].map(airports["Country"]),
        destination_country=population["ADES"].map(airports["Country"]),
    )
    rows = []
    for scope_id, frame in scope_frames(enriched).items():
        row = summarise_scope(scope_id, frame)
        international = frame[
            frame["origin_country"].notna()
            & frame["destination_country"].notna()
            & frame["origin_country"].ne(frame["destination_country"])
        ]
        row["median_international_arrival_delay_min"] = float(
            international["arrival_delay_min"].median()
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_monthly(population: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scope_id, frame in scope_frames(population).items():
        for period, month in frame.groupby("period", sort=True):
            row = summarise_scope(scope_id, month)
            row["period"] = period
            rows.append(row)
    keep = [
        "period", "scope_id", "scope_label", "flight_count",
        "delay_over_15_pct", "delay_over_15_wilson_low",
        "delay_over_15_wilson_high", "median_arrival_delay_min",
        "p90_arrival_delay_min", "total_positive_delay_hours",
    ]
    return pd.DataFrame(rows)[keep]


def build_severity(population: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = [
        "Early (<-5 min)", "Within 15 min (-5 to 15)",
        "Moderate delay (>15 to 60)", "Severe delay (>60 min)",
    ]
    for scope_id, frame in scope_frames(population).items():
        delay = frame["arrival_delay_min"]
        bands = pd.cut(
            delay,
            bins=[-np.inf, -5, 15, 60, np.inf],
            labels=labels,
            right=True,
        )
        counts = bands.value_counts(sort=False)
        for order, label in enumerate(labels):
            count = int(counts.get(label, 0))
            rows.append({
                "scope_id": scope_id,
                "scope_label": SCOPE_LABELS[scope_id],
                "delay_band": label,
                "band_order": order,
                "flight_count": count,
                "flight_pct": 100 * count / len(frame),
            })
    return pd.DataFrame(rows)


def build_duration_metrics(population: pd.DataFrame) -> pd.DataFrame:
    valid = population[population["scheduled_duration_min"] > 0].copy()
    valid["hour_order"] = np.floor(valid["scheduled_duration_min"] / 60).clip(0, 12).astype(int)
    valid["duration_hour"] = valid["hour_order"].map(
        lambda hour: f"{hour}-{hour + 1} h" if hour < 12 else "12+ h"
    )
    rows = []
    for order in sorted(valid["hour_order"].unique()):
        frame = valid[valid["hour_order"] == order]
        delay = frame["arrival_delay_min"].to_numpy(dtype=float)
        delayed = delay > 15
        low, high = wilson_interval(int(delayed.sum()), len(delay))
        rows.append({
            "duration_hour": f"{order}-{order + 1} h" if order < 12 else "12+ h",
            "hour_order": order,
            "flight_count": len(delay),
            "delay_over_15_pct": 100 * delayed.mean(),
            "delay_over_15_wilson_low": low,
            "delay_over_15_wilson_high": high,
            "median_arrival_delay_min": float(np.median(delay)),
            "median_delayed_only_min": float(np.median(delay[delayed])) if delayed.any() else np.nan,
            "p90_arrival_delay_min": float(np.quantile(delay, 0.90)),
            "total_positive_delay_hours": float(np.clip(delay, 0, None).sum() / 60),
        })
    return pd.DataFrame(rows)


def build_concentration(population: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scope_id, frame in scope_frames(population).items():
        positive = np.clip(frame["arrival_delay_min"].to_numpy(dtype=float), 0, None)
        ordered = np.sort(positive)[::-1]
        total_hours = ordered.sum() / 60
        for top_pct in (1, 5, 10, 20):
            selected = max(1, math.ceil(len(ordered) * top_pct / 100))
            selected_hours = ordered[:selected].sum() / 60
            rows.append({
                "scope_id": scope_id,
                "scope_label": SCOPE_LABELS[scope_id],
                "top_flight_pct": top_pct,
                "flight_count": selected,
                "positive_delay_hours": selected_hours,
                "share_of_positive_delay_pct": (
                    100 * selected_hours / total_hours if total_hours else np.nan
                ),
            })
    return pd.DataFrame(rows)


def build_delay_deciles(population: pd.DataFrame) -> pd.DataFrame:
    """Measure how much positive delay is contributed by each flight decile."""

    positive = np.clip(population["arrival_delay_min"].to_numpy(dtype=float), 0, None)
    ordered = np.sort(positive)[::-1]
    total_minutes = ordered.sum()
    deciles = np.minimum((np.arange(len(ordered)) * 10 // len(ordered)) + 1, 10)
    rows = []
    for decile in range(1, 11):
        values = ordered[deciles == decile]
        minutes = values.sum()
        rows.append({
            "delay_rank_decile": decile,
            "decile_label": f"D{decile}",
            "interpretation": (
                "Most delayed 10%" if decile == 1
                else "Least delayed 10%" if decile == 10
                else f"Delay-ranked decile {decile}"
            ),
            "flight_count": len(values),
            "positive_delay_hours": minutes / 60,
            "share_of_positive_delay_pct": (
                100 * minutes / total_minutes if total_minutes else np.nan
            ),
        })
    return pd.DataFrame(rows)


def build_concentration_summary(population: pd.DataFrame) -> pd.DataFrame:
    """Create the public worst-10% versus remaining-90% comparison."""

    positive = np.clip(population["arrival_delay_min"].to_numpy(dtype=float), 0, None)
    ordered = np.sort(positive)[::-1]
    worst_count = math.ceil(len(ordered) * 0.10)
    total_hours = ordered.sum() / 60
    worst_hours = ordered[:worst_count].sum() / 60
    rows = [
        {
            "segment": "Most delayed 10% of flights",
            "segment_order": 1,
            "flight_count": worst_count,
            "positive_delay_hours": worst_hours,
            "share_of_positive_delay_pct": 100 * worst_hours / total_hours,
        },
        {
            "segment": "Remaining 90% of flights",
            "segment_order": 2,
            "flight_count": len(ordered) - worst_count,
            "positive_delay_hours": total_hours - worst_hours,
            "share_of_positive_delay_pct": 100 * (total_hours - worst_hours) / total_hours,
        },
    ]
    return pd.DataFrame(rows)


def correlation_strength(coefficient: float) -> str:
    absolute = abs(coefficient)
    if absolute < 0.10:
        return "Very weak"
    if absolute < 0.30:
        return "Weak"
    if absolute < 0.50:
        return "Moderate"
    if absolute < 0.70:
        return "Strong"
    return "Very strong"


def build_correlation_metrics(population: pd.DataFrame) -> pd.DataFrame:
    """Publish a rank correlation without exposing flight-level observations."""

    valid = population[
        population["scheduled_duration_min"].gt(0)
        & population["scheduled_duration_min"].notna()
        & population["arrival_delay_min"].notna()
    ]
    coefficient = float(valid["scheduled_duration_min"].corr(
        valid["arrival_delay_min"], method="spearman"
    ))
    direction = "Positive" if coefficient > 0 else "Negative" if coefficient < 0 else "None"
    return pd.DataFrame([{
        "metric_id": "scheduled_duration_vs_arrival_delay_spearman",
        "x_variable": "Scheduled duration (minutes)",
        "y_variable": "Arrival delay (minutes)",
        "coefficient": coefficient,
        "absolute_strength": correlation_strength(coefficient),
        "direction": direction,
        "flight_count": len(valid),
    }])


def write_public_data(population: pd.DataFrame, months: list[str]) -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    tables = {
        "overview_kpis.csv": build_overview(population),
        "monthly_delay_trend.csv": build_monthly(population),
        "delay_severity_distribution.csv": build_severity(population),
        "duration_hour_metrics.csv": build_duration_metrics(population),
        "delay_concentration.csv": build_concentration(population),
        "delay_concentration_summary.csv": build_concentration_summary(population),
        "delay_decile_distribution.csv": build_delay_deciles(population),
        "correlation_metrics.csv": build_correlation_metrics(population),
    }
    for filename, table in tables.items():
        write_aggregate_csv(table, OUTPUT_ROOT / filename)

    metadata = pd.DataFrame([
        {"key": "dataset_start", "value": f"{min(months)[:4]}-{min(months)[4:]}"},
        {"key": "dataset_end", "value": f"{max(months)[:4]}-{max(months)[4:]}"},
        {"key": "available_periods", "value": ", ".join(months)},
        {"key": "study_year", "value": min(months)[:4]},
        {"key": "source", "value": "EUROCONTROL Aviation Data Repository for Research (ADRR)"},
        {"key": "source_url", "value": "https://www.eurocontrol.int/dashboard/aviation-data-research"},
        {"key": "terms_url", "value": "https://www.eurocontrol.int/publication/eurocontrol-aviation-data-repository-research-terms-use"},
        {"key": "publication_constraint", "value": "The accepted ADRR Terms of Use prohibit sharing or distributing the repository; only aggregated outputs are published"},
        {"key": "population_filter", "value": "Scheduled flights (ICAO Flight Type S) passing notebook-10 quality rules"},
        {"key": "delay_definition", "value": "Actual arrival more than 15 minutes after filed arrival"},
        {"key": "short_flight_definition", "value": "Positive scheduled duration below 180 minutes"},
        {"key": "data_granularity", "value": "Aggregated statistics only; no flight-level records"},
    ])
    metadata.to_csv(OUTPUT_ROOT / "dashboard_metadata.csv", index=False)

    definitions = pd.DataFrame([
        {"metric": "delay_over_15_pct", "display_name": "Flights delayed >15 min", "unit": "%", "description": "Share of arrivals more than 15 minutes late"},
        {"metric": "median_arrival_delay_min", "display_name": "Median arrival delay", "unit": "minutes", "description": "Median actual minus filed arrival time across all flights"},
        {"metric": "median_international_arrival_delay_min", "display_name": "Median arrival delay on international flights", "unit": "minutes", "description": "Median actual minus filed arrival time for flights whose origin and destination countries differ"},
        {"metric": "median_delayed_only_min", "display_name": "Median among delayed flights", "unit": "minutes", "description": "Median arrival delay among flights delayed more than 15 minutes"},
        {"metric": "p90_arrival_delay_min", "display_name": "90th percentile delay", "unit": "minutes", "description": "Ninety percent of flights have a delay at or below this value"},
        {"metric": "total_positive_delay_hours", "display_name": "Accumulated positive delay", "unit": "hours", "description": "Sum of positive arrival-delay minutes; early arrivals do not offset delays"},
        {"metric": "wilson_95", "display_name": "Wilson 95% interval", "unit": "percentage points", "description": "Uncertainty interval for the observed proportion delayed more than 15 minutes"},
        {"metric": "spearman_rho", "display_name": "Spearman rank correlation", "unit": "coefficient", "description": "Monotonic association between scheduled duration and arrival-delay minutes; correlation does not imply causation"},
    ])
    definitions.to_csv(OUTPUT_ROOT / "metric_definitions.csv", index=False)

    ROUTES_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    route_metrics = build_route_metrics(population)
    write_aggregate_csv(route_metrics, ROUTES_OUTPUT_ROOT / "route_metrics.csv")
    write_aggregate_csv(
        build_route_monthly_metrics(population, route_metrics),
        ROUTES_OUTPUT_ROOT / "route_monthly_metrics.csv",
    )
    write_aggregate_csv(
        build_route_operator_metrics(population, route_metrics),
        ROUTES_OUTPUT_ROOT / "route_operator_metrics.csv",
    )
    write_aggregate_csv(
        build_route_scope_summary(population),
        ROUTES_OUTPUT_ROOT / "route_scope_summary.csv",
    )
    pd.DataFrame([{
        "minimum_flights": ROUTE_MIN_FLIGHTS,
        "minimum_periods": ROUTE_MIN_PERIODS,
        "ranking_unit": "Directional route (ADEP → ADES)",
        "delay_threshold": "Arrival delay greater than 15 minutes",
    }]).to_csv(ROUTES_OUTPUT_ROOT / "route_ranking_methodology.csv", index=False)
    write_airline_public_data(population)
    write_airport_public_data(population)


def main() -> None:
    population, months = load_population(ANALYSIS_YEAR)
    write_public_data(population, months)
    print({
        "clean_flights": len(population),
        "periods": months,
        "output": str(OUTPUT_ROOT),
    })


if __name__ == "__main__":
    main()
