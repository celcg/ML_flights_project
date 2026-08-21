"""Entry point for the European aviation Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.data import load_public_data
from dashboard.introduction_page import render_introduction_page
from dashboard.layout import render_page_chrome
from dashboard.routes_page import render_routes_page
from dashboard.styles import apply_base_styles


VALID_PAGES = {"introduction", "routes"}


def _load_study_context() -> tuple[
    dict[str, pd.DataFrame],
    dict[str, str],
    pd.DatetimeIndex,
    str,
    str,
]:
    """Load published aggregates and derive values shared by both pages."""
    try:
        data = load_public_data()
    except FileNotFoundError as exc:
        st.error(
            "Public dashboard data is missing. Run "
            "`python streamlit_app/build_public_data.py` first."
        )
        st.exception(exc)
        st.stop()

    metadata = dict(zip(data["metadata"]["key"], data["metadata"]["value"]))
    available_periods = [
        value.strip() for value in metadata["available_periods"].split(",")
    ]
    period_dates = pd.to_datetime(available_periods, format="%Y%m")
    period_text = ", ".join(period_dates.strftime("%B"))
    study_year = metadata["study_year"]
    return data, metadata, period_dates, period_text, study_year


def _current_page() -> str:
    """Return a supported page from the query string."""
    requested_page: Any = st.query_params.get("page", "introduction")
    if isinstance(requested_page, list):
        requested_page = requested_page[0] if requested_page else "introduction"
    return requested_page if requested_page in VALID_PAGES else "introduction"


def main() -> None:
    """Configure and render the dashboard."""
    st.set_page_config(
        page_title="European Aviation Intelligence",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    apply_base_styles()

    data, metadata, period_dates, period_text, study_year = _load_study_context()
    current_page = _current_page()
    render_page_chrome(current_page, study_year)

    if current_page == "routes":
        render_routes_page(period_text, study_year)
        return

    render_introduction_page(
        data=data,
        metadata=metadata,
        period_dates=period_dates,
        period_text=period_text,
        study_year=study_year,
    )


if __name__ == "__main__":
    main()
