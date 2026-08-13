import unittest

import pandas as pd

from src.t60_modeling import MixedCategoricalRidgePreprocessor


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


if __name__ == "__main__":
    unittest.main()
