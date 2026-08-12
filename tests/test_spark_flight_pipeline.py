import math
import unittest

try:
    from pyspark.sql import SparkSession

    from src.flight_config import DataQualityConfig, FeatureConfig
    from src.spark_flight_pipeline import (
        FlightValueTransformer,
        apply_aviation_rules,
        calculate_delays,
        create_spark,
        select_available_features,
    )

    PYSPARK_AVAILABLE = True
except Exception as exc:  # PySpark may also fail on an unsupported Python/runtime pair.
    PYSPARK_AVAILABLE = False
    SPARK_IMPORT_ERROR = str(exc)


@unittest.skipUnless(
    PYSPARK_AVAILABLE,
    f"PySpark runtime is unavailable: {globals().get('SPARK_IMPORT_ERROR', 'not installed')}",
)
class SparkPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = create_spark("flight-pipeline-tests", master="local[1]")
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_delay_calculation_and_minimum_rule(self):
        rows = [
            (
                "01-12-2021 10:00:00",
                "01-12-2021 12:00:00",
                "01-12-2021 10:15:00",
                "01-12-2021 12:30:00",
                300.0,
                500.0,
                42.0,
                2.0,
                43.0,
                3.0,
            ),
            (
                "01-12-2021 10:00:00",
                "01-12-2021 12:00:00",
                "01-12-2021 07:00:00",
                "01-12-2021 09:00:00",
                300.0,
                500.0,
                42.0,
                2.0,
                43.0,
                3.0,
            ),
        ]
        columns = [
            "FILED OFF BLOCK TIME",
            "FILED ARRIVAL TIME",
            "ACTUAL OFF BLOCK TIME",
            "ACTUAL ARRIVAL TIME",
            "Requested FL",
            "Actual Distance Flown (nm)",
            "ADEP Latitude",
            "ADEP Longitude",
            "ADES Latitude",
            "ADES Longitude",
        ]
        frame = calculate_delays(self.spark.createDataFrame(rows, columns))
        cleaned = apply_aviation_rules(frame, DataQualityConfig())
        result = cleaned.select("Departure_Delay_Min", "Arrival_Delay_Min").collect()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Departure_Delay_Min"], 15.0)
        self.assertEqual(result[0]["Arrival_Delay_Min"], 30.0)

    def test_optional_transforms_can_be_disabled_or_enabled(self):
        frame = self.spark.createDataFrame(
            [(9.0, 120.0, -5.0, 10.0)],
            [
                "Requested FL",
                "Scheduled_Duration_Min",
                "Departure_Delay_Min",
                "Arrival_Delay_Min",
            ],
        )
        unchanged = FlightValueTransformer().transform(frame)
        self.assertNotIn("Distance_Log1p", unchanged.columns)
        self.assertNotIn("Arrival_Delay_YJ", unchanged.columns)

        transformed = FlightValueTransformer(
            applyLog=True,
            applyYeoJohnson=True,
            lambdaRequestedFlightLevel=1.0,
            lambdaScheduledDuration=1.0,
        ).transform(frame)
        self.assertAlmostEqual(
            transformed.first()["Requested_FL_Log1p"], math.log1p(9.0)
        )
        self.assertAlmostEqual(transformed.first()["Requested_FL_YJ"], 9.0)
        self.assertEqual(transformed.first()["Arrival_Delay_Min"], 10.0)
        self.assertNotIn("Arrival_Delay_YJ", transformed.columns)

    def test_regular_commercial_scope_keeps_only_scheduled_flights(self):
        frame = self.spark.createDataFrame(
            [("S",), ("N",)], ["ICAO Flight Type"]
        )
        result = apply_aviation_rules(
            frame, DataQualityConfig(regular_commercial_only=True)
        )
        self.assertEqual([row[0] for row in result.collect()], ["S"])

    def test_horizon_gate_removes_leakage(self):
        frame = self.spark.createDataFrame(
            [(1, "AAA", "BBB", 30.0, 100.0)],
            [
                "ECTRL ID",
                "ADEP",
                "ADES",
                "Departure_Delay_Min",
                "Actual Distance Flown (nm)",
            ],
        )
        selected = select_available_features(
            frame, FeatureConfig(prediction_horizon="pre_departure")
        )
        self.assertNotIn("Departure_Delay_Min", selected.columns)
        self.assertNotIn("Actual Distance Flown (nm)", selected.columns)


if __name__ == "__main__":
    unittest.main()
