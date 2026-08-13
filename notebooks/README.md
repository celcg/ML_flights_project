## Data Access

This project uses the **Eurocontrol Aviation Data Repository for Research**.

Due to licensing restrictions you must:
1. Register at OneSky Online and agree to Eurocontrol’s Terms of Use.
2. Download the dataset yourself. Extract only files of flights.
3. Place it in `data/raw/flights` and run the preprocessing scripts.

*Real Eurocontrol data is not included in this public repository.*

## Notebook order

1. `01_initial_analysis_sample.ipynb` — source contract and baseline exploration.
2. `02_numeric_data_profiling.ipynb` — seeded multi-period sample, data-quality
   rules and optional train-only numeric transforms.
3. `03_non_numeric_data_analysis.ipynb` — dimension integrity, coverage and
   guarded joins. Set `RUN_WRITES=True` only when you want to persist the merged
   airport dimension.
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
9. `09_business_aviation_analysis.ipynb` — English business-facing analysis of
   network demand, route and operator reliability, temporal patterns, delay
   recovery, correlations and hypothesis tests. It discovers one canonical
   file for each of nine monthly snapshots through June 2023 and audits raw
   null compatibility. Holdouts may be described but never fed into fitting.
10. `10_expanded_data_ingestion_cleaning_pyspark.ipynb` — expanded PySpark
    ingestion and cleaning with the previous rules, raw/post-clean null audits,
    four temporal partitions and optional leakage-audited T-60 features.
11. `11_expanded_arrival_pre_models_prediction.ipynb` — baseline, Ridge, Random
    Forest, GBT, XGBoost and CatBoost on the expanded Parquet contract. December
    selects the model; March and June 2023 are scored only after freezing it.

## Scaling experiment: 25% of train

`scripts/run_t60_25pct.py` is the low-memory scaling run for the current winning
model. It rebuilds the audited T-60 operational variables for a deterministic,
nested 25% training sample, keeps the same 5% validation rows, and freezes the
decisions selected at 10%:

- feature set: all airport, route, operator and rotation variables except the
  6-hour window;
- Ridge `alpha=10` and a 32,768-position categorical hash;
- no new tuning on validation and no access to the processed test period.

The run fits Ridge and the historical route+airline baseline only. This isolates
the effect of adding training rows and avoids the extra memory required by a
second CatBoost fit. Run it from the project root with the Python 3.13 environment:

```powershell
& 'C:\Users\celti\AppData\Local\Programs\Python\Python313\python.exe' scripts\run_t60_25pct.py
```

The explicit interpreter path is intentional: this project lives in OneDrive
and Windows can reject the executable shim inside `.venv313` even though its
packages are valid. The runner adds `.venv313\Lib\site-packages` itself.

Close browsers, VS Code, Word and other memory-heavy applications first. The
preflight requires at least 1.5 GB free for the reduced `local[1]` / 2 GB Spark
configuration; 4–5 GB free remains the recommended safe target. Results are
written separately under `data/processed/model/arrival_pre_t60_ops_25pct`,
`reports/09_t60_25pct_*` and `models/09_*_25pct.*`, so notebook-08 artifacts are
not overwritten. Continue to 50% only if the frozen Ridge improves the combined
MAE score by at least 0.20 minutes without worsening global MAE by more than 0.25.

### Executed result

The 25% run completed with 613,884 train rows and the same 29,315 validation
rows. Ridge achieved MAE 9.892 and RMSE 14.749 minutes. Relative to Ridge at 10%,
MAE improved by 0.049 minutes, RMSE by 0.049 minutes, and the 50/50 combined MAE
criterion by only 0.027 minutes. This is statistically positive but practically
too small to meet the 0.20-minute scaling threshold. The current decision is not
to continue to 50%/100% with the unchanged feature set; prioritize temporal
coverage and new signals first. Test remained unread.

The original exploratory notebook 03 is preserved unchanged at
`archive/03_non_numeric_data_analysis_original.ipynb`. The active notebook keeps
that investigation while separating historical exploration from executable
validation.

Run notebooks from the `notebooks` directory. Shared decisions live in
`src/flight_config.py`; reusable Spark functions live in
`src/spark_flight_pipeline.py`. The Spark notebook can rebuild the airport
dimension in memory when the processed CSV does not exist. Log and Yeo–Johnson
transforms are optional and disabled by default.

The current modelling population is scheduled commercial traffic (`ICAO Flight
Type = S`) and the active task is arrival delay at T-60 (`arrival_pre`). Train
covers the periods through September 2022, validation is December 2022, the
first untouched test is March 2023 and June 2023 is a future test.

The validated local environment uses Python 3.13 and PySpark 4.2. On Windows,
`create_spark` compiles a small local-filesystem adapter so Parquet can be written
without installing Hadoop, HDFS or the unofficial `winutils.exe` binary.
