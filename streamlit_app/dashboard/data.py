"""Cached access to the public aggregate datasets bundled with the app."""

from pathlib import Path

import pandas as pd
import streamlit as st


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT / "public_data" / "introduction"
ROUTES_DATA_ROOT = APP_ROOT / "public_data" / "routes"


def _load_csv_bundle(root: Path, files: dict[str, str]) -> dict[str, pd.DataFrame]:
    missing = [filename for filename in files.values() if not (root / filename).exists()]
    if missing:
        raise FileNotFoundError(
            "Missing public data: " + ", ".join(missing) + ". Run build_public_data.py first."
        )
    return {name: pd.read_csv(root / filename) for name, filename in files.items()}


@st.cache_data
def load_public_data() -> dict[str, pd.DataFrame]:
    return _load_csv_bundle(
        DATA_ROOT,
        {
            "overview": "overview_kpis.csv",
            "monthly": "monthly_delay_trend.csv",
            "duration": "duration_hour_metrics.csv",
            "correlation": "correlation_metrics.csv",
            "metadata": "dashboard_metadata.csv",
        },
    )


@st.cache_data
def load_route_data(cache_version: str = "route_drilldown_v1") -> dict[str, pd.DataFrame]:
    del cache_version
    return _load_csv_bundle(
        ROUTES_DATA_ROOT,
        {
            "metrics": "route_metrics.csv",
            "summary": "route_scope_summary.csv",
            "methodology": "route_ranking_methodology.csv",
            "monthly": "route_monthly_metrics.csv",
            "operators": "route_operator_metrics.csv",
        },
    )

