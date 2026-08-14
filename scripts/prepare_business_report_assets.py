"""Create the additional tables and figures for the full business report."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.business_eda import (  # noqa: E402
    RAW_COLUMNS,
    BusinessAnalysisConfig,
    benjamini_hochberg,
    development_flight_paths,
    period_otp15_trends,
    plot_otp15_trend_extremes,
    plot_top_airport_period_alerts,
    plot_weekday_otp15_performance,
    prepare_business_flights,
    read_business_flights,
    save_figure,
    top_airport_leave_one_period_out_alerts,
    two_proportion_z_test,
    weekday_otp15_analysis,
)
from src.flight_data_catalog import discover_monthly_flights  # noqa: E402


SOURCE = ROOT / "reports" / "business_eda"
OUTPUT = ROOT / "reports" / "business_report_full"
TABLES = OUTPUT / "tables"
FIGURES = OUTPUT / "figures"
BLUE = "#5B9BD5"
LIGHT_BLUE = "#D9EAF7"
GREEN = "#70AD47"
DARK_BLUE = "#1F4E78"
GREY = "#667085"
LIGHT_GREY = "#E7EDF3"
ORANGE = "#ED7D31"
WORLD_GEOJSON = ROOT / "data" / "raw" / "icao" / "ne_110m_admin_0_countries.geojson"
RYANAIR_CODES = {"RYR", "RYS", "RUK"}
WIZZ_CODES = {"WZZ", "WUK", "WMT", "WAZ"}
MILAN_AIRPORTS = {"LIMC", "LIML", "LIME"}
PASSENGER_MARKET_SEGMENTS = {"Mainline", "Lowcost", "Regional Aircraft"}


def wilson(successes: pd.Series, totals: pd.Series, z: float = 1.95996398454):
    n = totals.astype(float)
    p = successes.astype(float) / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return 100 * (centre - margin), 100 * (centre + margin)


def save_table(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    TABLES.mkdir(parents=True, exist_ok=True)
    frame.to_csv(TABLES / name, index=False)
    return frame


def style_axes(ax):
    ax.set_facecolor("white")
    ax.grid(axis="x", color="#D9D9D9", linewidth=0.7, alpha=0.75)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=GREY, labelsize=9)


def draw_greyscale_basemap(ax) -> None:
    """Draw Natural Earth country polygons without adding GIS dependencies."""

    world = json.loads(WORLD_GEOJSON.read_text(encoding="utf-8"))
    for feature in world["features"]:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
        for polygon in polygons:
            if not polygon:
                continue
            exterior = polygon[0]
            if len(exterior) < 3:
                continue
            longitude, latitude = zip(*exterior)
            ax.fill(
                longitude,
                latitude,
                facecolor="#E3E3E3",
                edgecolor="#B8B8B8",
                linewidth=0.35,
                zorder=0,
            )


def load_airport_dimension() -> pd.DataFrame:
    source = pd.read_csv(ROOT / "data" / "raw" / "icao" / "airports2.csv", low_memory=False)
    coords = source["coordinates"].astype("string").str.split(",", n=1, expand=True)
    source["latitude"] = pd.to_numeric(coords[0], errors="coerce")
    source["longitude"] = pd.to_numeric(coords[1], errors="coerce")
    candidates = []
    for priority, code_column in enumerate(("icao_code", "gps_code", "ident")):
        part = source[[code_column, "name", "iso_country", "municipality", "latitude", "longitude"]].copy()
        part = part.rename(columns={code_column: "airport"})
        part["priority"] = priority
        candidates.append(part)
    dimension = pd.concat(candidates, ignore_index=True)
    dimension["airport"] = dimension["airport"].astype("string").str.strip()
    dimension = dimension.dropna(subset=["airport"]).sort_values("priority")
    dimension = dimension.drop_duplicates("airport", keep="first")

    names = pd.read_csv(ROOT / "data" / "raw" / "icao" / "airports.csv", low_memory=False)
    names = names[["ICAO", "Country", "City"]].dropna(subset=["ICAO"]).drop_duplicates("ICAO")
    dimension = dimension.merge(names, left_on="airport", right_on="ICAO", how="left")
    dimension["country"] = dimension["Country"].fillna(dimension["iso_country"]).fillna("Unknown")
    dimension["city"] = dimension["City"].fillna(dimension["municipality"]).fillna("")
    return dimension.drop(columns=["priority", "ICAO", "Country", "City"], errors="ignore")


def airport_and_country_tables() -> dict[str, pd.DataFrame]:
    origin = pd.read_csv(SOURCE / "tables" / "origin_airport_performance.csv")
    destination = pd.read_csv(SOURCE / "tables" / "destination_airport_performance.csv")
    dimension = load_airport_dimension()

    origin = origin.rename(columns={
        "flights": "departures",
        "arrival_otp15_count": "origin_otp15_count",
        "arrival_delayed_15_count": "origin_delayed15_count",
        "arrival_delay_mean": "origin_arrival_delay_mean",
        "arrival_otp15_pct": "origin_arrival_otp15_pct",
    })
    destination = destination.rename(columns={
        "flights": "arrivals",
        "arrival_otp15_count": "destination_otp15_count",
        "arrival_delayed_15_count": "destination_delayed15_count",
        "arrival_delay_mean": "destination_arrival_delay_mean",
        "arrival_otp15_pct": "destination_arrival_otp15_pct",
    })
    keep_o = ["airport", "departures", "periods_active", "origin_otp15_count",
              "origin_delayed15_count", "origin_arrival_delay_mean", "origin_arrival_otp15_pct"]
    keep_d = ["airport", "arrivals", "periods_active", "destination_otp15_count",
              "destination_delayed15_count", "destination_arrival_delay_mean", "destination_arrival_otp15_pct"]
    combined = origin[keep_o].rename(columns={"periods_active": "origin_periods"}).merge(
        destination[keep_d].rename(columns={"periods_active": "destination_periods"}),
        on="airport", how="outer",
    )
    numeric = combined.select_dtypes(include="number").columns
    combined[numeric] = combined[numeric].fillna(0)
    combined["total_movements"] = combined["departures"] + combined["arrivals"]
    combined["otp15_count"] = combined["origin_otp15_count"] + combined["destination_otp15_count"]
    combined["delayed15_count"] = combined["origin_delayed15_count"] + combined["destination_delayed15_count"]
    combined["otp15_pct"] = 100 * combined["otp15_count"] / combined["total_movements"]
    combined["delayed15_pct"] = 100 * combined["delayed15_count"] / combined["total_movements"]
    combined["arrival_delay_minutes_net"] = (
        combined["departures"] * combined["origin_arrival_delay_mean"]
        + combined["arrivals"] * combined["destination_arrival_delay_mean"]
    )
    combined["arrival_delay_mean"] = combined["arrival_delay_minutes_net"] / combined["total_movements"]
    combined["periods_active"] = combined[["origin_periods", "destination_periods"]].max(axis=1)
    low, high = wilson(combined["otp15_count"], combined["total_movements"])
    combined["otp15_ci_low_pct"] = low
    combined["otp15_ci_high_pct"] = high
    combined = combined.merge(dimension, on="airport", how="left")
    combined["country"] = combined["country"].fillna("Unknown")
    combined = combined.sort_values("total_movements", ascending=False)
    top200 = combined.head(200).copy()
    save_table(top200, "top200_airports_by_total_movements.csv")

    country = top200.groupby(["country", "iso_country"], observed=True, dropna=False).agg(
        airports=("airport", "nunique"),
        total_movements=("total_movements", "sum"),
        departures=("departures", "sum"),
        arrivals=("arrivals", "sum"),
        otp15_count=("otp15_count", "sum"),
        delayed15_count=("delayed15_count", "sum"),
        latitude=("latitude", "mean"),
        longitude=("longitude", "mean"),
    ).reset_index()
    country["otp15_pct"] = 100 * country["otp15_count"] / country["total_movements"]
    country["delayed15_pct"] = 100 * country["delayed15_count"] / country["total_movements"]
    country["share_top200_movements_pct"] = 100 * country["total_movements"] / top200["total_movements"].sum()
    low, high = wilson(country["otp15_count"], country["total_movements"])
    country["otp15_ci_low_pct"] = low
    country["otp15_ci_high_pct"] = high
    country = country.sort_values("total_movements", ascending=False)
    save_table(country, "top200_airport_country_statistics.csv")

    country_all = combined.groupby(["country", "iso_country"], observed=True, dropna=False).agg(
        airports=("airport", "nunique"),
        total_movements=("total_movements", "sum"),
        departures=("departures", "sum"),
        arrivals=("arrivals", "sum"),
        otp15_count=("otp15_count", "sum"),
        delayed15_count=("delayed15_count", "sum"),
        latitude=("latitude", "mean"),
        longitude=("longitude", "mean"),
    ).reset_index()
    country_all = country_all.loc[country_all["total_movements"] >= 1_000].copy()
    country_all["otp15_pct"] = 100 * country_all["otp15_count"] / country_all["total_movements"]
    country_all["delayed15_pct"] = 100 * country_all["delayed15_count"] / country_all["total_movements"]
    country_all["representation_flag"] = np.where(
        country_all["airports"].eq(1), "Limited representation", "Multiple airports"
    )
    low, high = wilson(country_all["otp15_count"], country_all["total_movements"])
    country_all["otp15_ci_low_pct"] = low
    country_all["otp15_ci_high_pct"] = high
    total_network_movements = int(combined["total_movements"].sum())
    total_network_successes = int(combined["otp15_count"].sum())
    comparisons = []
    for row in country_all.itertuples(index=False):
        comparison = two_proportion_z_test(
            int(row.otp15_count),
            int(row.total_movements),
            total_network_successes - int(row.otp15_count),
            total_network_movements - int(row.total_movements),
        )
        comparisons.append(comparison)
    country_all["rest_of_network_otp15_pct"] = [item["rate_b_pct"] for item in comparisons]
    country_all["difference_percentage_points"] = [
        item["difference_percentage_points"] for item in comparisons
    ]
    country_all["p_value"] = [item["p_value"] for item in comparisons]
    country_all["adjusted_p_value"] = benjamini_hochberg(country_all["p_value"])
    country_all["practically_material"] = country_all[
        "difference_percentage_points"
    ].abs().ge(3.0)
    country_all["decision_signal"] = np.select(
        [
            country_all["adjusted_p_value"].lt(.05)
            & country_all["practically_material"]
            & country_all["difference_percentage_points"].gt(0),
            country_all["adjusted_p_value"].lt(.05)
            & country_all["practically_material"]
            & country_all["difference_percentage_points"].lt(0),
        ],
        ["reliably_above_network", "reliably_below_network"],
        default="not_material_or_inconclusive",
    )
    country_all = country_all.sort_values("total_movements", ascending=False)
    save_table(country_all, "country_statistics_min_1000_movements.csv")

    for role, frame in (("origin", pd.read_csv(SOURCE / "tables" / "origin_airport_performance.csv")),
                        ("destination", pd.read_csv(SOURCE / "tables" / "destination_airport_performance.csv"))):
        eligible = frame.loc[(frame["flights"] >= 200) & (frame["periods_active"] >= 3)].copy()
        reliable = eligible.sort_values(["arrival_otp15_ci_low_pct", "flights"], ascending=[False, False]).head(10)
        problematic = eligible.sort_values(["arrival_otp15_ci_high_pct", "flights"], ascending=[True, False]).head(10)
        save_table(reliable, f"most_reliable_{role}_airports.csv")
        save_table(problematic, f"most_problematic_{role}_airports.csv")

    located = top200.dropna(subset=["latitude", "longitude"]).copy()
    located["latitude_band"] = (np.floor(located["latitude"] / 5) * 5).astype(int)
    located["longitude_band"] = (np.floor(located["longitude"] / 5) * 5).astype(int)
    grid = located.groupby(["latitude_band", "longitude_band"]).agg(
        airports=("airport", "nunique"),
        movements=("total_movements", "sum"),
        delayed15_count=("delayed15_count", "sum"),
        otp15_count=("otp15_count", "sum"),
    ).reset_index()
    grid["delayed15_pct"] = 100 * grid["delayed15_count"] / grid["movements"]
    grid["latitude_centre"] = grid["latitude_band"] + 2.5
    grid["longitude_centre"] = grid["longitude_band"] + 2.5
    save_table(grid.sort_values("delayed15_count", ascending=False), "latitude_longitude_delay_hotspots.csv")
    return {"top200": top200, "country": country, "country_all": country_all, "grid": grid}


def operator_tables() -> dict[str, pd.DataFrame]:
    operators = pd.read_csv(SOURCE / "tables" / "operator_performance.csv")
    airline_names = pd.read_csv(ROOT / "data" / "raw" / "icao" / "airlines.csv")
    airline_names = airline_names[["3Ltr", "Company", "Country"]].drop_duplicates("3Ltr")
    airline_names = airline_names.rename(columns={
        "3Ltr": "AC Operator", "Company": "operator_name", "Country": "operator_country"
    })
    operators = operators.merge(airline_names, on="AC Operator", how="left")
    operators["operator_name"] = operators["operator_name"].fillna(operators["AC Operator"])
    eligible = operators.loc[
        (operators["flights"] >= 1_000)
        & (operators["periods_active"] >= 3)
        & (~operators["AC Operator"].isin(["ZZZ", "Unknown", "UNKNOWN", "UNK"]))
    ].copy()
    reliable = eligible.sort_values(
        ["arrival_otp15_ci_low_pct", "flights"], ascending=[False, False]
    ).head(10)
    problematic = eligible.sort_values(
        ["arrival_otp15_ci_high_pct", "flights"], ascending=[True, False]
    ).head(10)
    largest = eligible.sort_values("flights", ascending=False).head(15)
    save_table(reliable, "most_reliable_operating_carriers.csv")
    save_table(problematic, "most_problematic_operating_carriers.csv")
    save_table(largest, "largest_operating_carriers.csv")
    return {"reliable": reliable, "problematic": problematic, "largest": largest}


def _airline_dimension() -> pd.DataFrame:
    names = pd.read_csv(ROOT / "data" / "raw" / "icao" / "airlines.csv")
    names = names[["3Ltr", "Company", "Country"]].drop_duplicates("3Ltr")
    return names.rename(
        columns={
            "3Ltr": "AC Operator",
            "Company": "operator_name",
            "Country": "operator_country",
        }
    )


def _finalise_delay_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["arrival_otp15_pct"] = 100 * result["arrival_otp15_count"] / result["observed_arrivals"]
    result["relative_delay_burden_pct"] = (
        100 * result["positive_delay_minutes"] / result["scheduled_duration_minutes"]
    )
    return result


def carrier_and_case_study_tables(
    *,
    chunksize: int = 100_000,
    max_rows_per_file: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Scan the raw files once for carrier and concrete business-use cases.

    All outputs use observed arrival delay. Relative delay burden is the sum of
    positive arrival-delay minutes divided by scheduled flight minutes.
    """

    paths = [row.path for row in discover_monthly_flights(ROOT / "data" / "raw")]
    config = BusinessAnalysisConfig(analysis_end_exclusive="2023-07-01")
    operator_parts: list[pd.DataFrame] = []
    family_route_parts: list[pd.DataFrame] = []
    madrid_rows: list[pd.DataFrame] = []

    for raw_path in development_flight_paths(paths, config):
        for chunk in pd.read_csv(
            raw_path,
            compression="gzip",
            usecols=RAW_COLUMNS,
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            flights = prepare_business_flights(chunk, config)
            observed = flights.loc[
                flights["Arrival_Delay_Min"].notna()
                & flights["scheduled_duration_min"].gt(0),
                [
                    "ECTRL ID",
                    "ADEP",
                    "ADES",
                    "AC Operator",
                    "STATFOR Market Segment",
                    "FILED OFF BLOCK TIME",
                    "period",
                    "departure_hour",
                    "scheduled_duration_min",
                    "Arrival_Delay_Min",
                    "arrival_otp15",
                ],
            ].copy()
            if observed.empty:
                continue
            observed["positive_delay_minutes"] = observed["Arrival_Delay_Min"].clip(lower=0)

            operator_parts.append(
                observed.groupby(["AC Operator", "period"], observed=True).agg(
                    observed_arrivals=("ECTRL ID", "size"),
                    arrival_otp15_count=("arrival_otp15", "sum"),
                    positive_delay_minutes=("positive_delay_minutes", "sum"),
                    scheduled_duration_minutes=("scheduled_duration_min", "sum"),
                ).reset_index()
            )

            observed["airline_family"] = np.select(
                [
                    observed["AC Operator"].isin(RYANAIR_CODES),
                    observed["AC Operator"].isin(WIZZ_CODES),
                ],
                ["Ryanair Group", "Wizz Air Group"],
                default="Other",
            )
            family = observed.loc[observed["airline_family"].ne("Other")]
            if not family.empty:
                family_route_parts.append(
                    family.groupby(
                        ["airline_family", "ADEP", "ADES", "period"], observed=True
                    ).agg(
                        observed_arrivals=("ECTRL ID", "size"),
                        arrival_otp15_count=("arrival_otp15", "sum"),
                        positive_delay_minutes=("positive_delay_minutes", "sum"),
                        scheduled_duration_minutes=("scheduled_duration_min", "sum"),
                    ).reset_index()
                )

            madrid_mask = (
                observed["ADEP"].eq("LEMD") & observed["ADES"].isin(MILAN_AIRPORTS)
            ) | (
                observed["ADES"].eq("LEMD") & observed["ADEP"].isin(MILAN_AIRPORTS)
            )
            madrid = observed.loc[madrid_mask].copy()
            if not madrid.empty:
                madrid["route"] = madrid["ADEP"] + " -> " + madrid["ADES"]
                madrid_rows.append(madrid)

    airline_names = _airline_dimension()
    operator_period = (
        pd.concat(operator_parts, ignore_index=True)
        .groupby(["AC Operator", "period"], observed=True, as_index=False)
        [[
            "observed_arrivals",
            "arrival_otp15_count",
            "positive_delay_minutes",
            "scheduled_duration_minutes",
        ]]
        .sum()
    )
    operators = operator_period.groupby("AC Operator", observed=True).agg(
        observed_arrivals=("observed_arrivals", "sum"),
        periods_active=("period", "nunique"),
        arrival_otp15_count=("arrival_otp15_count", "sum"),
        positive_delay_minutes=("positive_delay_minutes", "sum"),
        scheduled_duration_minutes=("scheduled_duration_minutes", "sum"),
    ).reset_index()
    operators = _finalise_delay_metrics(operators).merge(
        airline_names, on="AC Operator", how="left"
    )
    operators["operator_name"] = operators["operator_name"].fillna(operators["AC Operator"])
    eligible_operators = operators.loc[
        (operators["observed_arrivals"] >= 1_000)
        & (operators["periods_active"] >= 3)
        & (~operators["AC Operator"].isin(["ZZZ", "Unknown", "UNKNOWN", "UNK"]))
    ].copy()
    carrier_best = eligible_operators.sort_values(
        ["relative_delay_burden_pct", "observed_arrivals"], ascending=[True, False]
    ).head(10)
    carrier_worst = eligible_operators.sort_values(
        ["relative_delay_burden_pct", "observed_arrivals"], ascending=[False, False]
    ).head(10)
    save_table(eligible_operators.sort_values("observed_arrivals", ascending=False), "operator_relative_delay_performance.csv")
    save_table(carrier_best, "best_operating_carriers_by_relative_delay.csv")
    save_table(carrier_worst, "worst_operating_carriers_by_relative_delay.csv")

    family_period_route = (
        pd.concat(family_route_parts, ignore_index=True)
        .groupby(["airline_family", "ADEP", "ADES", "period"], observed=True, as_index=False)
        [[
            "observed_arrivals",
            "arrival_otp15_count",
            "positive_delay_minutes",
            "scheduled_duration_minutes",
        ]]
        .sum()
    )
    family_routes = family_period_route.groupby(
        ["airline_family", "ADEP", "ADES"], observed=True
    ).agg(
        observed_arrivals=("observed_arrivals", "sum"),
        periods_active=("period", "nunique"),
        arrival_otp15_count=("arrival_otp15_count", "sum"),
        positive_delay_minutes=("positive_delay_minutes", "sum"),
        scheduled_duration_minutes=("scheduled_duration_minutes", "sum"),
    ).reset_index()
    family_routes = _finalise_delay_metrics(family_routes)
    family_routes["route"] = family_routes["ADEP"] + " -> " + family_routes["ADES"]
    shared_counts = family_routes.pivot_table(
        index=["ADEP", "ADES", "route"],
        columns="airline_family",
        values=[
            "observed_arrivals",
            "periods_active",
            "arrival_otp15_pct",
            "relative_delay_burden_pct",
        ],
        aggfunc="first",
    )
    shared_counts.columns = [f"{metric}_{family}" for metric, family in shared_counts.columns]
    shared = shared_counts.reset_index()
    for family in ("Ryanair Group", "Wizz Air Group"):
        shared = shared.loc[
            shared[f"observed_arrivals_{family}"].ge(20)
            & shared[f"periods_active_{family}"].ge(3)
        ]
    shared["minimum_family_flights"] = shared[[
        "observed_arrivals_Ryanair Group", "observed_arrivals_Wizz Air Group"
    ]].min(axis=1)
    shared["otp15_difference_wizz_minus_ryanair_pp"] = (
        shared["arrival_otp15_pct_Wizz Air Group"]
        - shared["arrival_otp15_pct_Ryanair Group"]
    )
    shared["relative_burden_difference_wizz_minus_ryanair_pp"] = (
        shared["relative_delay_burden_pct_Wizz Air Group"]
        - shared["relative_delay_burden_pct_Ryanair Group"]
    )
    shared = shared.sort_values("minimum_family_flights", ascending=False, ignore_index=True)
    save_table(shared, "ryanair_wizz_shared_directional_routes.csv")

    route_weights = shared["minimum_family_flights"]
    family_summary_rows = []
    for family in ("Ryanair Group", "Wizz Air Group"):
        family_summary_rows.append({
            "airline_family": family,
            "shared_directional_routes": len(shared),
            "balanced_route_weight": route_weights.sum(),
            "route_standardised_otp15_pct": np.average(
                shared[f"arrival_otp15_pct_{family}"], weights=route_weights
            ),
            "route_standardised_relative_delay_burden_pct": np.average(
                shared[f"relative_delay_burden_pct_{family}"], weights=route_weights
            ),
        })
    family_summary = pd.DataFrame(family_summary_rows)
    save_table(family_summary, "ryanair_wizz_shared_route_summary.csv")

    madrid = pd.concat(madrid_rows, ignore_index=True)
    madrid = madrid.merge(airline_names, on="AC Operator", how="left")
    madrid["operator_name"] = madrid["operator_name"].fillna(madrid["AC Operator"])
    passenger_codes = set(
        madrid.loc[
            madrid["STATFOR Market Segment"].isin(PASSENGER_MARKET_SEGMENTS),
            "AC Operator",
        ]
    )
    madrid = madrid.loc[
        madrid["AC Operator"].isin(passenger_codes)
        & (~madrid["AC Operator"].isin(["ZZZ", "Unknown", "UNKNOWN", "UNK"]))
    ].copy()
    madrid["departure_date"] = madrid["FILED OFF BLOCK TIME"].dt.strftime("%Y-%m-%d")

    def madrid_group(columns: list[str]) -> pd.DataFrame:
        grouped = madrid.groupby(columns, observed=True).agg(
            observed_arrivals=("ECTRL ID", "size"),
            arrival_otp15_count=("arrival_otp15", "sum"),
            positive_delay_minutes=("positive_delay_minutes", "sum"),
            scheduled_duration_minutes=("scheduled_duration_min", "sum"),
            arrival_delay_median=("Arrival_Delay_Min", "median"),
            arrival_delay_p90=("Arrival_Delay_Min", lambda values: values.quantile(.9)),
        ).reset_index()
        return _finalise_delay_metrics(grouped)

    madrid_period = madrid_group(["period"])
    madrid_operator = madrid_group(["AC Operator", "operator_name"])
    madrid_operator_period = madrid_group(["period", "AC Operator", "operator_name"])
    madrid_hour = madrid_group(["departure_hour"])
    madrid_route = madrid_group(["route"])
    madrid_operator_eligible = madrid_operator.loc[
        madrid_operator["observed_arrivals"].ge(50)
    ].sort_values("observed_arrivals", ascending=False)
    madrid_hour_eligible = madrid_hour.loc[madrid_hour["observed_arrivals"].ge(20)].copy()
    madrid_extremes = madrid.nlargest(5, "Arrival_Delay_Min")[[
        "ECTRL ID",
        "departure_date",
        "departure_hour",
        "route",
        "AC Operator",
        "operator_name",
        "scheduled_duration_min",
        "Arrival_Delay_Min",
    ]]
    save_table(madrid_period, "madrid_milan_period_performance.csv")
    save_table(madrid_operator_eligible, "madrid_milan_operator_performance.csv")
    save_table(madrid_operator_period, "madrid_milan_operator_period_performance.csv")
    save_table(madrid_hour_eligible, "madrid_milan_hour_performance.csv")
    save_table(madrid_route, "madrid_milan_directional_route_performance.csv")
    save_table(madrid_extremes, "madrid_milan_largest_observed_arrival_delays.csv")

    return {
        "carrier_best": carrier_best,
        "carrier_worst": carrier_worst,
        "shared": shared,
        "family_summary": family_summary,
        "madrid_period": madrid_period,
        "madrid_operator": madrid_operator_eligible,
        "madrid_operator_period": madrid_operator_period,
        "madrid_hour": madrid_hour_eligible,
        "madrid_extremes": madrid_extremes,
    }


def full_time_and_pressure_tables() -> dict[str, pd.DataFrame]:
    paths = [row.path for row in discover_monthly_flights(ROOT / "data" / "raw")]
    config = BusinessAnalysisConfig(analysis_end_exclusive="2023-07-01")
    flights = read_business_flights(development_flight_paths(paths, config), config)

    network_otp15_pct = 100 * flights["arrival_otp15"].sum() / flights["Arrival_Delay_Min"].notna().sum()
    weekday, weekday_tests = weekday_otp15_analysis(flights, config)
    save_table(weekday, "weekday_network_performance.csv")
    save_table(weekday_tests, "weekday_vs_rest_otp15_tests.csv")
    save_figure(
        plot_weekday_otp15_performance(weekday, network_otp15_pct),
        FIGURES / "weekday_otp15_performance.png",
    )

    airport_trends, _ = period_otp15_trends(
        flights, "ADEP", minimum_flights=200, minimum_periods=6
    )
    named = flights.loc[
        ~flights["AC Operator"].astype(str).isin(["ZZZ", "Unknown", "UNKNOWN", "UNK"])
    ]
    operator_trends, _ = period_otp15_trends(
        named, "AC Operator", minimum_flights=1_000, minimum_periods=6
    )
    route_trends, _ = period_otp15_trends(
        flights, "route", minimum_flights=200, minimum_periods=6
    )
    save_table(airport_trends, "origin_airport_otp15_trends.csv")
    save_table(operator_trends, "operator_otp15_trends.csv")
    save_table(route_trends, "route_otp15_trends.csv")
    save_figure(
        plot_otp15_trend_extremes(
            airport_trends, "ADEP", "Top-3 origin-airport OTP15 improvements and deteriorations",
            volume_pool=200,
        ),
        FIGURES / "origin_airport_otp15_trend_extremes.png",
    )
    save_figure(
        plot_otp15_trend_extremes(
            operator_trends, "AC Operator", "Top-3 operating-carrier OTP15 improvements and deteriorations",
            volume_pool=100,
        ),
        FIGURES / "operator_otp15_trend_extremes.png",
    )
    save_figure(
        plot_otp15_trend_extremes(
            route_trends, "route", "Top-3 high-volume route OTP15 improvements and deteriorations",
            volume_pool=500,
        ),
        FIGURES / "route_otp15_trend_extremes.png",
    )
    airport_alerts = top_airport_leave_one_period_out_alerts(flights, config, top_n=10)
    save_table(airport_alerts, "top10_origin_airport_period_alerts.csv")
    save_figure(
        plot_top_airport_period_alerts(airport_alerts),
        FIGURES / "top10_origin_airport_period_alerts.png",
    )

    hourly = flights.groupby("departure_hour", observed=True).agg(
        flights=("ECTRL ID", "size"),
        otp15_count=("arrival_otp15", "sum"),
        delayed15_count=("arrival_delayed_15", "sum"),
        arrival_delay_mean=("Arrival_Delay_Min", "mean"),
        arrival_delay_median=("Arrival_Delay_Min", "median"),
        arrival_delay_p90=("Arrival_Delay_Min", lambda s: s.quantile(0.9)),
    ).reset_index()
    hourly["otp15_pct"] = 100 * hourly["otp15_count"] / hourly["flights"]
    hourly["delayed15_pct"] = 100 * hourly["delayed15_count"] / hourly["flights"]
    low, high = wilson(hourly["otp15_count"], hourly["flights"])
    hourly["otp15_ci_low_pct"] = low
    hourly["otp15_ci_high_pct"] = high
    save_table(hourly, "hourly_network_performance.csv")

    cells = flights.groupby(["ADEP", "departure_date", "departure_hour"], observed=True).agg(
        scheduled_departures=("ECTRL ID", "size"),
        otp15_count=("arrival_otp15", "sum"),
        delayed15_count=("arrival_delayed_15", "sum"),
        arrival_delay_sum=("Arrival_Delay_Min", "sum"),
    ).reset_index()
    cells["within_airport_load_percentile"] = cells.groupby("ADEP")["scheduled_departures"].rank(
        method="average", pct=True
    )
    cells["pressure_band"] = pd.cut(
        cells["within_airport_load_percentile"],
        [0, .25, .50, .75, 1.0],
        labels=["Low (Q1)", "Moderate (Q2)", "High (Q3)", "Peak (Q4)"],
        include_lowest=True,
    )
    pressure = cells.groupby("pressure_band", observed=True).agg(
        airport_hour_observations=("ADEP", "size"),
        flights=("scheduled_departures", "sum"),
        otp15_count=("otp15_count", "sum"),
        delayed15_count=("delayed15_count", "sum"),
        arrival_delay_sum=("arrival_delay_sum", "sum"),
    ).reset_index()
    pressure["otp15_pct"] = 100 * pressure["otp15_count"] / pressure["flights"]
    pressure["delayed15_pct"] = 100 * pressure["delayed15_count"] / pressure["flights"]
    pressure["arrival_delay_mean"] = pressure["arrival_delay_sum"] / pressure["flights"]
    low, high = wilson(pressure["otp15_count"], pressure["flights"])
    pressure["otp15_ci_low_pct"] = low
    pressure["otp15_ci_high_pct"] = high
    save_table(pressure, "within_airport_pressure_band_performance.csv")

    windows = cells.groupby(["ADEP", "departure_hour"], observed=True).agg(
        active_days=("departure_date", "nunique"),
        total_departures=("scheduled_departures", "sum"),
        peak_departures_in_one_hour=("scheduled_departures", "max"),
        otp15_count=("otp15_count", "sum"),
        delayed15_count=("delayed15_count", "sum"),
    ).reset_index()
    windows["mean_departures_per_active_day"] = windows["total_departures"] / windows["active_days"]
    windows["otp15_pct"] = 100 * windows["otp15_count"] / windows["total_departures"]
    windows["delayed15_pct"] = 100 * windows["delayed15_count"] / windows["total_departures"]
    windows = windows.loc[windows["active_days"] >= 30].sort_values(
        "mean_departures_per_active_day", ascending=False
    )
    save_table(windows.head(30), "busiest_recurring_airport_hour_windows.csv")
    return {"hourly": hourly, "pressure": pressure, "windows": windows.head(30)}


def plot_operator_rankings(data: dict[str, pd.DataFrame]) -> None:
    reliable = data["reliable"].head(10).sort_values("arrival_otp15_pct")
    problematic = data["problematic"].head(10).sort_values("arrival_otp15_pct")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5), sharex=True)
    for ax, frame, title, color in (
        (axes[0], reliable, "Most reliable eligible operating carriers", GREEN),
        (axes[1], problematic, "Operating carriers requiring attention", ORANGE),
    ):
        xerr = np.vstack([
            frame["arrival_otp15_pct"] - frame["arrival_otp15_ci_low_pct"],
            frame["arrival_otp15_ci_high_pct"] - frame["arrival_otp15_pct"],
        ])
        labels = frame["operator_name"] + " (" + frame["AC Operator"] + ")"
        ax.errorbar(frame["arrival_otp15_pct"], labels, xerr=xerr,
                    fmt="o", color=color, ecolor=GREY, capsize=3, markersize=7)
        style_axes(ax)
        ax.set_title(title, color=DARK_BLUE, fontweight="bold")
        ax.set_xlabel("Arrival OTP15 (%) · 95% Wilson interval")
        for y, (_, row) in enumerate(frame.iterrows()):
            ax.text(row["arrival_otp15_ci_high_pct"] + .15, y,
                    f"{int(row['flights']):,} flights", va="center", fontsize=8, color=GREY)
    fig.suptitle("Carrier reliability after applying a 1,000-flight / 3-period eligibility rule",
                 color=DARK_BLUE, fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "carrier_reliability_rankings.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_operator_relative_delay_rankings(data: dict[str, pd.DataFrame]) -> None:
    best = data["carrier_best"].head(10).sort_values("relative_delay_burden_pct", ascending=False)
    worst = data["carrier_worst"].head(10).sort_values("relative_delay_burden_pct")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.7))
    for ax, frame, title, color in (
        (axes[0], best, "Lowest relative arrival-delay burden", GREEN),
        (axes[1], worst, "Highest relative arrival-delay burden", ORANGE),
    ):
        labels = frame["operator_name"] + " (" + frame["AC Operator"] + ")"
        bars = ax.barh(labels, frame["relative_delay_burden_pct"], color=color)
        style_axes(ax)
        ax.set_title(title, color=DARK_BLUE, fontweight="bold")
        ax.set_xlabel("Relative arrival-delay burden (%)")
        ax.bar_label(
            bars,
            labels=[
                f"{value:.1f}% | {int(n):,} flights"
                for value, n in zip(frame["relative_delay_burden_pct"], frame["observed_arrivals"])
            ],
            padding=3,
            fontsize=8,
            color=GREY,
        )
        ax.margins(x=.28)
    fig.suptitle(
        "Operating-carrier ranking after scaling delay by scheduled flight duration",
        color=DARK_BLUE,
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        .5,
        .01,
        "Relative burden = positive arrival-delay minutes / scheduled flight minutes.",
        ha="center",
        color=GREY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, .035, 1, .96))
    fig.savefig(FIGURES / "carrier_relative_delay_rankings.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_ryanair_wizz_shared_routes(data: dict[str, pd.DataFrame]) -> None:
    frame = data["shared"].head(10).sort_values("minimum_family_flights")
    y = np.arange(len(frame))
    height = .36
    fig, axes = plt.subplots(1, 2, figsize=(13, 7.2), sharey=True)
    for offset, family, color in (
        (-height / 2, "Ryanair Group", BLUE),
        (height / 2, "Wizz Air Group", ORANGE),
    ):
        axes[0].barh(
            y + offset,
            frame[f"arrival_otp15_pct_{family}"],
            height,
            label=family,
            color=color,
        )
        axes[1].barh(
            y + offset,
            frame[f"relative_delay_burden_pct_{family}"],
            height,
            label=family,
            color=color,
        )
    axes[0].set_yticks(y, frame["route"])
    axes[0].set_xlabel("Arrival OTP15 (%) - higher is better")
    axes[1].set_xlabel("Relative delay burden (%) - lower is better")
    axes[0].set_title("Arrival punctuality", color=DARK_BLUE, fontweight="bold")
    axes[1].set_title("Delay severity scaled by duration", color=DARK_BLUE, fontweight="bold")
    for ax in axes:
        style_axes(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(.5, .91))
    fig.suptitle(
        "Ryanair and Wizz Air on their highest-volume shared directional routes",
        color=DARK_BLUE,
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        .5,
        .01,
        "Each displayed route has at least 20 observed arrivals and three periods for each airline group.",
        ha="center",
        color=GREY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, .035, 1, .96))
    fig.savefig(FIGURES / "ryanair_wizz_shared_routes.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_madrid_milan_case_study(data: dict[str, pd.DataFrame]) -> None:
    period = data["madrid_period"].copy()
    operator = data["madrid_operator"].sort_values("arrival_otp15_pct")
    hour = data["madrid_hour"].sort_values("departure_hour")
    operator_period = data["madrid_operator_period"].copy()
    leading_codes = operator.nlargest(4, "observed_arrivals")["AC Operator"].tolist()
    short_names = {
        "IBE": "Iberia",
        "RYR": "Ryanair",
        "AEA": "Air Europa",
        "ANE": "Air Nostrum",
    }
    operator_labels = [
        f"{short_names.get(code, name)} ({code})"
        for code, name in zip(operator["AC Operator"], operator["operator_name"])
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 9.5))
    axes[0, 0].plot(period["period"], period["arrival_otp15_pct"], marker="o", color=GREEN, linewidth=2.3)
    axes[0, 0].set_title("City-pair OTP15 across the nine snapshots", color=DARK_BLUE, fontweight="bold")
    axes[0, 0].set_ylabel("Arrival OTP15 (%)")
    axes[0, 0].tick_params(axis="x", rotation=45)

    operator_colors = [GREEN if value >= operator["arrival_otp15_pct"].median() else ORANGE for value in operator["arrival_otp15_pct"]]
    axes[0, 1].barh(operator_labels, operator["arrival_otp15_pct"], color=operator_colors)
    axes[0, 1].set_title("Eligible operating carriers", color=DARK_BLUE, fontweight="bold")
    axes[0, 1].set_xlabel("Arrival OTP15 (%)")

    hour_colors = [
        GREEN if value == hour["arrival_otp15_pct"].max()
        else ORANGE if value == hour["arrival_otp15_pct"].min()
        else BLUE
        for value in hour["arrival_otp15_pct"]
    ]
    axes[1, 0].bar(hour["departure_hour"], hour["arrival_otp15_pct"], color=hour_colors)
    axes[1, 0].set_title("Scheduled departure hour screen", color=DARK_BLUE, fontweight="bold")
    axes[1, 0].set_xlabel("Scheduled departure hour")
    axes[1, 0].set_ylabel("Arrival OTP15 (%)")
    axes[1, 0].set_xticks(hour["departure_hour"])

    for code in leading_codes:
        line = operator_period.loc[operator_period["AC Operator"].eq(code)].sort_values("period")
        if len(line) < 2:
            continue
        name = short_names.get(code, line["operator_name"].iloc[0])
        axes[1, 1].plot(line["period"], line["arrival_otp15_pct"], marker="o", label=f"{name} ({code})")
    axes[1, 1].set_title("Highest-volume carriers over time", color=DARK_BLUE, fontweight="bold")
    axes[1, 1].set_ylabel("Arrival OTP15 (%)")
    axes[1, 1].tick_params(axis="x", rotation=45)
    axes[1, 1].legend(frameon=False, fontsize=8)

    for ax in axes.flat:
        style_axes(ax)
    fig.suptitle(
        "EUROCONTROL screening example: Madrid-Milan airport system",
        color=DARK_BLUE,
        fontsize=16,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(FIGURES / "madrid_milan_case_study.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_country_rankings(country: pd.DataFrame) -> None:
    eligible = country.loc[country["total_movements"] >= 1_000].copy()
    frame = pd.concat([
        eligible.nlargest(5, "otp15_ci_low_pct"),
        eligible.nsmallest(5, "otp15_ci_high_pct"),
    ]).drop_duplicates("country").sort_values("otp15_pct")
    fig, ax = plt.subplots(figsize=(10.5, 7.5))
    colors = [GREEN if value >= 82.1705 else ORANGE for value in frame["otp15_pct"]]
    ax.barh(frame["country"], frame["otp15_pct"], color=colors)
    ax.axvline(82.1705, color=DARK_BLUE, linestyle="--", linewidth=1.4, label="Network OTP15 82.2%")
    style_axes(ax)
    ax.set_xlabel("Arrival OTP15 across represented airport movements (%)")
    ax.set_title("Country or territory reliability with at least 1,000 historical movements",
                 color=DARK_BLUE, fontsize=15, fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    for y, (_, row) in enumerate(frame.iterrows()):
        limited = " · limited" if row["representation_flag"] == "Limited representation" else ""
        ax.text(row["otp15_pct"] + .3, y,
                f"{row['total_movements']/1000:.0f}k · {int(row['airports'])} airports{limited}",
                va="center", fontsize=8, color=GREY)
    fig.tight_layout()
    fig.savefig(FIGURES / "country_reliability_min_1000_movements.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_airport_maps(top200: pd.DataFrame, country: pd.DataFrame) -> None:
    located = top200.dropna(subset=["latitude", "longitude"]).copy()
    sizes = 18 + 360 * np.sqrt(located["total_movements"] / located["total_movements"].max())
    label_rows = pd.concat([
        located.nlargest(15, "total_movements"),
        located.loc[(located["total_movements"] >= 200) & (located["periods_active"] >= 3)]
        .nsmallest(10, "otp15_ci_high_pct"),
    ]).drop_duplicates("airport")
    fig, axes = plt.subplots(2, 1, figsize=(13, 11.5), gridspec_kw={"height_ratios": [1.35, 1]})
    for ax, extent, title in (
        (axes[0], (-25, 40, 30, 72), "European airport reliability and volume"),
        (axes[1], (-180, 180, -60, 85), "Global coverage check"),
    ):
        draw_greyscale_basemap(ax)
        scatter = ax.scatter(
            located["longitude"], located["latitude"], s=sizes,
            c=located["otp15_pct"], cmap="RdYlGn", vmin=60, vmax=100,
            alpha=.86, edgecolors="white", linewidth=.55, zorder=2,
        )
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_facecolor("#F7F7F7")
        ax.grid(color="white", linewidth=.6, alpha=.8)
        ax.set_title(title, color=DARK_BLUE, fontsize=13, fontweight="bold")
        if ax is axes[0]:
            for _, row in label_rows.iterrows():
                if extent[0] <= row["longitude"] <= extent[1] and extent[2] <= row["latitude"] <= extent[3]:
                    ax.annotate(
                        row["airport"], (row["longitude"], row["latitude"]),
                        xytext=(3, 3), textcoords="offset points", fontsize=7.5,
                        color=DARK_BLUE, zorder=3,
                    )
    cbar = fig.colorbar(scatter, ax=axes, pad=.012, fraction=.025)
    cbar.set_label("Arrival OTP15 (%)")
    volume_handles = []
    for movements in (50_000, 150_000, 300_000):
        marker_size = 18 + 360 * np.sqrt(movements / located["total_movements"].max())
        volume_handles.append(axes[0].scatter([], [], s=marker_size, color="#A5A5A5",
                                              edgecolors="white", label=f"{movements/1000:.0f}k movements"))
    axes[0].legend(handles=volume_handles, title="Bubble area", frameon=True,
                   facecolor="white", loc="lower left", fontsize=8)
    fig.suptitle("Top 200 airports: OTP15, volume and geographic context",
                 color=DARK_BLUE, fontsize=16, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "top200_airport_otp15_geographic_maps.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_country_map(country: pd.DataFrame) -> None:
    mapped = country.dropna(subset=["latitude", "longitude"]).copy()
    fig, ax = plt.subplots(figsize=(13, 7.2))
    draw_greyscale_basemap(ax)
    sizes = 35 + 850 * np.sqrt(mapped["total_movements"] / mapped["total_movements"].max())
    scatter = ax.scatter(
        mapped["longitude"],
        mapped["latitude"],
        s=sizes,
        c=mapped["otp15_pct"],
        cmap="RdYlGn",
        vmin=60,
        vmax=100,
        alpha=.82,
        edgecolors=DARK_BLUE,
        linewidth=.5,
        zorder=2,
    )
    ax.set_xlim(-25, 40)
    ax.set_ylim(30, 72)
    ax.set_xlabel("Mean longitude of represented airports")
    ax.set_ylabel("Mean latitude of represented airports")
    ax.set_facecolor("#F7F7F7")
    ax.grid(color="white", linewidth=1.0)
    ax.set_title(
        "Country or territory reliability represented by eligible airports",
        color=DARK_BLUE,
        fontsize=15,
        fontweight="bold",
    )
    cbar = fig.colorbar(scatter, ax=ax, pad=.015)
    cbar.set_label("Arrival OTP15 (%)")
    for _, row in mapped.nlargest(15, "total_movements").iterrows():
        ax.annotate(
            str(row["country"]),
            (row["longitude"], row["latitude"]),
            xytext=(3, 3),
            textcoords="offset points",
            fontsize=8,
            color=DARK_BLUE,
        )
    ax.text(
        -24,
        31,
        "Bubble area represents movements; position is the mean coordinate of represented airports.",
        fontsize=8.5,
        color=GREY,
        bbox=dict(facecolor="white", alpha=.8, edgecolor="none"),
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "country_otp15_geographic_map.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_airport_relative_delay_comparison(
    top200: pd.DataFrame,
    relative_delay: pd.DataFrame,
) -> pd.DataFrame:
    """Compare arrival OTP15 with delay minutes relative to flight duration."""

    frame = top200.merge(relative_delay, on="airport", how="left")
    frame = frame.loc[
        frame["latitude"].notna()
        & frame["longitude"].notna()
        & frame["observed_arrivals"].ge(200)
        & frame["periods_active_y"].ge(3)
    ].copy()
    frame = frame.rename(columns={"periods_active_y": "relative_delay_periods"})
    save_table(frame, "top200_destination_relative_delay.csv")

    europe = frame.loc[
        frame["longitude"].between(-25, 40)
        & frame["latitude"].between(30, 72)
    ].copy()
    maximum_arrivals = europe["observed_arrivals"].max()
    sizes = 35 + 300 * np.sqrt(europe["observed_arrivals"] / maximum_arrivals)
    burden_vmax = float(europe["relative_delay_burden_pct"].quantile(0.95))

    fig, axes = plt.subplots(1, 2, figsize=(15, 7.2), sharex=True, sharey=True)
    panels = [
        (
            axes[0],
            "destination_arrival_otp15_pct",
            "Arrival OTP15 (%)",
            "RdYlGn",
            60.0,
            100.0,
            "Arrival punctuality",
        ),
        (
            axes[1],
            "relative_delay_burden_pct",
            "Positive delay / scheduled duration (%)",
            "YlOrRd",
            0.0,
            burden_vmax,
            "Relative delay burden",
        ),
    ]
    for ax, column, colorbar_label, cmap, vmin, vmax, title in panels:
        draw_greyscale_basemap(ax)
        points = ax.scatter(
            europe["longitude"],
            europe["latitude"],
            s=sizes,
            c=europe[column],
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            alpha=0.86,
            edgecolor="white",
            linewidth=0.55,
            zorder=2,
        )
        ax.set_xlim(-25, 40)
        ax.set_ylim(30, 72)
        ax.set_title(title, color=DARK_BLUE, fontweight="bold")
        ax.set_xlabel("Longitude")
        ax.grid(color="white", linewidth=0.5, alpha=0.8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        colorbar = fig.colorbar(points, ax=ax, fraction=0.035, pad=0.02)
        colorbar.set_label(colorbar_label)
    axes[0].set_ylabel("Latitude")

    for row in europe.nlargest(10, "observed_arrivals").itertuples(index=False):
        for ax in axes:
            ax.annotate(
                row.airport,
                (row.longitude, row.latitude),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=7,
                color=GREY,
                zorder=3,
            )
    axes[1].text(
        0.01,
        0.015,
        f"Colour clipped at European p95 = {burden_vmax:.1f}%",
        transform=axes[1].transAxes,
        fontsize=8,
        color=GREY,
    )
    fig.suptitle(
        "Top-200 airports: punctuality versus arrival-delay burden",
        color=DARK_BLUE,
        fontweight="bold",
        fontsize=15,
    )
    fig.text(
        0.5,
        0.01,
        "Same destination airports in both panels · bubble area represents observed arrivals",
        ha="center",
        color=GREY,
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.035, 1, 0.95])
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        FIGURES / "top200_airport_relative_delay_comparison.png",
        dpi=190,
        bbox_inches="tight",
    )
    plt.close(fig)
    return frame


def plot_grid_hotspots(grid: pd.DataFrame) -> None:
    pivot = grid.pivot(index="latitude_band", columns="longitude_band", values="delayed15_count").fillna(0)
    fig, ax = plt.subplots(figsize=(12, 6.5))
    image = ax.imshow(np.log1p(pivot.values), aspect="auto", origin="lower", cmap="YlOrRd")
    ax.set_xticks(range(len(pivot.columns))[::max(1, len(pivot.columns)//12)])
    ax.set_xticklabels([f"{v}°" for v in pivot.columns[::max(1, len(pivot.columns)//12)]], rotation=45)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v}–{v+5}°" for v in pivot.index])
    ax.set_xlabel("Longitude band")
    ax.set_ylabel("Latitude band")
    ax.set_title("Where delayed airport movements accumulate (5° × 5° grid)",
                 color=DARK_BLUE, fontsize=15, fontweight="bold")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("log(1 + number of movements delayed >15 min)")
    fig.tight_layout()
    fig.savefig(FIGURES / "latitude_longitude_delay_hotspots.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_time_and_pressure(data: dict[str, pd.DataFrame]) -> None:
    hourly = data["hourly"]
    fig, ax1 = plt.subplots(figsize=(11.5, 5.8))
    ax1.bar(hourly["departure_hour"], hourly["flights"], color=LIGHT_BLUE, label="Flights")
    ax1.set_ylabel("Scheduled operated flights", color=DARK_BLUE)
    ax1.set_xlabel("Scheduled departure hour")
    ax1.set_xticks(range(24))
    ax2 = ax1.twinx()
    ax2.plot(hourly["departure_hour"], hourly["otp15_pct"], color=GREEN, marker="o", label="OTP15")
    ax2.set_ylabel("Arrival OTP15 (%)", color=GREEN)
    ax1.grid(axis="y", color="#D9D9D9", linewidth=.7)
    for spine in (*ax1.spines.values(), *ax2.spines.values()):
        spine.set_visible(False)
    ax1.set_title("Network volume and reliability by scheduled departure hour",
                  color=DARK_BLUE, fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "hourly_network_volume_reliability.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    pressure = data["pressure"]
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    colors = [GREEN, BLUE, "#A5A5A5", ORANGE]
    bars = ax.bar(pressure["pressure_band"].astype(str), pressure["delayed15_pct"], color=colors)
    style_axes(ax)
    ax.set_xlabel("Traffic-load quartile within each origin airport")
    ax.set_ylabel("Arrivals delayed >15 minutes (%)")
    ax.set_title("Congestion proxy: reliability across within-airport traffic pressure",
                 color=DARK_BLUE, fontsize=15, fontweight="bold")
    for bar, value, n in zip(bars, pressure["delayed15_pct"], pressure["flights"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + .2,
                f"{value:.1f}%\n{n/1e6:.2f}m flights", ha="center", fontsize=9, color=DARK_BLUE)
    fig.tight_layout()
    fig.savefig(FIGURES / "congestion_pressure_performance.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case-studies-only",
        action="store_true",
        help="Only build carrier-duration and concrete case-study assets.",
    )
    parser.add_argument("--max-rows-per-file", type=int, default=None)
    args = parser.parse_args()
    FIGURES.mkdir(parents=True, exist_ok=True)
    if args.case_studies_only:
        case_studies = carrier_and_case_study_tables(
            max_rows_per_file=args.max_rows_per_file
        )
        plot_operator_relative_delay_rankings(case_studies)
        plot_ryanair_wizz_shared_routes(case_studies)
        plot_madrid_milan_case_study(case_studies)
        print(json.dumps({
            "eligible_relative_delay_carriers": int(
                len(case_studies["carrier_best"]) + len(case_studies["carrier_worst"])
            ),
            "shared_ryanair_wizz_routes": int(len(case_studies["shared"])),
            "madrid_milan_observed_arrivals": int(
                case_studies["madrid_period"]["observed_arrivals"].sum()
            ),
        }, indent=2))
        return
    airports = airport_and_country_tables()
    operators = operator_tables()
    time_pressure = full_time_and_pressure_tables()
    plot_operator_rankings(operators)
    plot_country_rankings(airports["country_all"])
    plot_airport_maps(airports["top200"], airports["country_all"])
    plot_country_map(airports["country_all"])
    plot_grid_hotspots(airports["grid"])
    plot_time_and_pressure(time_pressure)
    summary = {
        "top200_airports": len(airports["top200"]),
        "top200_countries": int(airports["country"]["country"].nunique()),
        "countries_min_1000_movements": int(airports["country_all"]["country"].nunique()),
        "located_top200_airports": int(airports["top200"]["latitude"].notna().sum()),
        "eligible_carriers": int(len(pd.read_csv(TABLES / "most_reliable_operating_carriers.csv"))),
        "new_tables": sorted(path.name for path in TABLES.glob("*.csv")),
        "new_figures": sorted(path.name for path in FIGURES.glob("*.png")),
    }
    (OUTPUT / "asset_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
