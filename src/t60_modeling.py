"""Small pandas/scikit helpers for the T-60 operational experiment."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction import FeatureHasher
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


def add_schedule_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Create schedule-derived numeric features available at T-60."""

    result = frame.copy()
    filed_off = pd.to_datetime(result["FILED OFF BLOCK TIME"])
    filed_arrival = pd.to_datetime(result["FILED ARRIVAL TIME"])
    result["scheduled_duration_min"] = (
        filed_arrival - filed_off
    ).dt.total_seconds() / 60.0
    hour = filed_off.dt.hour + filed_off.dt.minute / 60.0
    day_of_week = filed_off.dt.dayofweek.astype(float)
    result["departure_hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    result["departure_hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    result["departure_dow_sin"] = np.sin(2 * np.pi * day_of_week / 7.0)
    result["departure_dow_cos"] = np.cos(2 * np.pi * day_of_week / 7.0)
    result["departure_month"] = filed_off.dt.month.astype(float)
    return result


def segment_metrics(
    y_true: Sequence[float],
    predictions: Sequence[float],
    model: str,
    training_scope: str,
) -> pd.DataFrame:
    """Return the frozen error metrics for all operational segments."""

    y = np.asarray(y_true, dtype=float)
    pred = np.asarray(predictions, dtype=float)
    absolute_error = np.abs(y - pred)
    squared_error = np.square(y - pred)
    segments = {
        "all": np.ones(len(y), dtype=bool),
        "punctual_<=15": y <= 15,
        "moderate_15_60": (y > 15) & (y <= 60),
        "severe_>60": y > 60,
        "delayed_>15": y > 15,
    }
    rows = []
    for name, mask in segments.items():
        rows.append(
            {
                "model": model,
                "training_scope": training_scope,
                "segment": name,
                "rows": int(mask.sum()),
                "MAE": float(absolute_error[mask].mean()),
                "RMSE": float(np.sqrt(squared_error[mask].mean())),
                "median_absolute_error": float(np.median(absolute_error[mask])),
                "p90_absolute_error": float(np.quantile(absolute_error[mask], 0.9)),
            }
        )
    return pd.DataFrame(rows)


def compact_score(metrics: pd.DataFrame) -> dict[str, float]:
    """Extract the global, delayed and equal-weight combined MAE."""

    indexed = metrics.set_index("segment")
    global_mae = float(indexed.loc["all", "MAE"])
    delayed_mae = float(indexed.loc["delayed_>15", "MAE"])
    return {
        "global_MAE": global_mae,
        "delayed_MAE": delayed_mae,
        "combined_MAE_score": 0.5 * (global_mae + delayed_mae),
    }


@dataclass
class HistoricalMedianBaseline:
    """Route/operator historical medians with the notebook-05 fallbacks."""

    target: str = "Arrival_Delay_Min"
    route_airline_min_rows: int = 20
    route_min_rows: int = 100
    mappings: list[tuple[list[str], pd.Series]] = field(default_factory=list)
    global_median: float | None = None

    def fit(self, frame: pd.DataFrame) -> "HistoricalMedianBaseline":
        hierarchy = [
            (["ADEP", "ADES", "AC Operator"], self.route_airline_min_rows),
            (["ADEP", "ADES"], self.route_min_rows),
            (["ADEP", "AC Operator"], self.route_airline_min_rows),
            (["ADEP"], self.route_min_rows),
        ]
        self.global_median = float(frame[self.target].median())
        self.mappings = []
        for keys, minimum in hierarchy:
            grouped = frame.groupby(keys, dropna=False)[self.target].agg(["count", "median"])
            self.mappings.append((keys, grouped.loc[grouped["count"] >= minimum, "median"]))
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.global_median is None:
            raise RuntimeError("The baseline must be fitted before predict")
        prediction = np.full(len(frame), np.nan, dtype=float)
        for keys, mapping in self.mappings:
            if len(keys) == 1:
                lookup = pd.Index(frame[keys[0]])
            else:
                lookup = pd.MultiIndex.from_frame(frame[keys])
            values = mapping.reindex(lookup).to_numpy(dtype=float)
            missing = np.isnan(prediction)
            prediction[missing] = values[missing]
        prediction[np.isnan(prediction)] = self.global_median
        return prediction


@dataclass
class HashedRidgePreprocessor:
    """Hash categorical tokens and train-only impute/scale numeric columns."""

    categorical_columns: Sequence[str]
    numeric_columns: Sequence[str]
    hash_features: int = 1 << 15
    numeric_medians: pd.Series | None = None
    scaler: StandardScaler = field(default_factory=lambda: StandardScaler(with_mean=False))
    hasher: FeatureHasher = field(init=False)

    def __post_init__(self) -> None:
        self.categorical_columns = list(self.categorical_columns)
        self.numeric_columns = list(self.numeric_columns)
        self.hasher = FeatureHasher(
            n_features=self.hash_features,
            input_type="string",
            alternate_sign=True,
        )

    def _categorical_tokens(self, frame: pd.DataFrame):
        categorical = frame[self.categorical_columns].fillna("__MISSING__").astype(str)
        columns = self.categorical_columns
        return (
            [f"{column}={value}" for column, value in zip(columns, row)]
            for row in categorical.itertuples(index=False, name=None)
        )

    def fit_transform(self, frame: pd.DataFrame):
        self.numeric_medians = frame[self.numeric_columns].median()
        if self.numeric_medians.isna().any():
            missing = self.numeric_medians[self.numeric_medians.isna()].index.tolist()
            raise ValueError(f"Numeric columns contain no train values: {missing}")
        categorical_matrix = self.hasher.transform(self._categorical_tokens(frame))
        numeric = frame[self.numeric_columns].fillna(self.numeric_medians).to_numpy(dtype=float)
        numeric_matrix = sparse.csr_matrix(self.scaler.fit_transform(numeric))
        return sparse.hstack([categorical_matrix, numeric_matrix], format="csr")

    def transform(self, frame: pd.DataFrame):
        if self.numeric_medians is None:
            raise RuntimeError("The preprocessor must be fitted before transform")
        categorical_matrix = self.hasher.transform(self._categorical_tokens(frame))
        numeric = frame[self.numeric_columns].fillna(self.numeric_medians).to_numpy(dtype=float)
        numeric_matrix = sparse.csr_matrix(self.scaler.transform(numeric))
        return sparse.hstack([categorical_matrix, numeric_matrix], format="csr")


def fit_ridge(
    train: pd.DataFrame,
    evaluate: pd.DataFrame,
    *,
    categorical_columns: Sequence[str],
    numeric_columns: Sequence[str],
    target: str,
    alpha: float,
) -> tuple[Ridge, HashedRidgePreprocessor, np.ndarray]:
    """Fit a memory-bounded hashed ridge model and return evaluation predictions."""

    preprocessor = HashedRidgePreprocessor(categorical_columns, numeric_columns)
    train_matrix = preprocessor.fit_transform(train)
    evaluate_matrix = preprocessor.transform(evaluate)
    model = Ridge(alpha=alpha, solver="lsqr")
    model.fit(train_matrix, train[target].to_numpy(dtype=float))
    predictions = model.predict(evaluate_matrix)
    return model, preprocessor, predictions


def ensemble_grid(
    y_true: Sequence[float],
    component_predictions: dict[str, Sequence[float]],
    *,
    step: float = 0.1,
    global_guardrail_minutes: float = 0.25,
) -> tuple[pd.DataFrame, pd.Series]:
    """Select non-negative three-model weights on tuning data only."""

    names = list(component_predictions)
    if len(names) != 3:
        raise ValueError("Exactly three component predictions are required")
    arrays = {name: np.asarray(component_predictions[name], dtype=float) for name in names}
    single_scores = [
        compact_score(segment_metrics(y_true, arrays[name], name, "internal_tuning"))
        for name in names
    ]
    global_limit = min(score["global_MAE"] for score in single_scores) + global_guardrail_minutes
    units = int(round(1.0 / step))
    rows = []
    for first, second in product(range(units + 1), repeat=2):
        if first + second > units:
            continue
        weights = np.array([first, second, units - first - second], dtype=float) / units
        prediction = sum(weights[index] * arrays[name] for index, name in enumerate(names))
        score = compact_score(
            segment_metrics(y_true, prediction, "ensemble", "internal_tuning")
        )
        rows.append(
            {
                **{f"weight_{name}": weights[index] for index, name in enumerate(names)},
                **score,
                "passes_global_guardrail": score["global_MAE"] <= global_limit,
                "global_MAE_limit": global_limit,
            }
        )
    results = pd.DataFrame(rows).sort_values(
        ["passes_global_guardrail", "combined_MAE_score", "global_MAE"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    return results, results.iloc[0]
