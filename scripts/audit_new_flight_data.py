"""Audit schema and null patterns for the expanded monthly flight dataset."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.flight_data_catalog import (
    compare_null_cohorts,
    discover_monthly_flights,
    profile_nulls_by_month,
    validate_flight_schemas,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rows-per-file", type=int)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "reports" / "data_quality" / "expanded",
    )
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    records = discover_monthly_flights(PROJECT_ROOT / "data" / "raw")
    paths = [record.path for record in records]
    months = [record.month for record in records]
    old_months = [month for month in months if month not in {"202106", "202109", "202306"}]
    new_months = [month for month in months if month in {"202106", "202109", "202306"}]

    catalog = __import__("pandas").DataFrame(
        [{"month": item.month, "path": str(item.path), "source": item.source} for item in records]
    )
    schema = validate_flight_schemas(paths)
    profile = profile_nulls_by_month(paths, max_rows_per_file=args.max_rows_per_file)
    comparison = compare_null_cohorts(profile, old_months, new_months)

    catalog.to_csv(args.output_root / "flight_file_catalog.csv", index=False)
    schema.to_csv(args.output_root / "schema_compatibility.csv", index=False)
    profile.to_csv(args.output_root / "null_profile_by_month.csv", index=False)
    comparison.to_csv(args.output_root / "null_profile_new_vs_reference.csv", index=False)
    print({
        "months": months,
        "new_months": new_months,
        "all_schemas_equal": bool(schema["matches_reference_schema"].all()),
        "material_null_changes": comparison.loc[comparison["material_change"], "column"].tolist(),
        "output_root": str(args.output_root),
    })


if __name__ == "__main__":
    main()
