"""Reusable, leakage-aware PySpark transformations for flight-delay modelling."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Mapping, Optional, Sequence

from pyspark import keyword_only
from pyspark.ml import Pipeline
from pyspark.ml.feature import FeatureHasher, OneHotEncoder, StringIndexer
from pyspark.ml.param.shared import Param, Params, TypeConverters
from pyspark.ml.util import DefaultParamsReadable, DefaultParamsWritable
from pyspark.ml import Transformer
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from src.flight_config import (
    DATETIME_FORMAT_SPARK,
    DataQualityConfig,
    FeatureConfig,
    SEED,
    TIME_COLUMNS,
    features_for_task,
)


FLIGHTS_SCHEMA = StructType(
    [
        StructField("ECTRL ID", LongType(), False),
        StructField("ADEP", StringType(), False),
        StructField("ADEP Latitude", DoubleType(), True),
        StructField("ADEP Longitude", DoubleType(), True),
        StructField("ADES", StringType(), False),
        StructField("ADES Latitude", DoubleType(), True),
        StructField("ADES Longitude", DoubleType(), True),
        StructField("FILED OFF BLOCK TIME", StringType(), False),
        StructField("FILED ARRIVAL TIME", StringType(), False),
        StructField("ACTUAL OFF BLOCK TIME", StringType(), True),
        StructField("ACTUAL ARRIVAL TIME", StringType(), True),
        StructField("AC Type", StringType(), False),
        StructField("AC Operator", StringType(), True),
        StructField("AC Registration", StringType(), True),
        StructField("ICAO Flight Type", StringType(), True),
        StructField("STATFOR Market Segment", StringType(), True),
        StructField("Requested FL", DoubleType(), True),
        StructField("Actual Distance Flown (nm)", DoubleType(), True),
    ]
)


def _windows_localfs_jar() -> Path:
    """Build the small Windows local-filesystem adapter when it is stale."""

    project_root = Path(__file__).resolve().parents[1]
    source = project_root / "src" / "java" / "localfs" / "WindowsRawLocalFileSystem.java"
    build_root = project_root / ".spark"
    classes = build_root / "windows-localfs-classes"
    jar_path = build_root / "windows-localfs.jar"
    if jar_path.exists() and jar_path.stat().st_mtime >= source.stat().st_mtime:
        return jar_path

    pyspark_root = Path(__file__).resolve().parents[1] / ".venv313" / "Lib" / "site-packages" / "pyspark"
    if not pyspark_root.exists():
        import pyspark

        pyspark_root = Path(pyspark.__file__).resolve().parent
    hadoop_jars = sorted((pyspark_root / "jars").glob("hadoop-client-*.jar"))
    if not hadoop_jars:
        raise RuntimeError("PySpark Hadoop client jars were not found")

    classes.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "javac",
            "-cp",
            os.pathsep.join(str(path) for path in hadoop_jars),
            "-d",
            str(classes),
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        ["jar", "--create", "--file", str(jar_path), "-C", str(classes), "."],
        check=True,
    )
    return jar_path


def create_spark(
    app_name: str = "flight-delay-pipeline",
    master: Optional[str] = None,
    driver_memory: Optional[str] = None,
    shuffle_partitions: Optional[int] = None,
) -> SparkSession:
    """Create or reuse a Spark session with deterministic SQL settings."""

    # On Windows Spark may otherwise resolve the Microsoft Store `python3`
    # alias instead of the interpreter running the driver.
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

    builder = SparkSession.builder.appName(app_name).config(
        "spark.sql.session.timeZone", "UTC"
    )
    if os.name == "nt":
        localfs_jar = _windows_localfs_jar()
        builder = (
            builder.config("spark.driver.extraClassPath", str(localfs_jar))
            .config("spark.executor.extraClassPath", str(localfs_jar))
            .config(
                "spark.hadoop.fs.file.impl", "localfs.WindowsRawLocalFileSystem"
            )
        )
    if driver_memory:
        builder = builder.config("spark.driver.memory", driver_memory)
    if shuffle_partitions:
        builder = builder.config(
            "spark.sql.shuffle.partitions", str(shuffle_partitions)
        )
    if master:
        builder = builder.master(master)
    return builder.getOrCreate()


def read_flights_spark(spark: SparkSession, paths: str | Sequence[str]) -> DataFrame:
    """Read one or more gzip CSV files with a stable schema."""

    return (
        spark.read.option("header", True)
        .option("mode", "FAILFAST")
        .schema(FLIGHTS_SCHEMA)
        .csv(paths)
    )


def calculate_delays(df: DataFrame) -> DataFrame:
    """Parse timestamps and calculate target and departure delay in minutes."""

    for column in TIME_COLUMNS:
        if column in df.columns:
            df = df.withColumn(
                column, F.to_timestamp(F.col(column), DATETIME_FORMAT_SPARK)
            )

    required_arrival = {"ACTUAL ARRIVAL TIME", "FILED ARRIVAL TIME"}
    if required_arrival.issubset(df.columns):
        df = df.withColumn(
            "Arrival_Delay_Min",
            (
                F.col("ACTUAL ARRIVAL TIME").cast("long")
                - F.col("FILED ARRIVAL TIME").cast("long")
            )
            / F.lit(60.0),
        )

    required_departure = {"ACTUAL OFF BLOCK TIME", "FILED OFF BLOCK TIME"}
    if required_departure.issubset(df.columns):
        df = df.withColumn(
            "Departure_Delay_Min",
            (
                F.col("ACTUAL OFF BLOCK TIME").cast("long")
                - F.col("FILED OFF BLOCK TIME").cast("long")
            )
            / F.lit(60.0),
        )
    return df


def apply_aviation_rules(
    df: DataFrame, config: DataQualityConfig = DataQualityConfig()
) -> DataFrame:
    """Remove physically invalid values while retaining nulls for later handling."""

    for delay_col in ("Departure_Delay_Min", "Arrival_Delay_Min"):
        if delay_col in df.columns:
            df = df.filter(
                F.col(delay_col).isNull()
                | (F.col(delay_col) >= F.lit(config.min_delay_minutes))
            )

    if config.regular_commercial_only and "ICAO Flight Type" in df.columns:
        df = df.filter(F.col("ICAO Flight Type") == config.regular_flight_type)

    min_fl = (
        config.scope_min_flight_level
        if config.scope_min_flight_level is not None
        else config.min_flight_level
    )
    if "Requested FL" in df.columns:
        df = df.filter(
            F.col("Requested FL").isNull()
            | F.col("Requested FL").between(min_fl, config.max_flight_level)
        )

    if "Actual Distance Flown (nm)" in df.columns:
        df = df.filter(
            F.col("Actual Distance Flown (nm)").isNull()
            | (F.col("Actual Distance Flown (nm)") > config.min_distance_nm)
        )

    for column in ("ADEP Latitude", "ADES Latitude"):
        if column in df.columns:
            df = df.filter(F.col(column).isNull() | F.col(column).between(-90, 90))
    for column in ("ADEP Longitude", "ADES Longitude"):
        if column in df.columns:
            df = df.filter(F.col(column).isNull() | F.col(column).between(-180, 180))
    return df


def fill_text_nulls(
    df: DataFrame, columns: Iterable[str], value: str = "Unknown"
) -> DataFrame:
    present = [column for column in columns if column in df.columns]
    return df.fillna({column: value for column in present}) if present else df


def fit_frequent_categories(
    train: DataFrame, column: str, min_count: int = 1_000
) -> list[str]:
    """Learn the non-rare vocabulary from train only."""

    return [
        row[column]
        for row in (
            train.where(F.col(column).isNotNull())
            .groupBy(column)
            .count()
            .where(F.col("count") >= min_count)
            .select(column)
            .collect()
        )
    ]


def group_rare_categories(
    df: DataFrame,
    column: str,
    frequent_values: Sequence[str],
    output_column: Optional[str] = None,
    other_value: str = "OTHER",
) -> DataFrame:
    """Map rare, null and unseen values to one stable category."""

    output = output_column or f"{column}_grouped"
    return df.withColumn(
        output,
        F.when(F.col(column).isin(list(frequent_values)), F.col(column)).otherwise(
            F.lit(other_value)
        ),
    )


def impute_airport_coordinates(
    flights: DataFrame,
    airports: DataFrame,
    flight_code_col: str,
    latitude_col: str,
    longitude_col: str,
    airport_code_col: str = "ICAO",
    airport_latitude_col: str = "Latitude",
    airport_longitude_col: str = "Longitude",
) -> DataFrame:
    """Fill coordinates from a deduplicated reference dimension, never constants."""

    reference = (
        airports.select(
            F.col(airport_code_col).alias("__airport_code"),
            F.col(airport_latitude_col).cast("double").alias("__airport_lat"),
            F.col(airport_longitude_col).cast("double").alias("__airport_lon"),
        )
        .where(F.col("__airport_code").isNotNull())
        .dropDuplicates(["__airport_code"])
    )
    result = flights.join(
        F.broadcast(reference),
        F.col(flight_code_col) == F.col("__airport_code"),
        "left",
    )
    return (
        result.withColumn(latitude_col, F.coalesce(F.col(latitude_col), F.col("__airport_lat")))
        .withColumn(longitude_col, F.coalesce(F.col(longitude_col), F.col("__airport_lon")))
        .drop("__airport_code", "__airport_lat", "__airport_lon")
    )


def validate_dimension(
    fact: DataFrame,
    dimension: DataFrame,
    fact_key: str,
    dimension_key: str,
) -> dict[str, float]:
    """Return key uniqueness, key coverage and flight-weighted coverage metrics."""

    dim_non_null = dimension.where(F.col(dimension_key).isNotNull())
    dim_rows = dim_non_null.count()
    dim_unique = dim_non_null.select(dimension_key).distinct().count()
    duplicate_rows = dim_rows - dim_unique

    fact_keys = fact.where(F.col(fact_key).isNotNull())
    fact_unique = fact_keys.select(fact_key).distinct().count()
    matched_unique = (
        fact_keys.select(F.col(fact_key).alias("__key"))
        .distinct()
        .join(
            dim_non_null.select(F.col(dimension_key).alias("__key")).distinct(),
            "__key",
            "left_semi",
        )
        .count()
    )
    fact_rows = fact_keys.count()
    matched_rows = (
        fact_keys.join(
            dim_non_null.select(F.col(dimension_key).alias(fact_key)).distinct(),
            fact_key,
            "left_semi",
        ).count()
    )
    return {
        "dimension_rows": float(dim_rows),
        "dimension_unique_keys": float(dim_unique),
        "duplicate_key_rows": float(duplicate_rows),
        "unique_key_coverage": matched_unique / fact_unique if fact_unique else 0.0,
        "flight_weighted_coverage": matched_rows / fact_rows if fact_rows else 0.0,
    }


def left_join_dimension(
    fact: DataFrame,
    dimension: DataFrame,
    fact_key: str,
    dimension_key: str,
    suffix: str,
    broadcast_dimension: bool = True,
    validate_row_count: bool = True,
) -> DataFrame:
    """Validated many-to-one left join that fails on duplicate dimension keys."""

    non_null = dimension.where(F.col(dimension_key).isNotNull())
    if non_null.count() != non_null.select(dimension_key).distinct().count():
        raise ValueError(f"Dimension key {dimension_key!r} is not unique")

    renamed = non_null.select(
        F.col(dimension_key).alias("__dimension_key"),
        *[
            F.col(column).alias(f"{column}_{suffix}")
            for column in dimension.columns
            if column != dimension_key
        ],
    )
    right = F.broadcast(renamed) if broadcast_dimension else renamed
    before = fact.count() if validate_row_count else None
    joined = fact.join(right, F.col(fact_key) == F.col("__dimension_key"), "left").drop(
        "__dimension_key"
    )
    if validate_row_count:
        after = joined.count()
        if before != after:
            raise AssertionError(f"Join changed row count from {before} to {after}")
    return joined


def temporal_split(
    df: DataFrame,
    cutoff: str,
    time_column: str = "FILED OFF BLOCK TIME",
) -> tuple[DataFrame, DataFrame]:
    """Train on observations before cutoff and test on cutoff or later."""

    boundary = F.to_timestamp(F.lit(cutoff))
    train = df.filter(F.col(time_column) < boundary)
    test = df.filter(F.col(time_column) >= boundary)
    return train, test


def temporal_train_validation_test_split(
    df: DataFrame,
    validation_start: str,
    test_start: str,
    time_column: str = "FILED OFF BLOCK TIME",
) -> tuple[DataFrame, DataFrame, DataFrame]:
    """Create disjoint train, validation and final test periods."""

    validation_boundary = F.to_timestamp(F.lit(validation_start))
    test_boundary = F.to_timestamp(F.lit(test_start))
    train = df.filter(F.col(time_column) < validation_boundary)
    validation = df.filter(
        (F.col(time_column) >= validation_boundary)
        & (F.col(time_column) < test_boundary)
    )
    test = df.filter(F.col(time_column) >= test_boundary)
    return train, validation, test


def temporal_train_validation_two_test_split(
    df: DataFrame,
    validation_start: str,
    test_start: str,
    future_test_start: str,
    time_column: str = "FILED OFF BLOCK TIME",
) -> tuple[DataFrame, DataFrame, DataFrame, DataFrame]:
    """Create train, validation, test and later temporal test partitions."""

    validation_boundary = F.to_timestamp(F.lit(validation_start))
    test_boundary = F.to_timestamp(F.lit(test_start))
    future_boundary = F.to_timestamp(F.lit(future_test_start))
    train = df.filter(F.col(time_column) < validation_boundary)
    validation = df.filter(
        (F.col(time_column) >= validation_boundary)
        & (F.col(time_column) < test_boundary)
    )
    test = df.filter(
        (F.col(time_column) >= test_boundary)
        & (F.col(time_column) < future_boundary)
    )
    future_test = df.filter(F.col(time_column) >= future_boundary)
    return train, validation, test, future_test


def fit_yeo_johnson_lambdas(
    train: DataFrame,
    columns: Sequence[str] = ("Requested FL", "Scheduled_Duration_Min"),
    sample_limit: int = 200_000,
    seed: int = SEED,
) -> Mapping[str, float]:
    """Estimate lambdas on a bounded train-only sample using sklearn."""

    import numpy as np
    from sklearn.preprocessing import PowerTransformer

    lambdas: dict[str, float] = {}
    for column in columns:
        if column not in train.columns:
            continue
        values = (
            train.select(column)
            .where(F.col(column).isNotNull())
            .orderBy(F.rand(seed))
            .limit(sample_limit)
            .toPandas()[column]
            .to_numpy(dtype=float)
        )
        if values.size:
            transformer = PowerTransformer(method="yeo-johnson", standardize=False)
            transformer.fit(np.asarray(values).reshape(-1, 1))
            lambdas[column] = float(transformer.lambdas_[0])
    return lambdas


def _yeo_johnson_expression(column, value: float):
    """Return a Spark expression for a fitted Yeo-Johnson transformation."""

    positive = (
        F.log1p(column)
        if value == 0.0
        else (F.pow(column + 1.0, value) - 1.0) / value
    )
    negative = (
        -F.log1p(-column)
        if value == 2.0
        else -(F.pow(-column + 1.0, 2.0 - value) - 1.0) / (2.0 - value)
    )
    return F.when(column.isNull(), F.lit(None).cast("double")).when(
        column >= 0, positive
    ).otherwise(negative)


def apply_yeo_johnson_lambdas(
    frame: DataFrame,
    lambdas: Mapping[str, float],
    output_columns: Optional[Mapping[str, str]] = None,
) -> DataFrame:
    """Apply train-fitted lambdas to predictors without modifying the target."""

    outputs = output_columns or {
        column: f"{column.replace(' ', '_')}_YJ" for column in lambdas
    }
    for source, value in lambdas.items():
        if source in frame.columns:
            frame = frame.withColumn(
                outputs[source], _yeo_johnson_expression(F.col(source), value)
            )
    return frame


class FlightValueTransformer(
    Transformer, DefaultParamsReadable, DefaultParamsWritable
):
    """Optional log and Yeo-Johnson transforms with persistible Spark Params."""

    applyLog = Param(
        Params._dummy(), "applyLog", "Apply log1p to non-negative scale features", TypeConverters.toBoolean
    )
    applyYeoJohnson = Param(
        Params._dummy(), "applyYeoJohnson", "Apply Yeo-Johnson to numeric predictors", TypeConverters.toBoolean
    )
    lambdaRequestedFlightLevel = Param(
        Params._dummy(), "lambdaRequestedFlightLevel", "Train-fitted requested-flight-level lambda", TypeConverters.toFloat
    )
    lambdaScheduledDuration = Param(
        Params._dummy(), "lambdaScheduledDuration", "Train-fitted scheduled-duration lambda", TypeConverters.toFloat
    )

    @keyword_only
    def __init__(
        self,
        applyLog: bool = False,
        applyYeoJohnson: bool = False,
        lambdaRequestedFlightLevel: float = 1.0,
        lambdaScheduledDuration: float = 1.0,
    ):
        super().__init__()
        self._setDefault(
            applyLog=False,
            applyYeoJohnson=False,
            lambdaRequestedFlightLevel=1.0,
            lambdaScheduledDuration=1.0,
        )
        kwargs = self._input_kwargs
        self.setParams(**kwargs)

    @keyword_only
    def setParams(
        self,
        applyLog: bool = False,
        applyYeoJohnson: bool = False,
        lambdaRequestedFlightLevel: float = 1.0,
        lambdaScheduledDuration: float = 1.0,
    ):
        return self._set(**self._input_kwargs)

    def _transform(self, dataset: DataFrame) -> DataFrame:
        if self.getOrDefault(self.applyLog):
            if "Requested FL" in dataset.columns:
                dataset = dataset.withColumn(
                    "Requested_FL_Log1p", F.log1p(F.col("Requested FL"))
                )
            if "Scheduled_Duration_Min" in dataset.columns:
                dataset = dataset.withColumn(
                    "Scheduled_Duration_Min_Log1p",
                    F.log1p(F.col("Scheduled_Duration_Min")),
                )

        if self.getOrDefault(self.applyYeoJohnson):
            mapping = {
                "Requested FL": (
                    "Requested_FL_YJ",
                    self.getOrDefault(self.lambdaRequestedFlightLevel),
                ),
                "Scheduled_Duration_Min": (
                    "Scheduled_Duration_Min_YJ",
                    self.getOrDefault(self.lambdaScheduledDuration),
                ),
            }
            for source, (target, value) in mapping.items():
                if source in dataset.columns:
                    dataset = dataset.withColumn(
                        target, _yeo_johnson_expression(F.col(source), value)
                    )
        return dataset


def build_value_transformer(
    train: DataFrame,
    config: FeatureConfig = FeatureConfig(),
) -> FlightValueTransformer:
    """Build optional transforms; lambdas are learned only when requested."""

    lambdas: Mapping[str, float] = {}
    if config.apply_yeo_johnson:
        columns = [
            column
            for column in ("Requested FL", "Scheduled_Duration_Min")
            if column in train.columns
        ]
        lambdas = fit_yeo_johnson_lambdas(train, columns=columns)
    return FlightValueTransformer(
        applyLog=config.apply_log,
        applyYeoJohnson=config.apply_yeo_johnson,
        lambdaRequestedFlightLevel=lambdas.get("Requested FL", 1.0),
        lambdaScheduledDuration=lambdas.get("Scheduled_Duration_Min", 1.0),
    )


def fit_categorical_pipeline(train: DataFrame, config: FeatureConfig):
    """Fit low-cardinality encoders on train; hash high-cardinality columns."""

    low_cardinality = [
        column
        for column in (
            "STATFOR Market Segment",
            "Class_aircraft",
            "Number+Engine Type_aircraft",
        )
        if column in train.columns
    ]
    indexers = [
        StringIndexer(
            inputCol=column,
            outputCol=f"{column}_idx",
            handleInvalid="keep",
        )
        for column in low_cardinality
    ]
    encoder = OneHotEncoder(
        inputCols=[f"{column}_idx" for column in low_cardinality],
        outputCols=[f"{column}_ohe" for column in low_cardinality],
        handleInvalid="keep",
    )
    high_cardinality = [
        column
        for column in ("ADEP", "ADES", "AC Operator", "AC Type_grouped")
        if column in train.columns
    ]
    hasher = FeatureHasher(
        inputCols=high_cardinality,
        outputCol="high_cardinality_hash",
        numFeatures=config.categorical_hash_features,
    )
    return Pipeline(stages=[*indexers, encoder, hasher]).fit(train)


def select_available_features(df: DataFrame, config: FeatureConfig) -> DataFrame:
    """Select only variables available at the configured prediction horizon."""

    allowed = set(features_for_task(config.target, config.prediction_horizon))
    # Keep only derivatives of variables available at the chosen horizon.
    allowed.add("Requested_FL_Imputed")
    allowed.add("Scheduled_Duration_Min")
    if config.apply_log:
        allowed.add("Requested_FL_Log1p")
        allowed.add("Scheduled_Duration_Min_Log1p")
    if config.apply_yeo_johnson:
        allowed.add("Requested_FL_YJ")
        allowed.add("Scheduled_Duration_Min_YJ")
    always_keep = {"ECTRL ID", config.target}
    selected = [column for column in df.columns if column in allowed | always_keep]
    return df.select(*selected)
