# Flight-delay prediction and business analysis at T-60

Business-intelligence and machine-learning project based on EUROCONTROL flight
data. Its first major deliverable is a complete descriptive report of European
scheduled aviation performance. Its predictive component estimates, **60
minutes before scheduled departure**, both arrival-delay minutes and the
probability that a flight will arrive more than 15 minutes late.

The project also provides descriptive analysis to identify airports, routes,
operators, countries and time windows that warrant operational investigation.
These results are prioritisation signals, not causal attributions of
responsibility.

## Contents

- [Executive summary](#executive-summary)
- [Descriptive business report](#descriptive-business-report)
- [Objective and scope](#objective-and-scope)
- [Data and temporal split](#data-and-temporal-split)
- [Project workflow](#project-workflow)
- [Implemented statistics and charts](#implemented-statistics-and-charts)
- [Delay prediction](#delay-prediction)
- [Current predictive results](#current-predictive-results)
- [Next steps](#next-steps)
- [Running the project](#running-the-project)
- [Environment and structure](#environment-and-structure)

## Executive summary

- The main completed deliverable is a **22-page executive business report**
  combining network KPIs, airport and country maps, reliability rankings,
  congestion analysis, route and carrier comparisons, temporal monitoring and
  two detailed operational case studies.
- The data catalogue contains **nine monthly snapshots from June 2021 to June
  2023**, covering 6,099,999 flights before applying the analytical scope.
- The business analysis contains **5,375,605 regular flights with an observed
  arrival** and a network OTP15 of **82.17%**.
- The prediction horizon is fixed at **T-60**: only information that would exist
  one hour before scheduled departure is allowed.
- Ridge is currently the preferred regression model because it balances global
  error, performance on delayed flights, stability and memory consumption.
- Using 25% of train, Ridge achieves **MAE 9.892 min and RMSE 14.749 min**.
  Increasing train from 10% to 25% improves error by less than 0.05 minutes, so
  better signals or more periods are more valuable than adding rows from the
  same historical distribution.
- Classification for arrival delay `>15 min` is implemented in notebook 11.
  Results on the expanded dataset are pending execution after rebuilding the
  Parquet files. Their previous generation stopped because of a duplicated
  cutoff column; that issue has now been fixed.
- Weather remains deferred until a reliable flight, schedule and recent
  operational-history baseline has been frozen.

The project therefore has two complementary outputs:

1. **Descriptive decision support:** explain where, when and under which network
   conditions delays accumulate.
2. **Predictive decision support:** estimate the expected delay and the risk of
   exceeding 15 minutes for an individual flight at T-60.

## Descriptive business report

The most complete deliverable produced so far is the English-language report:

**[European Scheduled Aviation Performance — Business Analysis](doc/European_Scheduled_Aviation_Business_Report_WITH_CASE_STUDIES_2026-08-14.docx)**

The report turns more than five million in-scope flight observations into an
executive view of network reliability. It is designed to help an airport,
airline, network manager or EUROCONTROL analyst decide **where to investigate
first**, while keeping statistical uncertainty and data limitations visible.

### What the report covers

- **Network overview:** traffic volume, OTP15, delay severity, median delay and
  the disruption tail.
- **Airports:** origin and destination rankings, volume-versus-reliability
  comparisons, geographical maps and alerts for the ten busiest origins.
- **Countries and territories:** rankings and a European map for jurisdictions
  with at least 1,000 historical movements.
- **Operating carriers:** raw OTP15, 95% Wilson intervals and delay minutes
  scaled by scheduled flight duration.
- **Routes:** high-volume route reliability, exceptional weak routes and
  matched comparisons that reduce network-mix bias.
- **Congestion:** a within-airport traffic-pressure proxy that compares each
  airport with its own historical activity distribution.
- **Time:** weekday performance, a weekday-by-hour heatmap and changes across
  the nine snapshots.
- **Change monitoring:** practically material deterioration signals for
  high-volume airports and operating carriers.
- **Case studies:** Ryanair versus Wizz Air on shared routes and the
  Madrid-Milan corridor by period, carrier, hour and individual flight records.

### Main descriptive findings

- Network OTP15 is **82.17%**, meaning almost one in five observed arrivals is
  more than 15 minutes late.
- Traffic pressure is strongly associated with reliability: the `>15 min`
  delay rate rises from **12.0% in low-pressure airport-hours to 21.1% at peak
  pressure**.
- Airport volume does not explain performance by itself. EDDF and EGLL each
  have roughly 261,000 movements, but their OTP15 values are **82.8% and 65.5%**.
- Among countries with sufficient volume, Norway records **94.9% OTP15**, while
  France records 78.4% and the Netherlands 77.2%. These are descriptive network
  results and must not be read as national causal rankings.
- Tuesday is descriptively strongest at **84.3% OTP15**, while Saturday records
  80.3%; the weekday-by-hour matrix reveals more actionable operating windows
  than daily averages alone.
- Flights up to 90 minutes have a 10.3% delay-above-15 rate, compared with 38.7%
  for flights over six hours. This makes duration and schedule-definition
  audits essential when comparing airports and operators.
- Across 319 shared directional routes, route-standardised OTP15 is 88.7% for
  Ryanair and 87.6% for Wizz Air. The small difference is more informative than
  an unadjusted network-wide league table.
- Madrid-Milan falls from **96.6% OTP15 in March 2022 to 80.3% in March 2023**,
  demonstrating how the data can identify a deteriorating corridor, period and
  operating window before drilling into individual records.

### Business value

The report can support:

- Prioritisation of airports, corridors and time windows for operational review.
- Capacity, staffing and stand-allocation discussions around peak pressure.
- Fairer airline comparisons after accounting for route and duration mix.
- Early-warning dashboards based on each entity's historical performance.
- Data-quality audits when extreme long-haul, timezone or schedule results
  appear implausible.
- Selection of new predictive variables from patterns observed in the
  descriptive analysis.

It deliberately avoids presenting associations as causes. Volume thresholds,
Wilson intervals, multiple-test correction and a three-percentage-point
practical threshold are used to prevent large datasets from making every small
difference appear operationally important.

## Objective and scope

The main task is `arrival_pre_t60`:

1. **Regression:** predict `Arrival_Delay_Min`.
2. **Classification:** predict whether `Arrival_Delay_Min > 15`.

Only regular commercial flights (`ICAO Flight Type = S`) are included.
Cancelled flights are unavailable, so the metrics describe operated services.
Passenger counts, revenue, gate assignments, official delay causes and weather
are also not yet available.

OTP15 defines a flight as punctual when it arrives **no more than 15 minutes
late**. A flight delayed by exactly 15 minutes belongs to the punctual class.

## Data and temporal split

The data comes from the **EUROCONTROL Aviation Data Repository for Research**
and is not distributed with this repository because of its licence conditions.

The expanded workflow uses:

| Purpose | Period | Permitted decision |
|---|---|---|
| Train | June 2021 to September 2022 | Fit imputation, encoding and models |
| Validation | December 2022 | Select hyperparameters and models |
| Locked test | March 2023 | Final evaluation without retuning |
| Future test | June 2023 | Assess temporal stability |

The months are non-consecutive snapshots. This supports temporal-transfer
testing but limits the analysis of continuous seasonality and delay propagation.

### Features available at T-60

- Scheduled duration, requested flight level, month, weekday and cyclical hour.
- Origin and destination airports, route, operator and grouped aircraft type.
- Counts, means, standard deviations and delay rates from already observed
  flights in 1-, 6- and 24-hour windows by airport, route and operator.
- The latest rotation of the assigned aircraft that had finished before T-60.
- One-hot encoding for low-cardinality categories and hashing for airports,
  operator and AC Type.
- Imputation, rare-category grouping and transformations fitted only on train.

The temporal audit removes the target flight's own contribution and verifies
that no event occurring after the prediction cutoff enters the features.

## Project workflow

| Stage | Notebooks | Output |
|---|---|---|
| Exploration and data contract | 01-03 | Quality, nulls, cardinality and transformation decisions |
| Initial cleaning | 04 | Aviation rules and reproducible PySpark dataset |
| Baselines and models | 05-08 | Historical baselines, benchmark and operational T-60 features |
| Business analysis | 09 | Charts, rankings, maps and statistical tests |
| Expanded data | 10 | Nine months, four temporal splits and leakage-safe Parquet |
| Expanded prediction | 11 | Minute regression and delay `>15 min` classification |

Details for each notebook and the supporting commands are available in
[`notebooks/README.md`](notebooks/README.md).

## Implemented statistics and charts

The report applies minimum-volume rules, 95% Wilson intervals and a **three
percentage-point OTP15 threshold** to distinguish practical relevance from mere
statistical significance. Benjamini-Hochberg correction is applied when
multiple hypotheses are tested.

The analysis also uses Spearman correlation, two-proportion tests, Wilcoxon for
paired comparisons and Kruskal-Wallis for distributions that are not assumed to
be normal.

### Chart catalogue and practical value

| Area | Main charts | Example conclusion | Real-world use |
|---|---|---|---|
| Methodology | *How rates, uncertainty, hypothesis tests and practical importance work together* | With millions of flights, a difference can be statistically significant without reaching three percentage points | Prevent expensive decisions based on operationally irrelevant effects |
| Airports | *Origin-airport OTP15 rankings*, *Destination-airport OTP15 rankings* and *Top-200 airport volume and OTP15 on a geographic basemap* | EDDF and EGLL each have approximately 261,000 movements, but their OTP15 values are 82.8% and 65.5% | Prioritise airports whose reliability is unusual for their traffic volume |
| Relative delay | *High-volume destination airports compared by OTP15 and relative delay burden* | Airports with similar OTP15 can have different delay severity relative to flight duration | Separate delay frequency from proportional operational damage |
| Countries | *Best and worst eligible country-or-territory OTP15 results* and the European map | Among countries with over 1,000 movements, Norway reaches 94.9%, Italy 89.0% and Spain 87.4%; France records 78.4% and the Netherlands 77.2% | Identify markets where capacity, network mix and operational practices warrant review |
| Operators | *Operating-carrier OTP15 with Wilson intervals* and *Delay burden scaled by duration* | The raw ranking changes when positive delay minutes are divided by scheduled flight minutes | Avoid automatically favouring long-haul operators and identify where adjusted analysis is required |
| Matched comparison | *Ryanair and Wizz Air on shared directional routes* | Across 319 shared routes, route-standardised OTP15 is 88.7% for Ryanair and 87.6% for Wizz Air; the difference is small | Compare competitors while reducing route-mix bias |
| Case study | *Madrid-Milan corridor by snapshot, carrier and departure hour* | OTP15 falls from 96.6% in March 2022 to 80.3% in March 2023; 05:00 reaches 96.3%, while 12:00 records 80.3% | Locate when a corridor deteriorates and which operating window to investigate |
| Routes | *Flight volume and delay-above-15 rate on the highest-volume directional routes* | The most frequently operated routes are not necessarily the most reliable | Prioritise routes that combine large volume and weak performance |
| Congestion | *Delay rate across within-airport traffic-load quartiles* | The `>15 min` delay rate rises from 12.0% in low-pressure airport-hours to 21.1% at peak pressure | Support staffing, stand-allocation and schedule-smoothing decisions |
| Duration | *Arrival-delay severity and traffic exposure by flight-duration band* | The `>15 min` rate is 10.3% for flights up to 90 minutes and 38.7% for flights over six hours | Interpret rankings after considering short-/long-haul mix and audit schedule or timezone definitions |
| Weekday and hour | *Weekday OTP15 with Wilson intervals* and *OTP15 by scheduled departure weekday and hour* | Tuesday records 84.3% OTP15 and Saturday 80.3%; the matrix reveals windows hidden by daily averages | Plan capacity and alerts by operational window |
| Temporal change | *Material airport OTP15 deteriorations* and *Material carrier OTP15 deteriorations* | Extreme changes are flagged for audit before responsibility is attributed | Separate persistent deterioration from coverage or schedule anomalies |

### How to interpret the results

- Rankings are **descriptive** and can reflect route mix, distance, airports
  served or schedule definitions.
- Extreme long-haul results should first trigger an audit of dates, time zones
  and scheduled times.
- A Wilson interval quantifies uncertainty around a proportion; it does not turn
  an association into a causal result.
- The final airline comparison should control for route, origin, destination,
  duration, hour and period.

This catalogue documents the statistical evidence behind the descriptive
business report presented near the top of this README.

## Delay prediction

### Models tested for delay minutes

- Global median and historical baselines with route, route-airline and airport
  fallback levels.
- Regularised Ridge regression.
- Ridge with original, log-transformed and Yeo-Johnson numeric features.
- Random Forest and Gradient-Boosted Trees.
- XGBoost.
- CatBoost with native categorical features.
- Ridge + CatBoost + historical-baseline ensemble.

### Models implemented for delayed/not delayed

- Majority-class baseline.
- Regularised logistic regression.
- CatBoostClassifier.
- Conversion of the winning regressor: `predicted minutes > 15`.

Classification reports **accuracy**, but accuracy is not used alone. Balanced
accuracy, precision, recall, specificity, F1, ROC-AUC, PR-AUC and the complete
confusion matrix are also calculated. Selection primarily uses PR-AUC because
delayed flights are the minority class.

Each final prediction contains:

- Estimated arrival-delay minutes.
- Probability of exceeding 15 minutes.
- Binary punctual/delayed decision.

Regression and classification artefacts are stored separately so that either
task can be updated or deployed independently.

## Current predictive results

Comparison on the same 29,315 validation rows:

| Model | Train | Global MAE | Global RMSE | MAE if delay >15 | RMSE if delay >15 |
|---|---:|---:|---:|---:|---:|
| Comparable historical baseline | 10% | 10.45 | 15.83 | 22.68 | 29.77 |
| Ridge T-60 | 10% | 9.94 | 14.80 | 18.21 | 25.88 |
| Ridge T-60 | 25% | **9.892** | **14.749** | **18.202** | **25.859** |
| Comparable baseline | 25% | 10.130 | 15.492 | 21.658 | 29.109 |

CatBoost achieves the best global MAE in some experiments but performs worse on
delayed flights. Ridge minimises the agreed criterion that gives equal weight
to global MAE and MAE on flights delayed by more than 15 minutes. It also uses
less memory and remains more stable across samples, making it the current
winner.

Moving from 10% to 25% of train improves Ridge by only **0.049 minutes in MAE
and 0.049 minutes in RMSE**. Training on many more rows with the same features
has low expected value; more diverse periods and new signals are more promising.

Classifier accuracy and PR-AUC on the expanded dataset are not published yet.
The code and tests are complete, but notebook 10 must first regenerate the
Parquet files and notebook 11 must then be executed. March and June must remain
locked until the classifier has been selected using December.

## Next steps

1. Regenerate the four expanded Parquet partitions with the corrected notebook
   10.
2. Train regression and classification using the same temporal train and
   validation sets.
3. Select the classifier using December PR-AUC, F1, recall and the cost of false
   negatives, rather than accuracy alone.
4. Freeze both models and evaluate March and June 2023 once.
5. Calibrate probabilities and determine whether the operational probability
   threshold should remain at 0.5 or reflect the real cost of missing a delay.
6. Compare adjusted airline effects after controlling for route, airport,
   duration, hour and period.
7. Acquire consecutive months, cancellations, diversions and passenger or seat
   exposure.
8. Add weather after freezing the expanded flight-only baseline.
9. Consider CNN/LSTM only if dense, continuous temporal sequences become
   available; tabular models remain preferable for isolated snapshots.

## Running the project

### Installation

```powershell
python -m venv .venv313
.\.venv313\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Build the expanded dataset

In notebook 10, set:

```python
RUN_FULL_DATA = True
WRITE_PARQUET = True
BUILD_OPERATIONAL_T60 = True
```

Run all cells. This creates `train`, `validation`, `test` and `future_test`
under `data/processed/expanded_arrival_pre_t60/`.

### Train both prediction tasks

In notebook 11, set:

```python
RUN_MODELS = True
RUN_CLASSIFICATION = True
RUN_CATBOOST_CLASSIFIER = True
```

The notebook selects models using December and only then opens March and June.
Results are written to `reports/expanded_models/`, while model artefacts are
stored in `models/expanded/`.

For a large local run, close browsers, editors and other applications until at
least 4-5 GB of RAM is available.

### Tests

```powershell
python -m unittest discover -s tests
```

## Environment and structure

- Python 3.13, PySpark 4.2, pandas, NumPy, PyArrow and scikit-learn.
- XGBoost and CatBoost for nonlinear models.
- PySpark runs locally: **no Hadoop cluster or HDFS is used**.
- Parquet preserves types, compresses data and supports column-level reads.

```text
ML_flights_project/
|-- data/          # local data and Parquet; not versioned
|-- doc/           # Word reports
|-- models/        # trained models
|-- notebooks/     # analytical and predictive workflow 01-11
|-- reports/       # metrics, audits, figures and predictions
|-- scripts/       # reproducible runners
|-- src/           # cleaning, features, modelling and analysis
|-- tests/         # unit and PySpark tests
|-- README.md
`-- requirements.txt
```
