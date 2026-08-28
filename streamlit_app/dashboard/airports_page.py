"""Airport analytics page with geographic, ranking and temporal drill-downs."""

import html

import pandas as pd
import streamlit as st

from dashboard.airport_visuals import (
    airport_heatmap_chart,
    airport_label,
    airport_map_deck,
    airport_timeline_chart,
)
from dashboard.common import render_eurocontrol_attribution
from dashboard.config import (
    AIRPORT_DELAY_VIEWS,
    ROUTE_SCOPE_LABELS,
)
from dashboard.data import load_airport_data
from dashboard.entity_analysis import (
    RANKING_VIEW_LABELS,
    rank_entities,
)
from dashboard.entity_selector import build_entity_search_pool, render_entity_selector


AIRPORT_MAP_LIMIT = 500
AIRPORT_RANKING_LIMIT = 15
AIRPORT_TABLE_HEIGHT = 394
AIRPORT_MIN_FLIGHTS = 500
AIRPORT_MIN_PERIODS = 3


def render_airports_page(period_text: str, study_year: str) -> None:
    """Render airport geography, rankings and selected-airport diagnostics."""

    try:
        data = load_airport_data()
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    scope_id, delay_view = _render_airport_filters()
    metrics = data["metrics"]
    scope_metrics = metrics[
        metrics["scope_id"].eq(scope_id)
        & metrics["executive_eligible"].eq(True)
    ].copy()
    metric_column = AIRPORT_DELAY_VIEWS[delay_view]["metric"]

    _render_airport_map(scope_metrics, metric_column, delay_view)

    detail_columns = st.columns([0.54, 0.46], gap="small", vertical_alignment="top")
    with detail_columns[0]:
        selected_code = _render_airport_ranking(
            scope_id, scope_metrics, metric_column, delay_view
        )
    with detail_columns[1]:
        _render_selected_airport(
            scope_id,
            scope_metrics,
            data["monthly"],
            data["heatmap"],
            delay_view,
            selected_code,
        )
    _render_airport_information(
        period_text,
        study_year,
        len(scope_metrics),
    )


def _render_airport_filters() -> tuple[str, str]:
    with st.container(key="airport_global_filters"):
        filter_columns = st.columns([0.50, 0.50], gap="small")
        with filter_columns[0]:
            st.html(
                '<div class="floating-filter-label">Flight-duration filter</div>',
            )
            scope_id = st.segmented_control(
                "Flight-duration filter",
                options=list(ROUTE_SCOPE_LABELS),
                default="all_flights",
                format_func=ROUTE_SCOPE_LABELS.get,
                key="airport_duration_scope",
                width="stretch",
                label_visibility="collapsed",
            ) or "all_flights"
        with filter_columns[1]:
            st.html(
                '<div class="floating-filter-label">Delay perspective · applies to map, ranking and heatmap</div>',
            )
            delay_view = st.segmented_control(
                "Delay perspective",
                options=list(AIRPORT_DELAY_VIEWS),
                default="both",
                format_func=lambda value: AIRPORT_DELAY_VIEWS[value]["short_label"],
                key="airport_delay_view",
                width="stretch",
                label_visibility="collapsed",
            ) or "both"
    return scope_id, delay_view


def _render_airport_map(
    scope_metrics: pd.DataFrame,
    metric_column: str,
    delay_view: str,
) -> None:
    with st.container(border=True, key="airport_map_card"):
        st.html(
            '<div class="section-kicker">01 · Major airport geography</div>',
        )
        title = AIRPORT_DELAY_VIEWS[delay_view]["label"]
        st.html(
            f'<div class="airport-panel-title">Top {AIRPORT_MAP_LIMIT} airports by movement volume · {html.escape(title)}</div>'
        )
        mapped = scope_metrics.dropna(
            subset=["latitude", "longitude", metric_column]
        ).nlargest(AIRPORT_MAP_LIMIT, "flight_count")
        if mapped.empty:
            st.info("No coordinate-complete airport aggregate is available.")
            return
        st.pydeck_chart(
            airport_map_deck(mapped, metric_column),
            width="stretch",
            height=340,
            key=f"airport_map_{delay_view}",
        )
        st.html(
            '<div class="airport-map-legend"><span><i class="good"></i>Lower delay rate</span><span><i class="mid"></i>Intermediate</span><span><i class="poor"></i>Higher delay rate</span><em>Point size = movement volume</em></div>',
        )


def _render_airport_ranking(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    metric_column: str,
    delay_view: str,
) -> str | None:
    with st.container(border=True, key="airport_ranking_card"):
        st.html(
            '<div class="section-kicker">03 · Airport ranking</div>',
        )
        if scope_metrics.empty:
            st.info("No airport meets the ranking threshold for this scope.")
            return None
        with st.container(key="airport_ranking_view_filter"):
            ranking_view = st.segmented_control(
                "Airport ranking",
                options=list(RANKING_VIEW_LABELS),
                default="most_popular",
                format_func=RANKING_VIEW_LABELS.get,
                key="airport_ranking_view",
                width="stretch",
                label_visibility="collapsed",
            ) or "most_popular"
        st.html(
            f'<div class="airport-ranking-state {ranking_view.replace("_", "-")}"></div>'
        )
        st.html(
            '<div class="airport-table-hint">Select an airport to update the detail, timeline and hourly pattern.</div>',
        )
        ranked = rank_entities(
            scope_metrics.dropna(subset=[metric_column]),
            ranking_view,
            metric_column,
            limit=AIRPORT_RANKING_LIMIT,
        )
        display = ranked[
            ["airport_code", "airport_name", "flight_count", metric_column]
        ].copy()
        display["Airport"] = display.apply(
            lambda row: airport_label(row["airport_code"], row["airport_name"]),
            axis=1,
        )
        metric_label = f"{AIRPORT_DELAY_VIEWS[delay_view]['short_label']} delayed (%)"
        display = display.rename(
            columns={"flight_count": "Movements", metric_column: metric_label}
        )
        event = st.dataframe(
            display[["Airport", "Movements", metric_label]],
            hide_index=True,
            width="stretch",
            height=AIRPORT_TABLE_HEIGHT,
            row_height=36,
            key=f"airport_ranking_table_{scope_id}_{delay_view}_{ranking_view}",
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Airport": st.column_config.TextColumn("Airport", width=210, pinned=True),
                "Movements": st.column_config.NumberColumn("Movements", format="%d", width=90),
                metric_label: st.column_config.NumberColumn(metric_label, format="%.1f", width=125),
            },
        )
        selected_index = event.selection.rows[0] if event.selection.rows else 0
        selected_code = str(display.iloc[selected_index]["airport_code"])
        st.session_state[f"selected_airport_{scope_id}"] = selected_code
        return selected_code


def _render_selected_airport(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    monthly_metrics: pd.DataFrame,
    heatmap_metrics: pd.DataFrame,
    delay_view: str,
    selected_code: str | None,
) -> None:
    with st.container(border=True, key="airport_detail_card"):
        if scope_metrics.empty:
            st.info("No airport detail is available for this scope.")
            return
        code = selected_code or st.session_state.get(f"selected_airport_{scope_id}")
        match = scope_metrics[scope_metrics["airport_code"].eq(code)]
        airport = match.iloc[0] if not match.empty else scope_metrics.nlargest(1, "flight_count").iloc[0]
        airport = _render_airport_search(scope_id, scope_metrics, airport)
        st.html(_airport_detail_markup(airport))

        monthly = monthly_metrics[
            monthly_metrics["scope_id"].eq(scope_id)
            & monthly_metrics["airport_code"].eq(airport["airport_code"])
        ]
        if not monthly.empty:
            st.plotly_chart(
                airport_timeline_chart(monthly),
                width="stretch",
                height=190,
                theme=None,
                key=f"airport_timeline_{scope_id}_{airport['airport_code']}",
                config={"displayModeBar": False, "scrollZoom": False},
            )

        heatmap = heatmap_metrics[
            heatmap_metrics["scope_id"].eq(scope_id)
            & heatmap_metrics["airport_code"].eq(airport["airport_code"])
            & heatmap_metrics["movement_type"].eq(delay_view)
        ]
        if not heatmap.empty:
            st.plotly_chart(
                airport_heatmap_chart(heatmap, delay_view),
                width="stretch",
                height=235,
                theme=None,
                key=f"airport_heatmap_{scope_id}_{delay_view}_{airport['airport_code']}",
                config={"displayModeBar": False, "scrollZoom": False},
            )


def _render_airport_search(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    selected_airport: pd.Series,
) -> pd.Series:
    """Render a searchable selector over the highest-volume half of airports."""

    search_pool = build_entity_search_pool(
        scope_metrics, selected_airport, "airport_code"
    )
    options = search_pool["airport_code"].astype(str).tolist()
    selected_code = str(selected_airport["airport_code"])
    labels = {
        str(row.airport_code): airport_label(row.airport_code, row.airport_name)
        for row in search_pool.itertuples(index=False)
    }
    chosen_code = render_entity_selector(
        title="02 · Selected airport",
        label="Search airport",
        options=options,
        selected_value=selected_code,
        labels=labels,
        key=f"airport_search_{scope_id}_{selected_code}",
        placeholder="Search airport",
    )
    return search_pool[search_pool["airport_code"].astype(str).eq(chosen_code)].iloc[0]

def _airport_detail_markup(airport: pd.Series) -> str:
    airport_name = "Airport name unavailable" if pd.isna(airport["airport_name"]) else str(airport["airport_name"])
    location = " · ".join(
        value for value in [
            None if pd.isna(airport["city"]) else str(airport["city"]),
            None if pd.isna(airport["country"]) else str(airport["country"]),
        ] if value
    )
    return f"""
    <div class="airport-detail-panel">
        <strong>{html.escape(str(airport['airport_code']))} · {html.escape(airport_name)}</strong>
        <span>{html.escape(location or 'Location unavailable')}</span>
        <div class="airport-detail-metrics">
            <span><b>{int(airport['flight_count']):,}</b> movements</span>
            <span><b>{airport['arrival_delay_over_15_pct']:.1f}%</b> arrivals delayed</span>
            <span><b>{airport['departure_delay_over_15_pct']:.1f}%</b> departures delayed</span>
        </div>
    </div>
    """


def _render_airport_information(
    period_text: str,
    study_year: str,
    eligible_airport_count: int,
) -> None:
    with st.expander("Airport information summary", expanded=False):
        st.markdown(
            f"""
            This page analyses airport arrivals and departures observed in **{period_text}
            {study_year}**. Rankings require at least
            **{AIRPORT_MIN_FLIGHTS:,} arrival/departure movements** and
            presence in **{AIRPORT_MIN_PERIODS} observed months**;
            **{eligible_airport_count:,} airports** meet those requirements for the
            selected duration scope. The map shows up to the **{AIRPORT_MAP_LIMIT}
            highest-volume airports**. Heatmap hours and weekdays use the filed schedule
            timestamps contained in each snapshot. Only aggregated results are published.
            """
        )
        render_eurocontrol_attribution()
