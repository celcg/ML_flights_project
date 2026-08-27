"""Shared searchable selector for high-traffic dashboard entities."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dashboard.entity_analysis import highest_traffic_half


def build_entity_search_pool(
    metrics: pd.DataFrame,
    selected_entity: pd.Series,
    entity_column: str,
) -> pd.DataFrame:
    """Return the busiest half while keeping the current selection available."""

    return (
        pd.concat(
            [highest_traffic_half(metrics), selected_entity.to_frame().T],
            ignore_index=True,
        )
        .drop_duplicates(entity_column)
        .sort_values("flight_count", ascending=False)
    )


def render_entity_selector(
    *,
    title: str,
    label: str,
    options: list[str],
    selected_value: str,
    labels: dict[str, str],
    key: str,
    placeholder: str,
) -> str:
    """Render the common title-and-search control used by entity detail cards."""

    header_columns = st.columns([0.36, 0.64], gap="small", vertical_alignment="center")
    with header_columns[0]:
        st.html(
            f'<div class="section-kicker entity-search-title">{html.escape(title)}</div>'
        )
    with header_columns[1]:
        return st.selectbox(
            label,
            options=options,
            index=options.index(selected_value),
            format_func=labels.get,
            key=key,
            placeholder=placeholder,
            label_visibility="collapsed",
        )
