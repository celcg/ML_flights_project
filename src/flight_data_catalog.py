"""Canonical discovery and schema/null audits for monthly flight files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Sequence

import pandas as pd


FLIGHT_FILE_PATTERN = re.compile(r"Flights_(\d{6})\d{2}_(\d{6})\d{2}\.csv\.gz$")


@dataclass(frozen=True)
class FlightFileRecord:
    month: str
    path: Path
    source: str


def _month_from_name(path: Path) -> str:
    match = FLIGHT_FILE_PATTERN.search(path.name)
    if match is None or match.group(1) != match.group(2):
        raise ValueError(f"Unexpected monthly flight filename: {path.name}")
    return match.group(1)


def discover_monthly_flights(raw_root: Path | str) -> list[FlightFileRecord]:
    """Return one flight file per month, preferring the month-named folders.

    Older files also live in ``raw/flights``.  The preference prevents a month
    from being ingested twice while still retaining December 2022, which is
    currently available only in that legacy folder.
    """

    root = Path(raw_root)
    candidates: list[FlightFileRecord] = []
    for path in sorted(root.glob("20????/Flights_*.csv.gz")):
        candidates.append(FlightFileRecord(_month_from_name(path), path, "monthly_folder"))
    for path in sorted((root / "flights").glob("Flights_*.csv.gz")):
        candidates.append(FlightFileRecord(_month_from_name(path), path, "legacy_flights_folder"))

    selected: dict[str, FlightFileRecord] = {}
    for record in candidates:
        prior = selected.get(record.month)
        if prior is None or (
            prior.source == "legacy_flights_folder" and record.source == "monthly_folder"
        ):
            selected[record.month] = record
    return [selected[month] for month in sorted(selected)]


def flight_paths_between(
    records: Sequence[FlightFileRecord],
    *,
    start: str | None = None,
    end_exclusive: str | None = None,
) -> list[Path]:
    start_month = start[:7].replace("-", "") if start else None
    end_month = end_exclusive[:7].replace("-", "") if end_exclusive else None
    return [
        record.path
        for record in records
        if (start_month is None or record.month >= start_month)
        and (end_month is None or record.month < end_month)
    ]


def validate_flight_schemas(paths: Sequence[Path | str]) -> pd.DataFrame:
    """Read headers only and report whether every raw schema is identical."""

    rows = []
    reference: list[str] | None = None
    for raw_path in paths:
        path = Path(raw_path)
        columns = pd.read_csv(path, compression="gzip", nrows=0).columns.tolist()
        if reference is None:
            reference = columns
        rows.append(
            {
                "month": _month_from_name(path),
                "file": path.name,
                "columns": len(columns),
                "matches_reference_schema": columns == reference,
                "missing_from_reference": "|".join(sorted(set(reference) - set(columns))),
                "extra_vs_reference": "|".join(sorted(set(columns) - set(reference))),
            }
        )
    return pd.DataFrame(rows)


def profile_nulls_by_month(
    paths: Sequence[Path | str],
    *,
    chunksize: int = 200_000,
    max_rows_per_file: int | None = None,
) -> pd.DataFrame:
    """Calculate null/blank rates with bounded memory for every raw column."""

    output = []
    for raw_path in paths:
        path = Path(raw_path)
        rows = 0
        null_counts: pd.Series | None = None
        for chunk in pd.read_csv(
            path,
            compression="gzip",
            chunksize=chunksize,
            nrows=max_rows_per_file,
            low_memory=False,
        ):
            text = chunk.select_dtypes(include=["object", "string"])
            if not text.empty:
                chunk[text.columns] = text.apply(
                    lambda values: values.mask(values.astype("string").str.strip().eq(""))
                )
            current = chunk.isna().sum().astype("int64")
            null_counts = current if null_counts is None else null_counts.add(current, fill_value=0)
            rows += len(chunk)
        if null_counts is None:
            continue
        month = _month_from_name(path)
        output.extend(
            {
                "month": month,
                "column": column,
                "rows": rows,
                "nulls": int(count),
                "null_pct": 100.0 * count / rows if rows else float("nan"),
            }
            for column, count in null_counts.items()
        )
    return pd.DataFrame(output)


def compare_null_cohorts(
    profile: pd.DataFrame,
    reference_months: Iterable[str],
    new_months: Iterable[str],
    *,
    material_delta_pp: float = 2.0,
) -> pd.DataFrame:
    """Compare row-weighted null rates and flag material changes."""

    def aggregate(months: set[str], label: str) -> pd.DataFrame:
        scoped = profile.loc[profile["month"].isin(months)]
        result = scoped.groupby("column", as_index=False).agg(rows=("rows", "sum"), nulls=("nulls", "sum"))
        result[f"{label}_null_pct"] = 100.0 * result["nulls"] / result["rows"]
        return result[["column", f"{label}_null_pct"]]

    reference = aggregate(set(reference_months), "reference")
    new = aggregate(set(new_months), "new")
    result = reference.merge(new, on="column", how="outer")
    result["delta_null_pp"] = result["new_null_pct"] - result["reference_null_pct"]
    result["material_change"] = result["delta_null_pp"].abs().ge(material_delta_pp)
    return result.sort_values(["material_change", "delta_null_pp"], ascending=[False, False], ignore_index=True)
