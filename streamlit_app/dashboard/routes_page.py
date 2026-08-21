"""Routes analytics page and its route-specific visual components."""

import html

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from dashboard.common import section_anchor, style_chart
from dashboard.config import (
    BLUE,
    GREEN,
    NAVY,
    ROUTE_RANKING_METRICS,
    ROUTE_SCOPE_LABELS,
)
from dashboard.data import load_route_data


def _route_extreme_chart(
    frame: pd.DataFrame,
    metric: str,
    reliable: bool,
    selection_name: str,
    color: str,
) -> alt.Chart:
    sort_ascending = reliable
    top = frame.sort_values(
        [metric, "flight_count"], ascending=[sort_ascending, False]
    ).head(5).copy().reset_index(drop=True)
    suffix = ROUTE_RANKING_METRICS[metric]["suffix"]
    top["display_value"] = top[metric].map(lambda value: f"{value:.1f}{suffix}")
    minimum = min(0.0, float(top[metric].min()) * 1.18)
    maximum = max(float(top[metric].max()) * 1.20, 0.1)
    route_selection = alt.selection_point(
        name=selection_name,
        fields=["route"],
        on="click",
        clear="dblclick",
        empty=True,
    )
    bars = alt.Chart(top).mark_bar(color=color, cornerRadiusEnd=5, size=28).encode(
        y=alt.Y(
            "route:N",
            title=None,
            sort=top["route"].tolist(),
            axis=alt.Axis(labelLimit=170),
        ),
        x=alt.X(
            metric,
            type="quantitative",
            title=ROUTE_RANKING_METRICS[metric]["axis"],
            scale=alt.Scale(domain=[minimum, maximum], nice=False),
            axis=alt.Axis(tickCount=6),
        ),
        opacity=alt.condition(route_selection, alt.value(1.0), alt.value(0.48)),
        tooltip=[
            alt.Tooltip("route:N", title="Directional route"),
            alt.Tooltip("origin_airport_name:N", title="Origin"),
            alt.Tooltip("destination_airport_name:N", title="Destination"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("periods_active:Q", title="Observed months"),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed >15 min", format=".1f"),
            alt.Tooltip("median_arrival_delay_min:Q", title="Median delay", format=".1f"),
            alt.Tooltip("p90_arrival_delay_min:Q", title="P90 delay", format=".1f"),
        ],
    )
    labels = alt.Chart(top).mark_text(
        align="left",
        dx=7,
        color=NAVY,
        font="Aptos",
        fontSize=12,
        fontWeight="bold",
    ).encode(
        y=alt.Y("route:N", sort=top["route"].tolist()),
        x=alt.X(metric, type="quantitative"),
        text="display_value:N",
    )
    return style_chart(
        (bars + labels)
        .add_params(route_selection)
        .properties(height=245, width="container")
    )


def _selected_route_from_chart(event: object, selection_name: str) -> str | None:
    try:
        values = event.selection[selection_name]
    except (AttributeError, KeyError, TypeError):
        try:
            values = event["selection"][selection_name]
        except (KeyError, TypeError):
            return None
    if not values:
        return None
    selected = values[0] if isinstance(values, list) else values
    return selected.get("route") if isinstance(selected, dict) else None


def _newly_selected_route(selection_id: str, route: str | None) -> str | None:
    state_key = f"_previous_route_selection_{selection_id}"
    previous = st.session_state.get(state_key)
    st.session_state[state_key] = route
    return route if route and route != previous else None


@st.dialog("Route details", width="large", on_dismiss="ignore")
def _show_route_details(
    route_row: pd.Series,
    reverse_row: pd.Series | None,
    operator_rows: pd.DataFrame,
) -> None:
    origin_name = route_row.get("origin_airport_name")
    destination_name = route_row.get("destination_airport_name")
    origin_name = "Airport name unavailable" if pd.isna(origin_name) else str(origin_name)
    destination_name = (
        "Airport name unavailable" if pd.isna(destination_name) else str(destination_name)
    )
    st.markdown(f"## {route_row['route']}")
    airport_columns = st.columns(2)
    airport_columns[0].markdown(
        f"**Origin · {route_row['ADEP']}**  \n{origin_name}  \n"
        f"{route_row.get('origin_city', '')}, {route_row.get('origin_country', '')}"
    )
    airport_columns[1].markdown(
        f"**Destination · {route_row['ADES']}**  \n{destination_name}  \n"
        f"{route_row.get('destination_city', '')}, {route_row.get('destination_country', '')}"
    )
    route_metrics = st.columns(4)
    route_metrics[0].metric("Flights", f"{int(route_row['flight_count']):,}")
    route_metrics[1].metric("Delayed >15 min", f"{route_row['delay_over_15_pct']:.1f}%")
    route_metrics[2].metric(
        "Median delay", f"{route_row['median_arrival_delay_min']:.1f} min"
    )
    route_metrics[3].metric("P90 delay", f"{route_row['p90_arrival_delay_min']:.1f} min")

    st.markdown("### Opposite direction")
    if reverse_row is None:
        st.info("No opposite-direction route with at least two observed flights is available.")
    else:
        st.markdown(f"**{reverse_row['route']}**")
        reverse_metrics = st.columns(3)
        reverse_metrics[0].metric("Flights", f"{int(reverse_row['flight_count']):,}")
        reverse_metrics[1].metric(
            "Delayed >15 min", f"{reverse_row['delay_over_15_pct']:.1f}%"
        )
        reverse_metrics[2].metric(
            "Median delay", f"{reverse_row['median_arrival_delay_min']:.1f} min"
        )

    st.markdown("### Operating companies")
    if operator_rows.empty:
        st.info("No named operating-company aggregate is available for this route.")
        return

    operators = operator_rows.sort_values("flight_count", ascending=False).copy()
    operators.loc[
        operators["operator_code"].isin(["ZZZ", "UNK", "UNKNOWN"]), "operator_name"
    ] = "Unknown / not identified"
    operators["route_share_pct"] = (
        100 * operators["flight_count"] / operators["flight_count"].sum()
    )
    operators = operators.head(12).rename(
        columns={
            "operator_name": "Operating company",
            "operator_code": "ICAO",
            "flight_count": "Flights",
            "route_share_pct": "Route share (%)",
            "delay_over_15_pct": "Delayed >15 min (%)",
        }
    )
    st.dataframe(
        operators[
            [
                "Operating company",
                "ICAO",
                "Flights",
                "Route share (%)",
                "Delayed >15 min (%)",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Flights": st.column_config.NumberColumn(format="%d"),
            "Route share (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Delayed >15 min (%)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    if len(operator_rows) > 12:
        st.caption(f"Showing the 12 largest of {len(operator_rows):,} observed operators.")


def _route_volume_reliability_chart(
    frame: pd.DataFrame, network_delay_pct: float
) -> alt.Chart:
    plot = frame.copy()
    volume_minimum = int(plot["flight_count"].min())
    volume_median = int(plot["flight_count"].median())
    volume_maximum = int(plot["flight_count"].max())
    legend_values = sorted({volume_minimum, volume_median, volume_maximum})
    points = alt.Chart(plot).mark_circle(
        color=BLUE,
        opacity=0.68,
        stroke="white",
        strokeWidth=0.8,
    ).encode(
        x=alt.X(
            "flight_count:Q",
            title="Flights on the directional route (log scale)",
            scale=alt.Scale(type="log"),
            axis=alt.Axis(titlePadding=14, labelPadding=6),
        ),
        y=alt.Y(
            "delay_over_15_pct:Q",
            title="Delayed >15 min (%)",
            scale=alt.Scale(zero=False),
            axis=alt.Axis(titlePadding=16, labelPadding=6),
        ),
        size=alt.Size(
            "flight_count:Q",
            title="Route volume (flights)",
            scale=alt.Scale(domain=[volume_minimum, volume_maximum], range=[35, 520]),
            legend=alt.Legend(
                orient="bottom",
                direction="horizontal",
                format=",.0f",
                symbolType="circle",
                values=legend_values,
            ),
        ),
        tooltip=[
            alt.Tooltip("route:N", title="Directional route"),
            alt.Tooltip("origin_airport_name:N", title="Origin"),
            alt.Tooltip("destination_airport_name:N", title="Destination"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed >15 min", format=".1f"),
            alt.Tooltip("median_arrival_delay_min:Q", title="Median delay", format=".1f"),
        ],
    )
    reference = alt.Chart(pd.DataFrame({"network_rate": [network_delay_pct]})).mark_rule(
        color=GREEN, strokeDash=[6, 5], strokeWidth=2
    ).encode(
        y="network_rate:Q",
        tooltip=[
            alt.Tooltip("network_rate:Q", title="Network delayed >15 min", format=".1f")
        ],
    )
    return style_chart(
        (points + reference).properties(
            height=355,
            width="container",
            padding={"left": 14, "right": 12, "top": 8, "bottom": 10},
        )
    )


def _route_map_deck(route: pd.Series) -> pdk.Deck:
    source = [float(route["origin_longitude"]), float(route["origin_latitude"])]
    target = [float(route["destination_longitude"]), float(route["destination_latitude"])]
    arc_data = [
        {
            "route": route["route"],
            "source": source,
            "target": target,
            "delay_rate": float(route["delay_over_15_pct"]),
            "median_delay": float(route["median_arrival_delay_min"]),
            "flights": int(route["flight_count"]),
        }
    ]
    point_data = [
        {"airport": route["ADEP"], "position": source, "role": "Origin"},
        {"airport": route["ADES"], "position": target, "role": "Destination"},
    ]
    span = max(abs(source[0] - target[0]), abs(source[1] - target[1]))
    zoom = 2.0 if span > 45 else 3.0 if span > 18 else 4.5 if span > 6 else 6.0
    return pdk.Deck(
        map_style="light",
        initial_view_state=pdk.ViewState(
            latitude=(source[1] + target[1]) / 2,
            longitude=(source[0] + target[0]) / 2,
            zoom=zoom,
            pitch=25,
        ),
        layers=[
            pdk.Layer(
                "ArcLayer",
                arc_data,
                get_source_position="source",
                get_target_position="target",
                get_source_color=[47, 111, 176, 210],
                get_target_color=[46, 139, 104, 210],
                get_width=5,
                pickable=True,
                auto_highlight=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                point_data,
                get_position="position",
                get_fill_color=[11, 31, 51, 235],
                get_radius=35000,
                radius_min_pixels=7,
                radius_max_pixels=14,
                pickable=True,
            ),
        ],
        tooltip={
            "html": "<b>{route}</b><br/>Delayed &gt;15 min: {delay_rate}%<br/>"
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
    route_operators = route_data["operators"]
    pending_route_detail: str | None = None

    st.title("Route Reliability")
    st.markdown(
        f"""
        <div class="hero route-hero">
            <div class="eyebrow">Directional route intelligence</div>
            <p>Explore repeated delay exposure across scheduled routes observed in
            <b>{period_text} {study_year}</b>. Rankings use directional routes, so A → B and
            B → A are evaluated separately. The page publishes route aggregates only.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    section_anchor("route-scope", "route-section-anchor")
    with st.container(key="route_scope_filter"):
        st.markdown(
            '<div class="floating-filter-label">Flight-duration filter · applies to the full page</div>',
            unsafe_allow_html=True,
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
    scope_metrics = metrics[
        metrics["scope_id"].eq(scope_id) & metrics["executive_eligible"].eq(True)
    ].copy()

    _render_scope_summary(scope_summary, methodology, scope_metrics)
    pending_route_detail = _render_route_rankings(scope_id, scope_metrics)
    _render_operational_impact(
        scope_id, scope_summary, scope_metrics, route_monthly
    )
    _render_route_geography(scope_id, scope_metrics)
    _open_pending_route_detail(
        pending_route_detail, scope_id, metrics, route_operators
    )


def _render_scope_summary(
    scope_summary: pd.Series,
    methodology: pd.Series,
    scope_metrics: pd.DataFrame,
) -> None:
    with st.container(border=True):
        st.markdown(
            '<div class="section-kicker">01 · Selected operating scope</div>',
            unsafe_allow_html=True,
        )
        summary_cards = st.columns(3)
        summary_cards[0].metric("Flights in scope", f"{int(scope_summary['flight_count']):,}")
        summary_cards[1].metric(
            "Directional routes", f"{int(scope_summary['route_count']):,}"
        )
        summary_cards[2].metric(
            "Network delayed >15 min", f"{scope_summary['delay_over_15_pct']:.1f}%"
        )
        st.caption(
            f"Top-5 rankings require at least {int(methodology['minimum_flights']):,} flights "
            f"and presence in {int(methodology['minimum_periods'])} observed months. "
            f"{len(scope_metrics):,} routes meet that rule for the selected scope."
        )


def _render_route_rankings(scope_id: str, scope_metrics: pd.DataFrame) -> str | None:
    section_anchor("route-rankings", "route-section-anchor")
    with st.container(border=True):
        st.markdown(
            '<div class="section-kicker">02 · Most problematic routes</div>',
            unsafe_allow_html=True,
        )
        ranking_metric = st.segmented_control(
            "Ranking metric",
            options=list(ROUTE_RANKING_METRICS),
            default="delay_over_15_pct",
            format_func=lambda value: ROUTE_RANKING_METRICS[value]["label"],
            key="route_ranking_metric",
            width="stretch",
        ) or "delay_over_15_pct"
        if scope_metrics.empty:
            st.warning("No routes meet the ranking threshold for this duration scope.")
            return None

        ranking_columns = st.columns(2, gap="medium")
        problematic_selection = f"problematic_{scope_id}_{ranking_metric}"
        reliable_selection = f"reliable_{scope_id}_{ranking_metric}"
        with ranking_columns[0]:
            st.markdown(
                '<div class="ranking-chart-title">Most problematic routes</div>',
                unsafe_allow_html=True,
            )
            problematic_event = st.altair_chart(
                _route_extreme_chart(
                    scope_metrics, ranking_metric, False, problematic_selection, BLUE
                ),
                width="stretch",
                key=f"problematic_chart_{scope_id}_{ranking_metric}",
                on_select="rerun",
                selection_mode=problematic_selection,
            )
            st.caption("Highest values for the selected metric. Click a bar for route details.")
        with ranking_columns[1]:
            st.markdown(
                '<div class="ranking-chart-title">Most reliable routes</div>',
                unsafe_allow_html=True,
            )
            reliable_event = st.altair_chart(
                _route_extreme_chart(
                    scope_metrics, ranking_metric, True, reliable_selection, GREEN
                ),
                width="stretch",
                key=f"reliable_chart_{scope_id}_{ranking_metric}",
                on_select="rerun",
                selection_mode=reliable_selection,
            )
            st.caption("Lowest values for the selected metric. Click a bar for route details.")

        problematic_route = _selected_route_from_chart(
            problematic_event, problematic_selection
        )
        reliable_route = _selected_route_from_chart(reliable_event, reliable_selection)
        return _newly_selected_route(
            problematic_selection, problematic_route
        ) or _newly_selected_route(reliable_selection, reliable_route)


def _render_operational_impact(
    scope_id: str,
    scope_summary: pd.Series,
    scope_metrics: pd.DataFrame,
    route_monthly: pd.DataFrame,
) -> None:
    section_anchor("route-impact", "route-section-anchor")
    with st.container(border=True):
        st.markdown(
            '<div class="section-kicker">03 · Operational impact</div>',
            unsafe_allow_html=True,
        )
        if scope_metrics.empty:
            st.warning("No eligible routes are available for this scope.")
            return
        impact_columns = st.columns([0.85, 1.15], gap="medium")
        with impact_columns[0]:
            _render_volume_reliability(scope_id, scope_summary, scope_metrics)
        with impact_columns[1]:
            _render_popular_routes(scope_id, scope_metrics, route_monthly)


def _render_volume_reliability(
    scope_id: str, scope_summary: pd.Series, scope_metrics: pd.DataFrame
) -> None:
    st.markdown(
        '<div class="impact-chart-title">Volume vs reliability</div>',
        unsafe_allow_html=True,
    )
    maximum_volume = int(scope_metrics["flight_count"].max())
    slider_maximum = max(1_000, ((maximum_volume + 99) // 100) * 100)
    scatter_chart_slot = st.empty()
    scatter_caption_slot = st.empty()
    with st.container(key="route_scatter_controls"):
        control_columns = st.columns([3, 1], gap="medium")
        with control_columns[0]:
            st.markdown("**Filter visible routes**")
            default_threshold = 1_000 if scope_id == "scheduled_duration_3h_or_more" else 1_500
            minimum_route_volume = st.slider(
                "Minimum route volume",
                min_value=500,
                max_value=slider_maximum,
                value=min(default_threshold, slider_maximum),
                step=100,
                key=f"route_minimum_volume_{scope_id}",
                help="Only routes with at least this many flights are drawn.",
            )
        visible_routes = scope_metrics[
            scope_metrics["flight_count"].ge(minimum_route_volume)
        ].copy()
        with control_columns[1]:
            st.metric("Routes", f"{len(visible_routes):,}")
        st.caption(
            "Point size represents route flight volume. Move the threshold left to include "
            "smaller eligible routes."
        )
    scatter_chart_slot.altair_chart(
        _route_volume_reliability_chart(
            visible_routes, float(scope_summary["delay_over_15_pct"])
        ),
        width="stretch",
    )
    scatter_caption_slot.caption(
        "Upper-right routes combine poor reliability with recurrent exposure. "
        "The dashed line is the full selected-scope network average."
    )


def _render_popular_routes(
    scope_id: str, scope_metrics: pd.DataFrame, route_monthly: pd.DataFrame
) -> None:
    st.markdown(
        '<div class="impact-chart-title">10 most popular routes</div>',
        unsafe_allow_html=True,
    )
    popular = scope_metrics.nlargest(10, "flight_count").copy()
    popular = popular.sort_values("flight_count", ascending=False).reset_index(drop=True)
    monthly_scope = route_monthly[route_monthly["scope_id"].eq(scope_id)]
    period_order = sorted(monthly_scope["period"].dropna().astype(str).unique())
    period_labels = [pd.Timestamp(period).strftime("%B") for period in period_order]
    trend_lookup = {
        route: dict(zip(group["period"].astype(str), group["delay_over_15_pct"]))
        for route, group in monthly_scope.groupby("route", observed=True)
    }
    popular["Monthly OTP15 trend"] = popular["route"].map(
        lambda route: [trend_lookup.get(route, {}).get(period) for period in period_order]
    )
    popular["Airport names"] = (
        popular["origin_airport_name"].fillna("Name unavailable")
        + " → "
        + popular["destination_airport_name"].fillna("Name unavailable")
    )
    display = popular[
        [
            "route",
            "Airport names",
            "flight_count",
            "delay_over_15_pct",
            "Monthly OTP15 trend",
        ]
    ].rename(
        columns={
            "route": "Route",
            "flight_count": "Volume",
            "delay_over_15_pct": "OTP15 (%)",
        }
    )
    trend_maximum = max(
        10.0,
        float(
            monthly_scope[monthly_scope["route"].isin(popular["route"])][
                "delay_over_15_pct"
            ].max()
        )
        * 1.05,
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=368,
        row_height=50,
        column_config={
            "Route": st.column_config.TextColumn(width=85, pinned=True),
            "Airport names": st.column_config.TextColumn(
                width=210, help="Full origin → destination airport names"
            ),
            "Volume": st.column_config.NumberColumn(format="%d", width=58),
            "OTP15 (%)": st.column_config.NumberColumn(format="%.1f%%", width=70),
            "Monthly OTP15 trend": st.column_config.LineChartColumn(
                "Trend",
                width=100,
                help="Delayed >15 min percentage in " + " → ".join(period_labels),
                y_min=0,
                y_max=trend_maximum,
                color=BLUE,
            ),
        },
    )
    st.caption(
        "Sorted by flight volume. The mini-line follows the observed monthly OTP15 "
        "percentages from " + " → ".join(period_labels) + "."
    )


def _render_route_geography(scope_id: str, scope_metrics: pd.DataFrame) -> None:
    section_anchor("route-geography", "route-section-anchor")
    with st.container(border=True):
        st.markdown(
            '<div class="section-kicker">04 · Geographic context</div>',
            unsafe_allow_html=True,
        )
        st.subheader("Map the route with the highest delayed-flight percentage")
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
        selected_route = located.nlargest(1, "delay_over_15_pct").iloc[0]
        origin_name = selected_route.get("origin_airport_name")
        destination_name = selected_route.get("destination_airport_name")
        origin_name = "Airport name unavailable" if pd.isna(origin_name) else origin_name
        destination_name = (
            "Airport name unavailable" if pd.isna(destination_name) else destination_name
        )
        st.markdown(
            f"""
            <div class="route-identity-card">
                <div class="route-identity-label">Mapped directional route</div>
                <div class="route-identity-code">{html.escape(str(selected_route['route']))}</div>
                <div class="route-identity-names">
                    {html.escape(str(origin_name))} → {html.escape(str(destination_name))}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        map_cards = st.columns(2)
        map_cards[0].metric(
            "Delayed >15 min", f"{selected_route['delay_over_15_pct']:.1f}%"
        )
        map_cards[1].metric(
            "Median arrival delay", f"{selected_route['median_arrival_delay_min']:.1f} min"
        )
        st.pydeck_chart(
            _route_map_deck(selected_route),
            width="stretch",
            height=460,
            key=f"route_map_{scope_id}",
        )
        st.caption(
            "The arc shows the selected directional route. Airport points and coordinates "
            "are aggregated route context; no individual flight track is published."
        )


def _open_pending_route_detail(
    pending_route_detail: str | None,
    scope_id: str,
    metrics: pd.DataFrame,
    route_operators: pd.DataFrame,
) -> None:
    if not pending_route_detail:
        return
    route_match = metrics[
        metrics["scope_id"].eq(scope_id)
        & metrics["route"].eq(pending_route_detail)
    ]
    if route_match.empty:
        return
    selected_row = route_match.iloc[0]
    reverse_match = metrics[
        metrics["scope_id"].eq(scope_id)
        & metrics["ADEP"].eq(selected_row["ADES"])
        & metrics["ADES"].eq(selected_row["ADEP"])
    ]
    reverse_row = None if reverse_match.empty else reverse_match.iloc[0]
    selected_operators = route_operators[
        route_operators["scope_id"].eq(scope_id)
        & route_operators["route"].eq(pending_route_detail)
    ].copy()
    _show_route_details(selected_row, reverse_row, selected_operators)

