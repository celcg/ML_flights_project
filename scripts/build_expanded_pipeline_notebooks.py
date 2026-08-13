"""Generate the expanded-data PySpark and modelling notebooks."""

from __future__ import annotations

from pathlib import Path
import sys
from functools import reduce

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".venv313" / "Lib" / "site-packages"
if SITE.exists():
    sys.path.insert(0, str(SITE))

import nbformat as nbf


def md(value):
    return nbf.v4.new_markdown_cell(value.strip())


def code(value):
    return nbf.v4.new_code_cell(value.strip())


META = {
    "kernelspec": {
        "display_name": "Python 3.13 (ML Flights)",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "version": "3.13"},
}


def ingestion_notebook():
    notebook = nbf.v4.new_notebook(metadata=META)
    notebook.cells = [
        md("""
# 10 - Expanded-data ingestion, cleaning and T-60 features (PySpark)

This notebook extends the previous pipeline without replacing it. It ingests
one canonical file per month, applies the same quality rules, audits null
behaviour and writes reusable Parquet.

Active task: arrival delay exactly 60 minutes before scheduled off-block.
Train runs through September 2022, validation is December 2022, test is March
2023 and the future test is June 2023. The two tests are never used to learn
imputers, category vocabularies, transformations or model settings.
"""),
        code("""
from pathlib import Path
import sys
import pandas as pd
from functools import reduce
from pyspark import StorageLevel
from pyspark.ml.feature import Imputer
from pyspark.sql import functions as F

PROJECT_ROOT = Path.cwd().resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.flight_config import DataQualityConfig, FeatureConfig
from src.flight_data_catalog import (
    compare_null_cohorts, discover_monthly_flights,
    profile_nulls_by_month, validate_flight_schemas,
)
from src.spark_flight_pipeline import (
    apply_aviation_rules, build_value_transformer, calculate_delays,
    create_spark, fill_text_nulls, fit_frequent_categories,
    group_rare_categories, read_flights_spark,
    left_join_dimension,
    temporal_train_validation_two_test_split,
)
from src.t60_operational_features import add_prediction_cutoff, build_standard_t60_features

QUALITY = DataQualityConfig(min_delay_minutes=-120, regular_commercial_only=True)
FEATURES = FeatureConfig(
    target="Arrival_Delay_Min", prediction_horizon="pre_departure",
    apply_log=False, apply_yeo_johnson=False,
    categorical_hash_features=1 << 15, rare_category_min_count=1_000,
)
VALIDATION_START = "2022-12-01 00:00:00"
TEST_START = "2023-03-01 00:00:00"
FUTURE_TEST_START = "2023-06-01 00:00:00"
RUN_FULL_DATA = False
SMOKE_ROWS_PER_FILE = 2_000
SMOKE_SPLIT_ROWS = 100
WRITE_PARQUET = False
BUILD_OPERATIONAL_T60 = False
WINDOWS_HOURS = (1, 6, 24)
OUTPUT_ROOT = PROJECT_ROOT / "data" / "processed" / "expanded_arrival_pre_t60"
REPORT_ROOT = PROJECT_ROOT / "reports" / "expanded_data"
REPORT_ROOT.mkdir(parents=True, exist_ok=True)
"""),
        md("""
## 1. Canonical catalog, schema and null audit

Month folders take priority over legacy copies, preventing duplicate ingestion.
All 18 raw columns must match. Null rates in the three new files are compared
with the six original files. A two-percentage-point change is flagged for
review, but does not automatically remove a variable.
"""),
        code("""
catalog = discover_monthly_flights(PROJECT_ROOT / "data" / "raw")
flight_files = [item.path for item in catalog]
catalog_pd = pd.DataFrame([
    {"month": item.month, "path": str(item.path), "source": item.source}
    for item in catalog
])
schema_audit = validate_flight_schemas(flight_files)
assert schema_audit["matches_reference_schema"].all(), schema_audit
null_profile = profile_nulls_by_month(
    flight_files,
    max_rows_per_file=None if RUN_FULL_DATA else SMOKE_ROWS_PER_FILE,
)
reference_months = ["202112", "202203", "202206", "202209", "202212", "202303"]
new_months = ["202106", "202109", "202306"]
null_comparison = compare_null_cohorts(
    null_profile, reference_months, new_months, material_delta_pp=2.0
)
catalog_pd.to_csv(REPORT_ROOT / "flight_file_catalog.csv", index=False)
schema_audit.to_csv(REPORT_ROOT / "schema_compatibility.csv", index=False)
null_profile.to_csv(REPORT_ROOT / "null_profile_by_month.csv", index=False)
null_comparison.to_csv(REPORT_ROOT / "null_profile_new_vs_reference.csv", index=False)
display(catalog_pd)
display(null_comparison)
"""),
        md("""
## 2. PySpark ingestion and unchanged aviation rules

The explicit schema prevents month-dependent type inference. Rules remain:
scheduled flights only, delays no lower than -120 minutes, valid flight level,
positive distance and valid coordinates. Null predictors are retained for
train-only imputation.
"""),
        code("""
spark = create_spark(
    "expanded-arrival-pre-cleaning", master="local[1]",
    driver_memory="2g", shuffle_partitions=8,
)
spark.sparkContext.setLogLevel("ERROR")
if RUN_FULL_DATA:
    raw = read_flights_spark(spark, [str(path) for path in flight_files])
else:
    monthly_smoke = [
        read_flights_spark(spark, str(path)).limit(SMOKE_ROWS_PER_FILE)
        for path in flight_files
    ]
    raw = reduce(lambda left, right: left.unionByName(right), monthly_smoke)
flights = calculate_delays(raw).withColumn(
    "Scheduled_Duration_Min",
    (F.col("FILED ARRIVAL TIME").cast("long")
     - F.col("FILED OFF BLOCK TIME").cast("long")) / F.lit(60.0),
)
before_rows = flights.count()
flights = apply_aviation_rules(flights, QUALITY)
flights = fill_text_nulls(
    flights, ["AC Operator", "AC Registration", "AC Type", "STATFOR Market Segment"]
).persist(StorageLevel.DISK_ONLY)
after_rows = flights.count()
print({"raw_rows": before_rows, "clean_rows": after_rows, "removed": before_rows-after_rows})
"""),
        md("""
## 3. Aircraft dimension enrichment

The previous flow enriched AC Type with aircraft class and engine family. The
join remains many-to-one and must preserve row count. These low-cardinality
fields are later one-hot encoded; AC Type itself stays grouped and hashed.
"""),
        code("""
actype = spark.read.option("header", True).option("inferSchema", True).csv(
    str(PROJECT_ROOT / "data" / "raw" / "icao" / "actype.csv")
)
pre_join_rows = flights.count()
clean_base = flights
flights = left_join_dimension(
    flights, actype, "AC Type", "Aircraft TypeDesignator", "aircraft",
    validate_row_count=False,
)
flights = fill_text_nulls(
    flights, ["Class_aircraft", "Number+Engine Type_aircraft"]
).persist(StorageLevel.DISK_ONLY)
assert flights.count() == pre_join_rows
clean_base.unpersist()
"""),
        md("""
## 4. Four-way temporal split before fitted operations

December remains the selection period used previously. March is the first
untouched test; June is a later robustness test. Rows missing the arrival target
are counted separately and removed only after the split.
"""),
        code("""
train, validation, test, future_test = temporal_train_validation_two_test_split(
    flights, VALIDATION_START, TEST_START, FUTURE_TEST_START
)
splits = {"train": train, "validation": validation, "test": test, "future_test": future_test}
missing_target = {}
for name, frame in list(splits.items()):
    missing_target[name] = frame.filter(F.col(FEATURES.target).isNull()).count()
    splits[name] = frame.filter(F.col(FEATURES.target).isNotNull())
split_counts = {name: frame.count() for name, frame in splits.items()}
assert all(value > 0 for value in split_counts.values()), split_counts
print({"split_counts": split_counts, "missing_target_removed": missing_target})

if not RUN_FULL_DATA:
    # Keep every temporal period represented while bounding all later actions.
    splits = {name: frame.limit(SMOKE_SPLIT_ROWS) for name, frame in splits.items()}
    split_counts = {name: frame.count() for name, frame in splits.items()}
    print({"bounded_smoke_split_counts": split_counts})
"""),
        md("""
## 5. Train-only imputation, optional transforms and rare aircraft

Flight-level median, optional Yeo-Johnson lambdas and frequent aircraft types
are learned only on train. AC Type is not one-hot encoded: rare and unseen
values become OTHER. Log and Yeo-Johnson remain optional and disabled by
default.
"""),
        code("""
value_transformer = build_value_transformer(splits["train"], FEATURES)
for name in splits:
    splits[name] = value_transformer.transform(splits[name])
imputer = Imputer(
    strategy="median", inputCols=["Requested FL"],
    outputCols=["Requested_FL_Imputed"],
).fit(splits["train"])
for name in splits:
    splits[name] = imputer.transform(splits[name])
frequent_ac_types = fit_frequent_categories(
    splits["train"], "AC Type", FEATURES.rare_category_min_count
)
for name in splits:
    splits[name] = group_rare_categories(
        splits[name], "AC Type", frequent_ac_types,
        output_column="AC Type_grouped",
    )
print({"frequent_ac_types": len(frequent_ac_types),
       "log": FEATURES.apply_log, "yeo_johnson": FEATURES.apply_yeo_johnson})
"""),
        md("""
## 6. T-60 feature gate and optional previous-flight variables

Base output contains only schedule and categorical predictors available at
T-60. If BUILD_OPERATIONAL_T60 is enabled, the same 1/6/24-hour airport, route,
operator and aircraft-rotation features are created. The reusable builder fails
if any event occurs after a target cutoff.
"""),
        code("""
base_keep = [
    "ECTRL ID", FEATURES.target, "ADEP", "ADES", "AC Operator",
    "AC Registration", "AC Type_grouped", "STATFOR Market Segment",
    "Class_aircraft", "Number+Engine Type_aircraft",
    "FILED OFF BLOCK TIME", "FILED ARRIVAL TIME",
    "Requested_FL_Imputed", "Scheduled_Duration_Min",
]
model_splits = {}
for name, frame in splits.items():
    selected = frame.select(*[column for column in base_keep if column in frame.columns])
    model_splits[name] = add_prediction_cutoff(selected)
forbidden = {"ACTUAL OFF BLOCK TIME", "ACTUAL ARRIVAL TIME",
             "Departure_Delay_Min", "Actual Distance Flown (nm)"}
assert all(not (forbidden & set(frame.columns)) for frame in model_splits.values())

feature_audit = []
if BUILD_OPERATIONAL_T60:
    events = flights.select(
        "ECTRL ID", "ADEP", "ADES", "AC Operator", "AC Registration",
        "ACTUAL OFF BLOCK TIME", "ACTUAL ARRIVAL TIME",
        "Departure_Delay_Min", "Arrival_Delay_Min",
    )
    for name in model_splits:
        model_splits[name], audit = build_standard_t60_features(
            model_splits[name], events, windows_hours=WINDOWS_HOURS
        )
        feature_audit.extend([{"split": name, **row} for row in audit])
feature_audit_pd = pd.DataFrame(feature_audit)
feature_audit_pd.to_csv(REPORT_ROOT / "t60_feature_leakage_audit.csv", index=False)
print({"operational_features": BUILD_OPERATIONAL_T60,
       "leakage_violations": int(feature_audit_pd.get(
           "leakage_violations", pd.Series(dtype=int)).sum())})
"""),
        md("""
## 7. Post-clean null contract and optional Parquet output

Target nulls are removed and reported. Text uses explicit Unknown, flight level
uses the train median, and missing operational history is allowed when no prior
event exists. Set both RUN_FULL_DATA and WRITE_PARQUET to true for the complete
build. PySpark runs locally; no HDFS or external Hadoop cluster is used.
"""),
        code("""
null_rows = []
for split_name, frame in model_splits.items():
    values = frame.agg(*[
        F.sum(F.col(column).isNull().cast("long")).alias(column)
        for column in frame.columns
    ]).first().asDict()
    total = split_counts[split_name]
    null_rows.extend([
        {"split": split_name, "column": column, "nulls": value,
         "rows": total, "null_pct": 100*value/total if total else None}
        for column, value in values.items()
    ])
post_clean_nulls = pd.DataFrame(null_rows)
post_clean_nulls.to_csv(REPORT_ROOT / "post_clean_null_profile.csv", index=False)
display(post_clean_nulls.sort_values(
    ["split", "null_pct"], ascending=[True, False]
).head(30))

if WRITE_PARQUET:
    for name, frame in model_splits.items():
        frame.write.mode("overwrite").parquet(str(OUTPUT_ROOT / name))
    pd.DataFrame([{
        "validation_start": VALIDATION_START, "test_start": TEST_START,
        "future_test_start": FUTURE_TEST_START,
        "operational_t60_built": BUILD_OPERATIONAL_T60,
        **{f"{name}_rows": count for name, count in split_counts.items()},
    }]).to_csv(REPORT_ROOT / "split_contract.csv", index=False)
else:
    print("Smoke complete. Enable full data and writes for notebook 11.")
flights.unpersist()
spark.stop()
"""),
        md("""
## Decisions preserved

- Same scheduled-commercial population and physical limits.
- Same arrival-delay target and T-60 horizon.
- Same train-only fitting, rare aircraft OTHER and categorical hashing policy.
- Two earlier 2021 months expand train; March and June 2023 are two independent
  future evaluations.
- Raw and cleaned null behaviour is measured rather than assumed.
"""),
    ]
    path = ROOT / "notebooks" / "10_expanded_data_ingestion_cleaning_pyspark.ipynb"
    nbf.write(notebook, path)
    return path


def modelling_notebook():
    notebook = nbf.v4.new_notebook(metadata=META)
    notebook.cells = [
        md("""
# 11 - Expanded-data arrival-delay models and prediction

This notebook continues the earlier model flow using notebook 10 Parquet.
It compares the historical baseline, Ridge, Random Forest, Gradient-Boosted
Trees, XGBoost and CatBoost under one temporal contract.

Model selection uses December 2022 only. March and June 2023 remain locked
until a winner is frozen. Every model is measured with MAE, RMSE, median
absolute error and p90 absolute error, including punctual and delayed segments.
"""),
        code("""
from pathlib import Path
import json
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.feature_extraction import FeatureHasher
from sklearn.linear_model import Ridge

PROJECT_ROOT = Path.cwd().resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.t60_modeling import (
    HistoricalMedianBaseline, MixedCategoricalRidgePreprocessor,
    add_schedule_features, compact_score, segment_metrics,
)

DATA_ROOT = PROJECT_ROOT / "data" / "processed" / "expanded_arrival_pre_t60"
REPORT_ROOT = PROJECT_ROOT / "reports" / "expanded_models"
MODEL_ROOT = PROJECT_ROOT / "models" / "expanded"
REPORT_ROOT.mkdir(parents=True, exist_ok=True)
MODEL_ROOT.mkdir(parents=True, exist_ok=True)
TARGET = "Arrival_Delay_Min"
RUN_MODELS = False
TRAIN_SAMPLE_PERCENT = 10
VALIDATION_SAMPLE_PERCENT = 5
TREE_SAMPLE_PERCENT = 1
SEED = 42
"""),
        md("""
## 1. Load frozen splits and audit leakage

Notebook 10 must first write Parquet. Sample percentages control resources,
not dates. Test labels are loaded for final scoring only after validation
freezes the winner.
"""),
        code("""
def deterministic_sample(frame, percent):
    if percent >= 100:
        return frame.copy()
    bucket = pd.util.hash_pandas_object(frame["ECTRL ID"], index=False) % 100
    return frame.loc[bucket < percent].copy()

if RUN_MODELS:
    development_splits = {
        name: add_schedule_features(pd.read_parquet(DATA_ROOT / name))
        for name in ("train", "validation")
    }
    forbidden = {"ACTUAL OFF BLOCK TIME", "ACTUAL ARRIVAL TIME",
                 "Departure_Delay_Min", "Actual Distance Flown (nm)"}
    assert all(not (forbidden & set(frame.columns)) for frame in development_splits.values())
    cutoff = (pd.to_datetime(development_splits["train"]["FILED OFF BLOCK TIME"])
              - pd.to_datetime(development_splits["train"]["prediction_cutoff_t60"])
             ).dt.total_seconds()/60
    assert np.allclose(cutoff, 60)
    train = deterministic_sample(development_splits["train"], TRAIN_SAMPLE_PERCENT)
    validation = deterministic_sample(
        development_splits["validation"], VALIDATION_SAMPLE_PERCENT
    )
    print({
        **{name: len(frame) for name, frame in development_splits.items()},
        "locked_test_partitions_read": False,
    })
else:
    print("Set RUN_MODELS=True after notebook 10 writes Parquet.")
"""),
        md("""
## 2. Shared features and historical baseline

Airports, operator and grouped aircraft are hashed for Ridge and native
categories for CatBoost. Numeric medians and scaling are learned on train.
Operational T-60 columns are included automatically if notebook 10 built them.

The baseline fallback is route+airline, route, departure-airport+airline,
departure airport and global median, all fitted on train.
"""),
        code("""
LOW_CARDINALITY_COLUMNS = [
    "STATFOR Market Segment", "Class_aircraft", "Number+Engine Type_aircraft",
]
HIGH_CARDINALITY_COLUMNS = [
    "ADEP", "ADES", "AC Operator", "AC Type_grouped", "AC Registration",
]
CATEGORICAL_COLUMNS = LOW_CARDINALITY_COLUMNS + HIGH_CARDINALITY_COLUMNS
STATIC_NUMERIC_COLUMNS = [
    "Requested_FL_Imputed", "scheduled_duration_min",
    "departure_hour_sin", "departure_hour_cos",
    "departure_dow_sin", "departure_dow_cos", "departure_month",
]
if RUN_MODELS:
    OPERATIONAL_COLUMNS = [
        column for column in train.columns
        if column.startswith(("adep_dep_", "ades_arr_", "route_arr_",
                              "operator_dep_", "operator_arr_", "rotation_"))
    ]
    NUMERIC_COLUMNS = STATIC_NUMERIC_COLUMNS + OPERATIONAL_COLUMNS
    baseline = HistoricalMedianBaseline().fit(train)
    validation_predictions = {
        "historical_baseline": baseline.predict(validation)
    }
    print({"numeric_features": len(NUMERIC_COLUMNS),
           "operational_features": len(OPERATIONAL_COLUMNS)})
"""),
        md("""
## 3. Ridge selection

Ridge remains the primary balanced model: it is memory-efficient, stable with
high-cardinality hashing and was comparatively strong for delayed flights.
Alpha is selected on validation only.
"""),
        code("""
if RUN_MODELS:
    ridge_rows, ridge_objects = [], {}
    for alpha in (0.1, 1.0, 10.0, 100.0):
        preprocessor = MixedCategoricalRidgePreprocessor(
            LOW_CARDINALITY_COLUMNS, HIGH_CARDINALITY_COLUMNS, NUMERIC_COLUMNS
        )
        x_train = preprocessor.fit_transform(train)
        x_validation = preprocessor.transform(validation)
        model = Ridge(alpha=alpha, solver="lsqr").fit(
            x_train, train[TARGET]
        )
        prediction = model.predict(x_validation)
        metrics = segment_metrics(
            validation[TARGET], prediction, f"ridge_{alpha:g}", "validation"
        )
        ridge_rows.append({"alpha": alpha, **compact_score(metrics)})
        ridge_objects[alpha] = (model, preprocessor, prediction)
    ridge_selection = pd.DataFrame(ridge_rows).sort_values(
        ["combined_MAE_score", "global_MAE"]
    )
    selected_alpha = float(ridge_selection.iloc[0]["alpha"])
    ridge_model, ridge_preprocessor, validation_predictions["ridge"] = (
        ridge_objects[selected_alpha]
    )
    display(ridge_selection)
"""),
        md("""
## 4. Random Forest, GBT and XGBoost

Tree models use a smaller deterministic train sample by default because they
need more RAM, but use identical validation rows. XGBoost is the agreed fourth
model. LightGBM/SynapseML remains a future option with extra runtime complexity.
"""),
        code("""
def dense_tree_frame(frame, medians=None):
    categorical = frame[CATEGORICAL_COLUMNS].fillna("__MISSING__").astype(str)
    hashed = FeatureHasher(
        n_features=512, input_type="string", alternate_sign=False
    ).transform(
        ([f"{column}={value}" for column, value in zip(CATEGORICAL_COLUMNS, row)]
         for row in categorical.itertuples(index=False, name=None))
    ).toarray()
    numeric = frame[NUMERIC_COLUMNS]
    medians = numeric.median() if medians is None else medians
    numeric = numeric.fillna(medians).to_numpy(dtype=np.float32)
    return np.hstack([hashed.astype(np.float32), numeric]), medians

if RUN_MODELS:
    tree_train = deterministic_sample(train, TREE_SAMPLE_PERCENT)
    x_tree_train, tree_medians = dense_tree_frame(tree_train)
    x_tree_validation, _ = dense_tree_frame(validation, tree_medians)
    tree_models = {
        "random_forest": RandomForestRegressor(
            n_estimators=100, max_depth=12, min_samples_leaf=5,
            n_jobs=2, random_state=SEED,
        ),
        "gradient_boosted_trees": HistGradientBoostingRegressor(
            max_iter=200, max_leaf_nodes=31, learning_rate=0.05,
            l2_regularization=5, random_state=SEED,
        ),
    }
    try:
        from xgboost import XGBRegressor
        tree_models["xgboost"] = XGBRegressor(
            n_estimators=400, max_depth=7, learning_rate=0.04,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=8,
            objective="reg:absoluteerror", n_jobs=2, random_state=SEED,
        )
    except ImportError:
        print("XGBoost unavailable; install project requirements.")
    for name, model in tree_models.items():
        model.fit(x_tree_train, tree_train[TARGET])
        validation_predictions[name] = model.predict(x_tree_validation)
"""),
        md("""
## 5. CatBoost

CatBoost is the nonlinear categorical challenger. Native categories capture
route/operator/aircraft interactions without huge one-hot matrices.
Early stopping and time-aware fitting limit overfitting.
"""),
        code("""
if RUN_MODELS:
    try:
        from catboost import CatBoostRegressor, Pool
        cat_train = train.sort_values("FILED OFF BLOCK TIME").copy()
        cat_validation = validation.sort_values("FILED OFF BLOCK TIME").copy()
        cat_medians = cat_train[NUMERIC_COLUMNS].median()
        for frame in (cat_train, cat_validation):
            frame[CATEGORICAL_COLUMNS] = (
                frame[CATEGORICAL_COLUMNS].fillna("__MISSING__").astype(str)
            )
            frame[NUMERIC_COLUMNS] = frame[NUMERIC_COLUMNS].fillna(cat_medians)
        cat_features = CATEGORICAL_COLUMNS + NUMERIC_COLUMNS
        train_pool = Pool(cat_train[cat_features], cat_train[TARGET],
                          cat_features=CATEGORICAL_COLUMNS)
        validation_pool = Pool(cat_validation[cat_features], cat_validation[TARGET],
                               cat_features=CATEGORICAL_COLUMNS)
        catboost_model = CatBoostRegressor(
            loss_function="MAE", eval_metric="MAE", iterations=1200,
            learning_rate=0.03, depth=7, l2_leaf_reg=8, has_time=True,
            one_hot_max_size=10, max_ctr_complexity=2, random_seed=SEED,
            thread_count=2, od_type="Iter", od_wait=80,
            allow_writing_files=False, verbose=False,
        )
        catboost_model.fit(
            train_pool, eval_set=validation_pool, use_best_model=True
        )
        validation_predictions["catboost"] = catboost_model.predict(
            validation_pool
        )
    except ImportError:
        print("CatBoost unavailable; install project requirements.")
"""),
        md("""
## 6. Freeze winner on validation

Ranking gives equal weight to global MAE and MAE among flights delayed over 15
minutes. RMSE, median and p90 errors remain in the detailed segment report.
No test label is accessed here.
"""),
        code("""
if RUN_MODELS:
    validation_metrics = pd.concat([
        segment_metrics(validation[TARGET], prediction, name, "validation")
        for name, prediction in validation_predictions.items()
    ], ignore_index=True)
    validation_summary = pd.DataFrame([
        {"candidate": name, **compact_score(group)}
        for name, group in validation_metrics.groupby("model")
    ]).sort_values(["combined_MAE_score", "global_MAE"])
    validation_metrics.to_csv(
        REPORT_ROOT / "validation_segment_metrics.csv", index=False
    )
    validation_summary.to_csv(
        REPORT_ROOT / "validation_model_ranking.csv", index=False
    )
    SELECTED_MODEL = validation_summary.iloc[0]["candidate"]
    (REPORT_ROOT / "selection.json").write_text(
        json.dumps({"selected_model": SELECTED_MODEL}, indent=2),
        encoding="utf-8",
    )
    display(validation_summary)
"""),
        md("""
## 7. Locked March and June evaluation

Run only after validation freezes the winner. March and June are reported
separately to expose temporal drift. A disappointing test must not be folded
back into training and retuned.
"""),
        code("""
def predict_frozen(name, frame):
    if name == "historical_baseline":
        return baseline.predict(frame)
    if name == "ridge":
        return ridge_model.predict(ridge_preprocessor.transform(frame))
    if name in tree_models:
        matrix, _ = dense_tree_frame(frame, tree_medians)
        return tree_models[name].predict(matrix)
    if name == "catboost":
        prepared = frame.copy()
        prepared[CATEGORICAL_COLUMNS] = (
            prepared[CATEGORICAL_COLUMNS].fillna("__MISSING__").astype(str)
        )
        prepared[NUMERIC_COLUMNS] = prepared[NUMERIC_COLUMNS].fillna(cat_medians)
        return catboost_model.predict(
            prepared[CATEGORICAL_COLUMNS + NUMERIC_COLUMNS]
        )
    raise KeyError(name)

if RUN_MODELS:
    locked_splits = {
        name: add_schedule_features(pd.read_parquet(DATA_ROOT / name))
        for name in ("test", "future_test")
    }
    assert all(not (forbidden & set(frame.columns)) for frame in locked_splits.values())
    final_metrics = pd.concat([
        segment_metrics(
            locked_splits[split_name][TARGET],
            predict_frozen(SELECTED_MODEL, locked_splits[split_name]),
            SELECTED_MODEL, split_name,
        )
        for split_name in ("test", "future_test")
    ], ignore_index=True)
    final_metrics.to_csv(REPORT_ROOT / "locked_test_metrics.csv", index=False)
    display(final_metrics)
"""),
        md("""
## 8. Save prediction contract

The bundle records the T-60 horizon, features, temporal periods and sample
fractions so later predictions cannot silently use a different contract.
"""),
        code("""
if RUN_MODELS:
    bundle = {
        "selected_model_name": SELECTED_MODEL,
        "prediction_horizon_minutes": 60,
        "target": TARGET,
        "categorical_columns": CATEGORICAL_COLUMNS,
        "numeric_columns": NUMERIC_COLUMNS,
        "train_sample_percent": TRAIN_SAMPLE_PERCENT,
        "tree_sample_percent": TREE_SAMPLE_PERCENT,
        "validation_period": "2022-12",
        "test_period": "2023-03",
        "future_test_period": "2023-06",
    }
    if SELECTED_MODEL == "ridge":
        bundle.update({"model": ridge_model, "preprocessor": ridge_preprocessor})
    elif SELECTED_MODEL == "historical_baseline":
        bundle["model"] = baseline
    elif SELECTED_MODEL == "catboost":
        bundle.update({"model": catboost_model, "numeric_medians": cat_medians})
    else:
        bundle.update({"model": tree_models[SELECTED_MODEL],
                       "numeric_medians": tree_medians})
    path = MODEL_ROOT / "arrival_pre_t60_expanded_selected.joblib"
    joblib.dump(bundle, path)
    print({"saved": str(path)})
"""),
        md("""
## Guardrails

- Lower validation error does not prove future reliability; report both tests.
- The new months improve coverage but remain non-consecutive snapshots.
- Weather stays deferred until this expanded flight-only baseline is frozen.
- CNN/LSTM remains secondary until dense continuous sequences are available.
"""),
    ]
    path = ROOT / "notebooks" / "11_expanded_arrival_pre_models_prediction.ipynb"
    nbf.write(notebook, path)
    return path


if __name__ == "__main__":
    print(ingestion_notebook())
    print(modelling_notebook())
