"""Flight search page combining public aggregates with an experimental Ridge scenario."""

from __future__ import annotations

from dataclasses import dataclass
import html

import pandas as pd
import streamlit as st

from dashboard.airport_visuals import airport_label
from dashboard.data import load_airport_data, load_route_data
from dashboard.entity_analysis import highest_traffic_half
from dashboard.flight_search import FlightSearchStats, build_search_stats
from dashboard.ridge_inference import predict_arrival_delay_minutes


MONTH_LABELS = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}
WEEKDAY_LABELS = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


@dataclass(frozen=True)
class FlightScenario:
    """Calendar inputs for one schedule-only prediction scenario."""

    day: int
    month: int
    weekday: int
    hour: int


@dataclass(frozen=True)
class FlightSearchSelection:
    """Entities and schedule selected by the user."""

    route: pd.Series
    operator: pd.Series
    scenario: FlightScenario


def render_search_page(period_text: str, study_year: str) -> None:
    """Render searchable historic evidence and a schedule-only model scenario."""

    route_data = load_route_data()
    airport_data = load_airport_data()
    routes = route_data["metrics"]
    routes = routes[
        routes["scope_id"].eq("all_flights") & routes["executive_eligible"].eq(True)
    ].copy()
    search_pool = highest_traffic_half(routes).sort_values("flight_count", ascending=False)
    if search_pool.empty:
        st.warning("No eligible route aggregate is available for flight search.")
        return

    selection = _render_search_controls(search_pool, route_data["operators"])
    statistics = build_search_stats(
        selection.route,
        selection.operator,
        airport_data["heatmap"],
        selection.scenario.hour,
    )
    _render_search_results(selection, statistics)
    _render_search_information(period_text, study_year)


def _render_search_controls(
    routes: pd.DataFrame,
    operators: pd.DataFrame,
) -> FlightSearchSelection:
    with st.container(border=True, key="flight_search_controls"):
        st.html(
            '<div class="section-kicker">01 · Flight search</div>',
        )
        st.html(
            '<div class="search-panel-title">Choose a scheduled flight scenario</div>',
        )
        route, operator = _render_route_controls(routes, operators)
        scenario = _render_schedule_controls()
    return FlightSearchSelection(route=route, operator=operator, scenario=scenario)


def _render_route_controls(
    routes: pd.DataFrame,
    operators: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    origins = routes.drop_duplicates("ADEP").sort_values(
        "flight_count", ascending=False
    )
    origin_labels = {
        str(row.ADEP): airport_label(row.ADEP, row.origin_airport_name)
        for row in origins.itertuples(index=False)
    }
    input_columns = st.columns([1, 1, 1.05], gap="small")
    with input_columns[0]:
        origin = st.selectbox(
            "Origin airport",
            options=origins["ADEP"].astype(str).tolist(),
            format_func=origin_labels.get,
            key="flight_search_origin",
            placeholder="Search origin",
        )

    destinations = routes[routes["ADEP"].eq(origin)].sort_values(
        "flight_count", ascending=False
    )
    destination_labels = {
        str(row.ADES): airport_label(row.ADES, row.destination_airport_name)
        for row in destinations.itertuples(index=False)
    }
    with input_columns[1]:
        destination = st.selectbox(
            "Destination airport",
            options=destinations["ADES"].astype(str).tolist(),
            format_func=destination_labels.get,
            key="flight_search_destination",
            placeholder="Search destination",
        )

    route = destinations[destinations["ADES"].eq(destination)].iloc[0]
    route_operators = operators[
        operators["scope_id"].eq("all_flights")
        & operators["ADEP"].eq(origin)
        & operators["ADES"].eq(destination)
    ].sort_values("flight_count", ascending=False)
    operator_labels = {
        str(row.operator_code): _operator_label(row.operator_code, row.operator_name)
        for row in route_operators.itertuples(index=False)
    }
    with input_columns[2]:
        operator_code = st.selectbox(
            "Airline",
            options=route_operators["operator_code"].astype(str).tolist(),
            format_func=operator_labels.get,
            key="flight_search_operator",
            placeholder="Search airline",
        )
    operator = route_operators[
        route_operators["operator_code"].eq(operator_code)
    ].iloc[0]
    return route, operator


def _render_schedule_controls() -> FlightScenario:
    schedule_columns = st.columns([0.55, 0.85, 1, 0.65], gap="small")
    with schedule_columns[0]:
        departure_day = st.selectbox(
            "Day of month",
            options=list(range(1, 32)),
            index=14,
            key="flight_search_day",
        )
    with schedule_columns[1]:
        departure_month = st.selectbox(
            "Month",
            options=list(MONTH_LABELS),
            index=5,
            format_func=MONTH_LABELS.get,
            key="flight_search_month",
        )
    with schedule_columns[2]:
        departure_weekday = st.selectbox(
            "Day of week",
            options=list(WEEKDAY_LABELS),
            index=2,
            format_func=WEEKDAY_LABELS.get,
            key="flight_search_weekday",
        )
    with schedule_columns[3]:
        departure_hour = st.selectbox(
            "Hour",
            options=list(range(24)),
            index=8,
            format_func=lambda value: f"{value:02d}:00",
            key="flight_search_hour",
        )
    return FlightScenario(
        day=departure_day,
        month=departure_month,
        weekday=departure_weekday,
        hour=departure_hour,
    )


def _render_search_results(
    selection: FlightSearchSelection,
    statistics: FlightSearchStats,
) -> None:
    route = selection.route
    operator = selection.operator
    scenario = selection.scenario
    with st.container(border=True, key="flight_search_results"):
        st.html(
            '<div class="section-kicker">02 · Delay evidence</div>',
        )
        st.html(
            f'<div class="search-route-title">{html.escape(str(route["ADEP"]))} '
            f'→ {html.escape(str(route["ADES"]))} · '
            f'{html.escape(_operator_label(operator["operator_code"], operator["operator_name"]))}'
            "</div>"
        )
        predicted_minutes: float | None = None
        prediction_error: str | None = None
        try:
            predicted_minutes = predict_arrival_delay_minutes(
                route,
                str(operator["operator_code"]),
                scenario.month,
                scenario.weekday,
                scenario.hour,
            )
        except (FileNotFoundError, ImportError, ValueError) as error:
            prediction_error = str(error)

        cards = [
            (
                "Route flights delayed >15 min",
                _percentage(statistics.route_delay_pct),
                f'{statistics.route_flights:,} flights on this route',
            ),
            (
                "Airline flights delayed >15 min · selected route",
                _percentage(statistics.operator_delay_pct),
                f'{statistics.operator_flights:,} airline flights on this route',
            ),
            (
                f"Origin departures delayed >15 min · {scenario.hour:02d}:00",
                _percentage(statistics.origin_hour_delay_pct),
                f'{statistics.origin_hour_flights:,} departures at the origin',
            ),
            (
                "Destination arrivals delayed >15 min · scheduled hour",
                _percentage(statistics.destination_hour_delay_pct),
                f'{statistics.destination_hour_flights:,} arrivals at the destination',
            ),
            (
                "Ridge arrival-delay estimate",
                "Unavailable"
                if predicted_minutes is None
                else f"{predicted_minutes:.1f} min",
                "Experimental T−60 scenario",
            ),
        ]
        st.html(_metric_cards_markup(cards))
        if prediction_error:
            st.caption(f"Ridge estimate unavailable: {prediction_error}")
        st.html(
            '<div class="search-model-note"><b>How to read this:</b> the four '
            "percentages are descriptive 2022 aggregates, not a probability for one "
            "flight. Ridge estimates arrival-delay minutes; because live operational "
            "and aircraft variables are not entered here, they use their training "
            "medians.</div>"
        )
        st.caption(
            f"Scenario: {WEEKDAY_LABELS[scenario.weekday]}, "
            f"{scenario.day} {MONTH_LABELS[scenario.month]} at {scenario.hour:02d}:00."
        )


def _metric_cards_markup(cards: list[tuple[str, str, str]]) -> str:
    return '<div class="search-metric-grid">' + "".join(
        f'<div class="search-metric"><span>{html.escape(label)}</span>'
        f'<strong>{html.escape(value)}</strong><small>{html.escape(context)}</small></div>'
        for label, value, context in cards
    ) + "</div>"


def _percentage(value: float | None) -> str:
    return "No data" if value is None else f"{value:.1f}%"


def _operator_label(code: object, name: object) -> str:
    clean_name = "Name unavailable" if pd.isna(name) else str(name).title()
    return f"{code} · {clean_name}"


def _render_search_information(period_text: str, study_year: str) -> None:
    with st.expander("Flight-search methodology", expanded=False):
        st.markdown(
            f"""
            Historical rates use public aggregates from **{period_text} {study_year}**.
            Origin rates correspond to departures in the selected hour; destination rates
            correspond to arrivals in the approximate scheduled-arrival hour, based on the
            route median duration. The Ridge model is the selected
            `ridge_without_registration` T−60 regression (test MAE **9.85 minutes**).
            Ridge uses month and weekday directly; day of month is retained as scenario
            context because it is not an independent model feature. Its operational-history,
            rotation and aircraft fields are unavailable in this
            search interface and are median-imputed, so this is an explanatory scenario—not
            an operational forecast or passenger decision tool.
            """
        )
