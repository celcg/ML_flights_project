"""Business-facing aviation statistics for the EUROCONTROL flight files.

The reporting period is explicit and may differ from the model-development
holdouts. All percentages use operated scheduled-commercial flights with an
observed target as their denominator.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, lgamma, log, sqrt
from pathlib import Path
import re
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

from src.flight_config import DATETIME_FORMAT_PANDAS


BUSINESS_BLUE = "#5B9BD5"
BUSINESS_LIGHT_BLUE = "#D9EAF7"
BUSINESS_GREEN = "#70AD47"
BUSINESS_DARK_BLUE = "#1F4E78"
BUSINESS_GREY = "#667085"
STANDARD_PALETTE = [
    BUSINESS_BLUE,
    BUSINESS_GREEN,
    "#A5A5A5",
    "#ED7D31",
    "#4472C4",
    "#FFC000",
]

RAW_COLUMNS = [
    "ECTRL ID",
    "ADEP",
    "ADES",
    "FILED OFF BLOCK TIME",
    "FILED ARRIVAL TIME",
    "ACTUAL OFF BLOCK TIME",
    "ACTUAL ARRIVAL TIME",
    "AC Type",
    "AC Operator",
    "ICAO Flight Type",
    "STATFOR Market Segment",
    "Requested FL",
    "Actual Distance Flown (nm)",
]

CATEGORY_COLUMNS = [
    "ADEP",
    "ADES",
    "route",
    "airport_pair",
    "AC Operator",
    "AC Type",
    "STATFOR Market Segment",
    "period",
    "haul_band",
    "departure_weekday",
]


def development_flight_paths(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
) -> list[Path]:
    """Exclude files starting at or after the configured reporting boundary."""

    config = config or BusinessAnalysisConfig()
    reporting_end = pd.Timestamp(config.reporting_end)
    selected: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        match = re.search(r"Flights_(\d{8})_", path.name)
        if match is None:
            raise ValueError(f"Cannot infer period from flight filename: {path.name}")
        file_start = pd.to_datetime(match.group(1), format="%Y%m%d")
        if file_start < reporting_end:
            selected.append(path)
    return sorted(selected)


@dataclass(frozen=True)
class BusinessAnalysisConfig:
    """Shared scope and ranking decisions for the business report."""

    test_start: str = "2023-01-01"
    analysis_end_exclusive: str | None = None
    regular_flight_type: str = "S"
    min_delay_minutes: float = -120.0
    max_flight_level: float = 500.0
    min_distance_nm: float = 0.0
    delay_thresholds: tuple[int, ...] = (15, 30, 60)
    route_volume_candidates: tuple[int, ...] = (20, 50, 100, 200, 500)
    period_candidates: tuple[int, ...] = (1, 2, 3)
    executive_min_route_flights: int = 20
    executive_min_route_periods: int = 3
    route_plot_min_flights: int = 2
    executive_min_airport_flights: int = 200
    executive_min_airport_periods: int = 3
    airport_plot_min_flights: int = 200
    airport_plot_top_n: int = 200
    route_plot_top_n: int = 500
    executive_min_operator_flights: int = 1_000
    adjusted_min_operator_flights: int = 5_000
    practical_otp15_difference_pp: float = 3.0
    practical_p90_difference_min: float = 5.0
    practical_median_difference_min: float = 2.0
    trend_min_periods: int = 6
    confidence_level: float = 0.95
    top_n: int = 20

    @property
    def reporting_end(self) -> str:
        """Return the explicit report boundary or the legacy test boundary."""

        return self.analysis_end_exclusive or self.test_start


def _parse_timestamp(series: pd.Series) -> pd.Series:
    """Parse the documented EUROCONTROL timestamp format."""

    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, format=DATETIME_FORMAT_PANDAS, errors="coerce")


def _valid_or_missing(series: pd.Series, condition: pd.Series) -> pd.Series:
    return series.isna() | condition


def prepare_business_flights(
    raw: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    """Clean one raw chunk and derive business KPIs without using test rows."""

    config = config or BusinessAnalysisConfig()
    missing = sorted(set(RAW_COLUMNS).difference(raw.columns))
    if missing:
        raise KeyError(f"Missing required flight columns: {missing}")

    frame = raw.loc[:, RAW_COLUMNS].copy()
    text_columns = frame.select_dtypes(include=["object", "string"]).columns
    frame[text_columns] = frame[text_columns].apply(lambda values: values.str.strip())
    frame = frame.replace(r"^\s*$", np.nan, regex=True)

    time_columns = [
        "FILED OFF BLOCK TIME",
        "FILED ARRIVAL TIME",
        "ACTUAL OFF BLOCK TIME",
        "ACTUAL ARRIVAL TIME",
    ]
    for column in time_columns:
        frame[column] = _parse_timestamp(frame[column])

    frame["Departure_Delay_Min"] = (
        frame["ACTUAL OFF BLOCK TIME"] - frame["FILED OFF BLOCK TIME"]
    ).dt.total_seconds() / 60.0
    frame["Arrival_Delay_Min"] = (
        frame["ACTUAL ARRIVAL TIME"] - frame["FILED ARRIVAL TIME"]
    ).dt.total_seconds() / 60.0

    before_test = frame["FILED OFF BLOCK TIME"] < pd.Timestamp(config.reporting_end)
    scheduled = frame["ICAO Flight Type"].eq(config.regular_flight_type)
    physically_valid = (
        _valid_or_missing(
            frame["Departure_Delay_Min"],
            frame["Departure_Delay_Min"].ge(config.min_delay_minutes),
        )
        & _valid_or_missing(
            frame["Arrival_Delay_Min"],
            frame["Arrival_Delay_Min"].ge(config.min_delay_minutes),
        )
        & _valid_or_missing(
            frame["Requested FL"],
            frame["Requested FL"].between(0, config.max_flight_level),
        )
        & _valid_or_missing(
            frame["Actual Distance Flown (nm)"],
            frame["Actual Distance Flown (nm)"].gt(config.min_distance_nm),
        )
    )
    frame = frame.loc[before_test & scheduled & physically_valid].copy()

    frame["scheduled_duration_min"] = (
        frame["FILED ARRIVAL TIME"] - frame["FILED OFF BLOCK TIME"]
    ).dt.total_seconds() / 60.0
    frame["actual_duration_min"] = (
        frame["ACTUAL ARRIVAL TIME"] - frame["ACTUAL OFF BLOCK TIME"]
    ).dt.total_seconds() / 60.0
    frame["schedule_buffer_min"] = (
        frame["scheduled_duration_min"] - frame["actual_duration_min"]
    )
    frame["recovery_minutes"] = (
        frame["Departure_Delay_Min"] - frame["Arrival_Delay_Min"]
    )

    frame["route"] = frame["ADEP"].astype("string") + " → " + frame["ADES"].astype("string")
    left = frame[["ADEP", "ADES"]].min(axis=1).astype("string")
    right = frame[["ADEP", "ADES"]].max(axis=1).astype("string")
    frame["airport_pair"] = left + " ↔ " + right
    frame["AC Operator"] = frame["AC Operator"].fillna("Unknown")
    frame["AC Type"] = frame["AC Type"].fillna("Unknown")
    frame["STATFOR Market Segment"] = frame["STATFOR Market Segment"].fillna("Unknown")

    filed_departure = frame["FILED OFF BLOCK TIME"]
    frame["period"] = filed_departure.dt.to_period("M").astype("string")
    frame["departure_date"] = filed_departure.dt.floor("D")
    frame["departure_hour"] = filed_departure.dt.hour.astype("uint8")
    frame["departure_weekday"] = pd.Categorical(
        filed_departure.dt.day_name(),
        categories=[
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
        ordered=True,
    )
    frame["haul_band"] = pd.cut(
        frame["scheduled_duration_min"],
        bins=[0, 90, 180, 360, np.inf],
        labels=["≤90 min", "90–180 min", "180–360 min", ">360 min"],
        include_lowest=True,
    )

    for threshold in config.delay_thresholds:
        frame[f"arrival_delayed_{threshold}"] = (
            frame["Arrival_Delay_Min"].gt(threshold).astype("int8")
        )
        frame[f"departure_delayed_{threshold}"] = (
            frame["Departure_Delay_Min"].gt(threshold).astype("int8")
        )
    frame["arrival_otp15"] = frame["Arrival_Delay_Min"].le(15).astype("int8")
    frame["recovered_to_otp15"] = (
        frame["Departure_Delay_Min"].gt(15)
        & frame["Arrival_Delay_Min"].le(15)
    ).astype("int8")
    frame["worsened_after_departure"] = (
        frame["Arrival_Delay_Min"] > frame["Departure_Delay_Min"]
    ).astype("int8")

    keep_columns = [
        "ECTRL ID",
        "ADEP",
        "ADES",
        "route",
        "airport_pair",
        "AC Operator",
        "AC Type",
        "STATFOR Market Segment",
        "FILED OFF BLOCK TIME",
        "departure_date",
        "period",
        "departure_hour",
        "departure_weekday",
        "haul_band",
        "Requested FL",
        "Actual Distance Flown (nm)",
        "scheduled_duration_min",
        "actual_duration_min",
        "schedule_buffer_min",
        "Departure_Delay_Min",
        "Arrival_Delay_Min",
        "recovery_minutes",
        "arrival_otp15",
        "recovered_to_otp15",
        "worsened_after_departure",
        *[f"arrival_delayed_{value}" for value in config.delay_thresholds],
        *[f"departure_delayed_{value}" for value in config.delay_thresholds],
    ]
    return frame[keep_columns]


def read_business_flights(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
    *,
    chunksize: int = 100_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Read selected files in bounded chunks and return a compact analysis frame."""

    config = config or BusinessAnalysisConfig()
    pieces: list[pd.DataFrame] = []
    for raw_path in development_flight_paths(paths, config):
        path = Path(raw_path)
        reader = pd.read_csv(
            path,
            compression="gzip",
            usecols=RAW_COLUMNS,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        )
        for chunk in reader:
            prepared = prepare_business_flights(chunk, config)
            if not prepared.empty:
                pieces.append(prepared)
    if not pieces:
        return pd.DataFrame()
    result = pd.concat(pieces, ignore_index=True)
    for column in CATEGORY_COLUMNS:
        if column in result:
            result[column] = result[column].astype("category")
    float_columns = result.select_dtypes(include=["float64"]).columns
    result[float_columns] = result[float_columns].astype("float32")
    if not result.empty:
        assert result["FILED OFF BLOCK TIME"].max() < pd.Timestamp(config.reporting_end)
    return result


def scan_route_volume(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
    *,
    chunksize: int = 200_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Count route volume and active periods exactly with very little memory."""

    config = config or BusinessAnalysisConfig()
    partials: list[pd.DataFrame] = []
    usecols = ["ADEP", "ADES", "FILED OFF BLOCK TIME", "ICAO Flight Type"]
    for raw_path in development_flight_paths(paths, config):
        for chunk in pd.read_csv(
            raw_path,
            compression="gzip",
            usecols=usecols,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            filed = _parse_timestamp(chunk["FILED OFF BLOCK TIME"])
            mask = (
                chunk["ICAO Flight Type"].astype("string").str.strip().eq(config.regular_flight_type)
                & filed.lt(pd.Timestamp(config.reporting_end))
                & filed.notna()
                & chunk["ADEP"].notna()
                & chunk["ADES"].notna()
            )
            scoped = chunk.loc[mask, ["ADEP", "ADES"]].copy()
            scoped["period"] = filed.loc[mask].dt.to_period("M").astype("string")
            partials.append(
                scoped.groupby(["ADEP", "ADES", "period"], observed=True)
                .size()
                .rename("flights")
                .reset_index()
            )
    if not partials:
        return pd.DataFrame(columns=["ADEP", "ADES", "route", "flights", "periods_active"])
    by_period = (
        pd.concat(partials, ignore_index=True)
        .groupby(["ADEP", "ADES", "period"], observed=True, as_index=False)["flights"]
        .sum()
    )
    routes = by_period.groupby(["ADEP", "ADES"], observed=True).agg(
        flights=("flights", "sum"), periods_active=("period", "nunique")
    ).reset_index()
    routes["route"] = routes["ADEP"].astype(str) + " → " + routes["ADES"].astype(str)
    return routes.sort_values("flights", ascending=False, ignore_index=True)


def scan_day_hour_otp15(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
    *,
    chunksize: int = 100_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Aggregate observed arrival OTP15 by scheduled departure weekday and hour.

    The calculation reuses the report's cleaning function but retains only a
    tiny grouped result from each chunk, so the complete dataset is never held
    in memory.
    """

    config = config or BusinessAnalysisConfig()
    partials: list[pd.DataFrame] = []
    for raw_path in development_flight_paths(paths, config):
        for chunk in pd.read_csv(
            raw_path,
            compression="gzip",
            usecols=RAW_COLUMNS,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            prepared = prepare_business_flights(chunk, config)
            observed = prepared.loc[
                prepared["Arrival_Delay_Min"].notna(),
                ["departure_weekday", "departure_hour", "arrival_otp15"],
            ]
            if observed.empty:
                continue
            partials.append(
                observed.groupby(
                    ["departure_weekday", "departure_hour"],
                    observed=True,
                ).agg(
                    flights=("arrival_otp15", "size"),
                    otp15_count=("arrival_otp15", "sum"),
                ).reset_index()
            )

    columns = [
        "departure_weekday",
        "departure_hour",
        "flights",
        "otp15_count",
        "otp15_pct",
        "otp15_ci_low_pct",
        "otp15_ci_high_pct",
    ]
    if not partials:
        return pd.DataFrame(columns=columns)

    result = (
        pd.concat(partials, ignore_index=True)
        .groupby(["departure_weekday", "departure_hour"], observed=True, as_index=False)
        [["flights", "otp15_count"]]
        .sum()
    )
    result["otp15_pct"] = 100.0 * result["otp15_count"] / result["flights"]
    intervals = result.apply(
        lambda row: wilson_interval(row["otp15_count"], row["flights"], config.confidence_level),
        axis=1,
        result_type="expand",
    )
    result[["otp15_ci_low_pct", "otp15_ci_high_pct"]] = 100.0 * intervals
    weekday_order = {
        day: index
        for index, day in enumerate(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        )
    }
    result["weekday_order"] = result["departure_weekday"].astype(str).map(weekday_order)
    result = result.sort_values(["weekday_order", "departure_hour"]).drop(columns="weekday_order")
    return result.loc[:, columns].reset_index(drop=True)


def scan_duration_delay_performance(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
    *,
    chunksize: int = 100_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Aggregate arrival-delay severity by scheduled flight-duration band.

    Only flights with an observed arrival delay and a positive scheduled
    duration enter the denominator. The grouped partials keep memory bounded.
    """

    config = config or BusinessAnalysisConfig()
    labels = ["0-90 min", "90-180 min", "180-360 min", ">360 min"]
    partials: list[pd.DataFrame] = []
    for raw_path in development_flight_paths(paths, config):
        for chunk in pd.read_csv(
            raw_path,
            compression="gzip",
            usecols=RAW_COLUMNS,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            prepared = prepare_business_flights(chunk, config)
            observed = prepared.loc[
                prepared["Arrival_Delay_Min"].notna()
                & prepared["scheduled_duration_min"].gt(0),
                ["scheduled_duration_min", "Arrival_Delay_Min"],
            ].copy()
            if observed.empty:
                continue
            observed["duration_band"] = pd.cut(
                observed["scheduled_duration_min"],
                bins=[0, 90, 180, 360, np.inf],
                labels=labels,
                include_lowest=False,
            )
            for threshold in (15, 30, 60):
                observed[f"delayed_{threshold}"] = observed["Arrival_Delay_Min"].gt(threshold)
            partials.append(
                observed.groupby("duration_band", observed=True).agg(
                    flights=("Arrival_Delay_Min", "size"),
                    delayed_15_count=("delayed_15", "sum"),
                    delayed_30_count=("delayed_30", "sum"),
                    delayed_60_count=("delayed_60", "sum"),
                ).reset_index()
            )

    columns = [
        "duration_band",
        "flights",
        "flight_share_pct",
        "delayed_15_count",
        "delayed_15_pct",
        "delayed_15_ci_low_pct",
        "delayed_15_ci_high_pct",
        "delayed_30_count",
        "delayed_30_pct",
        "delayed_60_count",
        "delayed_60_pct",
    ]
    if not partials:
        return pd.DataFrame(columns=columns)

    result = (
        pd.concat(partials, ignore_index=True)
        .groupby("duration_band", observed=True, as_index=False)
        [["flights", "delayed_15_count", "delayed_30_count", "delayed_60_count"]]
        .sum()
    )
    result["flight_share_pct"] = 100.0 * result["flights"] / result["flights"].sum()
    for threshold in (15, 30, 60):
        result[f"delayed_{threshold}_pct"] = (
            100.0 * result[f"delayed_{threshold}_count"] / result["flights"]
        )
    intervals = result.apply(
        lambda row: wilson_interval(
            row["delayed_15_count"], row["flights"], config.confidence_level
        ),
        axis=1,
        result_type="expand",
    )
    result[["delayed_15_ci_low_pct", "delayed_15_ci_high_pct"]] = 100.0 * intervals
    order = {label: index for index, label in enumerate(labels)}
    result["duration_order"] = result["duration_band"].astype(str).map(order)
    result = result.sort_values("duration_order").drop(columns="duration_order")
    return result.loc[:, columns].reset_index(drop=True)


def scan_destination_relative_delay(
    paths: Sequence[Path | str],
    config: BusinessAnalysisConfig | None = None,
    *,
    chunksize: int = 100_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Aggregate positive arrival-delay minutes relative to scheduled duration.

    The principal metric is exposure-weighted: total positive arrival-delay
    minutes divided by total scheduled flight minutes. Early arrivals cannot
    cancel delay, and only observed arrivals with positive scheduled duration
    enter the denominator.
    """

    config = config or BusinessAnalysisConfig()
    partials: list[pd.DataFrame] = []
    for raw_path in development_flight_paths(paths, config):
        for chunk in pd.read_csv(
            raw_path,
            compression="gzip",
            usecols=RAW_COLUMNS,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            prepared = prepare_business_flights(chunk, config)
            observed = prepared.loc[
                prepared["Arrival_Delay_Min"].notna()
                & prepared["scheduled_duration_min"].gt(0)
                & prepared["ADES"].notna(),
                ["ADES", "period", "scheduled_duration_min", "Arrival_Delay_Min"],
            ].copy()
            if observed.empty:
                continue
            observed["positive_delay_min"] = observed["Arrival_Delay_Min"].clip(lower=0)
            observed["flight_relative_delay"] = (
                observed["positive_delay_min"] / observed["scheduled_duration_min"]
            )
            observed["delay_exceeds_duration"] = observed["flight_relative_delay"].gt(1)
            partials.append(
                observed.groupby(["ADES", "period"], observed=True).agg(
                    observed_arrivals=("Arrival_Delay_Min", "size"),
                    positive_delay_minutes=("positive_delay_min", "sum"),
                    scheduled_duration_minutes=("scheduled_duration_min", "sum"),
                    flight_relative_delay_sum=("flight_relative_delay", "sum"),
                    delay_exceeds_duration_count=("delay_exceeds_duration", "sum"),
                ).reset_index()
            )

    columns = [
        "airport",
        "observed_arrivals",
        "periods_active",
        "positive_delay_minutes",
        "scheduled_duration_minutes",
        "relative_delay_burden_pct",
        "mean_flight_relative_delay_pct",
        "delay_exceeds_duration_count",
        "delay_exceeds_duration_pct",
    ]
    if not partials:
        return pd.DataFrame(columns=columns)

    by_period = (
        pd.concat(partials, ignore_index=True)
        .groupby(["ADES", "period"], observed=True, as_index=False)
        [[
            "observed_arrivals",
            "positive_delay_minutes",
            "scheduled_duration_minutes",
            "flight_relative_delay_sum",
            "delay_exceeds_duration_count",
        ]]
        .sum()
    )
    result = by_period.groupby("ADES", observed=True).agg(
        observed_arrivals=("observed_arrivals", "sum"),
        periods_active=("period", "nunique"),
        positive_delay_minutes=("positive_delay_minutes", "sum"),
        scheduled_duration_minutes=("scheduled_duration_minutes", "sum"),
        flight_relative_delay_sum=("flight_relative_delay_sum", "sum"),
        delay_exceeds_duration_count=("delay_exceeds_duration_count", "sum"),
    ).reset_index().rename(columns={"ADES": "airport"})
    result["relative_delay_burden_pct"] = (
        100.0 * result["positive_delay_minutes"] / result["scheduled_duration_minutes"]
    )
    result["mean_flight_relative_delay_pct"] = (
        100.0 * result["flight_relative_delay_sum"] / result["observed_arrivals"]
    )
    result["delay_exceeds_duration_pct"] = (
        100.0 * result["delay_exceeds_duration_count"] / result["observed_arrivals"]
    )
    return result.loc[:, columns].sort_values(
        "observed_arrivals", ascending=False, ignore_index=True
    )


def plot_duration_delay_context(summary: pd.DataFrame) -> plt.Figure:
    """Compare delay thresholds and traffic exposure across duration bands."""

    apply_business_plot_style()
    frame = summary.copy()
    x = np.arange(len(frame))
    width = 0.22
    fig, (ax, volume_ax) = plt.subplots(
        1,
        2,
        figsize=(12.5, 6.2),
        gridspec_kw={"width_ratios": [3.2, 1.25]},
    )
    series = [
        ("delayed_15_pct", ">15 min", "#ED7D31"),
        ("delayed_30_pct", ">30 min", "#A5A5A5"),
        ("delayed_60_pct", ">60 min", "#C00000"),
    ]
    for offset, (column, label, color) in zip((-width, 0, width), series):
        bars = ax.bar(x + offset, frame[column], width, label=label, color=color)
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8, color=BUSINESS_GREY)
    ax.set_xticks(x, frame["duration_band"].astype(str))
    ax.set_ylabel("Share of observed arrivals (%)")
    ax.set_xlabel("Scheduled flight duration")
    ax.set_title("Arrival-delay severity")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7, alpha=0.75)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    volume_bars = volume_ax.barh(
        frame["duration_band"].astype(str),
        frame["flight_share_pct"],
        color=BUSINESS_BLUE,
    )
    volume_ax.bar_label(
        volume_bars,
        labels=[
            f"{share:.1f}%  ({int(flights):,})"
            for share, flights in zip(frame["flight_share_pct"], frame["flights"])
        ],
        padding=4,
        fontsize=8,
        color=BUSINESS_GREY,
    )
    volume_ax.invert_yaxis()
    volume_ax.set_xlabel("Share of analysed flights (%)")
    volume_ax.set_title("Traffic exposure")
    volume_ax.grid(axis="x", color="#D9D9D9", linewidth=0.7, alpha=0.75)
    volume_ax.set_axisbelow(True)
    volume_ax.margins(x=0.32)
    for spine in volume_ax.spines.values():
        spine.set_visible(False)

    fig.suptitle(
        "Arrival delay by scheduled flight duration",
        color=BUSINESS_DARK_BLUE,
        fontweight="bold",
    )
    fig.tight_layout()
    return fig


def _percent(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if denominator else np.nan


def wilson_interval(
    successes: int | float,
    observations: int | float,
    confidence_level: float = 0.95,
) -> tuple[float, float]:
    """Return a Wilson score interval as proportions between zero and one."""

    if observations <= 0:
        return np.nan, np.nan
    z = stats.norm.ppf(1 - (1 - confidence_level) / 2)
    p = successes / observations
    denominator = 1 + z**2 / observations
    centre = (p + z**2 / (2 * observations)) / denominator
    margin = (
        z
        * sqrt((p * (1 - p) + z**2 / (4 * observations)) / observations)
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def overall_kpis(
    flights: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> pd.Series:
    """Create the executive network-level scorecard."""

    config = config or BusinessAnalysisConfig()
    arrival = flights["Arrival_Delay_Min"].dropna()
    departure = flights["Departure_Delay_Min"].dropna()
    delayed_departures = flights.loc[
        flights["Departure_Delay_Min"].gt(15)
        & flights["Arrival_Delay_Min"].notna()
    ]
    values: dict[str, float | int] = {
        "flights": len(flights),
        "routes": flights["route"].nunique(),
        "operators": flights["AC Operator"].nunique(),
        "departure_airports": flights["ADEP"].nunique(),
        "arrival_airports": flights["ADES"].nunique(),
        "periods": flights["period"].nunique(),
        "arrival_observed": len(arrival),
        "arrival_otp15_pct": _percent(arrival.le(15).sum(), len(arrival)),
        "arrival_delay_median": arrival.median(),
        "arrival_delay_p90": arrival.quantile(0.90),
        "arrival_delay_p95": arrival.quantile(0.95),
        "departure_delay_median": departure.median(),
        "scheduled_duration_median": flights["scheduled_duration_min"].median(),
        "recovery_median": flights["recovery_minutes"].median(),
        "recovered_to_otp15_pct": _percent(
            delayed_departures["recovered_to_otp15"].sum(), len(delayed_departures)
        ),
    }
    for threshold in config.delay_thresholds:
        values[f"arrival_delayed_{threshold}_pct"] = _percent(
            arrival.gt(threshold).sum(), len(arrival)
        )
    return pd.Series(values, name="value")


def grouped_performance(
    flights: pd.DataFrame,
    group_columns: str | Sequence[str],
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    """Calculate comparable volume, reliability, severity and recovery metrics."""

    config = config or BusinessAnalysisConfig()
    groups = [group_columns] if isinstance(group_columns, str) else list(group_columns)
    valid = flights.loc[flights["Arrival_Delay_Min"].notna()].copy()
    grouped = valid.groupby(groups, observed=True, dropna=False)
    result = grouped.agg(
        flights=("ECTRL ID", "size"),
        periods_active=("period", "nunique"),
        active_days=("departure_date", "nunique"),
        arrival_otp15_count=("arrival_otp15", lambda x: x.astype("int64").sum()),
        arrival_delay_mean=("Arrival_Delay_Min", "mean"),
        arrival_delay_median=("Arrival_Delay_Min", "median"),
        arrival_delay_p90=("Arrival_Delay_Min", lambda x: x.quantile(0.90)),
        arrival_delay_p95=("Arrival_Delay_Min", lambda x: x.quantile(0.95)),
        departure_delay_median=("Departure_Delay_Min", "median"),
        recovery_median=("recovery_minutes", "median"),
        scheduled_duration_median=("scheduled_duration_min", "median"),
        schedule_buffer_median=("schedule_buffer_min", "median"),
        recovered_to_otp15_count=(
            "recovered_to_otp15", lambda x: x.astype("int64").sum()
        ),
        worsened_count=(
            "worsened_after_departure", lambda x: x.astype("int64").sum()
        ),
    )
    for threshold in config.delay_thresholds:
        result[f"arrival_delayed_{threshold}_count"] = grouped[
            f"arrival_delayed_{threshold}"
        ].agg(lambda x: x.astype("int64").sum())

    result["arrival_otp15_pct"] = 100 * result["arrival_otp15_count"] / result["flights"]
    for threshold in config.delay_thresholds:
        result[f"arrival_delayed_{threshold}_pct"] = (
            100 * result[f"arrival_delayed_{threshold}_count"] / result["flights"]
        )
    result["worsened_pct"] = 100 * result["worsened_count"] / result["flights"]

    delayed_departure_counts = (
        flights.loc[
            flights["Departure_Delay_Min"].gt(15)
            & flights["Arrival_Delay_Min"].notna()
        ]
        .groupby(groups, observed=True, dropna=False)
        .size()
        .rename("departed_delayed15")
    )
    result = result.join(delayed_departure_counts, how="left")
    result["departed_delayed15"] = result["departed_delayed15"].fillna(0).astype(int)
    result["recovered_to_otp15_pct"] = np.where(
        result["departed_delayed15"] > 0,
        100 * result["recovered_to_otp15_count"] / result["departed_delayed15"],
        np.nan,
    )

    bounds = [
        wilson_interval(successes, observations, config.confidence_level)
        for successes, observations in zip(result["arrival_otp15_count"], result["flights"])
    ]
    result["arrival_otp15_ci_low_pct"] = [100 * item[0] for item in bounds]
    result["arrival_otp15_ci_high_pct"] = [100 * item[1] for item in bounds]
    return result.reset_index().sort_values("flights", ascending=False, ignore_index=True)


def route_performance(
    flights: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    return grouped_performance(flights, ["ADEP", "ADES", "route"], config)


def operator_performance(
    flights: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    result = grouped_performance(flights, "AC Operator", config)
    breadth = flights.groupby("AC Operator", observed=True).agg(
        routes=("route", "nunique"),
        airports=("ADEP", lambda x: len(set(x).union(set(flights.loc[x.index, "ADES"])))),
    )
    concentration = (
        flights.groupby(["AC Operator", "route"], observed=True)
        .size()
        .rename("route_flights")
        .reset_index()
    )
    concentration["operator_flights"] = concentration.groupby(
        "AC Operator", observed=True
    )["route_flights"].transform("sum")
    concentration["share_squared"] = (
        concentration["route_flights"] / concentration["operator_flights"]
    ) ** 2
    hhi = concentration.groupby("AC Operator", observed=True)["share_squared"].sum()
    return (
        result.merge(breadth.reset_index(), on="AC Operator", how="left")
        .merge(hhi.rename("route_concentration_hhi").reset_index(), on="AC Operator", how="left")
        .sort_values("flights", ascending=False, ignore_index=True)
    )


def airport_performance(
    flights: pd.DataFrame,
    role: str,
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    """Calculate reliability separately for origin and destination airports."""

    if role not in {"origin", "destination"}:
        raise ValueError("role must be 'origin' or 'destination'")
    key = "ADEP" if role == "origin" else "ADES"
    result = grouped_performance(flights, key, config).rename(columns={key: "airport"})
    result.insert(0, "role", role)
    return result


def route_threshold_sensitivity(
    routes: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> pd.DataFrame:
    """Show how many routes and flights remain under each executive threshold."""

    config = config or BusinessAnalysisConfig()
    total_routes = len(routes)
    total_flights = routes["flights"].sum()
    rows = []
    for minimum_flights in config.route_volume_candidates:
        for minimum_periods in config.period_candidates:
            eligible = routes.loc[
                routes["flights"].ge(minimum_flights)
                & routes["periods_active"].ge(minimum_periods)
            ]
            rows.append(
                {
                    "minimum_flights": minimum_flights,
                    "minimum_periods": minimum_periods,
                    "eligible_routes": len(eligible),
                    "route_coverage_pct": _percent(len(eligible), total_routes),
                    "covered_flights": int(eligible["flights"].sum()),
                    "flight_coverage_pct": _percent(eligible["flights"].sum(), total_flights),
                }
            )
    return pd.DataFrame(rows)


def executive_route_views(
    routes: pd.DataFrame,
    network_otp15_pct: float,
    config: BusinessAnalysisConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Return high-volume, reliable and problematic route tables."""

    config = config or BusinessAnalysisConfig()
    eligible = routes.loc[
        routes["flights"].ge(config.executive_min_route_flights)
        & routes["periods_active"].ge(config.executive_min_route_periods)
    ].copy()
    if eligible.empty:
        return {"eligible": eligible, "popular_reliable": eligible, "least_reliable": eligible}
    popular_cutoff = eligible["flights"].quantile(0.75)
    eligible["popular"] = eligible["flights"].ge(popular_cutoff)
    eligible["reliably_above_network"] = eligible["arrival_otp15_ci_low_pct"].gt(
        network_otp15_pct
    )
    popular_reliable = eligible.loc[
        eligible["popular"] & eligible["reliably_above_network"]
    ].sort_values(["arrival_otp15_pct", "flights"], ascending=[False, False])
    least_reliable = eligible.sort_values(
        ["arrival_otp15_ci_high_pct", "arrival_delay_p90"],
        ascending=[True, False],
    )
    return {
        "eligible": eligible,
        "popular_reliable": popular_reliable.head(config.top_n),
        "least_reliable": least_reliable.head(config.top_n),
    }


def numeric_correlation_table(
    flights: pd.DataFrame,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return Pearson and Spearman results with pairwise-complete observations."""

    columns = list(columns or [
        "scheduled_duration_min",
        "actual_duration_min",
        "schedule_buffer_min",
        "Actual Distance Flown (nm)",
        "Requested FL",
        "Departure_Delay_Min",
        "Arrival_Delay_Min",
        "recovery_minutes",
    ])
    rows = []
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            pair = flights[[left, right]].dropna()
            if len(pair) < 3 or pair[left].nunique() < 2 or pair[right].nunique() < 2:
                continue
            pearson = stats.pearsonr(pair[left], pair[right])
            spearman = stats.spearmanr(pair[left], pair[right])
            rows.append(
                {
                    "variable_1": left,
                    "variable_2": right,
                    "rows": len(pair),
                    "pearson_r": pearson.statistic,
                    "pearson_p": pearson.pvalue,
                    "spearman_rho": spearman.statistic,
                    "spearman_p": spearman.pvalue,
                }
            )
    return pd.DataFrame(rows)


def two_proportion_z_test(
    successes_a: int,
    observations_a: int,
    successes_b: int,
    observations_b: int,
) -> dict[str, float]:
    """Compare two rates and return both significance and business effect size."""

    if min(observations_a, observations_b) <= 0:
        raise ValueError("Both groups require observations")
    rate_a = successes_a / observations_a
    rate_b = successes_b / observations_b
    pooled = (successes_a + successes_b) / (observations_a + observations_b)
    standard_error = sqrt(pooled * (1 - pooled) * (1 / observations_a + 1 / observations_b))
    z_score = (rate_a - rate_b) / standard_error if standard_error else 0.0
    p_value = 2 * stats.norm.sf(abs(z_score))
    return {
        "rate_a_pct": 100 * rate_a,
        "rate_b_pct": 100 * rate_b,
        "difference_percentage_points": 100 * (rate_a - rate_b),
        "z_score": z_score,
        "p_value": p_value,
    }


def benjamini_hochberg(p_values: Iterable[float]) -> np.ndarray:
    """Control false discoveries when many routes or operators are compared."""

    values = np.asarray(list(p_values), dtype=float)
    if values.size == 0:
        return values
    adjusted = np.full(values.shape, np.nan, dtype=float)
    finite_positions = np.flatnonzero(np.isfinite(values))
    if finite_positions.size == 0:
        return adjusted
    finite_values = values[finite_positions]
    order = np.argsort(finite_values)
    ranked = finite_values[order]
    adjusted_ranked = np.minimum.accumulate(
        (ranked * len(finite_values) / np.arange(1, len(finite_values) + 1))[::-1]
    )[::-1]
    finite_adjusted = np.empty_like(adjusted_ranked)
    finite_adjusted[order] = np.clip(adjusted_ranked, 0, 1)
    adjusted[finite_positions] = finite_adjusted
    return adjusted


def otp15_group_vs_rest_tests(
    performance: pd.DataFrame,
    group_column: str,
    *,
    minimum_flights: int,
    minimum_periods: int = 1,
    practical_difference_pp: float = 3.0,
) -> pd.DataFrame:
    """Compare every eligible group's OTP15 with the rest of the network."""

    eligible = performance.loc[
        performance["flights"].ge(minimum_flights)
        & performance["periods_active"].ge(minimum_periods)
    ].copy()
    total_flights = int(performance["flights"].sum())
    total_successes = int(performance["arrival_otp15_count"].sum())
    rows: list[dict[str, object]] = []
    for _, values in eligible.iterrows():
        group_flights = int(values["flights"])
        group_successes = int(values["arrival_otp15_count"])
        rest_flights = total_flights - group_flights
        rest_successes = total_successes - group_successes
        comparison = two_proportion_z_test(
            group_successes, group_flights, rest_successes, rest_flights
        )
        rows.append({
            group_column: values[group_column],
            "flights": group_flights,
            "periods_active": int(values["periods_active"]),
            "otp15_pct": comparison["rate_a_pct"],
            "rest_of_network_otp15_pct": comparison["rate_b_pct"],
            "difference_percentage_points": comparison["difference_percentage_points"],
            "z_score": comparison["z_score"],
            "p_value": comparison["p_value"],
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["adjusted_p_value"] = benjamini_hochberg(result["p_value"])
    result["statistically_significant"] = result["adjusted_p_value"].lt(0.05)
    result["practically_material"] = result["difference_percentage_points"].abs().ge(
        practical_difference_pp
    )
    result["decision_signal"] = np.select(
        [
            result["statistically_significant"]
            & result["practically_material"]
            & result["difference_percentage_points"].gt(0),
            result["statistically_significant"]
            & result["practically_material"]
            & result["difference_percentage_points"].lt(0),
        ],
        ["reliably_above_network", "reliably_below_network"],
        default="not_material_or_inconclusive",
    )
    return result.sort_values("difference_percentage_points", ascending=False, ignore_index=True)


def weekday_otp15_analysis(
    flights: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return weekday OTP15 estimates and each day-versus-rest test."""

    config = config or BusinessAnalysisConfig()
    observed = flights.loc[flights["Arrival_Delay_Min"].notna()].copy()
    summary = observed.groupby("departure_weekday", observed=True).agg(
        flights=("ECTRL ID", "size"),
        otp15_count=("arrival_otp15", "sum"),
    ).reset_index()
    summary["otp15_pct"] = 100 * summary["otp15_count"] / summary["flights"]
    bounds = [
        wilson_interval(int(successes), int(total), config.confidence_level)
        for successes, total in zip(summary["otp15_count"], summary["flights"])
    ]
    summary["otp15_ci_low_pct"] = [100 * value[0] for value in bounds]
    summary["otp15_ci_high_pct"] = [100 * value[1] for value in bounds]

    total_flights = int(summary["flights"].sum())
    total_successes = int(summary["otp15_count"].sum())
    tests = []
    for row in summary.itertuples(index=False):
        comparison = two_proportion_z_test(
            int(row.otp15_count),
            int(row.flights),
            total_successes - int(row.otp15_count),
            total_flights - int(row.flights),
        )
        tests.append({
            "departure_weekday": str(row.departure_weekday),
            **comparison,
        })
    tests = pd.DataFrame(tests)
    tests["adjusted_p_value"] = benjamini_hochberg(tests["p_value"])
    tests["practically_material"] = tests["difference_percentage_points"].abs().ge(
        config.practical_otp15_difference_pp
    )
    tests["statistically_significant"] = tests["adjusted_p_value"].lt(0.05)
    return summary, tests


def period_otp15_trends(
    flights: pd.DataFrame,
    group_column: str,
    *,
    minimum_flights: int,
    minimum_periods: int = 6,
    practical_total_change_pp: float = 3.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate snapshot-level OTP15 trends using elapsed calendar months."""

    observed = flights.loc[flights["Arrival_Delay_Min"].notna()].copy()
    by_period = observed.groupby([group_column, "period"], observed=True).agg(
        flights=("ECTRL ID", "size"),
        otp15_count=("arrival_otp15", "sum"),
    ).reset_index()
    by_period["otp15_pct"] = 100 * by_period["otp15_count"] / by_period["flights"]
    period_dates = pd.to_datetime(by_period["period"].astype(str) + "-01")
    origin = period_dates.min()
    by_period["elapsed_months"] = (
        (period_dates.dt.year - origin.year) * 12 + period_dates.dt.month - origin.month
    ).astype(float)

    totals = by_period.groupby(group_column, observed=True).agg(
        total_flights=("flights", "sum"),
        periods_active=("period", "nunique"),
    )
    eligible_groups = totals.loc[
        totals["total_flights"].ge(minimum_flights)
        & totals["periods_active"].ge(minimum_periods)
    ].index
    span_months = float(by_period["elapsed_months"].max() - by_period["elapsed_months"].min())
    rows = []
    for group, frame in by_period.loc[by_period[group_column].isin(eligible_groups)].groupby(
        group_column, observed=True
    ):
        fit = stats.linregress(frame["elapsed_months"], frame["otp15_pct"])
        fitted_start = float(np.clip(fit.intercept, 0, 100))
        fitted_end = float(np.clip(fit.intercept + fit.slope * span_months, 0, 100))
        observed_periods = sorted(frame["period"].astype(str).unique())
        rows.append({
            group_column: group,
            "total_flights": int(frame["flights"].sum()),
            "periods_active": int(frame["period"].nunique()),
            "slope_pp_per_year": float(fit.slope * 12),
            "estimated_total_change_pp": fitted_end - fitted_start,
            "fitted_start_otp15_pct": fitted_start,
            "fitted_end_otp15_pct": fitted_end,
            "first_observed_period": observed_periods[0],
            "last_observed_period": observed_periods[-1],
            "extrapolated_to_full_window": observed_periods[0] != "2021-06" or observed_periods[-1] != "2023-06",
            "r_squared": float(fit.rvalue**2),
            "p_value": float(fit.pvalue),
        })
    trends = pd.DataFrame(rows)
    if trends.empty:
        return trends, by_period.iloc[0:0]
    trends["adjusted_p_value"] = benjamini_hochberg(trends["p_value"])
    trends["statistically_significant"] = trends["adjusted_p_value"].lt(0.05)
    trends["practically_material"] = trends["estimated_total_change_pp"].abs().ge(
        practical_total_change_pp
    )
    trends["trend_signal"] = np.select(
        [
            trends["statistically_significant"]
            & trends["practically_material"]
            & trends["estimated_total_change_pp"].lt(0),
            trends["statistically_significant"]
            & trends["practically_material"]
            & trends["estimated_total_change_pp"].gt(0),
        ],
        ["material_deterioration", "material_improvement"],
        default="not_material_or_inconclusive",
    )
    return trends.sort_values("estimated_total_change_pp", ignore_index=True), by_period


def top_airport_leave_one_period_out_alerts(
    flights: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
    top_n: int = 10,
) -> pd.DataFrame:
    """Compare each top-volume origin airport period with its other periods."""

    config = config or BusinessAnalysisConfig()
    observed = flights.loc[flights["Arrival_Delay_Min"].notna()].copy()
    top_airports = observed["ADEP"].value_counts().head(top_n).index
    grouped = observed.loc[observed["ADEP"].isin(top_airports)].groupby(
        ["ADEP", "period"], observed=True
    ).agg(flights=("ECTRL ID", "size"), otp15_count=("arrival_otp15", "sum")).reset_index()
    totals = grouped.groupby("ADEP", observed=True).agg(
        all_flights=("flights", "sum"), all_otp15_count=("otp15_count", "sum")
    ).reset_index()
    result = grouped.merge(totals, on="ADEP", how="left")
    rows = []
    for row in result.itertuples(index=False):
        reference_flights = int(row.all_flights - row.flights)
        reference_successes = int(row.all_otp15_count - row.otp15_count)
        comparison = two_proportion_z_test(
            int(row.otp15_count), int(row.flights), reference_successes, reference_flights
        )
        rows.append({
            "airport": row.ADEP,
            "period": str(row.period),
            "flights": int(row.flights),
            "otp15_pct": comparison["rate_a_pct"],
            "leave_one_period_out_otp15_pct": comparison["rate_b_pct"],
            "difference_percentage_points": comparison["difference_percentage_points"],
            "p_value": comparison["p_value"],
        })
    alerts = pd.DataFrame(rows)
    alerts["adjusted_p_value"] = benjamini_hochberg(alerts["p_value"])
    material = alerts["difference_percentage_points"].abs().ge(
        config.practical_otp15_difference_pp
    ) & alerts["adjusted_p_value"].lt(0.05)
    alerts["status"] = np.select(
        [material & alerts["difference_percentage_points"].lt(0),
         material & alerts["difference_percentage_points"].gt(0)],
        ["red_material_deterioration", "blue_material_improvement"],
        default="grey_not_conclusive",
    )
    alerts.loc[
        alerts["difference_percentage_points"].abs().lt(config.practical_otp15_difference_pp),
        "status",
    ] = "green_within_3pp"
    return alerts.sort_values(["airport", "period"], ignore_index=True)


def hypothesis_test_catalog() -> pd.DataFrame:
    """Document implemented and optional H0 tests before any full-data run."""

    rows = [
        {
            "test_id": "H01",
            "business_question": "Did December punctuality change between 2021 and 2022?",
            "null_hypothesis": "December 2021 and December 2022 have equal arrival OTP15.",
            "method": "Two-proportion z-test",
            "effect_size": "Difference in percentage points",
            "recommendation": "Core report",
            "implementation": "Automated",
        },
        {
            "test_id": "H02",
            "business_question": "Do flights leaving >15 minutes late recover time before arrival?",
            "null_hypothesis": "Median en-route recovery equals zero minutes.",
            "method": "Paired Wilcoxon signed-rank test",
            "effect_size": "Median minutes recovered",
            "recommendation": "Core report",
            "implementation": "Automated",
        },
        {
            "test_id": "H03",
            "business_question": "Does the arrival-delay distribution differ by flight-duration band?",
            "null_hypothesis": "All haul bands have the same arrival-delay distribution.",
            "method": "Kruskal-Wallis test",
            "effect_size": "Epsilon squared",
            "recommendation": "Core report",
            "implementation": "Automated",
        },
        {
            "test_id": "H04",
            "business_question": "Is origin-airport punctuality associated with the airport used?",
            "null_hypothesis": "Arrival OTP15 is independent of origin airport.",
            "method": "Each eligible airport vs rest: two-proportion z + BH",
            "effect_size": "OTP15 difference in percentage points",
            "recommendation": "Core executive comparison",
            "implementation": "Automated",
        },
        {
            "test_id": "H05",
            "business_question": "Is destination-airport punctuality associated with the airport used?",
            "null_hypothesis": "Arrival OTP15 is independent of destination airport.",
            "method": "Each eligible airport vs rest: two-proportion z + BH",
            "effect_size": "OTP15 difference in percentage points",
            "recommendation": "Core executive comparison",
            "implementation": "Automated",
        },
        {
            "test_id": "H06",
            "business_question": "Is punctuality associated with the operating carrier?",
            "null_hypothesis": "Arrival OTP15 is independent of AC Operator.",
            "method": "Each eligible carrier vs rest: two-proportion z + BH",
            "effect_size": "OTP15 difference in percentage points",
            "recommendation": "Descriptive; route mix is a confounder",
            "implementation": "Automated",
        },
        {
            "test_id": "H07",
            "business_question": "Are route reliability rates stable across observed periods?",
            "null_hypothesis": "For each eligible route, OTP15 is equal across periods.",
            "method": "Snapshot-level linear OTP15 slope + Benjamini-Hochberg",
            "effect_size": "Estimated June 2021 to June 2023 change",
            "recommendation": "Require at least six observed periods",
            "implementation": "Automated",
        },
        {
            "test_id": "H08",
            "business_question": "Does OTP15 differ by scheduled departure weekday?",
            "null_hypothesis": "Each weekday has the same OTP15 as the other six days.",
            "method": "Each weekday vs rest: two-proportion z + BH",
            "effect_size": "OTP15 difference in percentage points",
            "recommendation": "Pair with day-by-hour heatmap",
            "implementation": "Automated",
        },
        {
            "test_id": "H09",
            "business_question": "Is scheduled duration monotonically associated with arrival delay?",
            "null_hypothesis": "Spearman rho between duration and arrival delay equals zero.",
            "method": "Spearman rank-correlation test",
            "effect_size": "Spearman rho",
            "recommendation": "Optional; already reported in correlations",
            "implementation": "Available in correlation table",
        },
        {
            "test_id": "H10",
            "business_question": "Do operator differences remain after controlling for route, time and duration?",
            "null_hypothesis": "Adjusted operator effects on P(delay >15) are jointly zero.",
            "method": "Adjusted logistic regression + likelihood-ratio test",
            "effect_size": "Adjusted odds ratios",
            "recommendation": "Best for fair operator comparison",
            "implementation": "Future adjusted analysis",
        },
    ]
    return pd.DataFrame(rows)


def business_hypothesis_tests(flights: pd.DataFrame) -> pd.DataFrame:
    """Run a compact set of interpretable network-level statistical tests."""

    rows: list[dict[str, object]] = []
    periods = flights["period"].astype("string")
    dec_2021 = flights.loc[periods.eq("2021-12") & flights["Arrival_Delay_Min"].notna()]
    dec_2022 = flights.loc[periods.eq("2022-12") & flights["Arrival_Delay_Min"].notna()]
    if len(dec_2021) and len(dec_2022):
        comparison = two_proportion_z_test(
            int(dec_2021["arrival_otp15"].sum()),
            len(dec_2021),
            int(dec_2022["arrival_otp15"].sum()),
            len(dec_2022),
        )
        rows.append(
            {
                "test": "December OTP15 equality",
                "test_id": "H01",
                "null_hypothesis": "December 2021 and December 2022 have equal OTP15",
                "statistic": comparison["z_score"],
                "p_value": comparison["p_value"],
                "effect": comparison["difference_percentage_points"],
                "effect_unit": "percentage points (2021 minus 2022)",
            }
        )

    recovery = flights.loc[
        flights["Departure_Delay_Min"].gt(15), "recovery_minutes"
    ].dropna()
    if len(recovery) >= 10 and not np.allclose(recovery, 0):
        wilcoxon = stats.wilcoxon(recovery, alternative="two-sided")
        rows.append(
            {
                "test": "En-route recovery",
                "test_id": "H02",
                "null_hypothesis": "Median recovery is zero for flights departing >15 min late",
                "statistic": wilcoxon.statistic,
                "p_value": wilcoxon.pvalue,
                "effect": recovery.median(),
                "effect_unit": "median minutes recovered",
            }
        )

    haul_groups = [
        group["Arrival_Delay_Min"].dropna().to_numpy()
        for _, group in flights.groupby("haul_band", observed=True)
        if group["Arrival_Delay_Min"].notna().sum() >= 10
    ]
    if len(haul_groups) >= 2:
        kruskal = stats.kruskal(*haul_groups)
        total = sum(len(group) for group in haul_groups)
        epsilon_squared = max(0.0, (kruskal.statistic - len(haul_groups) + 1) / (total - len(haul_groups)))
        rows.append(
            {
                "test": "Delay equality across haul bands",
                "test_id": "H03",
                "null_hypothesis": "Arrival-delay distributions are equal across duration bands",
                "statistic": kruskal.statistic,
                "p_value": kruskal.pvalue,
                "effect": epsilon_squared,
                "effect_unit": "Kruskal-Wallis epsilon squared",
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result["p_value_bh"] = benjamini_hochberg(result["p_value"])
    return result


def load_dimension_labels(raw_icao_root: Path | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load readable airport and operator labels for report tables."""

    root = Path(raw_icao_root)
    airports = (
        pd.read_csv(root / "airports.csv", usecols=["ICAO", "Airport name", "Country", "City"])
        .dropna(subset=["ICAO"])
        .drop_duplicates("ICAO")
        .rename(columns={"ICAO": "airport_code"})
    )
    airlines = (
        pd.read_csv(root / "airlines.csv", usecols=["3Ltr", "Company", "Country"])
        .dropna(subset=["3Ltr"])
        .drop_duplicates("3Ltr")
        .rename(columns={"3Ltr": "AC Operator", "Company": "operator_name", "Country": "operator_country"})
    )
    return airports, airlines


def enrich_route_labels(routes: pd.DataFrame, airports: pd.DataFrame) -> pd.DataFrame:
    """Attach airport, city and country names to directional route metrics."""

    origin = airports.add_prefix("origin_").rename(columns={"origin_airport_code": "ADEP"})
    destination = airports.add_prefix("destination_").rename(columns={"destination_airport_code": "ADES"})
    return routes.merge(origin, on="ADEP", how="left").merge(destination, on="ADES", how="left")


def apply_business_plot_style() -> None:
    """Apply the white, light-blue and green report style."""

    sns.set_theme(style="whitegrid", palette=STANDARD_PALETTE)
    plt.rcParams.update(
        {
            "font.family": "Calibri",
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.titleweight": "bold",
            "axes.labelsize": 12,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "axes.edgecolor": BUSINESS_LIGHT_BLUE,
            "grid.color": "#E8EEF3",
            "legend.frameon": False,
        }
    )


def _route_plot_frame(
    routes: pd.DataFrame,
    config: BusinessAnalysisConfig,
    *,
    executive: bool,
) -> pd.DataFrame:
    """Apply the universal two-flight rule and optional executive thresholds."""

    eligible = routes.loc[routes["flights"].ge(config.route_plot_min_flights)].copy()
    if executive:
        eligible = eligible.loc[
            eligible["flights"].ge(config.executive_min_route_flights)
            & eligible["periods_active"].ge(config.executive_min_route_periods)
        ]
        eligible = eligible.nlargest(config.route_plot_top_n, "flights")
    return eligible


def plot_route_volume_reliability(
    routes: pd.DataFrame,
    network_otp15_pct: float,
    config: BusinessAnalysisConfig | None = None,
) -> plt.Figure:
    """Plot route popularity against reliability with executive thresholds."""

    config = config or BusinessAnalysisConfig()
    apply_business_plot_style()
    eligible = _route_plot_frame(routes, config, executive=True)
    fig, ax = plt.subplots(figsize=(11, 7))
    if not eligible.empty:
        size = np.clip(eligible["arrival_delay_p90"].fillna(0), 5, 90) * 5
        scatter = ax.scatter(
            eligible["flights"],
            eligible["arrival_otp15_pct"],
            s=size,
            c=eligible["arrival_delayed_30_pct"],
            cmap="YlGnBu_r",
            alpha=0.75,
            edgecolor="white",
            linewidth=0.5,
        )
        fig.colorbar(scatter, ax=ax, label="Flights delayed >30 min (%)")
        popular_cutoff = eligible["flights"].quantile(0.75)
        ax.axvline(popular_cutoff, color=BUSINESS_GREY, linestyle="--", label="Top-volume quartile")
    ax.axhline(network_otp15_pct, color=BUSINESS_GREEN, linestyle="--", label="Network OTP15")
    ax.set_xscale("log")
    ax.set_xlabel("Operated flights (log scale)")
    ax.set_ylabel("Arrival OTP15 (%)")
    ax.set_title("Route popularity and arrival reliability")
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


def plot_top_route_comparison(
    routes: pd.DataFrame,
    config: BusinessAnalysisConfig | None = None,
) -> plt.Figure:
    """Show volume and delay severity for the most-operated routes."""

    config = config or BusinessAnalysisConfig()
    apply_business_plot_style()
    eligible = _route_plot_frame(routes, config, executive=True)
    top = eligible.nlargest(config.top_n, "flights").sort_values("flights")
    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 8), sharey=True)
    left.barh(top["route"].astype(str), top["flights"], color=BUSINESS_BLUE)
    left.set_title("Most-operated routes")
    left.set_xlabel("Flights")
    right.barh(top["route"].astype(str), top["arrival_delayed_15_pct"], color=BUSINESS_GREEN)
    right.set_title("Delay rate on the same routes")
    right.set_xlabel("Arrivals delayed >15 min (%)")
    fig.tight_layout()
    return fig


def plot_airport_volume_reliability(
    airports: pd.DataFrame,
    role: str,
    network_otp15_pct: float,
    config: BusinessAnalysisConfig | None = None,
) -> plt.Figure:
    """Show airport scale, reliability and severe-delay exposure by role."""

    config = config or BusinessAnalysisConfig()
    if role not in {"origin", "destination"}:
        raise ValueError("role must be 'origin' or 'destination'")
    apply_business_plot_style()
    eligible = airports.loc[
        airports["flights"].ge(config.airport_plot_min_flights)
        & airports["periods_active"].ge(config.executive_min_airport_periods)
    ].nlargest(config.airport_plot_top_n, "flights").copy()
    fig, ax = plt.subplots(figsize=(11, 7))
    if not eligible.empty:
        size = np.clip(eligible["arrival_delay_p90"].fillna(0), 5, 90) * 5
        scatter = ax.scatter(
            eligible["flights"],
            eligible["arrival_otp15_pct"],
            s=size,
            c=eligible["arrival_delayed_30_pct"],
            cmap="YlGnBu_r",
            alpha=0.78,
            edgecolor="white",
            linewidth=0.5,
        )
        fig.colorbar(scatter, ax=ax, label="Flights delayed >30 min (%)")
        label_candidates = pd.concat(
            [
                eligible.nlargest(4, "flights"),
                eligible.nsmallest(3, "arrival_otp15_ci_high_pct"),
                eligible.nlargest(3, "arrival_otp15_ci_low_pct"),
            ]
        ).drop_duplicates("airport")
        for row in label_candidates.itertuples(index=False):
            ax.annotate(
                str(row.airport),
                (row.flights, row.arrival_otp15_pct),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=9,
            )
    ax.axhline(network_otp15_pct, color=BUSINESS_GREEN, linestyle="--", label="Network OTP15")
    ax.set_xscale("log")
    ax.set_xlabel("Operated flights (log scale)")
    ax.set_ylabel("Arrival OTP15 (%)")
    role_label = "Origin" if role == "origin" else "Destination"
    ax.set_title(f"{role_label} airport volume and reliability")
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


def plot_airport_reliability_rankings(
    airports: pd.DataFrame,
    role: str,
    config: BusinessAnalysisConfig | None = None,
) -> plt.Figure:
    """Compare most and least reliable airports using Wilson intervals."""

    config = config or BusinessAnalysisConfig()
    if role not in {"origin", "destination"}:
        raise ValueError("role must be 'origin' or 'destination'")
    apply_business_plot_style()
    eligible = airports.loc[
        airports["flights"].ge(config.executive_min_airport_flights)
        & airports["periods_active"].ge(config.executive_min_airport_periods)
    ].copy()
    # Sort by the same conservative Wilson bound used for selection.  With a
    # horizontal categorical axis, the final row is rendered at the top.
    reliable = eligible.nlargest(10, "arrival_otp15_ci_low_pct").sort_values(
        "arrival_otp15_ci_low_pct"
    )
    problematic = eligible.nsmallest(10, "arrival_otp15_ci_high_pct").sort_values(
        "arrival_otp15_ci_high_pct", ascending=False
    )
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, data, title, color in (
        (axes[0], reliable, "Most reliably above target", BUSINESS_GREEN),
        (axes[1], problematic, "Most reliably problematic", BUSINESS_BLUE),
    ):
        # Wilson contains the point estimate; clip only floating-point residue
        # such as 100.0 - 100.00000000000001 before passing it to Matplotlib.
        lower_error = np.maximum(
            data["arrival_otp15_pct"] - data["arrival_otp15_ci_low_pct"], 0.0
        )
        upper_error = np.maximum(
            data["arrival_otp15_ci_high_pct"] - data["arrival_otp15_pct"], 0.0
        )
        ax.errorbar(
            data["arrival_otp15_pct"],
            data["airport"].astype(str),
            xerr=np.vstack([lower_error, upper_error]),
            fmt="o",
            color=color,
            ecolor=BUSINESS_GREY,
            capsize=3,
        )
        for row in data.itertuples(index=False):
            ax.annotate(
                f"n={int(row.flights):,}",
                (row.arrival_otp15_ci_high_pct, str(row.airport)),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=8,
                color=BUSINESS_GREY,
            )
        ax.set_xlabel("Arrival OTP15 with 95% Wilson interval (%)")
        ax.set_title(title)
    role_label = "origin" if role == "origin" else "destination"
    fig.suptitle(f"Most and least reliable {role_label} airports", color=BUSINESS_DARK_BLUE)
    fig.tight_layout()
    return fig


def plot_time_reliability_heatmap(flights: pd.DataFrame) -> plt.Figure:
    """Show when the network is least reliable."""

    apply_business_plot_style()
    heatmap = flights.pivot_table(
        index="departure_weekday",
        columns="departure_hour",
        values="arrival_otp15",
        aggfunc="mean",
        observed=True,
    ) * 100
    fig, ax = plt.subplots(figsize=(14, 6))
    sns.heatmap(heatmap, cmap="YlGnBu", vmin=60, vmax=100, ax=ax, cbar_kws={"label": "OTP15 (%)"})
    ax.set_title("Arrival punctuality by scheduled departure day and hour")
    ax.set_xlabel("Scheduled departure hour")
    ax.set_ylabel("")
    fig.tight_layout()
    return fig


def plot_weekday_otp15_performance(
    summary: pd.DataFrame,
    network_otp15_pct: float,
) -> plt.Figure:
    """Show weekday OTP15 with Wilson intervals and the network reference."""

    apply_business_plot_style()
    frame = summary.copy()
    labels = frame["departure_weekday"].astype(str)
    lower = np.maximum(frame["otp15_pct"] - frame["otp15_ci_low_pct"], 0)
    upper = np.maximum(frame["otp15_ci_high_pct"] - frame["otp15_pct"], 0)
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    bars = ax.bar(labels, frame["otp15_pct"], color=BUSINESS_BLUE, alpha=0.88)
    ax.errorbar(
        labels,
        frame["otp15_pct"],
        yerr=np.vstack([lower, upper]),
        fmt="none",
        ecolor=BUSINESS_DARK_BLUE,
        capsize=4,
    )
    ax.axhline(network_otp15_pct, color=BUSINESS_GREEN, linestyle="--", label="Network OTP15")
    ax.set_ylim(max(0, frame["otp15_pct"].min() - 4), min(100, frame["otp15_pct"].max() + 3))
    ax.set_xlabel("Scheduled departure weekday")
    ax.set_ylabel("Arrival OTP15 (%)")
    ax.set_title("Weekday punctuality with 95% Wilson intervals")
    for bar, value in zip(bars, frame["otp15_pct"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + .25, f"{value:.1f}%", ha="center", fontsize=9)
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig


def plot_otp15_trend_extremes(
    trends: pd.DataFrame,
    group_column: str,
    title: str,
    top_n: int = 3,
    volume_pool: int | None = None,
) -> plt.Figure:
    """Plot only the three largest estimated improvements and deteriorations."""

    apply_business_plot_style()
    candidates = trends.copy()
    if volume_pool is not None:
        candidates = candidates.nlargest(volume_pool, "total_flights")
    decision_relevant = candidates.loc[
        candidates["trend_signal"].isin(["material_deterioration", "material_improvement"])
    ]
    deteriorated = decision_relevant.loc[
        decision_relevant["trend_signal"].eq("material_deterioration")
    ].nsmallest(top_n, "estimated_total_change_pp")
    improved = decision_relevant.loc[
        decision_relevant["trend_signal"].eq("material_improvement")
    ].nlargest(top_n, "estimated_total_change_pp")
    frame = pd.concat([deteriorated, improved]).drop_duplicates(group_column)
    frame = frame.sort_values("estimated_total_change_pp")
    colors = [
        "#C00000" if signal == "material_deterioration"
        else BUSINESS_GREEN if signal == "material_improvement"
        else "#A5A5A5"
        for signal in frame["trend_signal"]
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    if frame.empty:
        ax.text(.5, .5, "No group passes both the adjusted-p and ±3 pp decision thresholds.",
                transform=ax.transAxes, ha="center", va="center", color=BUSINESS_GREY)
        ax.set_axis_off()
        ax.set_title(title)
        fig.tight_layout()
        return fig
    bars = ax.barh(frame[group_column].astype(str), frame["estimated_total_change_pp"], color=colors)
    ax.axvline(0, color=BUSINESS_GREY, linewidth=1)
    ax.axvline(-3, color="#C00000", linestyle="--", linewidth=1, label="±3 pp material threshold")
    ax.axvline(3, color=BUSINESS_GREEN, linestyle="--", linewidth=1)
    ax.set_xlabel("Estimated OTP15 change, June 2021 to June 2023 (percentage points)")
    if improved.empty and not deteriorated.empty:
        display_title = title.replace("improvements and deteriorations", "material deteriorations")
    elif deteriorated.empty and not improved.empty:
        display_title = title.replace("improvements and deteriorations", "material improvements")
    else:
        display_title = title
    ax.set_title(display_title)
    xmin, xmax = ax.get_xlim()
    span = xmax - xmin
    for bar, (_, row) in zip(bars, frame.iterrows()):
        value = row["estimated_total_change_pp"]
        marker = "*" if row["statistically_significant"] and row["practically_material"] else ""
        label = f"{value:+.1f} pp{marker} · n={int(row['total_flights']):,}"
        if value < 0:
            x = min(-0.7, value + 0.04 * span)
            ha = "left"
        else:
            x = max(0.7, value - 0.04 * span)
            ha = "right"
        ax.text(
            x,
            bar.get_y() + bar.get_height()/2,
            label,
            va="center",
            ha=ha,
            fontsize=9,
            color="white" if abs(value) > 0.15 * span else BUSINESS_GREY,
        )
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    return fig


def plot_top_airport_period_alerts(alerts: pd.DataFrame) -> plt.Figure:
    """Plot leave-one-period-out OTP15 differences for ten busy airports."""

    apply_business_plot_style()
    matrix = alerts.pivot(index="airport", columns="period", values="difference_percentage_points")
    status = alerts.pivot(index="airport", columns="period", values="status").reindex_like(matrix)
    annotation = matrix.map(lambda value: f"{value:+.1f}" if pd.notna(value) else "")
    for airport in matrix.index:
        for period in matrix.columns:
            if status.loc[airport, period] in {
                "red_material_deterioration", "blue_material_improvement"
            }:
                annotation.loc[airport, period] += "*"
    status_to_code = {
        "red_material_deterioration": 0,
        "blue_material_improvement": 1,
        "green_within_3pp": 2,
        "grey_not_conclusive": 3,
    }
    status_codes = status.map(status_to_code.get).astype(float)
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(13, 6.5))
    sns.heatmap(
        status_codes,
        cmap=ListedColormap(["#C00000", BUSINESS_BLUE, BUSINESS_GREEN, "#A5A5A5"]),
        vmin=0,
        vmax=3,
        annot=annotation,
        fmt="",
        linewidths=.5,
        linecolor="white",
        cbar=False,
        ax=ax,
    )
    ax.set_title("Top-10 origin-airport alerts versus leave-one-period-out history")
    ax.set_xlabel("Observed monthly snapshot")
    ax.set_ylabel("Origin airport")
    ax.legend(handles=[
        Patch(color="#C00000", label="Material deterioration"),
        Patch(color=BUSINESS_BLUE, label="Material improvement"),
        Patch(color=BUSINESS_GREEN, label="Within ±3 pp"),
        Patch(color="#A5A5A5", label="Inconclusive"),
    ], frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(.5, -0.14))
    fig.tight_layout()
    return fig


def plot_departure_arrival_recovery(flights: pd.DataFrame) -> plt.Figure:
    """Explain how departure delay propagates into arrival delay."""

    apply_business_plot_style()
    values = flights[["Departure_Delay_Min", "Arrival_Delay_Min"]].dropna()
    quantiles = values.quantile([0.01, 0.99])
    lower = quantiles.loc[0.01]
    upper = quantiles.loc[0.99]
    fig, ax = plt.subplots(figsize=(8, 7))
    hb = ax.hexbin(
        values["Departure_Delay_Min"],
        values["Arrival_Delay_Min"],
        gridsize=55,
        mincnt=1,
        cmap="Blues",
        extent=[lower.iloc[0], upper.iloc[0], lower.iloc[1], upper.iloc[1]],
    )
    diagonal_min = min(lower.iloc[0], lower.iloc[1])
    diagonal_max = max(upper.iloc[0], upper.iloc[1])
    ax.plot([diagonal_min, diagonal_max], [diagonal_min, diagonal_max], color=BUSINESS_GREEN, linestyle="--")
    ax.set_xlabel("Departure delay (min)")
    ax.set_ylabel("Arrival delay (min)")
    ax.set_title("Delay propagation and recovery")
    fig.colorbar(hb, ax=ax, label="Flights per hexagon")
    fig.tight_layout()
    return fig


def plot_statistical_method_explainer() -> plt.Figure:
    """Create a report-ready visual explaining thresholds, intervals and tests."""

    apply_business_plot_style()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))

    axes[0].axvspan(-20, 15, color=BUSINESS_LIGHT_BLUE)
    axes[0].axvspan(15, 60, color="#FCE4D6")
    axes[0].axvspan(60, 100, color="#F4CCCC")
    axes[0].axvline(15, color=BUSINESS_DARK_BLUE, linestyle="--")
    axes[0].set_xlim(-20, 100)
    axes[0].set_yticks([])
    axes[0].set_xlabel("Arrival delay (minutes)")
    axes[0].set_title("1. OTP15 threshold")
    axes[0].text(-2, 0.5, "On time", ha="center")
    axes[0].text(37, 0.5, "Delayed", ha="center")

    points = [72, 78, 84]
    errors = [9, 4, 2]
    labels = ["25 flights", "250 flights", "2,500 flights"]
    axes[1].errorbar(points, range(3), xerr=errors, fmt="o", color=BUSINESS_BLUE, ecolor=BUSINESS_GREEN, capsize=5)
    axes[1].set_yticks(range(3), labels)
    axes[1].set_xlabel("Estimated OTP15 (%)")
    axes[1].set_title("2. Wilson uncertainty")
    axes[1].text(0.5, -0.28, "More flights → narrower interval", transform=axes[1].transAxes, ha="center")

    axes[2].axvline(0, color=BUSINESS_GREY)
    x = np.linspace(-4, 4, 300)
    density = np.exp(-(x**2) / 2)
    axes[2].plot(x, density, color=BUSINESS_BLUE)
    axes[2].fill_between(x, 0, density, where=np.abs(x) >= 1.96, color=BUSINESS_GREEN, alpha=0.6)
    axes[2].set_yticks([])
    axes[2].set_xlabel("Difference under H0")
    axes[2].set_title("3. Statistical test")
    axes[2].text(0.5, -0.28, "Report effect size and p-value", transform=axes[2].transAxes, ha="center")

    fig.suptitle("How the business reliability charts are constructed", color=BUSINESS_DARK_BLUE, fontsize=17, fontweight="bold")
    fig.tight_layout()
    return fig


def save_figure(figure: plt.Figure, path: Path | str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return destination


def export_business_analysis(
    flights: pd.DataFrame,
    output_root: Path | str,
    config: BusinessAnalysisConfig | None = None,
) -> dict[str, object]:
    """Calculate, export and plot the core business analysis."""

    config = config or BusinessAnalysisConfig()
    root = Path(output_root)
    tables = root / "tables"
    figures = root / "figures"
    tests_root = root / "statistical_tests"
    for directory in (tables, figures, tests_root):
        directory.mkdir(parents=True, exist_ok=True)

    kpis = overall_kpis(flights, config)
    routes = route_performance(flights, config)
    operators = operator_performance(flights, config)
    origin_airports = airport_performance(flights, "origin", config)
    destination_airports = airport_performance(flights, "destination", config)
    sensitivity = route_threshold_sensitivity(routes, config)
    correlations = numeric_correlation_table(flights)
    test_catalog = hypothesis_test_catalog()
    hypothesis_tests = business_hypothesis_tests(flights)
    route_views = executive_route_views(routes, float(kpis["arrival_otp15_pct"]), config)
    origin_airport_tests = otp15_group_vs_rest_tests(
        origin_airports,
        "airport",
        minimum_flights=config.executive_min_airport_flights,
        minimum_periods=config.executive_min_airport_periods,
        practical_difference_pp=config.practical_otp15_difference_pp,
    )
    destination_airport_tests = otp15_group_vs_rest_tests(
        destination_airports,
        "airport",
        minimum_flights=config.executive_min_airport_flights,
        minimum_periods=config.executive_min_airport_periods,
        practical_difference_pp=config.practical_otp15_difference_pp,
    )
    operator_tests = otp15_group_vs_rest_tests(
        operators,
        "AC Operator",
        minimum_flights=config.executive_min_operator_flights,
        minimum_periods=3,
        practical_difference_pp=config.practical_otp15_difference_pp,
    )
    weekday_summary, weekday_tests = weekday_otp15_analysis(flights, config)
    airport_trends, airport_trend_periods = period_otp15_trends(
        flights,
        "ADEP",
        minimum_flights=config.executive_min_airport_flights,
        minimum_periods=config.trend_min_periods,
        practical_total_change_pp=config.practical_otp15_difference_pp,
    )
    named_operator_flights = flights.loc[
        ~flights["AC Operator"].astype(str).isin(["ZZZ", "Unknown", "UNKNOWN", "UNK"])
    ]
    operator_trends, operator_trend_periods = period_otp15_trends(
        named_operator_flights,
        "AC Operator",
        minimum_flights=config.executive_min_operator_flights,
        minimum_periods=config.trend_min_periods,
        practical_total_change_pp=config.practical_otp15_difference_pp,
    )
    route_trends, route_trend_periods = period_otp15_trends(
        flights,
        "route",
        minimum_flights=max(config.executive_min_route_flights, 200),
        minimum_periods=config.trend_min_periods,
        practical_total_change_pp=config.practical_otp15_difference_pp,
    )
    airport_alerts = top_airport_leave_one_period_out_alerts(flights, config, top_n=10)

    kpis.to_frame().to_csv(tables / "network_kpis.csv")
    routes.to_csv(tables / "route_performance.csv", index=False)
    operators.to_csv(tables / "operator_performance.csv", index=False)
    origin_airports.to_csv(tables / "origin_airport_performance.csv", index=False)
    destination_airports.to_csv(tables / "destination_airport_performance.csv", index=False)
    sensitivity.to_csv(tables / "route_threshold_sensitivity.csv", index=False)
    route_views["popular_reliable"].to_csv(tables / "popular_reliable_routes.csv", index=False)
    route_views["least_reliable"].to_csv(tables / "least_reliable_routes.csv", index=False)
    correlations.to_csv(tests_root / "numeric_correlations.csv", index=False)
    test_catalog.to_csv(tests_root / "hypothesis_test_catalog.csv", index=False)
    hypothesis_tests.to_csv(tests_root / "hypothesis_tests.csv", index=False)
    origin_airport_tests.to_csv(tests_root / "origin_airport_vs_rest_otp15_tests.csv", index=False)
    destination_airport_tests.to_csv(tests_root / "destination_airport_vs_rest_otp15_tests.csv", index=False)
    operator_tests.to_csv(tests_root / "operator_vs_rest_otp15_tests.csv", index=False)
    weekday_tests.to_csv(tests_root / "weekday_vs_rest_otp15_tests.csv", index=False)
    weekday_summary.to_csv(tables / "weekday_network_performance.csv", index=False)
    airport_trends.to_csv(tables / "origin_airport_otp15_trends.csv", index=False)
    airport_trend_periods.to_csv(tables / "origin_airport_period_performance.csv", index=False)
    operator_trends.to_csv(tables / "operator_otp15_trends.csv", index=False)
    operator_trend_periods.to_csv(tables / "operator_period_performance.csv", index=False)
    route_trends.to_csv(tables / "route_otp15_trends.csv", index=False)
    route_trend_periods.to_csv(tables / "route_period_performance.csv", index=False)
    airport_alerts.to_csv(tables / "top10_origin_airport_period_alerts.csv", index=False)

    save_figure(
        plot_route_volume_reliability(routes, float(kpis["arrival_otp15_pct"]), config),
        figures / "route_volume_reliability.png",
    )
    save_figure(plot_top_route_comparison(routes, config), figures / "top_route_comparison.png")
    save_figure(
        plot_airport_volume_reliability(
            origin_airports, "origin", float(kpis["arrival_otp15_pct"]), config
        ),
        figures / "origin_airport_volume_reliability.png",
    )
    save_figure(
        plot_airport_reliability_rankings(origin_airports, "origin", config),
        figures / "origin_airport_reliability_rankings.png",
    )
    save_figure(
        plot_airport_volume_reliability(
            destination_airports, "destination", float(kpis["arrival_otp15_pct"]), config
        ),
        figures / "destination_airport_volume_reliability.png",
    )
    save_figure(
        plot_airport_reliability_rankings(destination_airports, "destination", config),
        figures / "destination_airport_reliability_rankings.png",
    )
    save_figure(plot_time_reliability_heatmap(flights), figures / "time_reliability_heatmap.png")
    save_figure(
        plot_weekday_otp15_performance(weekday_summary, float(kpis["arrival_otp15_pct"])),
        figures / "weekday_otp15_performance.png",
    )
    save_figure(
        plot_otp15_trend_extremes(
            airport_trends, "ADEP", "Top-3 origin-airport OTP15 improvements and deteriorations",
            volume_pool=200,
        ),
        figures / "origin_airport_otp15_trend_extremes.png",
    )
    save_figure(
        plot_otp15_trend_extremes(
            operator_trends, "AC Operator", "Top-3 operating-carrier OTP15 improvements and deteriorations",
            volume_pool=100,
        ),
        figures / "operator_otp15_trend_extremes.png",
    )
    save_figure(
        plot_otp15_trend_extremes(
            route_trends, "route", "Top-3 route OTP15 improvements and deteriorations",
            volume_pool=500,
        ),
        figures / "route_otp15_trend_extremes.png",
    )
    save_figure(
        plot_top_airport_period_alerts(airport_alerts),
        figures / "top10_origin_airport_period_alerts.png",
    )
    save_figure(plot_departure_arrival_recovery(flights), figures / "departure_arrival_recovery.png")
    save_figure(plot_statistical_method_explainer(), figures / "statistical_method_explainer.png")

    return {
        "kpis": kpis,
        "routes": routes,
        "operators": operators,
        "origin_airports": origin_airports,
        "destination_airports": destination_airports,
        "threshold_sensitivity": sensitivity,
        "correlations": correlations,
        "hypothesis_test_catalog": test_catalog,
        "hypothesis_tests": hypothesis_tests,
        "origin_airport_tests": origin_airport_tests,
        "destination_airport_tests": destination_airport_tests,
        "operator_tests": operator_tests,
        "weekday_summary": weekday_summary,
        "weekday_tests": weekday_tests,
        "airport_trends": airport_trends,
        "operator_trends": operator_trends,
        "route_trends": route_trends,
        "airport_alerts": airport_alerts,
        "route_views": route_views,
        "output_root": root,
        "memory_mb": flights.memory_usage(deep=True).sum() / 1024**2,
    }
