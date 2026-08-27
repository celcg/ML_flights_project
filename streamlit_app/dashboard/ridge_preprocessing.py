"""Deterministic preprocessing for the safely persisted Ridge artifact."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction import FeatureHasher


RIDGE_ARTIFACT_FORMAT_VERSION = 1


def transform_ridge_features(artifact: dict, frame: pd.DataFrame):
    """Reproduce the trained mixed categorical/numeric feature matrix."""

    _validate_artifact(artifact)
    low_columns = artifact["low_cardinality_columns"]
    high_columns = artifact["high_cardinality_columns"]
    numeric_columns = artifact["preprocessor_numeric_columns"]

    low = frame[low_columns].fillna("__MISSING__").astype(str)
    low_matrix = artifact["encoder"].transform(low)

    hasher = FeatureHasher(
        n_features=int(artifact["hash_features"]),
        input_type="string",
        alternate_sign=True,
    )
    high_matrix = hasher.transform(_hash_tokens(frame, high_columns))

    medians = pd.Series(
        artifact["numeric_medians"], index=numeric_columns, dtype=float
    )
    numeric = frame[numeric_columns].fillna(medians).to_numpy(dtype=float)
    numeric_matrix = sparse.csr_matrix(artifact["scaler"].transform(numeric))
    return sparse.hstack([low_matrix, high_matrix, numeric_matrix], format="csr")


def _hash_tokens(
    frame: pd.DataFrame,
    columns: list[str],
) -> Iterable[list[str]]:
    categorical = frame[columns].fillna("__MISSING__").astype(str)
    return (
        [f"{column}={value}" for column, value in zip(columns, row)]
        for row in categorical.itertuples(index=False, name=None)
    )


def _validate_artifact(artifact: dict) -> None:
    version = artifact.get("artifact_format_version")
    if version != RIDGE_ARTIFACT_FORMAT_VERSION:
        raise ValueError(
            "Unsupported Ridge artifact format: "
            f"expected {RIDGE_ARTIFACT_FORMAT_VERSION}, received {version}."
        )
