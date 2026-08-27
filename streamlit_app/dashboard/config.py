"""Shared visual and navigation constants."""

NAVY = "#0B1F33"
BLUE = "#2F6FB0"
GREEN = "#2E8B68"
RED = "#C35D5D"
TEXT = "#23364A"
MUTED = "#66788A"
GRID = "#E5EDF4"

COMPACT_CHART_PADDING = {"left": 6, "right": 20, "top": 4, "bottom": 8}
DELAYED_ROUTE_THRESHOLD_PCT = 30.0

ROUTE_SCOPE_LABELS = {
    "all_flights": "All flights",
    "scheduled_duration_under_3h": "Under 3 hours",
    "scheduled_duration_3h_or_more": "3 hours or more",
}

ROUTE_RANKING_METRICS = {
    "delay_over_15_pct": {
        "label": "Delayed-flight percentage",
        "axis": "Delayed >15 min (%)",
        "suffix": "%",
    },
    "median_arrival_delay_min": {
        "label": "Median arrival delay",
        "axis": "Median arrival delay (minutes)",
        "suffix": " min",
    },
}

AIRPORT_DELAY_VIEWS = {
    "both": {
        "label": "Arrivals + departures",
        "metric": "combined_delay_over_15_pct",
        "short_label": "Both",
    },
    "arrival": {
        "label": "Arrival delays",
        "metric": "arrival_delay_over_15_pct",
        "short_label": "Arrivals",
    },
    "departure": {
        "label": "Departure delays",
        "metric": "departure_delay_over_15_pct",
        "short_label": "Departures",
    },
}

RELIABILITY_ENTITY_LABELS = {
    "airports": "Airports",
    "routes": "Routes",
    "airlines": "Airlines",
}

RELIABILITY_VIEW_LABELS = {
    "most_reliable": "Most reliable",
    "least_reliable": "Least reliable",
}
