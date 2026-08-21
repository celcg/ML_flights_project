"""Persistent page navigation and shared dashboard chrome."""

import streamlit as st

from dashboard.styles import apply_layout_styles


def render_page_chrome(current_page: str, study_year: str) -> None:
    if "page_index_expanded" not in st.session_state:
        st.session_state.page_index_expanded = True

    expanded = st.session_state.page_index_expanded
    apply_layout_styles(current_page, expanded)

    with st.container(key="page_index_toggle"):
        st.button(
            "☰",
            key="toggle_page_index",
            help="Expand or collapse the page index",
            on_click=_toggle_page_index,
        )

    with st.container(key="page_navigation"):
        _page_button("Introduction", "home", "introduction", current_page)
        _page_button("Routes", "map", "routes", current_page)

    index_class = "expanded" if expanded else "collapsed"
    st.markdown(
        f"""
        <aside class="left-index {index_class}" aria-label="Page index">
            <div class="index-title">Pages</div>
        </aside>
        {_top_navigation(current_page, study_year)}
        """,
        unsafe_allow_html=True,
    )


def _toggle_page_index() -> None:
    st.session_state.page_index_expanded = not st.session_state.page_index_expanded


def _navigate_to(page_name: str) -> None:
    st.query_params["page"] = page_name


def _page_button(label: str, icon: str, page: str, current_page: str) -> None:
    st.button(
        label,
        key=f"navigate_{page}",
        icon=f":material/{icon}:",
        type="primary" if current_page == page else "secondary",
        help=f"Open the {label} page",
        on_click=_navigate_to,
        args=(page,),
        width="stretch",
    )


def _top_navigation(current_page: str, study_year: str) -> str:
    if current_page == "routes":
        return f"""
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
    return f"""
    <div class="brand-bar" id="introduction">
        <span>European aviation intelligence</span>
        <span class="edition">ADRR · {study_year} snapshots</span>
    </div>
    """

