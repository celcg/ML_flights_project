import unittest

import pandas as pd

from src.t60_modeling import (
    MixedCategoricalRidgePreprocessor,
    delay_classification_metrics,
)


class MixedCategoricalRidgePreprocessorTests(unittest.TestCase):
    def test_one_hot_low_cardinality_and_hash_high_cardinality(self):
        train = pd.DataFrame(
            {
                "segment": ["Traditional", "Lowcost", "Traditional"],
                "airport": ["AAA", "BBB", "CCC"],
                "numeric": [1.0, None, 3.0],
            }
        )
        validation = pd.DataFrame(
            {"segment": ["Unseen"], "airport": ["ZZZ"], "numeric": [None]}
        )
        processor = MixedCategoricalRidgePreprocessor(
            ["segment"], ["airport"], ["numeric"], hash_features=16
        )
        train_matrix = processor.fit_transform(train)
        validation_matrix = processor.transform(validation)
        self.assertEqual(train_matrix.shape[0], 3)
        self.assertEqual(validation_matrix.shape[0], 1)
        self.assertEqual(train_matrix.shape[1], validation_matrix.shape[1])


class DelayClassificationMetricsTests(unittest.TestCase):
    def test_probability_predictions_report_confusion_matrix_and_accuracy(self):
        metrics = delay_classification_metrics(
            [-2.0, 10.0, 16.0, 45.0],
            [0.1, 0.7, 0.8, 0.4],
            "classifier",
            "validation",
        ).iloc[0]
        self.assertAlmostEqual(metrics["accuracy"], 0.5)
        self.assertEqual(metrics["true_negative"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["false_negative"], 1)
        self.assertEqual(metrics["true_positive"], 1)

    def test_regression_minutes_can_be_reused_as_delay_classification(self):
        metrics = delay_classification_metrics(
            [0.0, 14.0, 16.0, 60.0],
            [2.0, 20.0, 18.0, 40.0],
            "regression_threshold",
            "test",
            scores_are_probabilities=False,
        ).iloc[0]
        self.assertAlmostEqual(metrics["accuracy"], 0.75)
        self.assertEqual(metrics["decision_threshold"], 15.0)

    def test_probability_scores_outside_unit_interval_are_rejected(self):
        with self.assertRaises(ValueError):
            delay_classification_metrics(
                [0.0, 20.0], [0.2, 1.1], "classifier", "validation"
            )


if __name__ == "__main__":
    unittest.main()
