"""Pure visual builders for airport maps, timelines and delay heatmaps."""

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk

from dashboard.config import AIRPORT_DELAY_VIEWS, BLUE, GREEN, RED


WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def airport_label(code: str, name: object) -> str:
    display_name = "Airport name unavailable" if pd.isna(name) else str(name)
    shortened = display_name if len(display_name) <= 42 else f"{display_name[:40].rstrip()}…"
    return f"{code} · {shortened}"


def airport_map_deck(airports: pd.DataFrame, metric_column: str) -> pdk.Deck:
    """Create a volume-sized, delay-coloured map from airport aggregates."""

    max_volume = max(float(airports["flight_count"].max()), 1.0)
    map_data = []
    for row in airports.itertuples(index=False):
        delay_rate = float(getattr(row, metric_column))
        map_data.append({
            "airport": airport_label(row.airport_code, row.airport_name),
            "city": "Unavailable" if pd.isna(row.city) else str(row.city),
            "country": "Unavailable" if pd.isna(row.country) else str(row.country),
            "position": [float(row.longitude), float(row.latitude)],
            "delay_rate": delay_rate,
            "arrivals": int(row.arrival_flight_count),
            "departures": int(row.departure_flight_count),
            "movements": int(row.flight_count),
            "color": _delay_color(delay_rate),
            "radius": 14_000 + 55_000 * math.sqrt(float(row.flight_count) / max_volume),
        })
    return pdk.Deck(
        map_style="light",
        initial_view_state=pdk.ViewState(latitude=46.0, longitude=8.0, zoom=1.15),
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                map_data,
                get_position="position",
                get_fill_color="color",
                get_line_color=[255, 255, 255, 220],
                get_radius="radius",
                radius_min_pixels=3,
                radius_max_pixels=18,
                line_width_min_pixels=1,
                stroked=True,
                pickable=True,
                auto_highlight=True,
            )
        ],
        tooltip={
            "html": "<b>{airport}</b><br/>{city}, {country}<br/>Delayed &gt;15 min: {delay_rate}%<br/>Movements: {movements}<br/>Arrivals: {arrivals} · Departures: {departures}",
            "style": {"backgroundColor": "#0B1F33", "color": "white"},
        },
    )


def airport_timeline_chart(monthly: pd.DataFrame) -> go.Figure:
    """Compare monthly arrival and departure delayed-flight rates."""

    trend = monthly.copy()
    trend["period"] = pd.to_datetime(trend["period"])
    trend = trend.sort_values("period")
    trend["month"] = trend["period"].dt.strftime("%b")
    figure = go.Figure()
    for column, label, color in [
        ("arrival_delay_over_15_pct", "Arrivals", RED),
        ("departure_delay_over_15_pct", "Departures", BLUE),
    ]:
        figure.add_trace(go.Scatter(
            x=trend["month"],
            y=trend[column],
            mode="lines+markers",
            name=label,
            line={"color": color, "width": 2.5},
            marker={"size": 7, "color": "#FFFFFF", "line": {"color": color, "width": 2}},
            hovertemplate=f"<b>%{{x}} 2022 · {label}</b><br>Delayed &gt;15 min: %{{y:.1f}}%<extra></extra>",
        ))
    figure.update_layout(
        title={"text": "Monthly delayed-flight rate", "x": 0.01, "font": {"size": 12}},
        height=190,
        margin={"l": 42, "r": 8, "t": 36, "b": 32},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "y": 1.12, "x": 0.44, "font": {"size": 9}},
        font={"color": "#23364A", "size": 9},
    )
    figure.update_xaxes(showgrid=False, fixedrange=True)
    figure.update_yaxes(ticksuffix="%", gridcolor="#E5EDF4", fixedrange=True)
    return figure


def airport_heatmap_chart(heatmap: pd.DataFrame, delay_view: str) -> go.Figure:
    """Create an airport delay heatmap by filed weekday and hour."""

    values = heatmap.pivot(
        index="weekday", columns="hour", values="delay_over_15_pct"
    ).reindex(WEEKDAY_ORDER)
    volumes = heatmap.pivot(
        index="weekday", columns="hour", values="flight_count"
    ).reindex(WEEKDAY_ORDER)
    hours = list(range(24))
    values = values.reindex(columns=hours)
    volumes = volumes.reindex(columns=hours)
    figure = go.Figure(go.Heatmap(
        z=values.to_numpy(),
        x=hours,
        y=WEEKDAY_ORDER,
        customdata=volumes.to_numpy(),
        colorscale=[[0, GREEN], [0.5, "#DEA037"], [1, RED]],
        colorbar={
            "title": {"text": "Delayed", "font": {"size": 9}},
            "ticksuffix": "%",
            "thickness": 8,
            "len": 0.7,
        },
        hovertemplate="<b>%{y} · %{x}:00</b><br>Delayed &gt;15 min: %{z:.1f}%<br>Flights: %{customdata:,.0f}<extra></extra>",
        zmin=0,
        zmax=max(40.0, float(np.nanquantile(values.to_numpy(), 0.95))),
    ))
    figure.update_layout(
        title={
            "text": f"Delay heatmap · {AIRPORT_DELAY_VIEWS[delay_view]['short_label'].lower()}",
            "x": 0.01,
            "font": {"size": 12},
        },
        height=235,
        margin={"l": 38, "r": 8, "t": 35, "b": 34},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#23364A", "size": 9},
    )
    figure.update_xaxes(
        title="Scheduled hour",
        tickmode="array",
        tickvals=list(range(0, 24, 3)),
        fixedrange=True,
    )
    figure.update_yaxes(title=None, autorange="reversed", fixedrange=True)
    return figure


def _delay_color(delay_rate: float) -> list[int]:
    if delay_rate <= 15:
        return [46, 139, 104, 210]
    if delay_rate <= 30:
        return [222, 160, 55, 215]
    return [195, 93, 93, 220]
