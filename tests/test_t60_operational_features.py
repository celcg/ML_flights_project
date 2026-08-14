from datetime import datetime
import unittest

try:
    from src.spark_flight_pipeline import create_spark
    from src.t60_operational_features import (
        build_rolling_event_features,
        build_rotation_features,
        build_standard_t60_features,
    )

    PYSPARK_AVAILABLE = True
except Exception as exc:
    PYSPARK_AVAILABLE = False
    SPARK_IMPORT_ERROR = str(exc)


@unittest.skipUnless(
    PYSPARK_AVAILABLE,
    f"PySpark runtime is unavailable: {globals().get('SPARK_IMPORT_ERROR', 'not installed')}",
)
class T60OperationalFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = create_spark("t60-feature-tests", master="local[1]")
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_rolling_features_exclude_future_and_subtract_the_target_itself(self):
        targets = self.spark.createDataFrame(
            [(2, "AAA", datetime(2022, 1, 1, 9, 0))],
            ["ECTRL ID", "ADEP", "prediction_cutoff_t60"],
        )
        events = self.spark.createDataFrame(
            [
                (1, "AAA", datetime(2022, 1, 1, 8, 30), 10.0),
                (2, "AAA", datetime(2022, 1, 1, 8, 45), 20.0),
                (3, "AAA", datetime(2022, 1, 1, 9, 15), 100.0),
            ],
            ["ECTRL ID", "ADEP", "event_time", "delay"],
        )
        result = build_rolling_event_features(
            targets,
            events,
            key_columns=["ADEP"],
            event_time_column="event_time",
            value_column="delay",
            prefix="adep_dep",
            windows_hours=(1,),
        ).first()
        self.assertEqual(result["adep_dep_1h_count"], 1)
        self.assertAlmostEqual(result["adep_dep_1h_mean"], 10.0)
        self.assertEqual(result["_adep_dep_1h_self_removed"], 1)
        self.assertLessEqual(
            result["_adep_dep_1h_max_event_time"],
            result["prediction_cutoff_t60"],
        )

    def test_rotation_uses_only_the_previous_completed_flight(self):
        targets = self.spark.createDataFrame(
            [(2, "REG1", datetime(2022, 1, 1, 9, 0))],
            ["ECTRL ID", "AC Registration", "prediction_cutoff_t60"],
        )
        events = self.spark.createDataFrame(
            [
                (1, "REG1", datetime(2022, 1, 1, 8, 30), 12.0, 5.0),
                (2, "REG1", datetime(2022, 1, 1, 11, 0), 40.0, 30.0),
            ],
            [
                "ECTRL ID",
                "AC Registration",
                "ACTUAL ARRIVAL TIME",
                "Arrival_Delay_Min",
                "Departure_Delay_Min",
            ],
        )
        result = build_rotation_features(targets, events).first()
        self.assertAlmostEqual(result["rotation_previous_arrival_delay"], 12.0)
        self.assertAlmostEqual(result["rotation_previous_departure_delay"], 5.0)
        self.assertAlmostEqual(
            result["rotation_minutes_since_previous_arrival"], 30.0
        )
        self.assertEqual(result["rotation_history_available"], 1)
        self.assertEqual(result["_rotation_self_match"], 0)

    def test_rotation_nulls_anomalous_self_match_instead_of_leaking_target(self):
        targets = self.spark.createDataFrame(
            [(2, "REG1", datetime(2022, 1, 1, 9, 0))],
            ["ECTRL ID", "AC Registration", "prediction_cutoff_t60"],
        )
        events = self.spark.createDataFrame(
            [
                (1, "REG1", datetime(2022, 1, 1, 8, 30), 12.0, 5.0),
                # Bad source timestamps can make the target appear completed
                # before its own T-60 cutoff. Its delays must never be exposed.
                (2, "REG1", datetime(2022, 1, 1, 8, 45), 40.0, 30.0),
            ],
            [
                "ECTRL ID",
                "AC Registration",
                "ACTUAL ARRIVAL TIME",
                "Arrival_Delay_Min",
                "Departure_Delay_Min",
            ],
        )
        result = build_rotation_features(targets, events).first()
        self.assertEqual(result["_rotation_self_match"], 1)
        self.assertIsNone(result["rotation_previous_arrival_delay"])
        self.assertIsNone(result["rotation_previous_departure_delay"])
        self.assertIsNone(result["rotation_minutes_since_previous_arrival"])
        self.assertEqual(result["rotation_history_available"], 0)

    def test_standard_feature_join_keeps_one_prediction_cutoff_column(self):
        cutoff = datetime(2022, 1, 1, 9, 0)
        targets = self.spark.createDataFrame(
            [(2, "AAA", "BBB", "OP1", "REG1", cutoff)],
            [
                "ECTRL ID", "ADEP", "ADES", "AC Operator",
                "AC Registration", "prediction_cutoff_t60",
            ],
        )
        events = self.spark.createDataFrame(
            [
                (
                    1, "AAA", "BBB", "OP1", "REG1",
                    datetime(2022, 1, 1, 8, 10),
                    datetime(2022, 1, 1, 8, 30), 5.0, 8.0,
                )
            ],
            [
                "ECTRL ID", "ADEP", "ADES", "AC Operator", "AC Registration",
                "ACTUAL OFF BLOCK TIME", "ACTUAL ARRIVAL TIME",
                "Departure_Delay_Min", "Arrival_Delay_Min",
            ],
        )
        result, audit = build_standard_t60_features(
            targets, events, windows_hours=(1,)
        )
        self.assertEqual(result.columns.count("prediction_cutoff_t60"), 1)
        self.assertEqual(result.count(), 1)
        self.assertEqual(len(audit), 6)


if __name__ == "__main__":
    unittest.main()
