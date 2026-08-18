"""Streamlit dashboard for public, aggregated flight-delay analytics."""

from __future__ import annotations

import html
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st


APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = APP_ROOT / "public_data" / "introduction"
ROUTES_DATA_ROOT = APP_ROOT / "public_data" / "routes"

# Compact, accessible dashboard palette.
NAVY = "#0B1F33"
BLUE = "#2F6FB0"
LIGHT_BLUE = "#DCEAF7"
GREEN = "#2E8B68"
TEXT = "#23364A"
MUTED = "#66788A"
GRID = "#E5EDF4"


@st.cache_data
def load_public_data() -> dict[str, pd.DataFrame]:
    files = {
        "overview": "overview_kpis.csv",
        "monthly": "monthly_delay_trend.csv",
        "duration": "duration_hour_metrics.csv",
        "correlation": "correlation_metrics.csv",
        "concentration_summary": "delay_concentration_summary.csv",
        "metadata": "dashboard_metadata.csv",
    }
    missing = [filename for filename in files.values() if not (DATA_ROOT / filename).exists()]
    if missing:
        raise FileNotFoundError(
            "Missing public data: " + ", ".join(missing)
            + ". Run build_public_data.py first."
        )
    return {name: pd.read_csv(DATA_ROOT / filename) for name, filename in files.items()}


@st.cache_data
def load_route_data(cache_version: str = "route_drilldown_v1") -> dict[str, pd.DataFrame]:
    # cache_version deliberately invalidates older route-dashboard sessions.
    del cache_version
    files = {
        "metrics": "route_metrics.csv",
        "summary": "route_scope_summary.csv",
        "methodology": "route_ranking_methodology.csv",
        "monthly": "route_monthly_metrics.csv",
        "operators": "route_operator_metrics.csv",
    }
    missing = [filename for filename in files.values() if not (ROUTES_DATA_ROOT / filename).exists()]
    if missing:
        raise FileNotFoundError(
            "Missing route data: " + ", ".join(missing)
            + ". Run build_public_data.py first."
        )
    return {
        name: pd.read_csv(ROUTES_DATA_ROOT / filename)
        for name, filename in files.items()
    }


def style_chart(chart: alt.Chart) -> alt.Chart:
    """Apply the same clean visual language to every chart."""

    return (
        chart
        .configure_view(strokeWidth=0)
        .configure_axis(
            domain=False,
            gridColor=GRID,
            gridOpacity=1,
            labelColor=MUTED,
            labelFont="Aptos",
            labelFontSize=12,
            titleColor=TEXT,
            titleFont="Aptos",
            titleFontSize=13,
            titleFontWeight="normal",
        )
        .configure_legend(
            labelColor=TEXT,
            labelFont="Aptos",
            labelFontSize=12,
            titleColor=TEXT,
            titleFont="Aptos",
        )
    )


def section_anchor(anchor_id: str, extra_class: str = "") -> None:
    classes = f"section-anchor {extra_class}".strip()
    st.markdown(f'<div id="{anchor_id}" class="{classes}"></div>', unsafe_allow_html=True)


def comparison_card(column, label: str, value: str, note: str) -> None:
    """Render an explanatory KPI without ambiguous arrows or abbreviations."""

    column.markdown(
        f"""
        <div class="comparison-card">
            <div class="comparison-label">{label}</div>
            <div class="comparison-value">{value}</div>
            <div class="comparison-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


ROUTE_SCOPE_LABELS = {
    "all_flights": "All flights",
    "scheduled_duration_under_3h": "Under 3 hours",
    "scheduled_duration_3h_or_more": "3 hours or more",
}


ROUTE_RANKING_METRICS = {
    "delay_over_15_pct": {
        "label": "Delayed-flight percentage",
        "axis": "Flights arriving more than 15 minutes late (%)",
        "suffix": "%",
    },
    "median_arrival_delay_min": {
        "label": "Median arrival delay",
        "axis": "Median arrival delay (minutes)",
        "suffix": " min",
    },
}


def route_extreme_chart(
    frame: pd.DataFrame,
    metric: str,
    reliable: bool,
    selection_name: str,
    color: str,
) -> alt.Chart:
    """Return a selectable Top-5 chart for the weakest or strongest routes."""

    if reliable:
        top = frame.sort_values(
            [metric, "flight_count"], ascending=[True, False]
        ).head(5)
    else:
        top = frame.sort_values(
            [metric, "flight_count"], ascending=[False, False]
        ).head(5)
    top = top.copy().reset_index(drop=True)
    suffix = ROUTE_RANKING_METRICS[metric]["suffix"]
    top["display_value"] = top[metric].map(
        lambda value: f"{value:.1f}{suffix}"
    )
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
        y=alt.Y("route:N", title=None, sort=top["route"].tolist(), axis=alt.Axis(labelLimit=170)),
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
        align="left", dx=7, color=NAVY, font="Aptos", fontSize=12, fontWeight="bold"
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


def selected_route_from_chart(event: object, selection_name: str) -> str | None:
    """Extract one route code from a Streamlit Altair selection event."""

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
    if isinstance(selected, dict):
        return selected.get("route")
    return None


def newly_selected_route(selection_id: str, route: str | None) -> str | None:
    """Return a route only when a chart or table selection has changed."""

    state_key = f"_previous_route_selection_{selection_id}"
    previous = st.session_state.get(state_key)
    st.session_state[state_key] = route
    return route if route and route != previous else None


@st.dialog("Route details", width="large", on_dismiss="ignore")
def show_route_details(
    route_row: pd.Series,
    reverse_row: pd.Series | None,
    operator_rows: pd.DataFrame,
) -> None:
    """Show aggregated route context without exposing flight-level data."""

    origin_name = route_row.get("origin_airport_name")
    destination_name = route_row.get("destination_airport_name")
    origin_name = "Airport name unavailable" if pd.isna(origin_name) else str(origin_name)
    destination_name = "Airport name unavailable" if pd.isna(destination_name) else str(destination_name)
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
    route_metrics[2].metric("Median delay", f"{route_row['median_arrival_delay_min']:.1f} min")
    route_metrics[3].metric("P90 delay", f"{route_row['p90_arrival_delay_min']:.1f} min")

    st.markdown("### Opposite direction")
    if reverse_row is None:
        st.info("No opposite-direction route with at least two observed flights is available.")
    else:
        st.markdown(f"**{reverse_row['route']}**")
        reverse_metrics = st.columns(3)
        reverse_metrics[0].metric("Flights", f"{int(reverse_row['flight_count']):,}")
        reverse_metrics[1].metric("Delayed >15 min", f"{reverse_row['delay_over_15_pct']:.1f}%")
        reverse_metrics[2].metric(
            "Median delay", f"{reverse_row['median_arrival_delay_min']:.1f} min"
        )

    st.markdown("### Operating companies")
    if operator_rows.empty:
        st.info("No named operating-company aggregate is available for this route.")
    else:
        operators = operator_rows.sort_values("flight_count", ascending=False).copy()
        operators.loc[
            operators["operator_code"].isin(["ZZZ", "UNK", "UNKNOWN"]),
            "operator_name",
        ] = "Unknown / not identified"
        operators["route_share_pct"] = 100 * operators["flight_count"] / operators["flight_count"].sum()
        operators = operators.head(12).rename(columns={
            "operator_name": "Operating company",
            "operator_code": "ICAO",
            "flight_count": "Flights",
            "route_share_pct": "Route share (%)",
            "delay_over_15_pct": "Delayed >15 min (%)",
        })
        st.dataframe(
            operators[[
                "Operating company", "ICAO", "Flights",
                "Route share (%)", "Delayed >15 min (%)",
            ]],
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


def route_volume_reliability_chart(
    frame: pd.DataFrame,
    network_delay_pct: float,
) -> alt.Chart:
    """Relate eligible route volume to the share delayed more than 15 minutes."""

    plot = frame.copy()
    plot["volume_label"] = plot["flight_count"].map(lambda value: f"{int(value):,} flights")
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
            scale=alt.Scale(
                domain=[volume_minimum, volume_maximum],
                range=[35, 520],
            ),
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
        color=GREEN,
        strokeDash=[6, 5],
        strokeWidth=2,
    ).encode(
        y="network_rate:Q",
        tooltip=[alt.Tooltip("network_rate:Q", title="Network delayed >15 min", format=".1f")],
    )
    return style_chart(
        (points + reference).properties(
            height=355,
            width="container",
            padding={"left": 14, "right": 12, "top": 8, "bottom": 10},
        )
    )


def popular_route_chart(frame: pd.DataFrame) -> alt.Chart:
    """Show volume and reliability together for the ten busiest eligible routes."""

    popular = frame.nlargest(10, ["flight_count", "delay_over_15_pct"]).copy()
    popular = popular.sort_values("flight_count")
    popular["display_value"] = popular.apply(
        lambda row: f"{int(row['flight_count']):,} · {row['delay_over_15_pct']:.1f}%",
        axis=1,
    )
    maximum = max(float(popular["flight_count"].max()), 1.0)
    bars = alt.Chart(popular).mark_bar(cornerRadiusEnd=5, size=23).encode(
        y=alt.Y(
            "route:N",
            title=None,
            sort=popular["route"].tolist(),
            axis=alt.Axis(labelLimit=155),
        ),
        x=alt.X(
            "flight_count:Q",
            title="Number of flights",
            scale=alt.Scale(domain=[0, maximum * 1.30], nice=False),
            axis=None,
        ),
        color=alt.Color(
            "delay_over_15_pct:Q",
            legend=None,
            scale=alt.Scale(scheme="blues", domainMid=25),
        ),
        tooltip=[
            alt.Tooltip("route:N", title="Directional route"),
            alt.Tooltip("origin_airport_name:N", title="Origin"),
            alt.Tooltip("destination_airport_name:N", title="Destination"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed >15 min", format=".1f"),
        ],
    )
    labels = alt.Chart(popular).mark_text(
        align="left",
        dx=7,
        color=NAVY,
        font="Aptos",
        fontSize=11,
        fontWeight="bold",
    ).encode(
        y=alt.Y("route:N", sort=popular["route"].tolist()),
        x="flight_count:Q",
        text="display_value:N",
    )
    return style_chart((bars + labels).properties(height=355, width="container"))


def route_map_deck(route: pd.Series) -> pdk.Deck:
    """Draw one directional route without publishing any flight-level location."""

    source = [float(route["origin_longitude"]), float(route["origin_latitude"])]
    target = [float(route["destination_longitude"]), float(route["destination_latitude"])]
    arc_data = [{
        "route": route["route"],
        "source": source,
        "target": target,
        "delay_rate": float(route["delay_over_15_pct"]),
        "median_delay": float(route["median_arrival_delay_min"]),
        "flights": int(route["flight_count"]),
    }]
    point_data = [
        {"airport": route["ADEP"], "position": source, "role": "Origin"},
        {"airport": route["ADES"], "position": target, "role": "Destination"},
    ]
    longitude_span = abs(source[0] - target[0])
    latitude_span = abs(source[1] - target[1])
    span = max(longitude_span, latitude_span)
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
    """Render the first public Routes analytics page."""

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
    if scope_id is None:
        scope_id = "all_flights"
    scope_summary = summary.loc[scope_id]
    scope_metrics = metrics[
        metrics["scope_id"].eq(scope_id) & metrics["executive_eligible"].eq(True)
    ].copy()

    with st.container(border=True):
        st.markdown('<div class="section-kicker">01 · Selected operating scope</div>', unsafe_allow_html=True)
        summary_cards = st.columns(3)
        summary_cards[0].metric("Flights in scope", f"{int(scope_summary['flight_count']):,}")
        summary_cards[1].metric("Directional routes", f"{int(scope_summary['route_count']):,}")
        summary_cards[2].metric("Network delayed >15 min", f"{scope_summary['delay_over_15_pct']:.1f}%")
        st.caption(
            f"Top-5 rankings require at least {int(methodology['minimum_flights']):,} flights "
            f"and presence in {int(methodology['minimum_periods'])} observed months. "
            f"{len(scope_metrics):,} routes meet that rule for the selected scope."
        )

    section_anchor("route-rankings", "route-section-anchor")
    with st.container(border=True):
        st.markdown('<div class="section-kicker">02 · Most problematic routes</div>', unsafe_allow_html=True)
        ranking_metric = st.segmented_control(
            "Ranking metric",
            options=list(ROUTE_RANKING_METRICS),
            default="delay_over_15_pct",
            format_func=lambda value: ROUTE_RANKING_METRICS[value]["label"],
            key="route_ranking_metric",
            width="stretch",
        )
        ranking_metric = ranking_metric or "delay_over_15_pct"
        if scope_metrics.empty:
            st.warning("No routes meet the ranking threshold for this duration scope.")
        else:
            ranking_columns = st.columns(2, gap="medium")
            problematic_selection = f"problematic_{scope_id}_{ranking_metric}"
            reliable_selection = f"reliable_{scope_id}_{ranking_metric}"
            with ranking_columns[0]:
                st.markdown(
                    '<div class="ranking-chart-title">Most problematic routes</div>',
                    unsafe_allow_html=True,
                )
                problematic_event = st.altair_chart(
                    route_extreme_chart(
                        scope_metrics,
                        ranking_metric,
                        False,
                        problematic_selection,
                        BLUE,
                    ),
                    width="stretch",
                    key=f"problematic_chart_{scope_id}_{ranking_metric}",
                    on_select="rerun",
                    selection_mode=problematic_selection,
                )
                st.caption(
                    "Highest values for the selected metric. Click a bar for route details."
                )
            with ranking_columns[1]:
                st.markdown(
                    '<div class="ranking-chart-title">Most reliable routes</div>',
                    unsafe_allow_html=True,
                )
                reliable_event = st.altair_chart(
                    route_extreme_chart(
                        scope_metrics,
                        ranking_metric,
                        True,
                        reliable_selection,
                        GREEN,
                    ),
                    width="stretch",
                    key=f"reliable_chart_{scope_id}_{ranking_metric}",
                    on_select="rerun",
                    selection_mode=reliable_selection,
                )
                st.caption(
                    "Lowest values for the selected metric. Click a bar for route details."
                )
            problematic_route = selected_route_from_chart(
                problematic_event, problematic_selection
            )
            reliable_route = selected_route_from_chart(reliable_event, reliable_selection)
            pending_route_detail = (
                newly_selected_route(problematic_selection, problematic_route)
                or newly_selected_route(reliable_selection, reliable_route)
            )

    section_anchor("route-impact", "route-section-anchor")
    with st.container(border=True):
        st.markdown('<div class="section-kicker">03 · Operational impact</div>', unsafe_allow_html=True)
        if scope_metrics.empty:
            st.warning("No eligible routes are available for this scope.")
        else:
            impact_columns = st.columns([0.85, 1.15], gap="medium")
            with impact_columns[0]:
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
                        default_volume_threshold = (
                            1_000 if scope_id == "scheduled_duration_3h_or_more" else 1_500
                        )
                        minimum_route_volume = st.slider(
                            "Minimum route volume",
                            min_value=500,
                            max_value=slider_maximum,
                            value=min(default_volume_threshold, slider_maximum),
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
                        "Point size represents route flight volume. Move the threshold left to "
                        "include smaller eligible routes."
                    )
                scatter_chart_slot.altair_chart(
                    route_volume_reliability_chart(
                        visible_routes,
                        float(scope_summary["delay_over_15_pct"]),
                    ),
                    width="stretch",
                )
                scatter_caption_slot.caption(
                    "Upper-right routes combine poor reliability with recurrent exposure. "
                    "The dashed line is the full selected-scope network average."
                )
            with impact_columns[1]:
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
                    lambda route: [
                        trend_lookup.get(route, {}).get(period, None)
                        for period in period_order
                    ]
                )
                popular["Airport names"] = (
                    popular["origin_airport_name"].fillna("Name unavailable")
                    + " → "
                    + popular["destination_airport_name"].fillna("Name unavailable")
                )
                popular_display = popular[[
                    "route", "Airport names", "flight_count",
                    "delay_over_15_pct", "Monthly OTP15 trend",
                ]].rename(columns={
                    "route": "Route",
                    "flight_count": "Volume",
                    "delay_over_15_pct": "OTP15 (%)",
                })
                trend_maximum = max(
                    10.0,
                    float(monthly_scope[
                        monthly_scope["route"].isin(popular["route"])
                    ]["delay_over_15_pct"].max()) * 1.05,
                )
                st.dataframe(
                    popular_display,
                    hide_index=True,
                    width="stretch",
                    height=368,
                    row_height=50,
                    column_config={
                        "Route": st.column_config.TextColumn(width=85, pinned=True),
                        "Airport names": st.column_config.TextColumn(
                            width=210,
                            help="Full origin → destination airport names",
                        ),
                        "Volume": st.column_config.NumberColumn(format="%d", width=58),
                        "OTP15 (%)": st.column_config.NumberColumn(
                            format="%.1f%%", width=70
                        ),
                        "Monthly OTP15 trend": st.column_config.LineChartColumn(
                            "Trend",
                            width=100,
                            help=(
                                "Delayed >15 min percentage in "
                                + " → ".join(period_labels)
                            ),
                            y_min=0,
                            y_max=trend_maximum,
                            color=BLUE,
                        ),
                    },
                )
                st.caption(
                    "Sorted by flight volume. The mini-line follows the observed monthly "
                    "OTP15 percentages from " + " → ".join(period_labels) + "."
                )

    section_anchor("route-geography", "route-section-anchor")
    with st.container(border=True):
        st.markdown('<div class="section-kicker">04 · Geographic context</div>', unsafe_allow_html=True)
        st.subheader("Map the route with the highest delayed-flight percentage")
        located = scope_metrics.dropna(subset=[
            "origin_latitude", "origin_longitude",
            "destination_latitude", "destination_longitude",
        ])
        if located.empty:
            st.info("No coordinate-complete eligible route is available for this filter.")
        else:
            selected_route = located.nlargest(1, "delay_over_15_pct").iloc[0]
            origin_name = selected_route.get("origin_airport_name")
            destination_name = selected_route.get("destination_airport_name")
            if pd.isna(origin_name):
                origin_name = "Airport name unavailable"
            if pd.isna(destination_name):
                destination_name = "Airport name unavailable"
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
            map_cards[0].metric("Delayed >15 min", f"{selected_route['delay_over_15_pct']:.1f}%")
            map_cards[1].metric("Median arrival delay", f"{selected_route['median_arrival_delay_min']:.1f} min")
            st.pydeck_chart(
                route_map_deck(selected_route),
                width="stretch",
                height=460,
                key=f"route_map_{scope_id}",
            )
            st.caption(
                "The arc shows the selected directional route. Airport points and coordinates "
                "are aggregated route context; no individual flight track is published."
            )

    if pending_route_detail:
        route_match = metrics[
            metrics["scope_id"].eq(scope_id)
            & metrics["route"].eq(pending_route_detail)
        ]
        if not route_match.empty:
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
            show_route_details(selected_row, reverse_row, selected_operators)

st.set_page_config(
    page_title="European Flight Delay Analytics",
    page_icon="✈️",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --navy: #0B1F33;
        --blue: #2F6FB0;
        --pale-blue: #EAF3FA;
        --green: #2E8B68;
        --text: #23364A;
        --muted: #66788A;
        --border: #D7E3ED;
    }
    [data-testid="stAppViewContainer"] { background: #EAF3FA; }
    [data-testid="stHeader"] {
        background: #0B0F14;
        border-bottom: 1px solid #28323D;
    }
    [data-testid="stHeader"] * { color: #FFFFFF !important; }
    [data-testid="stToolbar"] { right: 0.75rem; }
    [data-testid="stMainBlockContainer"] {
        max-width: 1440px;
        padding-top: 4.8rem;
        padding-right: 2rem;
        padding-left: 248px;
        padding-bottom: 4rem;
        transition: padding-left 180ms ease;
    }
    body, p, div, span, a, button, input, label {
        font-family: "Aptos", "Inter", "Segoe UI", Arial, sans-serif;
    }
    .stApp p, .stApp a, .stApp button, .stApp label, .stApp input,
    .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] {
        font-family: "Aptos", "Inter", "Segoe UI", Arial, sans-serif !important;
    }
    h1, h2, h3, .ranking-chart-title, .impact-chart-title {
        font-family: "Aptos Display", "Aptos", "Inter", "Segoe UI", Arial, sans-serif !important;
    }
    h1 {
        color: var(--navy);
        letter-spacing: -0.025em;
        font-size: 2.65rem !important;
        font-weight: 700 !important;
    }
    h2, h3 {
        color: var(--navy);
        letter-spacing: -0.012em;
        font-weight: 650 !important;
    }
    p { color: var(--text); line-height: 1.55; }
    .brand-bar {
        background: #0B0F14;
        color: #FFFFFF;
        border-radius: 12px;
        padding: 11px 17px;
        margin-bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        scroll-margin-top: 74px;
    }
    .brand-bar .edition { color: #A9BED0; font-weight: 500; }
    .journey-map {
        background: #FFFFFF;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        box-shadow: 0 5px 18px rgba(11, 31, 51, 0.05);
    }
    .journey-map .map-label {
        color: var(--muted);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.09em;
        margin-right: 5px;
    }
    .journey-map a {
        color: var(--navy) !important;
        text-decoration: none;
        font-size: 0.84rem;
        font-weight: 600;
        padding: 5px 9px;
        border-radius: 7px;
        background: #F3F7FA;
    }
    .journey-map a:hover { background: var(--pale-blue); color: var(--blue) !important; }
    .journey-map .arrow { color: #9AAABA; }
    .st-key-page_index_toggle {
        position: fixed;
        left: 178px;
        top: 72px;
        z-index: 1004;
        width: 34px;
        height: 34px;
        transition: left 180ms ease;
        padding: 0 !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        overflow: visible !important;
    }
    .st-key-page_index_toggle button {
        width: 34px !important;
        min-width: 34px !important;
        max-width: 34px !important;
        height: 34px;
        min-height: 34px;
        padding: 0;
        background: #FFFFFF;
        color: #0B1F33;
        border: 1px solid #C9D7E3;
        border-radius: 50%;
        box-shadow: 0 4px 14px rgba(11, 31, 51, 0.14);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .st-key-page_index_toggle button:hover {
        color: #2F6FB0;
        border-color: #7FAED8;
    }
    .st-key-page_index_toggle button p {
        width: 16px;
        height: 12px;
        margin: 0;
        padding: 0;
        overflow: visible;
        font-size: 0;
        line-height: 0;
    }
    .st-key-page_index_toggle button p::before {
        content: "";
        display: block;
        width: 16px;
        height: 2px;
        margin-top: 1px;
        border-radius: 2px;
        background: #0B1F33;
        box-shadow: 0 5px 0 #0B1F33, 0 10px 0 #0B1F33;
    }
    .left-index {
        position: fixed;
        left: 0;
        top: 59px;
        bottom: 0;
        width: 222px;
        z-index: 1000;
        background: #0B0F14;
        border-right: 1px solid #28323D;
        padding: 62px 12px 18px;
        box-shadow: 8px 0 28px rgba(11, 15, 20, 0.14);
        transition: width 180ms ease;
        overflow: hidden;
    }
    .left-index .index-title {
        color: #8FA4B8;
        font-size: 0.69rem;
        font-weight: 700;
        letter-spacing: 0.10em;
        margin: 0 8px 10px;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .st-key-page_navigation {
        position: fixed;
        left: 12px;
        top: 142px;
        width: 198px;
        z-index: 1002;
        padding: 0 !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        overflow: visible !important;
        transition: width 180ms ease;
    }
    .st-key-page_navigation [data-testid="stVerticalBlock"] { gap: 7px; }
    .st-key-page_navigation button {
        width: 100%;
        min-height: 46px;
        justify-content: flex-start;
        color: #EAF3FA;
        background: #1A2B3B;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 0 12px;
    }
    .st-key-page_navigation button:hover {
        color: #FFFFFF;
        background: #243C52;
        border-color: #35516A;
    }
    .st-key-page_navigation button[kind="primary"] {
        color: #FFFFFF;
        background: #304B68;
        border-color: #6E9BC3;
        box-shadow: inset 3px 0 0 #A6C8E6;
    }
    .st-key-page_navigation button span[data-testid="stIconMaterial"] {
        color: #D8E9F5;
        font-size: 1.25rem;
    }
    .st-key-page_navigation button p {
        color: inherit !important;
        margin: 0;
    }
    .left-index.collapsed { width: 66px; }
    .left-index.collapsed .index-title { display: none; }
    .hero {
        background: #D8E9F5;
        border: 1px solid #BCD3E4;
        border-radius: 14px;
        padding: 18px 21px;
        margin: 4px 0 22px;
        box-shadow: 0 7px 22px rgba(11, 31, 51, 0.06);
    }
    .hero .eyebrow {
        color: var(--blue);
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .hero p { margin: 0; }
    [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not(.st-key-page_index_toggle):not(.st-key-page_navigation) {
        background: #FFFFFF;
        border: 1px solid var(--border) !important;
        border-radius: 15px !important;
        box-shadow: 0 7px 22px rgba(11, 31, 51, 0.06);
        padding: 7px 9px 10px;
        margin-bottom: 17px;
    }
    [data-testid="stMetric"] {
        background: #F7FAFC;
        border: 1px solid #DDE7EF;
        border-radius: 11px;
        padding: 14px 15px;
        min-height: 112px;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: var(--navy); letter-spacing: -0.025em; }
    [data-testid="stMetricDelta"] { white-space: normal; line-height: 1.25; }
    .comparison-card {
        background: #F7FAFC;
        border: 1px solid #DDE7EF;
        border-radius: 11px;
        padding: 14px 15px;
        min-height: 126px;
    }
    .comparison-label { color: var(--muted); font-size: 0.92rem; margin-bottom: 6px; }
    .comparison-value {
        color: var(--navy);
        font-size: 2rem;
        letter-spacing: -0.025em;
        line-height: 1.1;
        margin-bottom: 9px;
    }
    .comparison-note {
        color: #40566B;
        font-size: 0.83rem;
        line-height: 1.3;
    }
    .st-key-overview_metrics {
        padding-top: 14px;
        padding-bottom: 10px;
    }
    [data-testid="stVegaLiteChart"] {
        background: #FFFFFF;
        border: 1px solid #E2EAF1;
        border-radius: 11px;
        padding: 8px 8px 3px;
    }
    .section-anchor { scroll-margin-top: 72px; }
    .route-section-anchor { scroll-margin-top: 148px; }
    .section-kicker {
        color: var(--blue);
        font-size: 0.73rem;
        font-weight: 700;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        margin-bottom: -4px;
    }
    [data-testid="stLayoutWrapper"]:has(> .st-key-route_scope_filter) {
        position: sticky !important;
        top: 62px;
        z-index: 995;
    }
    .st-key-route_scope_filter {
        position: static !important;
        background: rgba(255, 255, 255, 0.97) !important;
        border: 1px solid #BFD2E2 !important;
        border-radius: 13px !important;
        box-shadow: 0 8px 24px rgba(11, 31, 51, 0.13) !important;
        padding: 9px 13px 11px !important;
        margin: 0 0 17px !important;
        backdrop-filter: blur(8px);
    }
    .st-key-route_scope_filter [data-testid="stVerticalBlock"] { gap: 5px; }
    .floating-filter-label {
        color: var(--muted);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.055em;
        text-transform: uppercase;
    }
    .route-identity-card {
        width: 100%;
        box-sizing: border-box;
        background: linear-gradient(135deg, #F3F8FC 0%, #E8F2F8 100%);
        border: 1px solid #C8DBE9;
        border-radius: 12px;
        padding: 15px 17px;
        margin: 7px 0 12px;
        overflow: visible;
    }
    .route-identity-label {
        color: var(--muted);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .route-identity-code {
        color: var(--navy);
        font-size: clamp(1.55rem, 3vw, 2.25rem);
        font-weight: 720;
        letter-spacing: -0.025em;
        line-height: 1.15;
        white-space: normal;
        overflow: visible;
        overflow-wrap: anywhere;
        text-overflow: clip;
    }
    .route-identity-names {
        color: #40566B;
        font-size: 0.95rem;
        line-height: 1.35;
        margin-top: 5px;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .ranking-chart-title {
        min-height: 62px;
        display: flex;
        align-items: flex-end;
        color: var(--navy);
        font-size: 1.48rem;
        font-weight: 650;
        letter-spacing: -0.018em;
        line-height: 1.18;
        padding: 4px 0 9px;
        box-sizing: border-box;
    }
    .impact-chart-title {
        min-height: 54px;
        display: flex;
        align-items: flex-end;
        color: var(--navy);
        font-size: 1.48rem;
        font-weight: 650;
        letter-spacing: -0.018em;
        line-height: 1.18;
        padding: 4px 0 9px;
        box-sizing: border-box;
    }
    .st-key-route_scatter_controls {
        height: auto;
        background: #F3F8FC !important;
        border: 1px solid #D3E1EC !important;
        border-radius: 12px !important;
        padding: 12px 15px 9px !important;
        margin-top: 10px !important;
        box-shadow: none !important;
    }
    .st-key-route_scatter_controls [data-testid="stMetric"] {
        min-height: 86px;
        margin-top: 2px;
    }
    .impact-divider {
        height: 1px;
        background: #DDE7EF;
        margin: 24px 4px 18px;
    }
    [data-testid="stVegaLiteChart"],
    [data-testid="stVegaLiteChart"] > div {
        box-sizing: border-box !important;
        max-width: 100% !important;
    }
    [data-testid="stVegaLiteChart"] {
        width: calc(100% - 24px) !important;
        margin-right: 12px !important;
        margin-left: 12px !important;
        overflow: hidden;
    }
    [data-testid="stVegaLiteChart"] > div {
        width: 100% !important;
    }
    @media (max-width: 900px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 205px;
            padding-right: 1rem;
        }
        .left-index { width: 184px; }
        .st-key-page_index_toggle { left: 143px; }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        [data-testid="column"] {
            flex: 1 1 220px !important;
            min-width: 0 !important;
        }
    }
    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 82px;
            padding-right: 0.7rem;
        }
        .left-index { width: 60px; }
        .left-index .index-title { display: none; }
        .st-key-page_index_toggle { left: 12px; }
        .st-key-page_navigation { width: 42px !important; }
        .st-key-page_navigation button {
            justify-content: center !important;
            padding: 0 !important;
        }
        .st-key-page_navigation button p { display: none !important; }
        .journey-map .arrow { display: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    data = load_public_data()
except FileNotFoundError as error:
    st.error(str(error))
    st.stop()

overview = data["overview"]
monthly = data["monthly"]
monthly["period"] = pd.to_datetime(monthly["period"])
duration = data["duration"].sort_values("hour_order")
correlation = data["correlation"].iloc[0]
concentration_summary = data["concentration_summary"].sort_values("segment_order")
metadata = dict(zip(data["metadata"]["key"], data["metadata"]["value"]))
available_periods = [value.strip() for value in metadata["available_periods"].split(",")]
period_dates = pd.to_datetime(available_periods, format="%Y%m")
period_text = ", ".join(period_dates.strftime("%B"))
study_year = metadata["study_year"]
all_row = overview.set_index("scope_id").loc["all_flights"]
short_row = overview.set_index("scope_id").loc["scheduled_duration_under_3h"]
requested_page = st.query_params.get("page", "introduction")
current_page = requested_page if requested_page in {"introduction", "routes"} else "introduction"

if "page_index_expanded" not in st.session_state:
    st.session_state.page_index_expanded = True


def toggle_page_index() -> None:
    st.session_state.page_index_expanded = not st.session_state.page_index_expanded


index_expanded = st.session_state.page_index_expanded
index_class = "expanded" if index_expanded else "collapsed"
desktop_left = 248 if index_expanded else 88
tablet_left = 205 if index_expanded else 88
toggle_left = 178 if index_expanded else 15
tablet_toggle_left = 143 if index_expanded else 15
page_navigation_width = 198 if index_expanded else 42
tablet_navigation_width = 160 if index_expanded else 42
page_navigation_text_display = "block" if index_expanded else "none"
page_navigation_alignment = "flex-start" if index_expanded else "center"
page_navigation_padding = "0 12px" if index_expanded else "0"

st.markdown(
    f"""
    <style>
    @media (min-width: 901px) {{
        [data-testid="stMainBlockContainer"] {{ padding-left: {desktop_left}px !important; }}
        .st-key-page_index_toggle {{ left: {toggle_left}px !important; }}
        .st-key-page_navigation {{ width: {page_navigation_width}px !important; }}
    }}
    @media (min-width: 641px) and (max-width: 900px) {{
        [data-testid="stMainBlockContainer"] {{ padding-left: {tablet_left}px !important; }}
        .st-key-page_index_toggle {{ left: {tablet_toggle_left}px !important; }}
        .st-key-page_navigation {{ width: {tablet_navigation_width}px !important; }}
        .left-index.expanded {{ width: 184px; }}
    }}
    .st-key-page_navigation button {{
        justify-content: {page_navigation_alignment} !important;
        padding: {page_navigation_padding} !important;
    }}
    .st-key-page_navigation button p {{ display: {page_navigation_text_display}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="page_index_toggle"):
    st.button(
        "☰",
        key="toggle_page_index",
        help="Expand or collapse the page index",
        on_click=toggle_page_index,
    )


def navigate_to(page_name: str) -> None:
    st.query_params["page"] = page_name


with st.container(key="page_navigation"):
    st.button(
        "Introduction",
        key="navigate_introduction",
        icon=":material/home:",
        type="primary" if current_page == "introduction" else "secondary",
        help="Open the Introduction page",
        on_click=navigate_to,
        args=("introduction",),
        width="stretch",
    )
    st.button(
        "Routes",
        key="navigate_routes",
        icon=":material/map:",
        type="primary" if current_page == "routes" else "secondary",
        help="Open the Routes page",
        on_click=navigate_to,
        args=("routes",),
        width="stretch",
    )

if current_page == "routes":
    top_navigation_html = f"""
    <div class="brand-bar" id="routes-top">
        <span>European aviation intelligence</span>
        <span class="edition">Routes · ADRR {study_year}</span>
    </div>
    <div class="journey-map">
        <span class="map-label">ROUTES MAP</span>
        <a href="#route-scope">Scope</a><span class="arrow">→</span>
        <a href="#route-rankings">Rankings</a><span class="arrow">→</span>
        <a href="#route-impact">Impact</a><span class="arrow">→</span>
        <a href="#route-geography">Route map</a>
    </div>
    """
else:
    top_navigation_html = f"""
    <div class="brand-bar" id="introduction">
        <span>European aviation intelligence</span>
        <span class="edition">ADRR · {study_year} snapshots</span>
    </div>
    <div class="journey-map">
        <span class="map-label">ANALYSIS MAP</span>
        <a href="#overview">Network overview</a><span class="arrow">→</span>
        <a href="#comparison">Flight scope</a><span class="arrow">→</span>
        <a href="#trend">Time trend</a><span class="arrow">→</span>
        <a href="#reliability">Reliability</a><span class="arrow">→</span>
        <a href="#concentration">Concentration</a><span class="arrow">→</span>
        <a href="#methodology">Methodology</a>
    </div>
    """

st.markdown(
    f"""
    <aside class="left-index {index_class}" aria-label="Page index">
        <div class="index-title">Pages</div>
    </aside>
    {top_navigation_html}
    """,
    unsafe_allow_html=True,
)

if current_page == "routes":
    render_routes_page(period_text, study_year)
    st.stop()

st.title("European Flight Delay Analytics")
st.markdown(
    f"""
    <div class="hero">
        <div class="eyebrow">Public aggregated study</div>
        <p>This study examines <b>scheduled commercial flights observed in {period_text} {study_year}</b>.
        A flight is delayed when it arrives more than 15 minutes after its filed arrival time.
        Only aggregated statistics are published: the accepted EUROCONTROL ADRR Terms of Use
        prohibit sharing or distributing the underlying flight-level repository. These months
        are snapshots and must not be interpreted as a complete {study_year} calendar year.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

section_anchor("overview")
with st.container(border=True):
    st.markdown('<div class="section-kicker">01 · Network overview</div>', unsafe_allow_html=True)
    st.subheader("The scale of the delay problem")
    with st.container(key="overview_metrics"):
        cards_top = st.columns(3)
        cards_top[0].metric("Flights analysed", f"{int(all_row['flight_count']):,}")
        cards_top[1].metric("Delayed >15 min", f"{all_row['delay_over_15_pct']:.1f}%")
        cards_top[2].metric("Severe delays >60 min", f"{all_row['delay_over_60_pct']:.1f}%")
        cards_bottom = st.columns(3)
        cards_bottom[0].metric("Median arrival delay", f"{all_row['median_arrival_delay_min']:.1f} min")
        cards_bottom[1].metric("Median when delayed >15 min", f"{all_row['median_delayed_only_min']:.1f} min")
        cards_bottom[2].metric("Positive delay accumulated", f"{all_row['total_positive_delay_hours']:,.0f} h")
    st.markdown(
        """
        Delays affect passengers, airline operations, aircraft rotations and airport capacity.
        This analysis moves beyond a single network average to reveal which flights, airlines,
        airports, routes, dates and operating periods are more or less reliable. These patterns
        can support schedule design, resource planning and disruption monitoring.

        **Interpretation note:** accumulated delay counts positive arrival-delay minutes only;
        early arrivals do not cancel the operational burden created by late flights.
        """
    )

section_anchor("comparison")
with st.container(border=True):
    st.markdown('<div class="section-kicker">02 · Flight scope</div>', unsafe_allow_html=True)
    st.subheader("Overall vs under-three-hour flights")
    comparison_cards_top = st.columns(2)
    comparison_card(
        comparison_cards_top[0],
        "Under-3h flights",
        f"{int(short_row['flight_count']):,}",
        f"{100 * short_row['flight_count'] / all_row['flight_count']:.1f}% of all flights",
    )
    delayed_difference = short_row["delay_over_15_pct"] - all_row["delay_over_15_pct"]
    comparison_card(
        comparison_cards_top[1],
        "Under-3h delayed >15 min",
        f"{short_row['delay_over_15_pct']:.1f}%",
        f"{abs(delayed_difference):.1f} percentage points lower than all flights",
    )
    comparison_cards_bottom = st.columns(2)
    comparison_card(
        comparison_cards_bottom[0],
        "Under-3h median delay",
        f"{short_row['median_arrival_delay_min']:.1f} min",
        f"{all_row['median_arrival_delay_min'] - short_row['median_arrival_delay_min']:.1f} minutes lower than all flights",
    )
    comparison_card(
        comparison_cards_bottom[1],
        "Under-3h severe delays",
        f"{short_row['delay_over_60_pct']:.1f}%",
        f"{all_row['delay_over_60_pct'] - short_row['delay_over_60_pct']:.1f} percentage points lower than all flights",
    )

    comparison = overview.copy()
    comparison["label"] = comparison["delay_over_15_pct"].map(lambda value: f"{value:.1f}%")
    comparison_order = comparison["scope_label"].tolist()
    comparison_axis_max = float(comparison["delay_over_15_pct"].max()) + 2
    bars = alt.Chart(comparison).mark_bar(cornerRadiusEnd=6, size=34).encode(
        y=alt.Y("scope_label:N", title=None, sort=comparison_order, axis=alt.Axis(labelLimit=350)),
        x=alt.X(
            "delay_over_15_pct:Q",
            title="Flights delayed more than 15 minutes (%)",
            scale=alt.Scale(domain=[0, comparison_axis_max]),
        ),
        color=alt.Color(
            "scope_label:N",
            legend=None,
            scale=alt.Scale(range=[BLUE, GREEN]),
        ),
        tooltip=[
            alt.Tooltip("scope_label:N", title="Scope"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
        ],
    )
    labels = alt.Chart(comparison).mark_text(
        dx=8, align="left", font="Calibri", fontSize=14, fontWeight="bold", color=NAVY
    ).encode(
        y=alt.Y("scope_label:N", sort=comparison_order),
        x="delay_over_15_pct:Q",
        text="label:N",
    )
    st.altair_chart(
        style_chart((bars + labels).properties(height=220, width="container")),
        width="stretch",
    )
    st.caption(
        "The comparison uses ordinary percentages: 19.2% of all scheduled flights and "
        "14.4% of flights under three hours arrived more than 15 minutes late."
    )

section_anchor("trend")
with st.container(border=True):
    st.markdown('<div class="section-kicker">03 · Time trend</div>', unsafe_allow_html=True)
    st.subheader(f"Delay rate over the available {study_year} snapshots")
    monthly_all = monthly[monthly["scope_id"] == "all_flights"].copy()
    monthly_all["month_label"] = monthly_all["period"].dt.strftime("%B")
    month_order = period_dates.strftime("%B").tolist()
    monthly_chart = alt.Chart(monthly_all).mark_line(
        point=alt.OverlayMarkDef(filled=True, size=110), color=BLUE, strokeWidth=3
    ).encode(
        x=alt.X("month_label:N", title=None, sort=month_order, axis=alt.Axis(labelAngle=0, labelPadding=10)),
        y=alt.Y("delay_over_15_pct:Q", title="Flights delayed >15 min (%)", scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip("month_label:N", title="Month"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
            alt.Tooltip("median_arrival_delay_min:Q", title="Median delay", format=".1f"),
        ],
    )
    st.altair_chart(
        style_chart(monthly_chart.properties(height=340, width="container")),
        width="stretch",
    )

section_anchor("reliability")
with st.container(border=True):
    st.markdown('<div class="section-kicker">04 · Reliability</div>', unsafe_allow_html=True)
    st.subheader("Reliability changes with scheduled flight duration")
    duration_order = duration["duration_hour"].tolist()
    duration_delay = alt.Chart(duration).mark_bar(color=BLUE, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("duration_hour:N", title="Scheduled duration", sort=duration_order, axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("delay_over_15_pct:Q", title="Flights delayed >15 min (%)"),
        tooltip=[
            alt.Tooltip("duration_hour:N", title="Duration"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
        ],
    )
    st.altair_chart(
        style_chart(duration_delay.properties(height=350, width="container")),
        width="stretch",
    )
    st.caption(
        "Durations are grouped hour by hour; flights of 12 hours or more are combined "
        "to avoid unstable, low-volume tail categories."
    )

    correlation_value = float(correlation["coefficient"])
    correlation_columns = st.columns([1, 2])
    correlation_columns[0].metric(
        "Duration–delay Spearman ρ",
        f"{correlation_value:.3f}",
        f"{correlation['absolute_strength']} {str(correlation['direction']).lower()} association",
        delta_color="off",
    )
    correlation_columns[1].markdown(
        f"""
        **How to read it.** Spearman's ρ measures whether longer scheduled flights tend to rank
        above or below shorter flights in arrival delay. It is less sensitive to extreme delays
        than Pearson correlation. The coefficient uses **{int(correlation['flight_count']):,}**
        valid flights. It describes association, not causation; operational context may explain
        part of the relationship.

        <strong>There is a small positive association: longer scheduled flights tend to experience
        slightly higher arrival delays, but flight duration alone explains only a limited part
        of reliability.</strong>
        """,
        unsafe_allow_html=True,
    )

section_anchor("concentration")
with st.container(border=True):
    st.markdown('<div class="section-kicker">05 · Concentration</div>', unsafe_allow_html=True)
    st.subheader("A small share of flights creates most positive delay")
    worst_ten = concentration_summary.iloc[0]
    concentration_cards = st.columns(2)
    concentration_cards[0].metric("Positive delay generated by worst 10%", f"{worst_ten['share_of_positive_delay_pct']:.1f}%")
    concentration_cards[1].metric("Positive delay in worst 10%", f"{worst_ten['positive_delay_hours']:,.0f} h")

    concentration_plot = concentration_summary.copy()
    concentration_plot["group"] = "All flights"
    concentration_bar = alt.Chart(concentration_plot).mark_bar(size=50).encode(
        y=alt.Y("group:N", title=None, axis=None),
        x=alt.X("share_of_positive_delay_pct:Q", title="Share of all accumulated positive arrival delay (%)", stack="zero"),
        color=alt.Color(
            "segment:N",
            title=None,
            sort=concentration_summary["segment"].tolist(),
            scale=alt.Scale(range=[GREEN, LIGHT_BLUE]),
            legend=alt.Legend(orient="bottom"),
        ),
        order=alt.Order("segment_order:Q"),
        tooltip=[
            alt.Tooltip("segment:N", title="Flight group"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("positive_delay_hours:Q", title="Positive delay (hours)", format=",.0f"),
            alt.Tooltip("share_of_positive_delay_pct:Q", title="Share of delay", format=".1f"),
        ],
    )
    st.altair_chart(
        style_chart(concentration_bar.properties(height=175, width="container")),
        width="stretch",
    )
    st.caption(
        "Flights are ranked from highest to lowest arrival delay. Positive delay includes late "
        "minutes only, so early arrivals do not offset disruption elsewhere."
    )

section_anchor("methodology")
with st.container(border=True):
    st.markdown('<div class="section-kicker">06 · Methodology</div>', unsafe_allow_html=True)
    st.subheader("Methodology and public-data scope")
    with st.expander("Read the study methodology", expanded=False):
        st.markdown(
            f"""
            **Source and coverage.** The source is the
            [EUROCONTROL Aviation Data Repository for Research (ADRR)]({metadata['source_url']}).
            The study uses the four available {study_year} snapshots: **{period_text}**.
            They are non-consecutive representative months, not a continuous annual series.

            **Why this dataset was selected.** Despite not covering every month, ADRR provides
            unusually rich operational and categorical information, including origin and
            destination airports, aircraft type, operator, market segment, registration,
            filed times and actual times. That combination supports analysis of differences
            between routes, airlines, airports, periods and aircraft operations that would not
            be possible with a smaller set of variables.

            **Population and cleaning.** Only scheduled flights (`ICAO Flight Type = S`) are
            included. The analysis applies the same central quality rules as notebook 10:
            physically plausible delays, flight levels, distances and coordinates. Rows without
            a usable arrival-delay target are excluded. A delay means actual arrival more than
            15 minutes after filed arrival; the under-three-hour comparison requires a positive
            scheduled duration below 180 minutes.

            **Statistical methods.** Medians describe the typical flight robustly, while
            accumulated positive delay quantifies operational burden without allowing early
            arrivals to cancel late arrivals. Duration results are aggregated hour by hour.
            Spearman rank correlation measures monotonic association between scheduled duration
            and arrival delay without assuming a linear relationship. Concentration statistics
            rank flights by delay and compare the worst-performing 10% with the remaining 90%.

            **Publication and governance.** The raw flight records cannot legally be republished
            under the accepted [ADRR Terms of Use]({metadata['terms_url']}), which prohibit sharing
            or distributing the repository. This app therefore contains aggregated CSVs only and
            does not expose individual flights, registrations or identifiers. EUROCONTROL is duly
            acknowledged as the source; the analysis and interpretations are those of this project.
            """
        )
