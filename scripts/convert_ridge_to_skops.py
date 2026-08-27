"""Convert the trusted legacy Ridge joblib into a restricted skops artifact."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import skops.io as sio


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_ROOT = PROJECT_ROOT / "streamlit_app"
for module_root in (PROJECT_ROOT, STREAMLIT_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from dashboard.ridge_features import build_schedule_feature_frame
from dashboard.ridge_preprocessing import (
    RIDGE_ARTIFACT_FORMAT_VERSION,
    transform_ridge_features,
)


DEFAULT_SOURCE = (
    PROJECT_ROOT / "models" / "expanded" / "arrival_pre_t60_expanded_selected.joblib"
)
DEFAULT_TARGET = (
    PROJECT_ROOT / "models" / "expanded" / "arrival_pre_t60_expanded_selected.skops"
)


def convert_artifact(source: Path, target: Path) -> tuple[list[str], float, str]:
    """Convert, inspect and compare the new artifact with the trusted source."""

    legacy = joblib.load(source)
    preprocessor = legacy["preprocessor"]
    safe_artifact = {
        "artifact_format_version": RIDGE_ARTIFACT_FORMAT_VERSION,
        "model": legacy["model"],
        "encoder": preprocessor.encoder,
        "scaler": preprocessor.scaler,
        "low_cardinality_columns": list(preprocessor.low_cardinality_columns),
        "high_cardinality_columns": list(preprocessor.high_cardinality_columns),
        "preprocessor_numeric_columns": list(preprocessor.numeric_columns),
        "numeric_medians": {
            str(column): float(value)
            for column, value in preprocessor.numeric_medians.items()
        },
        "hash_features": int(preprocessor.hash_features),
        "numeric_columns": list(legacy["numeric_columns"]),
        "categorical_columns": list(legacy["categorical_columns"]),
        "prediction_horizon_minutes": legacy["prediction_horizon_minutes"],
        "selected_model_name": legacy["selected_model_name"],
        "selected_hyperparameters": legacy["selected_hyperparameters"],
        "target": legacy["target"],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    sio.dump(safe_artifact, target)

    untrusted_types = sorted(sio.get_untrusted_types(file=target))
    loaded = sio.load(target, trusted=untrusted_types)
    maximum_difference = _maximum_prediction_difference(legacy, loaded)
    if maximum_difference > 1e-10:
        raise RuntimeError(
            "Prediction parity failed; maximum absolute difference was "
            f"{maximum_difference:.12g}."
        )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return untrusted_types, maximum_difference, digest


def _maximum_prediction_difference(legacy: dict, converted: dict) -> float:
    routes = pd.read_csv(
        STREAMLIT_ROOT / "public_data" / "routes" / "route_metrics.csv"
    )
    routes = routes[
        routes["scope_id"].eq("all_flights")
        & routes["flight_count"].ge(20)
        & routes["median_scheduled_duration_min"].notna()
    ].nlargest(30, "flight_count")
    operators = pd.read_csv(
        STREAMLIT_ROOT / "public_data" / "routes" / "route_operator_metrics.csv"
    )

    frames = []
    for index, route in enumerate(routes.to_dict("records")):
        route_operators = operators[
            operators["scope_id"].eq("all_flights")
            & operators["ADEP"].eq(route["ADEP"])
            & operators["ADES"].eq(route["ADES"])
            & operators["flight_count"].ge(20)
        ]
        operator_code = (
            str(route_operators.nlargest(1, "flight_count").iloc[0]["operator_code"])
            if not route_operators.empty
            else "ZZZ"
        )
        frames.append(
            build_schedule_feature_frame(
                pd.Series(route),
                operator_code,
                departure_month=(3, 6, 9, 12)[index % 4],
                departure_weekday=index % 7,
                departure_hour=(index * 5) % 24,
                numeric_columns=converted["numeric_columns"],
                categorical_columns=converted["categorical_columns"],
            )
        )
    validation_frame = pd.concat(frames, ignore_index=True)
    expected = legacy["model"].predict(
        legacy["preprocessor"].transform(validation_frame)
    )
    actual = converted["model"].predict(
        transform_ridge_features(converted, validation_frame)
    )
    return float(np.max(np.abs(expected - actual)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    arguments = parser.parse_args()
    untrusted, difference, digest = convert_artifact(
        arguments.source.resolve(), arguments.target.resolve()
    )
    print(f"Wrote: {arguments.target.resolve()}")
    print(f"Untrusted types requiring review: {untrusted}")
    print(f"Maximum prediction difference: {difference:.12g}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
