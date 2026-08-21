"""Introduction page for network-level flight-delay analytics."""

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.common import section_anchor, style_chart
from dashboard.config import (
    BLUE,
    COMPACT_CHART_PADDING,
    GREEN,
    RELIABILITY_ENTITY_LABELS,
    RELIABILITY_VIEW_LABELS,
)
from dashboard.data import load_route_data
from dashboard.rankings import ranking_panel, reliability_rankings


def render_introduction_page(
    data: dict[str, pd.DataFrame],
    period_dates: pd.DatetimeIndex,
    period_text: str,
    study_year: str,
    metadata: dict[str, str],
) -> None:
    """Render the compact network overview and methodology sections."""

    try:
        route_data = load_route_data()
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    overview = data["overview"]
    monthly = data["monthly"].copy()
    monthly["period"] = pd.to_datetime(monthly["period"])
    duration = data["duration"].sort_values("hour_order")
    all_flights = overview.set_index("scope_id").loc["all_flights"]

    _render_overview_cards(all_flights, route_data)
    _render_compact_charts(overview, monthly, duration, period_dates, study_year)
    _render_study_information(period_text, study_year)
    _render_methodology(metadata, period_text, study_year)


def _render_overview_cards(
    all_flights: pd.Series, route_data: dict[str, pd.DataFrame]
) -> None:
    section_anchor("overview")
    columns = st.columns([3, 7], gap=None, vertical_alignment="top")
    with columns[0]:
        _render_scale_card(all_flights)
    with columns[1]:
        _render_rankings_card(route_data)


def _render_scale_card(all_flights: pd.Series) -> None:
    with st.container(border=True, key="overview_kpi_card", height=310):
        st.subheader("The scale of the delay problem")
        with st.container(key="overview_metrics"):
            top = st.columns(2)
            top[0].metric("Flights in analysis", f"{int(all_flights['flight_count']):,}")
            top[1].metric("Delayed >15 min", f"{all_flights['delay_over_15_pct']:.1f}%")
            middle = st.columns(2)
            middle[0].metric(
                "Severe delays >60 min", f"{all_flights['delay_over_60_pct']:.1f}%"
            )
            middle[1].metric(
                "Median arrival delay", f"{all_flights['median_arrival_delay_min']:.1f} min"
            )
            bottom = st.columns(2)
            bottom[0].metric(
                "Median when delayed >15 min",
                f"{all_flights['median_delayed_only_min']:.1f} min",
            )
            bottom[1].metric(
                "Positive delay accumulated",
                f"{all_flights['total_positive_delay_hours']:,.0f} h",
            )


def _render_rankings_card(route_data: dict[str, pd.DataFrame]) -> None:
    with st.container(border=True, key="overview_rankings_card", height=310):
        st.subheader("Reliability rankings")
        with st.container(key="reliability_entity_filter"):
            entity = st.segmented_control(
                "Reliability ranking entity",
                options=list(RELIABILITY_ENTITY_LABELS),
                default="airports",
                format_func=RELIABILITY_ENTITY_LABELS.get,
                key="introduction_reliability_entity",
                width="stretch",
                label_visibility="collapsed",
            ) or "airports"
        with st.container(key="reliability_view_filter"):
            view = st.segmented_control(
                "Reliability ranking direction",
                options=list(RELIABILITY_VIEW_LABELS),
                default="most_reliable",
                format_func=RELIABILITY_VIEW_LABELS.get,
                key="introduction_reliability_view",
                width="stretch",
                label_visibility="collapsed",
            ) or "most_reliable"

        rankings = {
            ranking_entity: reliability_rankings(route_data, ranking_entity)
            for ranking_entity in RELIABILITY_ENTITY_LABELS
        }
        most_reliable, least_reliable = rankings[entity]
        selected = most_reliable if view == "most_reliable" else least_reliable
        accent_class = "most-reliable" if view == "most_reliable" else "least-reliable"
        ranking_panel(RELIABILITY_VIEW_LABELS[view], selected, accent_class)


def _render_compact_charts(
    overview: pd.DataFrame,
    monthly: pd.DataFrame,
    duration: pd.DataFrame,
    period_dates: pd.DatetimeIndex,
    study_year: str,
) -> None:
    comparison_chart = _scope_comparison_chart(overview)
    duration_chart = _duration_chart(duration)
    monthly_chart = _monthly_chart(monthly, period_dates, study_year)

    columns = st.columns([2, 1], gap=None, vertical_alignment="top")
    with columns[0]:
        with st.container(border=True, key="scope_reliability_card"):
            paired = st.columns(2, gap=None)
            with paired[0]:
                section_anchor("comparison")
                _chart_title("Overall vs under-three-hour flights")
                st.altair_chart(comparison_chart, width="stretch")
            with paired[1]:
                section_anchor("reliability")
                _chart_title("Reliability by scheduled duration")
                st.altair_chart(duration_chart, width="stretch")
    with columns[1]:
        with st.container(border=True, key="trend_card"):
            section_anchor("trend")
            _chart_title(f"Delay rate across {study_year} snapshots")
            st.altair_chart(monthly_chart, width="stretch")


def _chart_title(title: str) -> None:
    st.markdown(f'<div class="compact-chart-title">{title}</div>', unsafe_allow_html=True)


def _scope_comparison_chart(overview: pd.DataFrame) -> alt.Chart:
    comparison = overview.copy()
    comparison["scope_display"] = comparison["scope_id"].map(
        {
            "all_flights": "All flights",
            "scheduled_duration_under_3h": "Under 3 hours",
        }
    )
    comparison["label"] = comparison["delay_over_15_pct"].map(
        lambda value: f"{value:.1f}%"
    )
    order = comparison["scope_display"].tolist()
    axis_maximum = float(comparison["delay_over_15_pct"].max()) + 5
    bars = alt.Chart(comparison).mark_bar(cornerRadiusEnd=5, size=28).encode(
        y=alt.Y(
            "scope_display:N",
            title="Scope",
            sort=order,
            axis=alt.Axis(labelLimit=105, labelFontSize=10, titleFontSize=10),
        ),
        x=alt.X(
            "delay_over_15_pct:Q",
            title="Delayed flights (%)",
            scale=alt.Scale(domain=[0, axis_maximum]),
            axis=alt.Axis(labelFontSize=9, titleFontSize=10, tickCount=4),
        ),
        color=alt.Color(
            "scope_display:N", legend=None, scale=alt.Scale(range=[BLUE, GREEN])
        ),
        tooltip=[
            alt.Tooltip("scope_label:N", title="Scope"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
        ],
    )
    labels = alt.Chart(comparison).mark_text(
        dx=-4,
        align="right",
        font="Aptos",
        fontSize=10,
        fontWeight="bold",
        color="white",
    ).encode(
        y=alt.Y("scope_display:N", sort=order),
        x="delay_over_15_pct:Q",
        text="label:N",
    )
    return style_chart(
        (bars + labels).properties(
            height=185, width="container", padding=COMPACT_CHART_PADDING
        )
    )


def _monthly_chart(
    monthly: pd.DataFrame,
    period_dates: pd.DatetimeIndex,
    study_year: str,
) -> alt.Chart:
    monthly_all = monthly[monthly["scope_id"].eq("all_flights")].copy()
    monthly_all["month_label"] = monthly_all["period"].dt.strftime("%b")
    month_order = period_dates.strftime("%b").tolist()
    chart = alt.Chart(monthly_all).mark_line(
        point=alt.OverlayMarkDef(filled=True, size=80),
        color=BLUE,
        strokeWidth=3,
    ).encode(
        x=alt.X(
            "month_label:N",
            title=study_year,
            sort=month_order,
            scale=alt.Scale(padding=0.4),
            axis=alt.Axis(
                labelAngle=0, labelPadding=6, titlePadding=6, labelFontSize=10
            ),
        ),
        y=alt.Y(
            "delay_over_15_pct:Q",
            title="Delayed flights (%)",
            scale=alt.Scale(zero=False),
            axis=alt.Axis(labelFontSize=9, titleFontSize=10, tickCount=4),
        ),
        tooltip=[
            alt.Tooltip("month_label:N", title="Month"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
            alt.Tooltip("median_arrival_delay_min:Q", title="Median delay", format=".1f"),
        ],
    )
    return style_chart(
        chart.properties(
            height=185, width="container", padding=COMPACT_CHART_PADDING
        )
    )


def _duration_chart(duration: pd.DataFrame) -> alt.Chart:
    duration_order = duration["duration_hour"].tolist()
    chart = alt.Chart(duration).mark_bar(
        color=BLUE, cornerRadiusTopLeft=3, cornerRadiusTopRight=3
    ).encode(
        x=alt.X(
            "duration_hour:N",
            title="Scheduled duration",
            sort=duration_order,
            scale=alt.Scale(paddingInner=0.12, paddingOuter=0.35),
            axis=alt.Axis(
                labelAngle=-45,
                labelFontSize=8,
                titleFontSize=10,
                labelOverlap="greedy",
            ),
        ),
        y=alt.Y(
            "delay_over_15_pct:Q",
            title="Delayed flights (%)",
            axis=alt.Axis(labelFontSize=9, titleFontSize=10, tickCount=4),
        ),
        tooltip=[
            alt.Tooltip("duration_hour:N", title="Duration"),
            alt.Tooltip("flight_count:Q", title="Flights", format=","),
            alt.Tooltip("delay_over_15_pct:Q", title="Delayed", format=".1f"),
        ],
    )
    return style_chart(
        chart.properties(
            height=185, width="container", padding=COMPACT_CHART_PADDING
        )
    )


def _render_study_information(period_text: str, study_year: str) -> None:
    with st.expander("Study information summary", expanded=False):
        st.markdown(
            f"""
            This study examines **scheduled commercial flights observed in
            {period_text} {study_year}**. A flight is delayed when it arrives more than
            15 minutes after its filed arrival time. Only aggregated statistics are
            published: the accepted EUROCONTROL ADRR Terms of Use prohibit sharing or
            distributing the underlying flight-level repository. These months are snapshots
            and must not be interpreted as a complete {study_year} calendar year.
            """
        )


def _render_methodology(
    metadata: dict[str, str], period_text: str, study_year: str
) -> None:
    section_anchor("methodology")
    with st.container(border=True):
        st.subheader("Methodology and public-data scope")
        with st.expander("Read the study methodology", expanded=False):
            st.markdown(
                f"""
                **Source and coverage.** The source is the
                [EUROCONTROL Aviation Data Repository for Research (ADRR)]({metadata['source_url']}).
                The study uses the four available {study_year} snapshots: **{period_text}**.
                They are non-consecutive representative months, not a continuous annual series.

                **Why this dataset was selected.** Despite not covering every month, ADRR
                provides unusually rich operational and categorical information, including
                origin and destination airports, aircraft type, operator, market segment,
                registration, filed times and actual times. That combination supports analysis
                of differences between routes, airlines, airports, periods and aircraft
                operations that would not be possible with a smaller set of variables.

                **Population and cleaning.** Only scheduled flights (`ICAO Flight Type = S`)
                are included. The analysis applies the same central quality rules as notebook 10:
                physically plausible delays, flight levels, distances and coordinates. Rows
                without a usable arrival-delay target are excluded. A delay means actual arrival
                more than 15 minutes after filed arrival; the under-three-hour comparison requires
                a positive scheduled duration below 180 minutes.

                **Statistical methods.** Medians describe the typical flight robustly, while
                accumulated positive delay quantifies operational burden without allowing early
                arrivals to cancel late arrivals. Duration results are aggregated hour by hour.
                Spearman rank correlation measures monotonic association between scheduled
                duration and arrival delay without assuming a linear relationship. Concentration
                statistics rank flights by delay and compare the worst-performing 10% with the
                remaining 90%.

                **Publication and governance.** The raw flight records cannot legally be
                republished under the accepted [ADRR Terms of Use]({metadata['terms_url']}),
                which prohibit sharing or distributing the repository. This app therefore
                contains aggregated CSVs only and does not expose individual flights,
                registrations or identifiers. EUROCONTROL is duly acknowledged as the source;
                the analysis and interpretations are those of this project.
                """
            )

