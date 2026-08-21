# Source modules

- `flight_config.py` — shared targets, horizons, quality rules and feature configuration.
- `flight_data_catalog.py` — discovers monthly files and audits schema and null consistency.
- `spark_flight_pipeline.py` — creates Spark sessions and performs cleaning, joins, splits and transformations.
- `t60_operational_features.py` — builds leakage-safe T-60 traffic, congestion and rotation features.
- `t60_modeling.py` — contains baselines, preprocessing, regression and classification metrics.
- `business_eda.py` — produces business KPIs, statistical tests, rankings and charts.
- `java/localfs/` — Windows local-filesystem compatibility helper used by PySpark.
- `archive/` — reserved for retired source modules; none are archived currently because every module above is active.
