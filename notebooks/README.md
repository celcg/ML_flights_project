## Data Access

This project uses the **Eurocontrol Aviation Data Repository for Research**.

Due to licensing restrictions you must:
1. Register at OneSky Online and agree to Eurocontrol’s Terms of Use.
2. Download the dataset yourself. Extract only files of flights.
3. Place it in `data/raw/flights` and run the preprocessing scripts.

## Notebook order

1. `01_initial_analysis_sample.ipynb` — source contract and baseline exploration.
2. `02_numeric_data_profiling.ipynb` — seeded multi-period sample, data-quality
   rules and optional train-only numeric transforms.
3. `03_non_numeric_data_analysis.ipynb` — dimension integrity, coverage and
   guarded joins. Set `RUN_WRITES=True` only when you want to persist the merged
   airport dimension to `data/processed/dimensions/airports_merged.csv`.
4. `04_cleaning_pyspark.ipynb` — complete Spark cleaning and feature pipeline.

5. `05_arrival_pre_baselines.ipynb` — leakage-safe global, route and
   route+airline median baselines, temporal evaluation and segmented metrics.
6. `06_arrival_pre_model_benchmark.ipynb` — low-memory 1% resource benchmark for
   regularised linear regression, Random Forest, GBT and XGBoost. It uses 5% of
   validation, a 4 GB Spark driver and an 8,192-position categorical hash.
7. `07_arrival_pre_aligned_validation.ipynb` — executed CatBoost weight sweep and
   nested 1/5/10% learning curve. All candidates use the identical 5% validation
   sample; ranking gives 50% weight to global MAE and 50% to delayed-flight MAE
   at T-60 and never reads test.
8. `08_arrival_pre_t60_operational_features.ipynb` — executed leakage-audited
   rolling operational features at T-60. It uses observed departures and completed
   arrivals in 1/6/24-hour windows, previous-aircraft rotation, an internal temporal
   tuning split, feature ablation and a Ridge/CatBoost/baseline ensemble. The
   enriched 10% train and 5% validation samples are persisted as reusable Parquet;
   the external test period remains untouched.
9. `09_business_aviation_analysis.ipynb` —  business-facing analysis of
   network demand, route and operator reliability, temporal patterns, delay
   recovery, correlations and hypothesis tests. It discovers one canonical
   file for each of nine monthly snapshots through June 2023 and audits raw
   null compatibility.
10. `10_expanded_data_ingestion_cleaning_pyspark.ipynb` — expanded PySpark
    ingestion and cleaning with the previous rules, raw/post-clean null audits,
    four temporal partitions and optional leakage-audited T-60 features.
11. `11_expanded_arrival_pre_models_prediction.ipynb` — baseline, Ridge, Random
    Forest, GBT, XGBoost and CatBoost on the expanded Parquet contract. It keeps
    the minute-regression task and adds a separate classifier for arrival delay
    above 15 minutes, with accuracy, balanced accuracy, precision, recall, F1,
    ROC-AUC, PR-AUC and confusion counts. December selects both models; March and
    June 2023 are scored only after freezing them.
