"""CSS loading and the small state-dependent layout overrides."""

from pathlib import Path

import streamlit as st


STYLE_PATH = Path(__file__).resolve().parents[1] / "styles.css"


def apply_base_styles() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def apply_layout_styles(current_page: str, index_expanded: bool) -> None:
    desktop_left = 248 if index_expanded else 88
    tablet_left = 205 if index_expanded else 88
    toggle_left = 178 if index_expanded else 15
    tablet_toggle_left = 143 if index_expanded else 15
    navigation_width = 198 if index_expanded else 42
    tablet_navigation_width = 160 if index_expanded else 42
    text_display = "block" if index_expanded else "none"
    alignment = "flex-start" if index_expanded else "center"
    navigation_padding = "0 12px" if index_expanded else "0"
    main_top_padding = "0.5rem" if current_page == "introduction" else "4.8rem"
    journey_margin = "10px" if current_page == "introduction" else "20px"
    brand_margin = "3px" if current_page == "introduction" else "14px"

    st.markdown(
        f"""
        <style>
        [data-testid="stMainBlockContainer"] {{ padding-top: {main_top_padding} !important; }}
        .journey-map {{ margin-bottom: {journey_margin} !important; }}
        .brand-bar {{ margin-bottom: {brand_margin} !important; }}
        @media (min-width: 901px) {{
            [data-testid="stMainBlockContainer"] {{ padding-left: {desktop_left}px !important; }}
            .st-key-page_index_toggle {{ left: {toggle_left}px !important; }}
            .st-key-page_navigation {{ width: {navigation_width}px !important; }}
        }}
        @media (min-width: 641px) and (max-width: 900px) {{
            [data-testid="stMainBlockContainer"] {{ padding-left: {tablet_left}px !important; }}
            .st-key-page_index_toggle {{ left: {tablet_toggle_left}px !important; }}
            .st-key-page_navigation {{ width: {tablet_navigation_width}px !important; }}
            .left-index.expanded {{ width: 184px; }}
        }}
        .st-key-page_navigation button {{
            justify-content: {alignment} !important;
            padding: {navigation_padding} !important;
        }}
        .st-key-page_navigation button p {{ display: {text_display}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

