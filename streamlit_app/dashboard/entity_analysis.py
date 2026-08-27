"""Reusable ranking and temporal-profile logic for routes and airlines."""

import math

import pandas as pd
import plotly.graph_objects as go

from dashboard.config import GREEN, RED


RANKING_VIEW_LABELS = {
    "most_popular": "Most popular",
    "most_reliable": "Most reliable",
    "least_reliable": "Least reliable",
}


def highest_traffic_half(metrics: pd.DataFrame) -> pd.DataFrame:
    """Return the highest-volume half of entities for searchable selectors."""

    if metrics.empty:
        return metrics.copy()
    limit = max(1, math.ceil(len(metrics) * 0.5))
    return metrics.nlargest(limit, "flight_count").copy()


def rank_entities(
    metrics: pd.DataFrame,
    ranking_view: str,
    ranking_metric: str,
    *,
    limit: int = 10,
) -> pd.DataFrame:
    """Return a deterministic entity ranking for the requested perspective."""

    if ranking_view == "most_popular":
        return metrics.nlargest(limit, "flight_count").copy()
    ascending = ranking_view == "most_reliable"
    return (
        metrics.sort_values(
            [ranking_metric, "flight_count"], ascending=[ascending, False]
        )
        .head(limit)
        .copy()
    )


def build_on_time_trend_figure(
    monthly: pd.DataFrame,
    *,
    height: int = 175,
) -> go.Figure:
    """Build a common on-time trend with colour indicating improvement."""

    trend = monthly.copy()
    trend["period"] = pd.to_datetime(trend["period"])
    trend = trend.sort_values("period")
    trend["month"] = trend["period"].dt.strftime("%b")
    trend["on_time_pct"] = 100 - trend["delay_over_15_pct"]
    improves = trend["on_time_pct"].iloc[-1] >= trend["on_time_pct"].iloc[0]
    trend_color = GREEN if improves else RED
    spread = float(trend["on_time_pct"].max() - trend["on_time_pct"].min())
    padding = max(1.0, spread * 0.35)
    y_range = [
        max(0.0, float(trend["on_time_pct"].min()) - padding),
        min(100.0, float(trend["on_time_pct"].max()) + padding),
    ]
    figure = go.Figure(
        go.Scatter(
            x=trend["month"],
            y=trend["on_time_pct"],
            customdata=trend[["delay_over_15_pct", "flight_count"]],
            mode="lines+markers",
            line={"color": trend_color, "width": 3},
            marker={
                "color": "#FFFFFF",
                "line": {"color": trend_color, "width": 2.5},
                "size": 8,
            },
            hovertemplate=(
                "<b>%{x} 2022</b><br>On time: %{y:.1f}%"
                "<br>Delayed >15 min: %{customdata[0]:.1f}%"
                "<br>Flights: %{customdata[1]:,.0f}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        title={"text": "On-time flights (%)", "x": 0.02, "font": {"size": 13}},
        height=height,
        margin={"l": 42, "r": 8, "t": 35, "b": 34},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        hovermode="x unified",
        font={"color": "#23364A", "size": 10},
    )
    figure.update_xaxes(title=None, showgrid=False, fixedrange=True, tickfont={"size": 10})
    figure.update_yaxes(
        title=None,
        range=y_range,
        ticksuffix="%",
        gridcolor="#E5EDF4",
        fixedrange=True,
        tickfont={"size": 9},
    )
    return figure
