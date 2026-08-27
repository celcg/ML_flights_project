"""Reliability ranking calculations and compact leaderboard rendering."""

import html

import pandas as pd
import streamlit as st


def reliability_rankings(
    route_data: dict[str, pd.DataFrame],
    entity: str,
    minimum_flights: int = 500,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return robust Top-3 arrival-reliability rankings from public aggregates."""

    if entity == "routes":
        summary = route_data["metrics"].loc[
            lambda frame: frame["scope_id"].eq("all_flights")
            & frame["executive_eligible"].eq(True),
            ["route", "flight_count", "delayed_over_15_count"],
        ].rename(columns={"route": "entity_name"})
    elif entity == "airports":
        summary = _airport_summary(route_data["metrics"])
    elif entity == "airlines":
        summary = _airline_summary(route_data["operators"])
    else:
        raise ValueError(f"Unsupported reliability entity: {entity}")

    summary = summary.loc[summary["flight_count"].ge(minimum_flights)].copy()
    summary["delay_over_15_pct"] = (
        100 * summary["delayed_over_15_count"] / summary["flight_count"]
    )
    reliable = summary.sort_values(
        ["delay_over_15_pct", "flight_count"], ascending=[True, False]
    ).head(3)
    least_reliable = summary.sort_values(
        ["delay_over_15_pct", "flight_count"], ascending=[False, False]
    ).head(3)
    return reliable, least_reliable


def _airport_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    airport_routes = metrics.loc[
        lambda frame: frame["scope_id"].eq("all_flights"),
        ["ADES", "destination_airport_name", "flight_count", "delayed_over_15_count"],
    ].copy()
    summary = airport_routes.groupby("ADES", as_index=False).agg(
        entity_label=("destination_airport_name", "first"),
        flight_count=("flight_count", "sum"),
        delayed_over_15_count=("delayed_over_15_count", "sum"),
    )
    summary["entity_label"] = summary["entity_label"].fillna(summary["ADES"])
    summary["entity_name"] = summary["ADES"] + " · " + summary["entity_label"]
    return summary


def _airline_summary(operators: pd.DataFrame) -> pd.DataFrame:
    operator_routes = operators.loc[
        lambda frame: frame["scope_id"].eq("all_flights"),
        ["operator_code", "operator_name", "flight_count", "delayed_over_15_count"],
    ].copy()
    operator_routes = operator_routes.loc[
        ~operator_routes["operator_code"].isin(["ZZZ", "UNK", "UNKNOWN"])
    ]
    summary = operator_routes.groupby("operator_code", as_index=False).agg(
        entity_label=("operator_name", "first"),
        flight_count=("flight_count", "sum"),
        delayed_over_15_count=("delayed_over_15_count", "sum"),
    )
    summary["entity_label"] = summary["entity_label"].fillna(summary["operator_code"])
    summary["entity_name"] = summary["entity_label"]
    return summary


def ranking_panel(title: str, frame: pd.DataFrame, accent_class: str) -> None:
    """Render a compact three-row reliability leaderboard."""

    rows = []
    for rank, (_, row) in enumerate(frame.iterrows(), start=1):
        name = html.escape(str(row["entity_name"]))
        flights = html.escape(f"{int(row['flight_count']):,} flights")
        rows.append(
            f'<div class="mini-rank-row" title="{flights}">'
            f'<span class="mini-rank-position">{rank}</span>'
            f'<span class="mini-rank-name">{name}</span>'
            f'<span class="mini-rank-rate">{row["delay_over_15_pct"]:.1f}%</span>'
            "</div>"
        )
    st.html(
        f'<div class="mini-ranking {accent_class}">'
        '<div class="mini-ranking-heading">'
        f'<div class="mini-ranking-title">{html.escape(title)}</div>'
        '<div class="mini-ranking-unit">Delayed &gt;15 min (%)</div>'
        "</div>"
        f'{"".join(rows)}</div>'
    )
