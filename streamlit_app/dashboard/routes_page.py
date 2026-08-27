"""Routes analytics page and its route-specific visual components."""

import html
import math

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from dashboard.common import style_chart
from dashboard.config import (
    BLUE,
    DELAYED_ROUTE_THRESHOLD_PCT,
    ROUTE_RANKING_METRICS,
    ROUTE_SCOPE_LABELS,
)
from dashboard.data import load_route_data
from dashboard.entity_analysis import (
    RANKING_VIEW_LABELS,
    build_on_time_trend_figure,
    highest_traffic_half,
    rank_entities,
)


POPULAR_ROUTE_LIMIT = 10
ROUTE_TABLE_HEIGHT = 286


def _route_map_deck(route: pd.Series) -> pdk.Deck:
    """Build an aggregate directional-route map without flight-level tracks."""
    source = [float(route["origin_longitude"]), float(route["origin_latitude"])]
    target = [float(route["destination_longitude"]), float(route["destination_latitude"])]
    arc_data = [
        {
            "route": route["route"],
            "role": f"Origin {route['ADEP']} → destination {route['ADES']}",
            "source": source,
            "target": target,
            "delay_rate": float(route["delay_over_15_pct"]),
            "median_delay": float(route["median_arrival_delay_min"]),
            "flights": int(route["flight_count"]),
        }
    ]
    longitude_delta = ((target[0] - source[0] + 180) % 360) - 180
    center_longitude = ((source[0] + longitude_delta / 2 + 180) % 360) - 180
    center_latitude = (source[1] + target[1]) / 2
    route_span = max(abs(longitude_delta), abs(source[1] - target[1]), 0.7)
    shared_metrics = {
        "route": route["route"],
        "delay_rate": float(route["delay_over_15_pct"]),
        "median_delay": float(route["median_arrival_delay_min"]),
        "flights": int(route["flight_count"]),
    }
    airport_points = [
        {
            **shared_metrics,
            "position": source,
            "role": f"Origin · {route['ADEP']}",
            "color": [47, 111, 176, 245],
        },
        {
            **shared_metrics,
            "position": target,
            "role": f"Destination · {route['ADES']}",
            "color": [46, 139, 104, 245],
        },
    ]
    latitude_scale = max(math.cos(math.radians(center_latitude)), 0.2)
    direction_x = longitude_delta * latitude_scale
    direction_y = target[1] - source[1]
    direction_norm = max(math.hypot(direction_x, direction_y), 1e-9)
    unit_x = direction_x / direction_norm
    unit_y = direction_y / direction_norm
    arrow_length = min(3.0, max(0.18, route_span * 0.14))
    tip_x, tip_y = unit_x * arrow_length * 0.65, unit_y * arrow_length * 0.65
    base_x, base_y = -unit_x * arrow_length * 0.35, -unit_y * arrow_length * 0.35
    wing_x, wing_y = -unit_y * arrow_length * 0.45, unit_x * arrow_length * 0.45

    def arrow_point(offset_x: float, offset_y: float) -> list[float]:
        longitude = center_longitude + offset_x / latitude_scale
        return [((longitude + 180) % 360) - 180, center_latitude + offset_y]

    direction_marker = [
        {
            "polygon": [
                arrow_point(tip_x, tip_y),
                arrow_point(base_x + wing_x, base_y + wing_y),
                arrow_point(base_x - wing_x, base_y - wing_y),
            ]
        }
    ]
    zoom = min(6.0, max(1.5, math.log2(180 / route_span) - 1.65))
    return pdk.Deck(
        map_style="light",
        initial_view_state=pdk.ViewState(
            latitude=center_latitude,
            longitude=center_longitude,
            zoom=zoom,
            pitch=0,
            bearing=0,
        ),
        layers=[
            pdk.Layer(
                "ArcLayer",
                arc_data,
                get_source_position="source",
                get_target_position="target",
                get_source_color=[47, 111, 176, 235],
                get_target_color=[47, 111, 176, 235],
                get_width=5,
                pickable=True,
                auto_highlight=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                airport_points,
                get_position="position",
                get_fill_color="color",
                get_radius=35_000,
                radius_min_pixels=7,
                radius_max_pixels=14,
                pickable=True,
            ),
            pdk.Layer(
                "PolygonLayer",
                direction_marker,
                get_polygon="polygon",
                get_fill_color=[11, 31, 51, 255],
                filled=True,
                stroked=False,
                pickable=False,
            ),
        ],
        tooltip={
            "html": "<b>{route}</b><br/>{role}<br/>Delayed &gt;15 min: {delay_rate}%<br/>"
            "Median delay: {median_delay} min<br/>Flights: {flights}",
            "style": {"backgroundColor": "#0B1F33", "color": "white"},
        },
    )


def render_routes_page(period_text: str, study_year: str) -> None:
    """Render the public directional-route analytics page."""

    try:
        route_data = load_route_data()
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    metrics = route_data["metrics"]
    summary = route_data["summary"].set_index("scope_id")
    methodology = route_data["methodology"].iloc[0]
    route_monthly = route_data["monthly"]

    with st.container(key="route_scope_filter"):
        st.html(
            '<div class="floating-filter-label">Flight-duration filter · applies to the full page</div>',
        )
        scope_id = st.segmented_control(
            "Flight-duration filter",
            options=list(ROUTE_SCOPE_LABELS),
            default="all_flights",
            format_func=ROUTE_SCOPE_LABELS.get,
            key="route_duration_scope",
            width="stretch",
            label_visibility="collapsed",
        )
    scope_id = scope_id or "all_flights"
    scope_summary = summary.loc[scope_id]
    all_scope_metrics = metrics[metrics["scope_id"].eq(scope_id)].copy()
    scope_metrics = metrics[
        metrics["scope_id"].eq(scope_id) & metrics["executive_eligible"].eq(True)
    ].copy()

    overview_columns = st.columns([0.30, 0.70], gap="small", vertical_alignment="top")
    with overview_columns[0]:
        _render_scope_summary(scope_summary, all_scope_metrics)
        _render_route_delay_distribution(scope_metrics)
    with overview_columns[1]:
        _render_route_explorer(scope_id, scope_metrics, route_monthly)
    _render_route_information(period_text, study_year, methodology, len(scope_metrics))


def _render_scope_summary(
    scope_summary: pd.Series,
    scope_metrics: pd.DataFrame,
) -> None:
    with st.container(border=True, key="route_scope_summary"):
        st.html(
            '<div class="section-kicker">01 · Selected operating scope</div>',
        )
        delayed_routes = int(
            scope_metrics["delay_over_15_pct"].gt(DELAYED_ROUTE_THRESHOLD_PCT).sum()
        )
        delayed_route_share = 100 * delayed_routes / int(scope_summary["route_count"])
        st.html(
            f"""
            <div class="combined-route-kpi">
                <span class="combined-route-label">Routes delayed &gt;30%</span>
                <div class="combined-route-number-line">
                    <span class="combined-route-value">{delayed_routes:,}</span>
                    <span class="combined-route-total">/{int(scope_summary['route_count']):,}</span>
                </div>
                <span class="combined-route-unit">directional routes</span>
                <span class="combined-route-share">{delayed_route_share:.1f}% of routes</span>
            </div>
            """
        )


def _render_route_explorer(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    route_monthly: pd.DataFrame,
) -> None:
    """Combine the interactive ranking and selected-route map in one card."""
    with st.container(border=True, key="route_explorer_card"):
        st.html(
            '<div class="section-kicker">03 · Route ranking and map</div>',
        )
        explorer_columns = st.columns(
            [0.44, 0.56], gap="small", vertical_alignment="top"
        )
        with explorer_columns[0]:
            mapped_route = _render_route_ranking(scope_id, scope_metrics)
        with explorer_columns[1]:
            _render_route_geography(
                scope_id, scope_metrics, route_monthly, mapped_route
            )


def _render_route_ranking(
    scope_id: str,
    scope_metrics: pd.DataFrame,
) -> str | None:
    st.html(
        '<div class="route-panel-title">Route ranking</div>',
    )
    if scope_metrics.empty:
        st.warning("No routes meet the ranking threshold for this duration scope.")
        return None

    with st.container(key="route_ranking_filters"):
        with st.container(key="route_ranking_metric_filter"):
            ranking_metric = st.segmented_control(
                "Ranking metric",
                options=list(ROUTE_RANKING_METRICS),
                default="delay_over_15_pct",
                format_func=lambda value: ROUTE_RANKING_METRICS[value]["label"],
                key="route_ranking_metric",
                width="stretch",
                label_visibility="collapsed",
            ) or "delay_over_15_pct"
        with st.container(key="route_ranking_view_filter"):
            ranking_view = st.segmented_control(
                "Route table ranking",
                options=list(RANKING_VIEW_LABELS),
                default="most_popular",
                format_func=RANKING_VIEW_LABELS.get,
                key="route_ranking_view",
                width="stretch",
                label_visibility="collapsed",
            ) or "most_popular"
    state_class = ranking_view.replace("_", "-")
    st.html(f'<div class="route-ranking-state {state_class}"></div>')
    st.html(
        '<div class="route-table-hint">Select a route in the table to update the map and inspect its details.</div>',
    )

    ranked_routes = rank_entities(
        scope_metrics,
        ranking_view,
        ranking_metric,
        limit=POPULAR_ROUTE_LIMIT,
    )
    metric_column = (
        "Delayed >15 min (%)"
        if ranking_metric == "delay_over_15_pct"
        else "Median delay (min)"
    )
    display = ranked_routes[["route", "flight_count", ranking_metric]].rename(
        columns={
            "route": "Route",
            "flight_count": "Flights",
            ranking_metric: metric_column,
        }
    )
    event = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=ROUTE_TABLE_HEIGHT,
        row_height=36,
        key=f"route_ranking_table_{ranking_view}_{scope_id}_{ranking_metric}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Route": st.column_config.TextColumn(
                "Directional route", width=105, pinned=True
            ),
            "Flights": st.column_config.NumberColumn("Flights", format="%d", width=70),
            metric_column: st.column_config.NumberColumn(
                metric_column, format="%.1f", width=125
            ),
        },
    )
    selected_rows = event.selection.rows
    selected_index = selected_rows[0] if selected_rows else 0
    mapped_route = str(display.iloc[selected_index]["Route"])
    st.session_state[f"mapped_route_{scope_id}"] = mapped_route
    return mapped_route


def _render_route_delay_distribution(scope_metrics: pd.DataFrame) -> None:
    with st.container(border=True, key="route_distribution_card"):
        st.html(
            '<div class="section-kicker">02 · Route delay distribution</div>',
        )
        st.altair_chart(
            _route_delay_distribution_chart(scope_metrics),
            width="stretch",
        )


def _route_delay_distribution_chart(scope_metrics: pd.DataFrame) -> alt.Chart:
    bin_edges = list(range(0, 101, 10))
    bin_labels = [f"{start}–{start + 10}%" for start in bin_edges[:-1]]
    distribution = scope_metrics.assign(
        delay_band=pd.cut(
            scope_metrics["delay_over_15_pct"],
            bins=bin_edges,
            labels=bin_labels,
            include_lowest=True,
        )
    )
    distribution = (
        distribution.groupby("delay_band", observed=False)
        .size()
        .reindex(bin_labels, fill_value=0)
        .rename("route_count")
        .reset_index()
    )
    bars = alt.Chart(distribution).mark_bar(
        color=BLUE,
        cornerRadiusEnd=4,
        size=22,
    ).encode(
        y=alt.Y(
            "delay_band:N",
            title="Delayed flights (%)",
            sort=bin_labels,
            axis=alt.Axis(labelFontSize=9, titleFontSize=10, labelPadding=5),
        ),
        x=alt.X(
            "route_count:Q",
            title="Number of directional routes",
            axis=alt.Axis(labelFontSize=9, titleFontSize=10, tickCount=4, format="d"),
        ),
        tooltip=[
            alt.Tooltip("delay_band:N", title="Delayed-flight rate"),
            alt.Tooltip("route_count:Q", title="Routes", format=","),
        ],
    )
    return style_chart(
        bars.properties(
            height=382,
            width="container",
            padding={"left": 4, "right": 18, "top": 8, "bottom": 8},
        )
    )


def _selected_route_on_time_chart(
    route_monthly: pd.DataFrame,
    scope_id: str,
    route_code: str,
) -> object:
    """Build a readable on-time percentage trend for the selected route."""
    monthly = route_monthly.loc[
        route_monthly["scope_id"].eq(scope_id)
        & route_monthly["route"].eq(route_code)
    ].copy()
    return build_on_time_trend_figure(monthly)


def _render_route_geography(
    scope_id: str,
    scope_metrics: pd.DataFrame,
    route_monthly: pd.DataFrame,
    mapped_route: str | None,
) -> None:
    """Render the ranking-selected directional route on an aggregate map."""
    located = scope_metrics.dropna(
        subset=[
            "origin_latitude",
            "origin_longitude",
            "destination_latitude",
            "destination_longitude",
        ]
    )
    if located.empty:
        st.info("No coordinate-complete eligible route is available for this filter.")
        return

    selected_code = mapped_route or st.session_state.get(f"mapped_route_{scope_id}")
    selected_match = located[located["route"].eq(selected_code)]
    selected_route = (
        selected_match.iloc[0]
        if not selected_match.empty
        else located.nlargest(1, "delay_over_15_pct").iloc[0]
    )
    selected_route = _render_route_search(scope_id, located, selected_route)
    origin_name = selected_route.get("origin_airport_name")
    destination_name = selected_route.get("destination_airport_name")
    origin_name = "Airport name unavailable" if pd.isna(origin_name) else origin_name
    destination_name = (
        "Airport name unavailable" if pd.isna(destination_name) else destination_name
    )
    st.pydeck_chart(
        _route_map_deck(selected_route),
        width="stretch",
        height=220,
        key=f"route_map_{scope_id}_{selected_route['route']}",
    )
    with st.container(key="route_map_footer"):
        detail_columns = st.columns(
            [0.38, 0.62], gap="small", vertical_alignment="center"
        )
        with detail_columns[0]:
            st.html(
                f"""
                <div class="route-detail-panel">
                    <strong>{html.escape(str(selected_route['route']))}</strong>
                    <span class="route-airport-names">{html.escape(str(origin_name))} →
                        {html.escape(str(destination_name))}</span>
                    <div class="route-detail-metrics">
                        <span><b>{int(selected_route['flight_count']):,}</b> flights</span>
                        <span><b>{selected_route['delay_over_15_pct']:.1f}%</b> delayed</span>
                        <span><b>{selected_route['median_arrival_delay_min']:.1f} min</b> median</span>
                    </div>
                </div>
                """
            )
        with detail_columns[1]:
            st.plotly_chart(
                _selected_route_on_time_chart(
                    route_monthly,
                    scope_id,
                    str(selected_route["route"]),
                ),
                width="stretch",
                height=175,
                theme=None,
                key=f"route_on_time_{scope_id}_{selected_route['route']}",
                config={"displayModeBar": False, "scrollZoom": False},
            )


def _render_route_search(
    scope_id: str,
    located_routes: pd.DataFrame,
    selected_route: pd.Series,
) -> pd.Series:
    """Render dependent origin/destination search over the busiest route half."""

    search_pool = highest_traffic_half(located_routes)
    search_pool = pd.concat(
        [search_pool, selected_route.to_frame().T], ignore_index=True
    ).drop_duplicates("route")
    search_pool = search_pool.sort_values("flight_count", ascending=False)
    selected_origin = str(selected_route["ADEP"])
    selected_destination = str(selected_route["ADES"])

    origin_names = _airport_names(search_pool, "ADEP", "origin_airport_name")
    origin_options = search_pool["ADEP"].astype(str).drop_duplicates().tolist()
    header_columns = st.columns(
        [0.26, 0.37, 0.37], gap="small", vertical_alignment="center"
    )
    with header_columns[0]:
        st.html(
            '<div class="route-panel-title entity-search-title">Selected route</div>',
        )
    with header_columns[1]:
        origin = st.selectbox(
            "Origin airport",
            options=origin_options,
            index=origin_options.index(selected_origin),
            format_func=lambda code: _airport_search_label(code, origin_names),
            key=f"route_origin_search_{scope_id}_{selected_route['route']}",
            placeholder="Search origin",
            label_visibility="collapsed",
        )

    destination_pool = search_pool[search_pool["ADEP"].astype(str).eq(origin)]
    destination_names = _airport_names(
        destination_pool, "ADES", "destination_airport_name"
    )
    destination_options = (
        destination_pool["ADES"].astype(str).drop_duplicates().tolist()
    )
    default_destination = (
        selected_destination if selected_destination in destination_options else destination_options[0]
    )
    with header_columns[2]:
        destination = st.selectbox(
            "Destination airport",
            options=destination_options,
            index=destination_options.index(default_destination),
            format_func=lambda code: _airport_search_label(code, destination_names),
            key=f"route_destination_search_{scope_id}_{selected_route['route']}_{origin}",
            placeholder="Search destination",
            label_visibility="collapsed",
        )
    return destination_pool[
        destination_pool["ADES"].astype(str).eq(destination)
    ].iloc[0]


def _airport_names(
    routes: pd.DataFrame,
    code_column: str,
    name_column: str,
) -> dict[str, str]:
    return {
        str(row[code_column]): (
            "Airport name unavailable" if pd.isna(row[name_column]) else str(row[name_column])
        )
        for _, row in routes[[code_column, name_column]].drop_duplicates(code_column).iterrows()
    }


def _airport_search_label(code: str, names: dict[str, str]) -> str:
    name = names.get(code, "Airport name unavailable")
    shortened = name if len(name) <= 28 else f"{name[:26].rstrip()}…"
    return f"{code} · {shortened}"


def _render_route_information(
    period_text: str,
    study_year: str,
    methodology: pd.Series,
    eligible_route_count: int,
) -> None:
    with st.expander("Route information summary", expanded=False):
        st.markdown(
            f"""
            This page analyses directional scheduled routes observed in **{period_text}
            {study_year}**. A → B and B → A are treated as separate routes, and only
            aggregated results are published.

            Rankings require at least **{int(methodology['minimum_flights']):,} flights**
            and presence in **{int(methodology['minimum_periods'])} observed months**.
            **{eligible_route_count:,} routes** meet those requirements for the selected
            duration scope. Select a ranking-table row to highlight it in blue and update
            the map.
            """
        )
