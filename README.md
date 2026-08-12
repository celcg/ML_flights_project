# ML Flights Project

Work in progress. Machine learning project focused on analyzing and predicting flight delay patterns using EUROCONTROL flight data and METAR weather data. The pipeline covers data ingestion, profiling, feature engineering, and will culminate in a predictive model for arrival and departure delays.

---

## Project Structure

```
ML_flights_project/
├── notebooks/
│   ├── 01_initial_analysis_sample.ipynb   # Field-by-field exploration of the flights fact table and schema design
│   └── 02_data_profiling.ipynb            # Full EDA: missing values, outliers, skewness, correlations, Sweetviz report
├── reports/
│   ├── 01_delay_distribution.png
│   ├── 02_aviation_sweetviz_report.html   # Auto-generated Sweetviz HTML report
│   ├── 02_correlation_heatmap.png
│   ├── 02_delay_arr_distribution.png
│   ├── 02_delay_dep_distribution.png
│   ├── 02_missing_values.png
│   ├── 02_outliers_boxplots.png
│   └── 02_skew_yeo_transform.png
├── scripts/
│   └── download_weatherdata.py            # Downloads METAR data from Iowa State Mesonet API for target airports
├── Plan.docx                              # Project planning document
├── requirements.txt
└── .gitignore
```

> `data/` is gitignored. Raw `.csv.gz` flight files must be placed under `data/raw/flights/` before running the notebooks. I cannot not include these files because of author licenses, so in order to execute the notebooks they need to be downloaded first from EUROCONTROL (more details in next section).

---

## Data Sources

**Flight data:** EUROCONTROL Network Manager. Monthly `.csv.gz` files structured as a star schema:

| Table | Description |
|-------|-------------|
| `Flights_YYYYMMDD_YYYYMMDD.csv.gz` | Fact table. One row per flight: ECTRL ID, ADEP/ADES (ICAO), filed and actual off-block/arrival times, aircraft type, operator, distance flown |
| ICAO airport reference | Airport name, country, coordinates |
| ICAO aircraft type reference | Model, engine type |
| ICAO airline reference | Operator name |
| `Flight_Points_*` | Trajectory waypoints (optional enrichment) |
| `Flight_FIRs_*` | FIR airspace crossings (optional enrichment) |

**Weather data:** Iowa State University Mesonet ASOS API (`mesonet.agron.iastate.edu`). METAR and SPECI observations for target airports. Currently scoped to LEMD, LEBL, LEMG (December 2021).

---

## Tech Stack

| Layer | Library |
|-------|---------|
| Data manipulation | `pandas >= 2.0.0`, `numpy` |
| Big data processing | `pyspark >= 3.4.0` |
| EDA & profiling | `sweetviz`, `missingno` |
| Visualization | `matplotlib`, `seaborn` |
| Machine learning | `scikit-learn`, `xgboost`, `lightgbm` |
| Environment | `jupyterlab`, `ipykernel` |

---

## Installation

**Requirements:** Python 3.8+

```bash
# 1. Clone the repository
git clone https://github.com/celcg/ML_flights_project.git
cd ML_flights_project

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Download weather data

Edit `scripts/download_weatherdata.py` to set the target airports and date range, then run:

```bash
python scripts/download_weatherdata.py
```

This fetches METAR/SPECI observations from the Iowa State Mesonet API and saves a `weather_data_<year>.csv` file locally.

### Run notebooks

Place raw EUROCONTROL flight files under `data/raw/flights/` (`.csv.gz` format), then launch JupyterLab:

```bash
jupyter lab
```

Run notebooks in order:

1. `01_initial_analysis_sample.ipynb` — schema exploration and field documentation
2. `02_data_profiling.ipynb` — EDA, missing value analysis, outlier detection (IQR + Z-score), skewness correction (log and Yeo-Johnson transforms), correlation heatmap, and Sweetviz HTML report

---

## Key Engineered Features

Computed inside the notebooks from the raw time columns:

| Feature | Formula |
|---------|---------|
| `Arrival_Delay_Min` | `ACTUAL ARRIVAL TIME` − `FILED ARRIVAL TIME` (seconds / 60) |
| `Departure_Delay_Min` | `ACTUAL OFF BLOCK TIME` − `FILED OFF BLOCK TIME` (seconds / 60) |
| `duration_actual_min` | `ACTUAL ARRIVAL TIME` − `ACTUAL OFF BLOCK TIME` (seconds / 60) |
| `Log_Actual_Distance` | `log1p(Actual Distance Flown (nm))` |
| `Arrival_Delay_Min_YJ` | Yeo-Johnson transform of arrival delay (handles negative values) |
| `Departure_Delay_Min_YJ` | Yeo-Johnson transform of departure delay |

---

## Gitignore Notes

The following are not tracked and must be sourced or generated locally:

- All `.csv`, `.csv.gz`, `.xlsx`, `.zip`, `.tar.gz` files
- The `data/` directory
- Virtual environments (`venv/`)
- Jupyter checkpoint folders
- `.env` and credential files
