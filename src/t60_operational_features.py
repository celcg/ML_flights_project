"""Leakage-safe operational features available at a T-60 prediction cutoff."""

from __future__ import annotations

from collections.abc import Sequence

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def deterministic_percent_sample(
    frame: DataFrame,
    percent: int,
    id_column: str = "ECTRL ID",
) -> DataFrame:
    """Return stable, nested integer-percent samples based on the flight id."""

    if not 0 < percent <= 100:
        raise ValueError("percent must be between 1 and 100")
    return frame.filter(F.pmod(F.hash(id_column), F.lit(100)) < percent)


def add_prediction_cutoff(
    frame: DataFrame,
    scheduled_off_block_column: str = "FILED OFF BLOCK TIME",
    cutoff_column: str = "prediction_cutoff_t60",
    lead_minutes: int = 60,
) -> DataFrame:
    """Attach the exact timestamp at which a prediction must be available."""

    return frame.withColumn(
        cutoff_column,
        F.col(scheduled_off_block_column) - F.expr(f"INTERVAL {lead_minutes} MINUTES"),
    )


def build_rolling_event_features(
    targets: DataFrame,
    events: DataFrame,
    *,
    key_columns: Sequence[str],
    event_time_column: str,
    value_column: str,
    prefix: str,
    windows_hours: Sequence[int] = (1, 6, 24),
    id_column: str = "ECTRL ID",
    cutoff_column: str = "prediction_cutoff_t60",
) -> DataFrame:
    """Build exact rolling aggregates and subtract a target's own event if present.

    Event and target rows share a timeline per entity. Range windows avoid the
    combinatorial explosion of a range join. Count, sum and squared sum are
    decomposable, so a very-early target event can be removed exactly.
    """

    keys = list(key_columns)
    if not keys:
        raise ValueError("At least one key column is required")
    windows = tuple(sorted(set(int(value) for value in windows_hours)))
    if not windows or min(windows) <= 0:
        raise ValueError("windows_hours must contain positive integers")

    usable_events = events.where(
        F.col(event_time_column).isNotNull()
        & F.col(value_column).isNotNull()
        & F.col(id_column).isNotNull()
        & F.expr(" AND ".join(f"`{column}` IS NOT NULL" for column in keys))
    )
    event_rows = usable_events.select(
        F.lit(None).cast("long").alias("_target_id"),
        F.col(id_column).cast("long").alias("_event_id"),
        *[F.col(column) for column in keys],
        F.col(event_time_column).alias("_timeline_time"),
        F.col(value_column).cast("double").alias("_event_value"),
        (F.col(value_column) > F.lit(15.0)).cast("double").alias("_event_delayed"),
        F.lit(0).alias("_row_kind"),
    )
    target_rows = targets.select(
        F.col(id_column).cast("long").alias("_target_id"),
        F.lit(None).cast("long").alias("_event_id"),
        *[F.col(column) for column in keys],
        F.col(cutoff_column).alias("_timeline_time"),
        F.lit(None).cast("double").alias("_event_value"),
        F.lit(None).cast("double").alias("_event_delayed"),
        F.lit(1).alias("_row_kind"),
    )
    combined = event_rows.unionByName(target_rows).withColumn(
        "_timeline_epoch", F.col("_timeline_time").cast("long")
    )

    raw_columns: list[str] = []
    for hours in windows:
        window = (
            Window.partitionBy(*keys)
            .orderBy(F.col("_timeline_epoch"))
            .rangeBetween(-hours * 3600, 0)
        )
        names = {
            "count": f"_{prefix}_{hours}h_raw_count",
            "sum": f"_{prefix}_{hours}h_raw_sum",
            "sumsq": f"_{prefix}_{hours}h_raw_sumsq",
            "delayed": f"_{prefix}_{hours}h_raw_delayed",
            "max_time": f"_{prefix}_{hours}h_max_event_time",
        }
        combined = (
            combined.withColumn(names["count"], F.count("_event_value").over(window))
            .withColumn(names["sum"], F.sum("_event_value").over(window))
            .withColumn(
                names["sumsq"], F.sum(F.pow(F.col("_event_value"), 2)).over(window)
            )
            .withColumn(names["delayed"], F.sum("_event_delayed").over(window))
            .withColumn(
                names["max_time"],
                F.max(F.when(F.col("_event_value").isNotNull(), F.col("_timeline_time"))).over(window),
            )
        )
        raw_columns.extend(names.values())

    target_aggregates = combined.where(F.col("_row_kind") == 1).select(
        F.col("_target_id").alias(id_column),
        F.col("_timeline_time").alias(cutoff_column),
        *raw_columns,
    )
    current_event = usable_events.select(
        F.col(id_column).cast("long").alias(id_column),
        F.col(event_time_column).alias("_current_event_time"),
        F.col(value_column).cast("double").alias("_current_event_value"),
    ).dropDuplicates([id_column])
    result = target_aggregates.join(current_event, id_column, "left")

    output_columns = [id_column, cutoff_column]
    for hours in windows:
        raw_count = F.col(f"_{prefix}_{hours}h_raw_count")
        raw_sum = F.coalesce(F.col(f"_{prefix}_{hours}h_raw_sum"), F.lit(0.0))
        raw_sumsq = F.coalesce(F.col(f"_{prefix}_{hours}h_raw_sumsq"), F.lit(0.0))
        raw_delayed = F.coalesce(F.col(f"_{prefix}_{hours}h_raw_delayed"), F.lit(0.0))
        self_in_window = (
            F.col("_current_event_time").isNotNull()
            & (F.col("_current_event_time") <= F.col(cutoff_column))
            & (
                F.col("_current_event_time")
                > F.col(cutoff_column) - F.expr(f"INTERVAL {hours} HOURS")
            )
        )
        self_indicator = self_in_window.cast("long")
        adjusted_count_name = f"{prefix}_{hours}h_count"
        adjusted_sum_name = f"_{prefix}_{hours}h_adjusted_sum"
        adjusted_sumsq_name = f"_{prefix}_{hours}h_adjusted_sumsq"
        adjusted_delayed_name = f"_{prefix}_{hours}h_adjusted_delayed"
        mean_name = f"{prefix}_{hours}h_mean"
        result = (
            result.withColumn(adjusted_count_name, raw_count - self_indicator)
            .withColumn(
                adjusted_sum_name,
                raw_sum
                - F.when(self_in_window, F.col("_current_event_value")).otherwise(F.lit(0.0)),
            )
            .withColumn(
                adjusted_sumsq_name,
                raw_sumsq
                - F.when(
                    self_in_window, F.pow(F.col("_current_event_value"), 2)
                ).otherwise(F.lit(0.0)),
            )
            .withColumn(
                adjusted_delayed_name,
                raw_delayed
                - F.when(self_in_window, (F.col("_current_event_value") > 15).cast("double"))
                .otherwise(F.lit(0.0)),
            )
            .withColumn(
                mean_name,
                F.when(
                    F.col(adjusted_count_name) > 0,
                    F.col(adjusted_sum_name) / F.col(adjusted_count_name),
                ),
            )
            .withColumn(
                f"{prefix}_{hours}h_std",
                F.when(
                    F.col(adjusted_count_name) > 0,
                    F.sqrt(
                        F.greatest(
                            F.col(adjusted_sumsq_name) / F.col(adjusted_count_name)
                            - F.pow(F.col(mean_name), 2),
                            F.lit(0.0),
                        )
                    ),
                ),
            )
            .withColumn(
                f"{prefix}_{hours}h_delayed_rate",
                F.when(
                    F.col(adjusted_count_name) > 0,
                    F.col(adjusted_delayed_name) / F.col(adjusted_count_name),
                ),
            )
            .withColumn(f"_{prefix}_{hours}h_self_removed", self_indicator)
        )
        output_columns.extend(
            [
                adjusted_count_name,
                mean_name,
                f"{prefix}_{hours}h_std",
                f"{prefix}_{hours}h_delayed_rate",
                f"_{prefix}_{hours}h_max_event_time",
                f"_{prefix}_{hours}h_self_removed",
            ]
        )
    return result.select(*output_columns)


def build_rotation_features(
    targets: DataFrame,
    events: DataFrame,
    *,
    registration_column: str = "AC Registration",
    arrival_time_column: str = "ACTUAL ARRIVAL TIME",
    arrival_delay_column: str = "Arrival_Delay_Min",
    departure_delay_column: str = "Departure_Delay_Min",
    id_column: str = "ECTRL ID",
    cutoff_column: str = "prediction_cutoff_t60",
    unknown_value: str = "Unknown",
) -> DataFrame:
    """Attach the most recent completed flight of the assigned aircraft."""

    usable_events = events.where(
        F.col(registration_column).isNotNull()
        & (F.col(registration_column) != unknown_value)
        & F.col(arrival_time_column).isNotNull()
    )
    usable_targets = targets.where(
        F.col(registration_column).isNotNull()
        & (F.col(registration_column) != unknown_value)
    )
    event_rows = usable_events.select(
        F.col(registration_column),
        F.col(arrival_time_column).alias("_timeline_time"),
        F.lit(0).alias("_row_kind"),
        F.col(id_column).cast("long").alias("_event_id"),
        F.lit(None).cast("long").alias("_target_id"),
        F.col(arrival_delay_column).cast("double").alias("_arrival_delay"),
        F.col(departure_delay_column).cast("double").alias("_departure_delay"),
    )
    target_rows = usable_targets.select(
        F.col(registration_column),
        F.col(cutoff_column).alias("_timeline_time"),
        F.lit(1).alias("_row_kind"),
        F.lit(None).cast("long").alias("_event_id"),
        F.col(id_column).cast("long").alias("_target_id"),
        F.lit(None).cast("double").alias("_arrival_delay"),
        F.lit(None).cast("double").alias("_departure_delay"),
    )
    combined = event_rows.unionByName(target_rows)
    timeline = (
        Window.partitionBy(registration_column)
        .orderBy(F.col("_timeline_time"), F.col("_row_kind"))
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    enriched = (
        combined.withColumn(
            "_previous_event_time",
            F.last(
                F.when(F.col("_event_id").isNotNull(), F.col("_timeline_time")),
                ignorenulls=True,
            ).over(timeline),
        )
        .withColumn("_previous_event_id", F.last("_event_id", ignorenulls=True).over(timeline))
        .withColumn(
            "_previous_arrival_delay", F.last("_arrival_delay", ignorenulls=True).over(timeline)
        )
        .withColumn(
            "_previous_departure_delay",
            F.last("_departure_delay", ignorenulls=True).over(timeline),
        )
        .where(F.col("_row_kind") == 1)
        .withColumn(
            "_rotation_self_match", (F.col("_previous_event_id") == F.col("_target_id")).cast("long")
        )
        .withColumn(
            "rotation_previous_arrival_delay",
            F.when(F.col("_rotation_self_match") == 0, F.col("_previous_arrival_delay")),
        )
        .withColumn(
            "rotation_previous_departure_delay",
            F.when(F.col("_rotation_self_match") == 0, F.col("_previous_departure_delay")),
        )
        .withColumn(
            "rotation_minutes_since_previous_arrival",
            F.when(
                F.col("_rotation_self_match") == 0,
                (F.col("_timeline_time").cast("long") - F.col("_previous_event_time").cast("long"))
                / F.lit(60.0),
            ),
        )
        .withColumn(
            "rotation_history_available",
            (F.col("rotation_minutes_since_previous_arrival").isNotNull()).cast("long"),
        )
    )
    return enriched.select(
        F.col("_target_id").alias(id_column),
        F.col("_timeline_time").alias(cutoff_column),
        "rotation_previous_arrival_delay",
        "rotation_previous_departure_delay",
        "rotation_minutes_since_previous_arrival",
        "rotation_history_available",
        F.col("_previous_event_time").alias("_rotation_previous_event_time"),
        "_rotation_self_match",
    )
