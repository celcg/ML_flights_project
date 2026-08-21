"""Shared presentation helpers used by both dashboard pages."""

from __future__ import annotations

import altair as alt
import streamlit as st

from dashboard.config import GRID, MUTED, TEXT


def style_chart(chart: alt.TopLevelMixin) -> alt.TopLevelMixin:
    """Apply the dashboard's common accessible chart styling."""

    return (
        chart.configure_view(strokeWidth=0)
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
