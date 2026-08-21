"""Run the business aviation EDA without opening Jupyter.

Examples
--------
Small validation run:
    python scripts/run_business_eda.py --max-rows-per-file 2000

Full expanded descriptive run through June 2023:
    python scripts/run_business_eda.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv313" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.exists():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.business_eda import (  # noqa: E402
    BusinessAnalysisConfig,
    development_flight_paths,
    export_business_analysis,
    read_business_flights,
)
from src.flight_data_catalog import discover_monthly_flights


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate business aviation EDA outputs")
    parser.add_argument(
        "--max-rows-per-file",
        type=int,
        default=None,
        help="Read only the first N rows of each file for a quick smoke test",
    )
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "reports" / "business" / "analysis",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    all_paths = [
        record.path
        for record in discover_monthly_flights(PROJECT_ROOT / "data" / "raw")
    ]
    if not all_paths:
        raise FileNotFoundError("No EUROCONTROL monthly flight files were found")

    config = BusinessAnalysisConfig(analysis_end_exclusive="2023-07-01")
    paths = development_flight_paths(all_paths, config)
    flights = read_business_flights(
        paths,
        config,
        chunksize=args.chunksize,
        max_rows_per_file=args.max_rows_per_file,
    )
    if flights.empty:
        raise RuntimeError("The selected files produced no in-scope flights")
    result = export_business_analysis(flights, args.output_root, config)
    elapsed = time.perf_counter() - started

    summary = {
        "input_files": [path.name for path in paths],
        "analysis_end_exclusive": config.reporting_end,
        "max_rows_per_file": args.max_rows_per_file,
        "analysis_rows": len(flights),
        "analysis_memory_mb": round(float(result["memory_mb"]), 2),
        "elapsed_seconds": round(elapsed, 2),
        "output_root": str(args.output_root.resolve()),
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "execution_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
