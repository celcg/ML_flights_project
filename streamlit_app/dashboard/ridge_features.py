"""Schedule-only feature construction shared by conversion and inference."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


EUROPEAN_COUNTRIES = {
    "ALBANIA", "AUSTRIA", "BELARUS", "BELGIUM", "BOSNIA AND HERZEGOVINA",
    "BULGARIA", "CROATIA", "CYPRUS", "CZECH REPUBLIC", "CZECHIA", "DENMARK",
    "ESTONIA", "FINLAND", "FRANCE", "GEORGIA", "GERMANY", "GREECE", "HUNGARY",
    "ICELAND", "IRELAND", "ITALY", "KOSOVO", "LATVIA", "LITHUANIA",
    "LUXEMBOURG", "MALTA", "MOLDOVA", "MONTENEGRO", "NETHERLANDS",
    "NORTH MACEDONIA", "NORWAY", "POLAND", "PORTUGAL", "ROMANIA", "SERBIA",
    "SLOVAKIA", "SLOVENIA", "SPAIN", "SWEDEN", "SWITZERLAND", "TURKEY",
    "UKRAINE", "UNITED KINGDOM",
}
NORTH_AMERICAN_COUNTRIES = {
    "CANADA", "GREENLAND", "MEXICO", "UNITED STATES", "UNITED STATES OF AMERICA",
}
SOUTH_AMERICAN_COUNTRIES = {
    "ARGENTINA", "BOLIVIA", "BRAZIL", "CHILE", "COLOMBIA", "ECUADOR",
    "GUYANA", "PARAGUAY", "PERU", "SURINAME", "URUGUAY", "VENEZUELA",
}


def build_schedule_feature_frame(
    route: pd.Series,
    operator_code: str,
    departure_month: int,
    departure_weekday: int,
    departure_hour: int,
    *,
    numeric_columns: list[str],
    categorical_columns: list[str],
) -> pd.DataFrame:
    """Build the schedule-only feature row expected by the trained model."""

    duration = float(route["median_scheduled_duration_min"])
    origin_continent = _continent_code(route.get("origin_country"))
    destination_continent = _continent_code(route.get("destination_country"))
    direction = _transatlantic_direction(origin_continent, destination_continent)
    arrival_hour = (departure_hour + duration / 60) % 24
    weekday = float(departure_weekday)

    values: dict[str, object] = {column: np.nan for column in numeric_columns}
    values.update({column: "__MISSING__" for column in categorical_columns})
    values.update(
        {
            "ADEP": str(route["ADEP"]),
            "ADES": str(route["ADES"]),
            "AC Operator": operator_code,
            "ADEP_Continent": origin_continent,
            "ADES_Continent": destination_continent,
            "Duration_Band": "LONG_HAUL_>6H" if duration > 360 else "SHORT_MEDIUM_<=6H",
            "Transatlantic_Direction": direction,
            "scheduled_duration_min": duration,
            "departure_hour_sin": math.sin(2 * math.pi * departure_hour / 24),
            "departure_hour_cos": math.cos(2 * math.pi * departure_hour / 24),
            "departure_dow_sin": math.sin(2 * math.pi * weekday / 7),
            "departure_dow_cos": math.cos(2 * math.pi * weekday / 7),
            "departure_month": float(departure_month),
            "scheduled_arrival_hour_sin": math.sin(2 * math.pi * arrival_hour / 24),
            "scheduled_arrival_hour_cos": math.cos(2 * math.pi * arrival_hour / 24),
            "Is_Transatlantic": float(direction != "NON_TRANSATLANTIC"),
            "duration_x_europe_to_americas": (
                duration if direction == "EUROPE_TO_AMERICAS" else 0.0
            ),
            "duration_x_americas_to_europe": (
                duration if direction == "AMERICAS_TO_EUROPE" else 0.0
            ),
        }
    )
    return pd.DataFrame([values])


def _continent_code(country: object) -> str:
    country_name = "" if pd.isna(country) else str(country).strip().upper()
    if country_name in EUROPEAN_COUNTRIES:
        return "EU"
    if country_name in NORTH_AMERICAN_COUNTRIES:
        return "NA"
    if country_name in SOUTH_AMERICAN_COUNTRIES:
        return "SA"
    return "Unknown"


def _transatlantic_direction(origin: str, destination: str) -> str:
    americas = {"NA", "SA"}
    if origin == "EU" and destination in americas:
        return "EUROPE_TO_AMERICAS"
    if origin in americas and destination == "EU":
        return "AMERICAS_TO_EUROPE"
    return "NON_TRANSATLANTIC"
