"""Schedule-only inference adapter for the selected Ridge artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import skops.io as sio
import streamlit as st

from dashboard.ridge_features import build_schedule_feature_frame
from dashboard.ridge_preprocessing import transform_ridge_features


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RIDGE_MODEL_PATH = (
    PROJECT_ROOT / "models" / "expanded" / "arrival_pre_t60_expanded_selected.skops"
)
TRUSTED_SKOPS_TYPES: frozenset[str] = frozenset()
RIDGE_MODEL_SHA256 = "92c1a809d0ceae86059f81018c3bf04f9e85526f6d294e0d93fe09ab68250e99"

@st.cache_resource(show_spinner=False)
def load_ridge_artifact() -> dict:
    """Load the selected T-60 Ridge artifact once per Streamlit process."""

    if not RIDGE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Ridge artifact not found: {RIDGE_MODEL_PATH}")
    actual_digest = hashlib.sha256(RIDGE_MODEL_PATH.read_bytes()).hexdigest()
    if actual_digest != RIDGE_MODEL_SHA256:
        raise ValueError("Ridge artifact integrity check failed.")
    untrusted_types = set(sio.get_untrusted_types(file=RIDGE_MODEL_PATH))
    unexpected_types = untrusted_types - TRUSTED_SKOPS_TYPES
    if unexpected_types:
        raise ValueError(
            "Ridge artifact contains unapproved types: "
            + ", ".join(sorted(unexpected_types))
        )
    return sio.load(
        RIDGE_MODEL_PATH,
        trusted=sorted(untrusted_types & TRUSTED_SKOPS_TYPES),
    )


def predict_arrival_delay_minutes(
    route: pd.Series,
    operator_code: str,
    departure_month: int,
    departure_weekday: int,
    departure_hour: int,
) -> float:
    """Run a schedule-only Ridge scenario, median-imputing unavailable live fields."""

    artifact = load_ridge_artifact()
    feature_frame = build_schedule_feature_frame(
        route,
        operator_code,
        departure_month,
        departure_weekday,
        departure_hour,
        numeric_columns=artifact["numeric_columns"],
        categorical_columns=artifact["categorical_columns"],
    )
    transformed = transform_ridge_features(artifact, feature_frame)
    return float(artifact["model"].predict(transformed)[0])
