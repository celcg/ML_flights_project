"""Airline analytics page and airline-specific visual components."""

import html
import math

import altair as alt
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from dashboard.common import style_chart
from dashboard.config import (
    BLUE,
    DELAYED_ROUTE_THRESHOLD_PCT,
    ROUTE_RANKING_METRICS,
    ROUTE_SCOPE_LABELS,
)
from dashboard.data import load_airline_data, load_route_data
from dashboard.entity_analysis import (
    RANKING_VIEW_LABELS,
    build_on_time_trend_figure,
    rank_entities,
)
from dashboard.entity_selector import build_entity_search_pool, render_entity_selector


AIRLINE_RANKING_LIMIT = 15
AIRLINE_TABLE_HEIGHT = 394
UNKNOWN_OPERATOR_CODES = {"ZZZ", "UNK", "UNKNOWN"}


def render_airlines_page(period_text: str, study_year: str) -> None:
    """Render a three-column airline comparison and drill-down dashboard."""

    try:
        airline_data = load_airline_data()
        route_data = load_route_data()
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    with st.container(key="airline_scope_filter"):
        st.html(
            '<div class="floating-filter-label">Flight-duration filter · applies to the full page</div>',
        )
        scope_id = st.segmented_control(
            "Flight-duration filter",
            options=list(ROUTE_SCOPE_LABELS),
            default="all_flights",
            format_func=ROUTE_SCOPE_LABELS.get,
            key="airline_duration_scope",
            width="stretch",
            label_visibility="collapsed",
        ) or "all_flights"

    airline_metrics = airline_data["metrics"]
    scope_metrics = airline_metrics[
        airline_metrics["scope_id"].eq(scope_id)
        & airline_metrics["executive_eligible"].eq(True)
    ].copy()
    columns = st.columns([0.34, 0.32, 0.34], gap="small", vertical_alignment="top")
    with columns[0]:
        _render_airline_profile(scope_metrics)
    with columns[1]:
        selected_airline = _render_airline_ranking(scope_id, scope_metrics)
    with columns[2]:
        _render_airline_detail(
            scope_id,
            scope_metrics,
            airline_data["monthly"],
            route_data,
            selected_airline,
        )

    _render_preserved_high_delay_chart(route_data, scope_id)
    _render_airline_information(
        period_text,
        study_year,
        airline_data["methodology"].iloc[0],
        len(scope_metrics),
    )


def _render_airline_profile(scope_metrics: pd.DataFrame) -> None:
    with st.container(border=True, key="airline_profile_card"):
        st.html(
            '<div class="section-kicker">01 · Airline operating profile</div>',
        )
        st.html(
            '<div class="airline-panel-title">Duration, delay and flight volume</div>',
        )
        if scope_metrics.empty:
            st.info("No airline aggregate is available for this duration scope.")
            return
        st.plotly_chart(
            _airline_profile_chart(scope_metrics),
            width="stretch",
            height=470,
            theme=None,
            key="airline_profile_scatter",
            config={
                "displayModeBar": True,
                "displaylogo": False,
                "scrollZoom": True,
                "doubleClick": "reset+autosize",
                "modeBarButtonsToRemove": ["toImage", "select2d", "lasso2d"],
            },
        )


def _airline_profile_chart(scope_metrics: pd.DataFrame):
    plot_data = scope_metrics.assign(
        airline=scope_metrics.apply(
            lambda row: _airline_label(row["operator_code"], row["operator_name"]),
            axis=1,
        )
    )
    figure = px.scatter(
        plot_data,
        x="median_scheduled_duration_min",
        y="median_arrival_delay_min",
        size="flight_count",
        color="delay_over_15_pct",
        color_continuous_scale=["#2E8B68", "#AFC9DD", "#C35D5D"],
        hover_name="airline",
        hover_data={
            "median_scheduled_duration_min": ":.1f",
            "median_arrival_delay_min": ":.1f",
            "flight_count": ":,",
            "delay_over_15_pct": ":.1f",
            "route_count": ":,",
        },
        labels={
            "median_scheduled_duration_min": "Median scheduled duration (min)",
            "median_arrival_delay_min": "Median arrival delay (min)",
            "flight_count": "Flights",
            "delay_over_15_pct": "Delayed >15 min (%)",
            "route_count": "Directional routes",
        },
        size_max=33,
    )
    figure.update_traces(
        marker={"line": {"color": "#FFFFFF", "width": 1.2}, "opacity": 0.84}
    )
    figure.update_layout(
        height=470,
        margin={"l": 48, "r": 12, "t": 18, "b": 54},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#23364A", "size": 10},
        coloraxis_colorbar={
            "title": {"text": "Delayed<br>>15 min", "font": {"size": 9}},
            "thickness": 8,
            "len": 0.45,
            "x": 1.0,
            "tickfont": {"size": 8},
            "ticksuffix": "%",
        },
        dragmode="zoom",
    )
    figure.update_xaxes(
        gridcolor="#E5EDF4", fixedrange=False, title_font={"size": 10}
    )
    figure.update_yaxes(
        gridcolor="#E5EDF4", fixedrange=False, title_font={"size": 10}, ticksuffix=" min"
    )
    return figure


def _render_airline_ranking(scope_id: str, scope_metrics: pd.DataFrame) -> str | None:
    with st.container(border=True, key="airline_ranking_card"):
        st.html(
            '<div class="section-kicker">02 · Airline ranking</div>',
        )
        if scope_metrics.empty:
            st.info("No airline meets the ranking threshold for this scope.")
            return None
        with st.container(key="airline_ranking_filters"):
            with st.container(key="airline_ranking_metric_filter"):
                ranking_metric = st.segmented_control(
                    "Ranking metric",
                    options=list(ROUTE_RANKING_METRICS),
                    default="delay_over_15_pct",
                    format_func=lambda value: ROUTE_RANKING_METRICS[value]["label"],
                    key="airline_ranking_metric",
                    width="stretch",
                    label_visibility="collapsed",
                ) or "delay_over_15_pct"
            with st.container(key="airline_ranking_view_filter"):
                ranking_view = st.segmented_control(
                    "Airline table ranking",
                    options=list(RANKING_VIEW_LABELS),
                    default="most_popular",
                    format_func=RANKING_VIEW_LABELS.get,
                    key="airline_ranking_view",
                    width="stretch",
                    label_visibility="collapsed",
                ) or "most_popular"
        state_class = ranking_view.replace("_", "-")
        st.html(f'<div class="airline-ranking-state {state_class}"></div>')
        st.html(
            '<div class="airline-table-hint">Select an airline to update its routes and monthly performance.</div>',
        )
        ranked = rank_entities(
            scope_metrics,
            ranking_view,
            ranking_metric,
            limit=AIRLINE_RANKING_LIMIT,
        )
        metric_column = (
            "Delayed >15 min (%)"
            if ranking_metric == "delay_over_15_pct"
            else "Median delay (min)"
        )
        display = ranked[
            ["operator_code", "operator_name", "flight_count", ranking_metric]
        ].copy()
        display["Airline"] = display.apply(
            lambda row: _airline_label(row["operator_code"], row["operator_name"]),
            axis=1,
        )
        display = display.rename(
            columns={"flight_count": "Flights", ranking_metric: metric_column}
        )
        event = st.dataframe(
            display[["Airline", "Flights", metric_column]],
            hide_index=True,
            width="stretch",
            height=AIRLINE_TABLE_HEIGHT,
            row_height=36,
            key=f"airline_ranking_table_{ranking_view}_{scope_id}_{ranking_metric}",
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Airline": st.column_config.TextColumn("Airline", width=125, pinned=True),
                "Flights": st.column_config.NumberColumn("Flights", format="%d", width=65),
                metric_column: st.column_config.NumberColumn(
                    metric_column, format="%.1f", width=112
                ),
            },
        )
        selected_rows = event.selection.rows
        selected_index = selected_rows[0] if selected_rows else 0
        selected_code = str(display.iloc[selected_index]["operator_code"])
        st.session_state[f"mapped_airline_{scope_id}"] = selected_code
        return selected_code


def _render_airline_detail(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    monthly_metrics: pd.DataFrame,
    route_data: dict[str, pd.DataFrame],
    selected_code: str | None,
) -> None:
    with st.container(border=True, key="airline_detail_card"):
        if scope_metrics.empty:
            st.info("No airline detail is available for this scope.")
            return
        code = selected_code or st.session_state.get(f"mapped_airline_{scope_id}")
        selected = scope_metrics[scope_metrics["operator_code"].eq(code)]
        airline = selected.iloc[0] if not selected.empty else scope_metrics.iloc[0]
        airline = _render_airline_search(scope_id, scope_metrics, airline)
        routes = _selected_airline_routes(route_data, scope_id, str(airline["operator_code"]))
        if routes.empty:
            st.info("No coordinate-complete eligible route is available for this airline.")
        else:
            st.pydeck_chart(
                _airline_route_map(routes),
                width="stretch",
                height=210,
                key=f"airline_map_{scope_id}_{airline['operator_code']}",
            )
        country = airline.get("operator_country")
        country_text = "Country unavailable" if pd.isna(country) else str(country)
        st.html(
            f"""
            <div class="airline-detail-panel">
                <strong>{html.escape(str(airline['operator_name']))}</strong>
                <span>{html.escape(str(airline['operator_code']))} · {html.escape(country_text)}</span>
                <div class="airline-detail-metrics">
                    <span><b>{int(airline['flight_count']):,}</b> flights</span>
                    <span><b>{airline['delay_over_15_pct']:.1f}%</b> delayed</span>
                    <span><b>{int(airline['route_count']):,}</b> routes</span>
                </div>
            </div>
            """
        )
        monthly = monthly_metrics[
            monthly_metrics["scope_id"].eq(scope_id)
            & monthly_metrics["operator_code"].eq(airline["operator_code"])
        ]
        if not monthly.empty:
            st.plotly_chart(
                build_on_time_trend_figure(monthly, height=190),
                width="stretch",
                height=190,
                theme=None,
                key=f"airline_on_time_{scope_id}_{airline['operator_code']}",
                config={"displayModeBar": False, "scrollZoom": False},
            )


def _render_airline_search(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    selected_airline: pd.Series,
) -> pd.Series:
    """Render a searchable selector over the highest-volume half of airlines."""

    search_pool = build_entity_search_pool(
        scope_metrics, selected_airline, "operator_code"
    )
    options = search_pool["operator_code"].astype(str).tolist()
    selected_code = str(selected_airline["operator_code"])
    labels = {
        str(row.operator_code): _airline_label(row.operator_code, row.operator_name)
        for row in search_pool.itertuples(index=False)
    }
    chosen_code = render_entity_selector(
        title="03 · Selected airline",
        label="Search airline",
        options=options,
        selected_value=selected_code,
        labels=labels,
        key=f"airline_search_{scope_id}_{selected_code}",
        placeholder="Search airline",
    )
    return search_pool[search_pool["operator_code"].astype(str).eq(chosen_code)].iloc[0]


def _selected_airline_routes(
    route_data: dict[str, pd.DataFrame],
    scope_id: str,
    operator_code: str,
) -> pd.DataFrame:
    operators = route_data["operators"]
    routes = operators[
        operators["scope_id"].eq(scope_id)
        & operators["operator_code"].eq(operator_code)
    ][["scope_id", "route", "flight_count", "delay_over_15_pct"]].copy()
    metrics = route_data["metrics"]
    geometry_columns = [
        "scope_id",
        "route",
        "ADEP",
        "ADES",
        "origin_latitude",
        "origin_longitude",
        "destination_latitude",
        "destination_longitude",
    ]
    routes = routes.merge(metrics[geometry_columns], on=["scope_id", "route"], how="left")
    routes = routes.dropna(
        subset=[
            "origin_latitude",
            "origin_longitude",
            "destination_latitude",
            "destination_longitude",
        ]
    )
    return routes.nlargest(35, "flight_count").copy()


def _airline_route_map(routes: pd.DataFrame) -> pdk.Deck:
    max_flights = max(float(routes["flight_count"].max()), 1.0)
    arc_data = []
    for row in routes.itertuples(index=False):
        arc_data.append({
            "route": row.route,
            "source": [float(row.origin_longitude), float(row.origin_latitude)],
            "target": [float(row.destination_longitude), float(row.destination_latitude)],
            "flights": int(row.flight_count),
            "delay_rate": float(row.delay_over_15_pct),
            "width": 1.2 + 5.0 * math.sqrt(float(row.flight_count) / max_flights),
        })
    latitudes = pd.concat([routes["origin_latitude"], routes["destination_latitude"]])
    longitudes = pd.concat([routes["origin_longitude"], routes["destination_longitude"]])
    return pdk.Deck(
        map_style="light",
        initial_view_state=pdk.ViewState(
            latitude=float(latitudes.median()),
            longitude=float(longitudes.median()),
            zoom=1.35,
            pitch=0,
        ),
        layers=[
            pdk.Layer(
                "ArcLayer",
                arc_data,
                get_source_position="source",
                get_target_position="target",
                get_source_color=[47, 111, 176, 210],
                get_target_color=[46, 139, 104, 210],
                get_width="width",
                width_min_pixels=1,
                pickable=True,
                auto_highlight=True,
            )
        ],
        tooltip={
            "html": "<b>{route}</b><br/>Flights: {flights}<br/>Delayed &gt;15 min: {delay_rate}%",
            "style": {"backgroundColor": "#0B1F33", "color": "white"},
        },
    )


def _render_preserved_high_delay_chart(
    route_data: dict[str, pd.DataFrame],
    scope_id: str,
) -> None:
    with st.expander("High-delay route exposure", expanded=False):
        route_metrics = route_data["metrics"]
        eligible_routes = route_metrics[
            route_metrics["scope_id"].eq(scope_id)
            & route_metrics["executive_eligible"].eq(True)
        ]
        summary = _high_delay_airline_summary(
            route_data["operators"], eligible_routes, scope_id
        )
        if summary.empty:
            st.info("No identified airline aggregate is available for this scope.")
        else:
            st.altair_chart(_airline_delay_chart(summary), width="stretch")


def _high_delay_airline_summary(
    route_operators: pd.DataFrame,
    eligible_routes: pd.DataFrame,
    scope_id: str,
) -> pd.DataFrame:
    delayed_routes = eligible_routes.loc[
        eligible_routes["delay_over_15_pct"].gt(DELAYED_ROUTE_THRESHOLD_PCT), "route"
    ]
    airlines = route_operators[
        route_operators["scope_id"].eq(scope_id)
        & route_operators["route"].isin(delayed_routes)
        & ~route_operators["operator_code"].isin(UNKNOWN_OPERATOR_CODES)
    ].copy()
    if airlines.empty:
        return airlines
    summary = airlines.groupby("operator_code", as_index=False).agg(
        operator_name=("operator_name", "first"),
        delayed_routes=("route", "nunique"),
        flight_count=("flight_count", "sum"),
        delayed_over_15_count=("delayed_over_15_count", "sum"),
    )
    summary["delay_over_15_pct"] = (
        summary["delayed_over_15_count"] / summary["flight_count"] * 100
    )
    summary = summary.nlargest(12, "delayed_routes").copy()
    summary["airline_label"] = summary.apply(
        lambda row: _airline_label(row["operator_code"], row["operator_name"]), axis=1
    )
    return summary


def _airline_delay_chart(airlines: pd.DataFrame) -> alt.Chart:
    axis_maximum = max(1.0, float(airlines["delayed_routes"].max()) * 1.12)
    order = airlines.sort_values("delayed_routes")["airline_label"].tolist()
    bars = alt.Chart(airlines).mark_bar(
        color=BLUE, cornerRadiusEnd=5, size=24
    ).encode(
        y=alt.Y(
            "airline_label:N",
            title="Airline",
            sort=order,
            axis=alt.Axis(labelLimit=280, labelFontSize=10, labelPadding=6),
        ),
        x=alt.X(
            "delayed_routes:Q",
            title="Directional routes delayed >30%",
            scale=alt.Scale(domain=[0, axis_maximum]),
            axis=alt.Axis(labelFontSize=10, titleFontSize=11, tickCount=6, format="d"),
        ),
        tooltip=[
            alt.Tooltip("operator_name:N", title="Airline"),
            alt.Tooltip("operator_code:N", title="ICAO code"),
            alt.Tooltip("delayed_routes:Q", title="Routes delayed >30%", format=","),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed flights", format=".1f"),
        ],
    )
    return style_chart(
        bars.properties(
            height=390,
            width="container",
            padding={"left": 6, "right": 24, "top": 8, "bottom": 10},
        )
    )


def _airline_label(operator_code: str, operator_name: str) -> str:
    name = str(operator_name).title()
    shortened_name = name if len(name) <= 36 else f"{name[:34].rstrip()}…"
    return f"{operator_code} · {shortened_name}"


def _render_airline_information(
    period_text: str,
    study_year: str,
    methodology: pd.Series,
    eligible_airline_count: int,
) -> None:
    with st.expander("Airline information summary", expanded=False):
        st.markdown(
            f"""
            This page analyses identified airline operators on scheduled flights observed
            in **{period_text} {study_year}**. Rankings require at least
            **{int(methodology['minimum_flights']):,} flights** and presence in
            **{int(methodology['minimum_periods'])} observed months**;
            **{eligible_airline_count:,} airlines** meet those requirements for the
            selected duration scope. Point size represents flight volume. The map shows
            up to the selected airline's 35 highest-volume eligible directional routes.
            Only aggregated results are published.
            """
        )
