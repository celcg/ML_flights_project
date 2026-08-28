"""Introduction page for network-level flight-delay analytics."""

import html
import json
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from dashboard.common import (
    render_eurocontrol_attribution,
    section_anchor,
    style_chart,
)
from dashboard.config import (
    BLUE,
    COMPACT_CHART_PADDING,
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
    _render_compact_charts(
        monthly,
        duration,
        route_data["metrics"],
        period_dates,
        study_year,
    )
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
    with st.container(border=True, key="overview_kpi_card", height=280):
        st.subheader("The scale of the delay problem")
        with st.container(key="overview_metrics"):
            st.html(
                f"""
                <div class="scale-metric-grid">
                    <div class="scale-metric-primary">
                        <span class="scale-metric-label">Flights in analysis</span>
                        <strong>{int(all_flights['flight_count']):,}</strong>
                        <span class="scale-metric-context">usable scheduled flights</span>
                    </div>
                    <div class="scale-metric-group">
                        <span class="scale-group-title">Delay rates</span>
                        <div class="scale-metric-pair">
                            <div>
                                <strong>{all_flights['delay_over_15_pct']:.1f}%</strong>
                                <span>Delayed &gt;15 min</span>
                            </div>
                            <div>
                                <strong>{all_flights['delay_over_60_pct']:.1f}%</strong>
                                <span>Severe &gt;60 min</span>
                            </div>
                        </div>
                    </div>
                    <div class="scale-metric-group">
                        <span class="scale-group-title">Flight profile</span>
                        <div class="scale-metric-pair">
                            <div>
                                <strong>{all_flights['median_arrival_delay_min']:.1f} min</strong>
                                <span>Median arrival delay</span>
                            </div>
                            <div>
                                <strong>{all_flights['median_international_arrival_delay_min']:.1f} min</strong>
                                <span>International flights median</span>
                            </div>
                        </div>
                    </div>
                </div>
                """
            )


def _render_rankings_card(route_data: dict[str, pd.DataFrame]) -> None:
    with st.container(border=True, key="overview_rankings_card", height=280):
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
    monthly: pd.DataFrame,
    duration: pd.DataFrame,
    route_metrics: pd.DataFrame,
    period_dates: pd.DatetimeIndex,
    study_year: str,
) -> None:
    country_map, legend_minimum, legend_maximum = _country_delay_map(route_metrics)
    duration_chart = _duration_chart(duration)
    monthly_chart = _monthly_chart(monthly, period_dates, study_year)

    columns = st.columns([2, 1], gap=None, vertical_alignment="top")
    with columns[0]:
        with st.container(border=True, key="scope_reliability_card"):
            paired = st.columns(2, gap=None)
            with paired[0]:
                section_anchor("comparison")
                _chart_title("Delayed flights by country (in + out)")
                st.pydeck_chart(
                    country_map,
                    width="stretch",
                    height=158,
                    key="country_delay_map",
                )
                st.html(
                    f"""
                    <div class="country-delay-legend">
                        <span>{legend_minimum:.1f}%</span>
                        <div class="country-delay-gradient"></div>
                        <span>{legend_maximum:.1f}%</span>
                        <small>Delayed &gt;15 min</small>
                    </div>
                    """
                )
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
    st.html(f'<div class="compact-chart-title">{html.escape(title)}</div>')


def _country_delay_map(route_metrics: pd.DataFrame) -> tuple[pdk.Deck, float, float]:
    country_metrics = _country_delay_metrics(route_metrics)
    metric_lookup = country_metrics.set_index("country").to_dict("index")
    country_aliases = {
        "Republic of Serbia": "Serbia",
        "The Bahamas": "Bahamas",
        "United Republic of Tanzania": "Tanzania",
    }
    map_path = (
        Path(__file__).resolve().parents[1]
        / "public_data"
        / "geography"
        / "world_countries_110m.geojson"
    )
    with map_path.open(encoding="utf-8") as map_file:
        geography = json.load(map_file)

    for feature in geography["features"]:
        properties = feature["properties"]
        map_country = properties["ADMIN"]
        metric_country = country_aliases.get(map_country, map_country)
        metric = metric_lookup.get(metric_country)
        properties["country"] = metric_country
        if metric is None:
            properties.update(
                fill_color=[220, 227, 235, 105],
                delay_rate_label="No data",
                flight_count_label="—",
            )
        else:
            properties.update(
                fill_color=metric["fill_color"],
                delay_rate_label=metric["delay_rate_label"],
                flight_count_label=metric["flight_count_label"],
            )

    layer = pdk.Layer(
        "GeoJsonLayer",
        data=geography,
        get_fill_color="properties.fill_color",
        get_line_color=[255, 255, 255, 190],
        line_width_min_pixels=1,
        pickable=True,
        stroked=True,
        filled=True,
        opacity=0.9,
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            latitude=30,
            longitude=8,
            zoom=0.15,
            pitch=0,
            bearing=0,
        ),
        map_style="light",
        tooltip={
            "html": (
                "<b>{country}</b><br/>"
                "Delayed &gt;15 min: <b>{delay_rate_label}</b><br/>"
                "Flights (in + out): {flight_count_label}"
            ),
            "style": {"backgroundColor": "#17233a", "color": "white"},
        },
    )
    return (
        deck,
        float(country_metrics["delay_rate"].min()),
        float(country_metrics["delay_rate"].max()),
    )


def _country_delay_metrics(route_metrics: pd.DataFrame) -> pd.DataFrame:
    routes = route_metrics.loc[route_metrics["scope_id"].eq("all_flights")].copy()
    endpoint_frames = []
    for endpoint in ("origin", "destination"):
        endpoint_frames.append(
            routes.rename(
                columns={
                    f"{endpoint}_country": "country",
                }
            )[
                [
                    "country",
                    "flight_count",
                    "delayed_over_15_count",
                ]
            ]
        )

    endpoints = pd.concat(endpoint_frames, ignore_index=True).dropna(
        subset=["country", "flight_count"]
    )
    endpoints = endpoints.loc[endpoints["flight_count"].gt(0)].copy()

    countries = endpoints.groupby("country", as_index=False).agg(
        flight_count=("flight_count", "sum"),
        delayed_over_15_count=("delayed_over_15_count", "sum"),
    )
    countries["delay_rate"] = (
        countries["delayed_over_15_count"] / countries["flight_count"] * 100
    )

    lower_rate = float(countries["delay_rate"].min())
    upper_rate = float(countries["delay_rate"].max())
    rate_range = max(upper_rate - lower_rate, 1.0)
    normalized_rate = ((countries["delay_rate"] - lower_rate) / rate_range).clip(0, 1)
    countries["fill_color"] = normalized_rate.map(
        lambda value: [
            round(54 + 172 * value),
            round(116 - 55 * value),
            round(180 - 88 * value),
            220,
        ]
    )

    countries["delay_rate_label"] = countries["delay_rate"].map(
        lambda value: f"{value:.1f}%"
    )
    countries["flight_count_label"] = countries["flight_count"].map(
        lambda value: f"{int(value):,}"
    )
    return countries


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
            distributing the underlying flight-level repository. Route-level analyses only
            include directional routes whose **origin or destination is in Europe**. These
            months are snapshots and must not be interpreted as a complete {study_year}
            calendar year.
            """
        )
        render_eurocontrol_attribution()


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
            render_eurocontrol_attribution()
