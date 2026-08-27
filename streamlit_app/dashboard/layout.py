"""Persistent page navigation and shared dashboard chrome."""

import html

import streamlit as st

from dashboard.styles import apply_layout_styles


def render_page_chrome(current_page: str, study_year: str) -> None:
    if "page_index_expanded" not in st.session_state:
        st.session_state.page_index_expanded = True

    expanded = st.session_state.page_index_expanded
    apply_layout_styles(expanded)

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
        _page_button("Airlines", "flight_takeoff", "airlines", current_page)
        _page_button("Airports", "location_on", "airports", current_page)
        _page_button("Flight search", "search", "search", current_page)

    index_class = "expanded" if expanded else "collapsed"
    st.html(
        f"""
        <aside class="left-index {index_class}" aria-label="Page index">
            <div class="index-title">Pages</div>
        </aside>
        {_top_navigation(current_page, study_year)}
        """
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
    safe_year = html.escape(str(study_year))
    if current_page == "routes":
        return f"""
        <div class="brand-bar" id="routes-top">
            <span>European aviation intelligence</span>
            <span class="edition">Routes · ADRR {safe_year}</span>
        </div>
        """
    if current_page == "airlines":
        return f"""
        <div class="brand-bar" id="airlines-top">
            <span>European aviation intelligence</span>
            <span class="edition">Airlines · ADRR {safe_year}</span>
        </div>
        """
    if current_page == "airports":
        return f"""
        <div class="brand-bar" id="airports-top">
            <span>European aviation intelligence</span>
            <span class="edition">Airports · ADRR {safe_year}</span>
        </div>
        """
    if current_page == "search":
        return f"""
        <div class="brand-bar" id="search-top">
            <span>European aviation intelligence</span>
            <span class="edition">Flight search · ADRR {safe_year}</span>
        </div>
        """
    return f"""
    <div class="brand-bar" id="introduction">
        <span>European aviation intelligence</span>
        <span class="edition">ADRR · {safe_year} snapshots</span>
    </div>
    """
