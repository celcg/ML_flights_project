"""Shared project decisions used by both Pandas and PySpark notebooks."""

from dataclasses import dataclass
from typing import Literal, Optional


PredictionHorizon = Literal["pre_departure", "post_off_block"]
TargetColumn = Literal["Departure_Delay_Min", "Arrival_Delay_Min"]


@dataclass(frozen=True)
class DataQualityConfig:
    """Physical and project-scope limits.

    Scheduled commercial traffic is identified by ``ICAO Flight Type == 'S'``.
    ``scope_min_flight_level`` is optional because FL100 is a scope decision,
    not a physical validity boundary.
    """

    min_delay_minutes: float = -120.0
    min_flight_level: float = 0.0
    max_flight_level: float = 500.0
    regular_commercial_only: bool = True
    regular_flight_type: str = "S"
    scope_min_flight_level: Optional[float] = None
    min_distance_nm: float = 0.0


@dataclass(frozen=True)
class FeatureConfig:
    target: TargetColumn = "Arrival_Delay_Min"
    prediction_horizon: PredictionHorizon = "pre_departure"
    apply_log: bool = False
    apply_yeo_johnson: bool = False
    categorical_hash_features: int = 1 << 15
    rare_category_min_count: int = 1_000


SEED = 42
SAMPLE_FRACTION = 0.15
DATETIME_FORMAT_PANDAS = "%d-%m-%Y %H:%M:%S"
DATETIME_FORMAT_SPARK = "dd-MM-yyyy HH:mm:ss"
TIME_COLUMNS = (
    "FILED ARRIVAL TIME",
    "ACTUAL ARRIVAL TIME",
    "FILED OFF BLOCK TIME",
    "ACTUAL OFF BLOCK TIME",
)

# These are the only raw variables available at each operational horizon.
# Target columns and post-arrival measurements are intentionally absent.
PRE_DEPARTURE_FEATURES = (
    "ADEP",
    "ADES",
    "AC Type",
    "Class_aircraft",
    "Number+Engine Type_aircraft",
    "AC Operator",
    "STATFOR Market Segment",
    "Requested FL",
    "FILED OFF BLOCK TIME",
    "FILED ARRIVAL TIME",
)

POST_OFF_BLOCK_FEATURES = PRE_DEPARTURE_FEATURES + (
    "ACTUAL OFF BLOCK TIME",
    "Departure_Delay_Min",
)


TARGET_COLUMNS = ("Departure_Delay_Min", "Arrival_Delay_Min")


def features_for_horizon(horizon: PredictionHorizon) -> tuple[str, ...]:
    if horizon == "pre_departure":
        return PRE_DEPARTURE_FEATURES
    if horizon == "post_off_block":
        return POST_OFF_BLOCK_FEATURES
    raise ValueError(f"Unsupported prediction horizon: {horizon}")


def features_for_task(
    target: TargetColumn, horizon: PredictionHorizon
) -> tuple[str, ...]:
    """Return operationally available features and reject meaningless tasks."""

    if target == "Departure_Delay_Min" and horizon == "post_off_block":
        raise ValueError(
            "Departure delay is already observed post-off-block; predict it only "
            "at the pre-departure horizon."
        )
    return features_for_horizon(horizon)
