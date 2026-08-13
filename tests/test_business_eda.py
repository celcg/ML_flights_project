from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.business_eda import (
    BusinessAnalysisConfig,
    benjamini_hochberg,
    airport_performance,
    development_flight_paths,
    executive_route_views,
    grouped_performance,
    hypothesis_test_catalog,
    overall_kpis,
    operator_performance,
    prepare_business_flights,
    plot_departure_arrival_recovery,
    plot_airport_reliability_rankings,
    plot_airport_volume_reliability,
    plot_route_volume_reliability,
    plot_top_route_comparison,
    route_performance,
    route_threshold_sensitivity,
    two_proportion_z_test,
    wilson_interval,
)


def raw_flights() -> pd.DataFrame:
    rows = [
        # On-time arrival after a delayed departure: ten minutes recovered.
        (1, "AAA", "BBB", "01-12-2022 10:00:00", "01-12-2022 12:00:00", "01-12-2022 10:20:00", "01-12-2022 12:10:00", "A320", "OP1", "S", "Traditional Scheduled", 300, 500),
        # Arrival delayed by more than 15 minutes.
        (2, "AAA", "BBB", "02-12-2022 10:00:00", "02-12-2022 12:00:00", "02-12-2022 10:30:00", "02-12-2022 12:25:00", "A320", "OP1", "S", "Traditional Scheduled", 300, 500),
        # A second route in an earlier development period.
        (3, "BBB", "CCC", "03-09-2022 08:00:00", "03-09-2022 09:00:00", "03-09-2022 08:00:00", "03-09-2022 09:00:00", "B738", "OP2", "S", "Lowcost", 250, 300),
        # Non-scheduled traffic must be excluded.
        (4, "AAA", "BBB", "04-12-2022 10:00:00", "04-12-2022 12:00:00", "04-12-2022 10:50:00", "04-12-2022 13:00:00", "A320", "OP1", "N", "Other", 300, 500),
        # March 2023 is the blind test and must never enter this analysis.
        (5, "AAA", "BBB", "01-03-2023 10:00:00", "01-03-2023 12:00:00", "01-03-2023 10:40:00", "01-03-2023 13:00:00", "A320", "OP1", "S", "Traditional Scheduled", 300, 500),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "ECTRL ID",
            "ADEP",
            "ADES",
            "FILED OFF BLOCK TIME",
            "FILED ARRIVAL TIME",
            "ACTUAL OFF BLOCK TIME",
            "ACTUAL ARRIVAL TIME",
            "AC Type",
            "AC Operator",
            "ICAO Flight Type",
            "STATFOR Market Segment",
            "Requested FL",
            "Actual Distance Flown (nm)",
        ],
    )


class BusinessEdaTests(unittest.TestCase):
    def setUp(self):
        self.config = BusinessAnalysisConfig(
            executive_min_route_flights=2,
            executive_min_route_periods=1,
            route_volume_candidates=(1, 2),
            period_candidates=(1,),
            top_n=5,
            airport_plot_min_flights=1,
        )
        self.flights = prepare_business_flights(raw_flights(), self.config)

    def test_scope_excludes_non_scheduled_and_blind_test(self):
        self.assertEqual(set(self.flights["ECTRL ID"]), {1, 2, 3})
        self.assertTrue(self.flights["FILED OFF BLOCK TIME"].lt("2023-01-01").all())
        self.assertTrue(self.flights["route"].isin(["AAA → BBB", "BBB → CCC"]).all())

    def test_blind_test_file_is_excluded_before_reading(self):
        paths = [
            "Flights_20221201_20221231.csv.gz",
            "Flights_20230301_20230331.csv.gz",
        ]
        selected = development_flight_paths(paths, self.config)
        self.assertEqual([path.name for path in selected], ["Flights_20221201_20221231.csv.gz"])

    def test_explicit_reporting_end_can_include_model_holdout(self):
        config = BusinessAnalysisConfig(analysis_end_exclusive="2023-07-01")
        paths = [
            "Flights_20221201_20221231.csv.gz",
            "Flights_20230301_20230331.csv.gz",
            "Flights_20230601_20230630.csv.gz",
        ]
        self.assertEqual(len(development_flight_paths(paths, config)), 3)

    def test_delay_and_recovery_features(self):
        first = self.flights.set_index("ECTRL ID").loc[1]
        second = self.flights.set_index("ECTRL ID").loc[2]
        self.assertAlmostEqual(first["Departure_Delay_Min"], 20.0)
        self.assertAlmostEqual(first["Arrival_Delay_Min"], 10.0)
        self.assertAlmostEqual(first["recovery_minutes"], 10.0)
        self.assertEqual(first["recovered_to_otp15"], 1)
        self.assertEqual(second["arrival_delayed_15"], 1)

    def test_network_and_route_metrics_use_correct_denominators(self):
        kpis = overall_kpis(self.flights, self.config)
        self.assertEqual(kpis["flights"], 3)
        self.assertAlmostEqual(kpis["arrival_otp15_pct"], 200 / 3)
        routes = route_performance(self.flights, self.config)
        aaa_bbb = routes.set_index("route").loc["AAA → BBB"]
        self.assertEqual(aaa_bbb["flights"], 2)
        self.assertAlmostEqual(aaa_bbb["arrival_delayed_15_pct"], 50.0)
        self.assertAlmostEqual(aaa_bbb["recovered_to_otp15_pct"], 50.0)

    def test_threshold_sensitivity_and_executive_views(self):
        routes = route_performance(self.flights, self.config)
        sensitivity = route_threshold_sensitivity(routes, self.config)
        at_two = sensitivity.loc[sensitivity["minimum_flights"].eq(2)].iloc[0]
        self.assertEqual(at_two["eligible_routes"], 1)
        views = executive_route_views(routes, 60.0, self.config)
        self.assertEqual(len(views["eligible"]), 1)

    def test_statistical_helpers(self):
        low, high = wilson_interval(80, 100)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)
        comparison = two_proportion_z_test(80, 100, 60, 100)
        self.assertAlmostEqual(comparison["difference_percentage_points"], 20.0)
        adjusted = benjamini_hochberg([0.01, 0.04, 0.03])
        self.assertTrue(np.all(adjusted >= np.array([0.01, 0.04, 0.03])))
        self.assertTrue(np.all(adjusted <= 1))

    def test_departure_arrival_plot_accepts_dataframe_quantiles(self):
        figure = plot_departure_arrival_recovery(self.flights)
        self.assertEqual(len(figure.axes), 2)  # main plot plus colour bar

    def test_airport_performance_and_plots_separate_origin_and_destination(self):
        origins = airport_performance(self.flights, "origin", self.config)
        destinations = airport_performance(self.flights, "destination", self.config)
        self.assertIn("AAA", set(origins["airport"].astype(str)))
        self.assertIn("BBB", set(destinations["airport"].astype(str)))
        self.assertEqual(len(plot_airport_volume_reliability(origins, "origin", 70, self.config).axes), 2)
        self.assertEqual(len(plot_airport_reliability_rankings(destinations, "destination", self.config).axes), 2)

    def test_airport_ranking_plot_accepts_perfect_otp15(self):
        airports = pd.DataFrame(
            {
                "airport": ["PERF", "MIXD"],
                "flights": [35, 35],
                "arrival_otp15_pct": [100.0, 80.0],
                "arrival_otp15_ci_low_pct": [90.109901, 64.1],
                "arrival_otp15_ci_high_pct": [100.00000000000001, 90.0],
            }
        )
        figure = plot_airport_reliability_rankings(airports, "origin", self.config)
        self.assertEqual(len(figure.axes), 2)

    def test_operator_performance_returns_breadth_and_concentration(self):
        operators = operator_performance(self.flights, self.config)
        self.assertIsInstance(operators, pd.DataFrame)
        self.assertIn("routes", operators.columns)
        self.assertIn("route_concentration_hhi", operators.columns)

    def test_grouped_indicator_counts_do_not_overflow_int8(self):
        repeated = pd.concat([self.flights.iloc[[1]]] * 300, ignore_index=True)
        repeated["ECTRL ID"] = np.arange(300)
        repeated["Arrival_Delay_Min"] = 45.0
        repeated["arrival_otp15"] = np.int8(0)
        repeated["arrival_delayed_15"] = np.int8(1)
        repeated["arrival_delayed_30"] = np.int8(1)
        repeated["arrival_delayed_60"] = np.int8(0)
        repeated["recovered_to_otp15"] = np.int8(0)
        repeated["worsened_after_departure"] = np.int8(1)

        metrics = grouped_performance(repeated, "ADEP", self.config).iloc[0]

        self.assertEqual(metrics["arrival_delayed_30_count"], 300)
        self.assertEqual(metrics["arrival_delayed_30_pct"], 100.0)
        self.assertEqual(metrics["worsened_count"], 300)

    def test_route_plots_exclude_singleton_routes(self):
        routes = pd.DataFrame(
            {
                "route": ["ONE → TWO", "AAA → BBB"],
                "flights": [1, 5],
                "periods_active": [1, 3],
                "arrival_otp15_pct": [0.0, 80.0],
                "arrival_delay_p90": [100.0, 20.0],
                "arrival_delayed_15_pct": [100.0, 20.0],
                "arrival_delayed_30_pct": [100.0, 10.0],
            }
        )
        config = BusinessAnalysisConfig(
            route_plot_min_flights=2,
            executive_min_route_flights=2,
            executive_min_route_periods=1,
            top_n=5,
        )
        top_figure = plot_top_route_comparison(routes, config)
        labels = [label.get_text() for label in top_figure.axes[0].get_yticklabels()]
        self.assertNotIn("ONE → TWO", labels)
        volume_figure = plot_route_volume_reliability(routes, 75.0, config)
        offsets = volume_figure.axes[0].collections[0].get_offsets()
        self.assertEqual(len(offsets), 1)

    def test_hypothesis_catalog_makes_selection_explicit(self):
        catalog = hypothesis_test_catalog()
        self.assertEqual(len(catalog), 10)
        self.assertEqual(set(catalog.loc[catalog["recommendation"].eq("Core report"), "test_id"]), {"H01", "H02", "H03"})


if __name__ == "__main__":
    unittest.main()
