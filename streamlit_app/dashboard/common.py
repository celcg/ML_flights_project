"""Shared presentation helpers used by both dashboard pages."""

from __future__ import annotations

import re

import altair as alt
import streamlit as st

from dashboard.config import GRID, MUTED, TEXT


EUROCONTROL_ATTRIBUTION_NOTICE = """
---

**EUROCONTROL attribution and disclaimer**

This document/R&D product has been created with or contains elements of the
Aviation Data Repository for Research made available by EUROCONTROL. ©2020,
EUROCONTROL.

EUROCONTROL does not necessarily support and/or endorse the conclusion of this
document/R&D product. EUROCONTROL shall not be liable for any direct, indirect,
incidental or consequential damages arising out of or in connection with this
document/product and/or the underlying Aviation Data Repository for Research.
"""


def style_chart(chart: alt.TopLevelMixin) -> alt.TopLevelMixin:
    """Apply the dashboard's common accessible chart styling."""

    return (
        chart.configure_view(strokeWidth=0)
        .configure_axis(
            domain=False,
            gridColor=GRID,
            gridOpacity=0.82,
            gridWidth=1,
            labelColor=MUTED,
            labelFont="Aptos",
            labelFontSize=11,
            labelPadding=7,
            titleColor=TEXT,
            titleFont="Aptos",
            titleFontSize=12,
            titleFontWeight=500,
            titlePadding=12,
            tickColor=GRID,
            tickSize=4,
        )
        .configure_legend(
            labelColor=TEXT,
            labelFont="Aptos",
            labelFontSize=11,
            titleColor=TEXT,
            titleFont="Aptos",
            titleFontSize=11,
            titleFontWeight=600,
            padding=8,
        )
    )


def render_eurocontrol_attribution() -> None:
    """Render the required ADRR source attribution and liability disclaimer."""

    st.markdown(EUROCONTROL_ATTRIBUTION_NOTICE)


def section_anchor(anchor_id: str, extra_class: str = "") -> None:
    """Render an anchor after validating every value used as an HTML token."""

    token_pattern = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
    tokens = [anchor_id, *extra_class.split()]
    if any(token_pattern.fullmatch(token) is None for token in tokens):
        raise ValueError("Section anchor IDs and classes must be safe HTML tokens.")
    classes = f"section-anchor {extra_class}".strip()
    st.html(f'<div id="{anchor_id}" class="{classes}"></div>')
