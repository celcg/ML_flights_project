# Flight Delay Intelligence at T-60

## 1. Project introduction

This project turns EUROCONTROL flight records into operational analytics and arrival-delay predictions available **60 minutes before scheduled departure**. It began as a flight-delay modelling exercise and evolved into an end-to-end decision-support project after exploratory analysis showed that airports, routes, operators, schedules and network pressure all provide useful business context.

The work combines a reproducible PySpark data pipeline, a descriptive aviation dashboard and two predictive tasks: estimating arrival-delay minutes and classifying whether a flight will arrive more than 15 minutes late. Only regular operated flights are modelled, and every predictive feature is checked against the T-60 information boundary.

Current outputs include a complete business report, a Streamlit analytics application, leakage-safe train/validation/test datasets and saved regression and classification models. Ridge is the selected minute-regression model: on the locked March 2023 test it achieved **9.85-minute MAE and 15.22-minute RMSE**. The classifier is useful as a risk-ranking prototype, but its recall still needs improvement before operational deployment.

The final objectives of this project:
- A interactive dashboard analyzing patterns in delays, useful for airlines to track delays, but also customers to know most and least reliable airports, airlines, routes, hours and periods. 
-A ML model as a reusable tool that helps analysts identify unreliable routes and operating windows, compare network performance fairly and prioritise flights with elevated delay risk.

## 2. Technologies

| Technology | Why it is used |
|---|---|
| Python | Provides one language for ingestion, analysis, modelling and deployment. |
| PySpark | Processes millions of flight records with explicit schemas and scalable transformations on a local machine. |
| pandas, NumPy and SciPy | Support compact analysis, statistical tests and model-ready tables. |
| scikit-learn | Implements reproducible preprocessing, Ridge and classification workflows. |
| XGBoost and CatBoost | Test nonlinear alternatives and native handling of complex categorical structure. |
| PyArrow and Parquet | Preserve schemas and enable compressed, column-oriented exchange between Spark and Python models. |
| Matplotlib, Seaborn and Altair | Produce static report figures and interactive dashboard charts. |
| Streamlit | Turns aggregated, licence-safe outputs into an accessible analytics dashboard. |
| Jupyter | Documents the analytical workflow and key decisions step by step. |

PySpark runs locally; the project does **not** require an external Hadoop cluster or HDFS.

## 3. Installation and execution

Python 3.13 and a Java runtime compatible with PySpark are recommended.

```powershell
python -m venv .venv313
.\.venv313\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The flight data cannot be redistributed with this repository. Register for the **EUROCONTROL Aviation Data Repository for Research**, accept its terms and download the monthly `Flights_*.csv.gz` files into `data/raw/<YYYYMM>/` or `data/raw/flights/`. The project uses this source despite its non-consecutive coverage because it offers millions of European operations and unusually rich categorical and operational fields for airports, operators, aircraft, routes and schedules.

Run the notebooks in numerical order. For the expanded workflow, notebook 10 builds the temporal Parquet partitions and notebook 11 trains and evaluates both prediction tasks.

```powershell
jupyter lab
python -m unittest discover -s tests
streamlit run streamlit_app/app.py
```

The optional weather downloader is kept for later experiments:

```powershell
python scripts/download_weatherdata.py
```

## 4. Repository structure

```text
ML_flights_project/
|-- data/            # private raw downloads and processed Parquet/dimensions
|-- doc/             # final Word deliverables
|-- models/          # saved regression and classification artefacts
|-- notebooks/       # ordered analytical workflow from exploration to prediction
|-- reports/         # reusable metrics, audits, figures and prediction outputs
|-- scripts/         # repeatable command-line runners and data utilities
|-- src/             # tested cleaning, feature, modelling and EDA modules
|-- streamlit_app/   # interactive dashboard and publishable aggregated data
|-- tests/           # unit and PySpark tests
|-- README.md
`-- requirements.txt
```

Folder-level guides are available in [`notebooks/README.md`](notebooks/README.md), [`reports/README.md`](reports/README.md), [`scripts/README.md`](scripts/README.md) and [`src/README.md`](src/README.md). The principal descriptive deliverable is [`doc/Business_report.docx`](doc/Business_report.docx).

## 5. Key decisions

- **T-60 prediction boundary:** only data observable one hour before scheduled departure is admitted, preventing operational leakage.
- **Temporal validation:** earlier snapshots train the models, December 2022 selects them, and March and June 2023 measure locked and future performance.
- **Two complementary targets:** regression estimates delay severity; classification communicates the risk of exceeding the operational 15-minute threshold.
- **Regular flights only:** the scope is kept operationally coherent; cancellations cannot be analysed because they are absent from the source.
- **Categorical strategy:** one-hot encoding is used for low-cardinality fields, while hashing and rare-category grouping control memory for airports, routes, operators and aircraft types.
- **Train-only preparation:** imputation, category grouping and transformations are learned exclusively from training data.
- **Ridge as the current winner:** it provides the best balance between global error, delayed-flight performance, stability, interpretability and local memory use. Nonlinear models remain benchmarks rather than assumed improvements.
- **Operational history features:** congestion, recently observed flights and completed aircraft rotations use only events available by each flight's cutoff.
- **Business statistics with safeguards:** minimum-volume thresholds, Wilson intervals, multiple-test correction and a three-percentage-point practical threshold reduce misleading rankings in a very large dataset.
- **Weather deferred:** the flight-only baseline is frozen first so any later weather improvement can be measured honestly.
- **Aggregated public data:** the Streamlit app publishes reusable summaries rather than licensed row-level EUROCONTROL records.
