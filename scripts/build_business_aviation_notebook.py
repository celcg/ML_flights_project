"""Generate the English business-aviation analysis notebook."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv313" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.exists():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

import nbformat as nbf


OUTPUT = PROJECT_ROOT / "notebooks" / "09_business_aviation_analysis.ipynb"


def markdown(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


def build_notebook() -> Path:
    notebook = nbf.v4.new_notebook()
    notebook["metadata"] = {
        "kernelspec": {
            "display_name": "Python 3.13 (ML Flights)",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.13"},
    }
    notebook["cells"] = [
        markdown(
            """
# 09 · Business aviation performance analysis

This notebook converts the EUROCONTROL flight records into a business-facing
view of network demand, punctuality, severity and operational recovery.

**Scope**

- Scheduled commercial traffic only: `ICAO Flight Type == 'S'`.
- Directional routes: `ADEP → ADES`.
- Nine monthly snapshots from June 2021 through June 2023.
- March and June 2023 are descriptive here, but remain model holdouts elsewhere.
- Counts refer to operated flights, not passengers, seats or revenue.

The notebook adds a new analysis layer. It does not replace notebooks 01–03.
"""
        ),
        code(
            """
from pathlib import Path
import sys
import time

import matplotlib.pyplot as plt
import pandas as pd
from IPython.display import display, Image

PROJECT_ROOT = Path.cwd().resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.business_eda import (
    BusinessAnalysisConfig,
    airport_performance,
    business_hypothesis_tests,
    development_flight_paths,
    executive_route_views,
    export_business_analysis,
    hypothesis_test_catalog,
    load_dimension_labels,
    numeric_correlation_table,
    operator_performance,
    overall_kpis,
    plot_departure_arrival_recovery,
    plot_airport_reliability_rankings,
    plot_airport_volume_reliability,
    plot_route_volume_reliability,
    plot_statistical_method_explainer,
    plot_time_reliability_heatmap,
    plot_top_route_comparison,
    read_business_flights,
    route_performance,
    route_threshold_sensitivity,
    scan_route_volume,
)
from src.flight_data_catalog import discover_monthly_flights
from src.flight_data_catalog import (
    compare_null_cohorts,
    profile_nulls_by_month,
    validate_flight_schemas,
)

RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_ICAO = PROJECT_ROOT / "data" / "raw" / "icao"
BASE_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "business_eda"
flight_catalog = discover_monthly_flights(RAW_ROOT)
all_flight_files = [record.path for record in flight_catalog]
assert all_flight_files, "No flight files were found"
"""
        ),
        markdown(
            """
## 1. Reproducible business rules

The configuration below makes every reporting choice visible. The executive
route ranking requires at least 500 operated flights and activity in three
observed periods. A broader 100-flight view is retained for network coverage.

Set `RUN_FULL_ANALYSIS = True` when producing the final report. The default
smoke mode reads only a few rows and is safe for rapid validation.

The file catalog combines the new month folders with the legacy flight folder,
prefers one canonical file per month and prevents duplicate ingestion.
"""
        ),
        code(
            """
CONFIG = BusinessAnalysisConfig(
    test_start="2023-01-01",
    analysis_end_exclusive="2023-07-01",
    executive_min_route_flights=500,
    executive_min_route_periods=3,
    executive_min_operator_flights=1_000,
    route_plot_min_flights=2,
    airport_plot_min_flights=30,
)

RUN_FULL_ANALYSIS = False
SMOKE_ROWS_PER_FILE = 2_000
MAX_ROWS_PER_FILE = None if RUN_FULL_ANALYSIS else SMOKE_ROWS_PER_FILE
OUTPUT_ROOT = (
    BASE_OUTPUT_ROOT
    if RUN_FULL_ANALYSIS
    else PROJECT_ROOT / "reports" / "business_eda_smoke"
)

print({
    "run_full_analysis": RUN_FULL_ANALYSIS,
    "max_rows_per_file": MAX_ROWS_PER_FILE,
    "reporting_end_exclusive": CONFIG.reporting_end,
    "output_root": str(OUTPUT_ROOT),
    "months": [record.month for record in flight_catalog],
})

# Enforce the configured reporting boundary before any CSV reader opens a file.
flight_files = development_flight_paths(all_flight_files, CONFIG)
print({
    "reporting_files": [path.name for path in flight_files],
    "excluded_files": sorted(set(path.name for path in all_flight_files) - set(path.name for path in flight_files)),
})
"""
        ),
        markdown(
            """
## 2. Expanded-data contract and null audit

The original source contained six monthly snapshots. The new files add June
and September 2021 plus June 2023. Before calculating business KPIs, the audit
checks that all 18 raw columns still match and compares row-weighted null rates.

A two-percentage-point difference is highlighted for review; it is not an
automatic reason to delete a column. The final full report should rerun this
cell with `RUN_FULL_ANALYSIS = True`.
"""
        ),
        code(
            """
schema_audit = validate_flight_schemas(all_flight_files)
assert schema_audit["matches_reference_schema"].all(), schema_audit
null_audit = profile_nulls_by_month(
    all_flight_files,
    max_rows_per_file=MAX_ROWS_PER_FILE,
)
reference_months = ["202112", "202203", "202206", "202209", "202212", "202303"]
new_months = ["202106", "202109", "202306"]
null_comparison = compare_null_cohorts(null_audit, reference_months, new_months)

audit_root = OUTPUT_ROOT / "data_quality"
audit_root.mkdir(parents=True, exist_ok=True)
schema_audit.to_csv(audit_root / "schema_compatibility.csv", index=False)
null_audit.to_csv(audit_root / "null_profile_by_month.csv", index=False)
null_comparison.to_csv(audit_root / "null_profile_new_vs_reference.csv", index=False)
display(schema_audit)
display(null_comparison)
"""
        ),
        markdown(
            """
## 3. Is a 500-flight route threshold sufficiently inclusive?

This lightweight scan reads only route, period and flight-type columns. It uses
all reporting files even when the rest of the notebook runs in smoke mode.

Two thresholds are useful for different questions:

- **500 flights + 3 periods:** defensible executive comparison.
- **100 flights + 3 periods:** broader network monitoring and discovery.
"""
        ),
        code(
            """
# Exact volume scan across the configured reporting period.
volume_started = time.perf_counter()
route_volume = scan_route_volume(
    flight_files, CONFIG, max_rows_per_file=MAX_ROWS_PER_FILE
)
volume_sensitivity = route_threshold_sensitivity(route_volume, CONFIG)
display(volume_sensitivity.round(2))
print(f"Route-volume scan: {time.perf_counter() - volume_started:.1f} seconds")
"""
        ),
        markdown(
            """
### How to interpret the threshold table

`eligible_routes` measures breadth; `flight_coverage_pct` measures how much of
the operated network remains. A high minimum volume increases statistical
stability but removes thin routes. The final report therefore presents both the
executive and broad-coverage views rather than hiding this trade-off.
"""
        ),
        markdown(
            """
## 4. Build the compact analytical flight table

The raw compressed files are read in chunks. Only report variables are kept,
continuous values are stored as 32-bit floats, and repeated text fields become
categories. This keeps the full analysis feasible on a low-memory computer.
"""
        ),
        code(
            """
load_started = time.perf_counter()
flights = read_business_flights(
    flight_files,
    CONFIG,
    chunksize=100_000,
    max_rows_per_file=MAX_ROWS_PER_FILE,
)

# This assertion protects the explicit reporting boundary.
assert flights["FILED OFF BLOCK TIME"].max() < pd.Timestamp(CONFIG.reporting_end)
print({
    "analysis_rows": len(flights),
    "periods": sorted(flights["period"].astype(str).unique()),
    "memory_mb": round(flights.memory_usage(deep=True).sum() / 1024**2, 1),
    "load_seconds": round(time.perf_counter() - load_started, 1),
})
"""
        ),
        code(
            """
# Compute each table once and reuse it throughout the narrative.
analysis_started = time.perf_counter()
analysis = export_business_analysis(flights, OUTPUT_ROOT, CONFIG)
print({
    "analysis_seconds": round(time.perf_counter() - analysis_started, 1),
    "output_root": str(analysis["output_root"]),
    "outside_reporting_period_rows": 0,
})
"""
        ),
        markdown(
            """
## 5. Executive network scorecard

OTP15 is the share of observed arrivals no more than 15 minutes late. Median
delay describes a typical flight; p90 and p95 reveal the operational tail that
drives disruption and customer impact.
"""
        ),
        code(
            """
kpis = analysis["kpis"]
display(kpis.to_frame("value").round(2))
"""
        ),
        markdown(
            """
## 5. Route demand and reliability

Raw percentages are not ranked without a volume rule. Wilson intervals express
uncertainty: small routes receive wider intervals, while high-volume routes are
estimated more precisely.
"""
        ),
        code(
            """
routes = analysis["routes"]
route_views = analysis["route_views"]

display(routes.head(20).round(2))
display(route_views["popular_reliable"].head(15).round(2))
display(route_views["least_reliable"].head(15).round(2))
"""
        ),
        code(
            """
# Volume and reliability answer different business questions, so both are shown.
display(plot_top_route_comparison(routes, CONFIG))
display(plot_route_volume_reliability(routes, float(kpis["arrival_otp15_pct"]), CONFIG))
plt.show()
"""
        ),
        markdown(
            """
### Business interpretation

- High volume + high OTP15: dependable core network.
- High volume + low OTP15: priority for operational intervention.
- Low volume + wide confidence interval: monitor before escalating.
- High p90 with acceptable median: usually reliable but exposed to severe tails.

Every route chart first excludes routes with fewer than two historical flights.
Executive reliability charts then apply the stronger 500-flight / three-period
rule. The two-flight rule prevents singleton routes from appearing as 0% or 100%
reliable while preserving broad volume charts.

The route table remains descriptive. It does not prove that a route causes a
delay because operator, airport, time and duration mix may differ.
"""
        ),
        markdown(
            """
## 6. Airline breadth and reliability

`AC Operator` is the operating carrier, not necessarily the marketing airline.
Route count measures network breadth; HHI measures concentration. A high HHI
means that a small number of routes dominate the operator's activity.
"""
        ),
        code(
            """
operators = analysis["operators"]
eligible_operators = operators.loc[
    operators["flights"].ge(CONFIG.executive_min_operator_flights)
]

display(
    eligible_operators[
        [
            "AC Operator", "flights", "routes", "airports",
            "arrival_otp15_pct", "arrival_delayed_30_pct",
            "arrival_delay_p90", "recovered_to_otp15_pct",
            "route_concentration_hhi",
        ]
    ].head(25).round(2)
)
"""
        ),
        markdown(
            """
## 7. Which origin and destination airports are most problematic?

Origin and destination roles are analysed separately because they answer
different operational questions. Origin results reflect the conditions under
which a flight begins; destination results reflect the environment into which
the flight arrives. Airports require at least 30 observed flights in these smoke-
safe charts, and every estimate is accompanied by a 95% Wilson interval.
"""
        ),
        code(
            """
origin_airports = analysis["origin_airports"]
destination_airports = analysis["destination_airports"]

display(origin_airports.head(15).round(2))
display(destination_airports.head(15).round(2))

display(plot_airport_volume_reliability(
    origin_airports, "origin", float(kpis["arrival_otp15_pct"]), CONFIG
))
display(plot_airport_reliability_rankings(origin_airports, "origin", CONFIG))
display(plot_airport_volume_reliability(
    destination_airports, "destination", float(kpis["arrival_otp15_pct"]), CONFIG
))
display(plot_airport_reliability_rankings(destination_airports, "destination", CONFIG))
plt.show()
"""
        ),
        markdown(
            """
### Airport-chart interpretation

- The volume–reliability charts show scale, OTP15 and >30-minute exposure.
- The ranking charts use Wilson intervals, not raw percentages.
- A problematic origin is associated with weaker arrival outcomes for flights
  leaving that airport; a problematic destination is associated with weaker
  outcomes for flights arriving there.
- These are unadjusted associations. Route, operator, time and duration mix can
  explain part of the difference and should be controlled before assigning cause.
"""
        ),
        markdown(
            """
## 8. When is the network least reliable?

The heatmap uses scheduled departure time, which is known in advance. It helps
identify operational windows for staffing, disruption monitoring and customer
communications. It is descriptive and should not be interpreted as causal.
"""
        ),
        code(
            """
display(plot_time_reliability_heatmap(flights))
plt.show()
"""
        ),
        markdown(
            """
## 9. Delay propagation and recovery

Each hexagon groups many flights. The green diagonal represents equal departure
and arrival delay. Points below it recovered minutes; points above it worsened
after departure.
"""
        ),
        code(
            """
display(plot_departure_arrival_recovery(flights))
plt.show()
"""
        ),
        markdown(
            """
## 10. Correlation: association, not causation

Pearson measures linear association. Spearman measures monotonic association and
is less sensitive to extreme delays. Post-event variables are valid for this
retrospective report but remain unavailable to the T−60 prediction model.
"""
        ),
        code(
            """
correlations = analysis["correlations"]
display(
    correlations.reindex(
        correlations["spearman_rho"].abs().sort_values(ascending=False).index
    ).head(20).round(4)
)
"""
        ),
        markdown(
            """
## 11. Hypothesis tests: what exactly is being tested?

The catalog below separates tests already automated for the core report from
optional tests that require a business decision before execution.

**Core tests already implemented**

- **H01 — December change:** H0 says December 2021 and December 2022 have equal
  arrival OTP15. A two-proportion z-test is paired with the percentage-point
  difference.
- **H02 — En-route recovery:** H0 says median recovery equals zero among flights
  leaving more than 15 minutes late. Wilcoxon is used because delay differences
  are skewed and contain extreme events.
- **H03 — Haul bands:** H0 says all flight-duration bands share the same arrival-
  delay distribution. Kruskal–Wallis avoids a normality assumption.

**Recommended optional tests for selection**

- H04/H05: origin- and destination-airport association with OTP15.
- H06: operator association with OTP15, with a route-mix warning.
- H07: per-route stability across observed periods, corrected for multiple tests.
- H08: differences across scheduled departure-hour bands.
- H09: monotonic relationship between duration and delay.
- H10: adjusted operator effects after controlling for route, time and duration.

Large datasets can produce tiny p-values for unimportant differences. The report
therefore shows effect size and units alongside significance. Benjamini–Hochberg
is used only when many related hypotheses are tested simultaneously.
"""
        ),
        code(
            """
h0_catalog = analysis["hypothesis_test_catalog"]
hypothesis_tests = analysis["hypothesis_tests"]
display(h0_catalog)
display(hypothesis_tests.round(5))
display(plot_statistical_method_explainer())
plt.show()
"""
        ),
        markdown(
            """
## 12. Generate report-ready assets

The export keeps tables, statistical outputs and figures separate. The future
Word report can therefore be regenerated without copying values manually.
"""
        ),
        code(
            """
print({
    "output_root": str(analysis["output_root"]),
    "tables": sorted(path.name for path in (OUTPUT_ROOT / "tables").glob("*.csv")),
    "figures": sorted(path.name for path in (OUTPUT_ROOT / "figures").glob("*.png")),
    "outside_reporting_period_rows": 0,
})
"""
        ),
        markdown(
            """
## 13. Reporting limitations

1. The expanded data contains nine separated monthly snapshots, not a continuous calendar.
2. The descriptive report includes March and June 2023. Model notebooks keep them outside fitting and tuning.
3. Results describe operated flights; cancellations and diversions are absent.
4. Flight volume is not passenger, seat or revenue volume.
5. Operator comparisons are affected by route, airport and schedule mix.
6. `STATFOR Market Segment` loses detail in later files and must be interpreted cautiously.
7. Statistical significance does not establish operational causality.

Recommended next data: consecutive months, cancellations, aircraft capacity,
airport constraints, ATFM regulations and weather after the flight-only baseline
is fully documented.
"""
        ),
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(notebook, OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build_notebook())
