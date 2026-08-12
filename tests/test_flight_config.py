import unittest

from src.flight_config import features_for_horizon, features_for_task


class FeatureAvailabilityTests(unittest.TestCase):
    def test_pre_departure_excludes_realised_values(self):
        features = features_for_horizon("pre_departure")
        self.assertNotIn("Departure_Delay_Min", features)
        self.assertNotIn("Actual Distance Flown (nm)", features)
        self.assertNotIn("ACTUAL ARRIVAL TIME", features)
        self.assertNotIn("ICAO Flight Type", features)

    def test_post_off_block_allows_departure_delay(self):
        features = features_for_horizon("post_off_block")
        self.assertIn("Departure_Delay_Min", features)
        self.assertIn("ACTUAL OFF BLOCK TIME", features)
        self.assertNotIn("Actual Distance Flown (nm)", features)

    def test_departure_delay_cannot_be_a_post_off_block_target(self):
        with self.assertRaises(ValueError):
            features_for_task("Departure_Delay_Min", "post_off_block")

    def test_arrival_delay_supports_both_horizons(self):
        self.assertNotIn(
            "Departure_Delay_Min",
            features_for_task("Arrival_Delay_Min", "pre_departure"),
        )
        self.assertIn(
            "Departure_Delay_Min",
            features_for_task("Arrival_Delay_Min", "post_off_block"),
        )


if __name__ == "__main__":
    unittest.main()
