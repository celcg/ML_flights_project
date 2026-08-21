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
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def align_predictions_to_index(
    predictions: Sequence[float],
    prediction_index: Sequence,
    target_index: Sequence,
) -> np.ndarray:
    """Restore predictions made on a sorted frame to the target row order."""

    values = np.asarray(predictions)
    source_index = pd.Index(prediction_index)
    destination_index = pd.Index(target_index)
    if len(values) != len(source_index):
        raise ValueError("Prediction values and prediction_index must have equal length")
    if not source_index.is_unique or not destination_index.is_unique:
        raise ValueError("Prediction alignment requires unique row indices")
    if len(source_index) != len(destination_index) or not source_index.isin(
        destination_index
    ).all():
        raise ValueError("Prediction and target indices must contain the same rows")
    return pd.Series(values, index=source_index).reindex(destination_index).to_numpy()


def weighted_prediction_blend(
    first_predictions: Sequence[float],
    second_predictions: Sequence[float],
    first_weight: float,
) -> np.ndarray:
    """Blend two aligned regression predictions with a bounded first weight."""

    if not 0.0 <= first_weight <= 1.0:
        raise ValueError("first_weight must be between zero and one")
    first = np.asarray(first_predictions, dtype=float)
    second = np.asarray(second_predictions, dtype=float)
    if first.shape != second.shape:
        raise ValueError("The two prediction arrays must have the same shape")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("Prediction blending requires finite values")
    return first_weight * first + (1.0 - first_weight) * second


def hurdle_expected_delay(
    delay_probability: Sequence[float],
    delayed_severity_prediction: Sequence[float],
    non_delayed_reference: float,
    *,
    delay_threshold_minutes: float = 15.0,
    maximum_delay_minutes: float | None = None,
) -> np.ndarray:
    """Combine P(delay) with E[minutes | delay] into expected delay minutes."""

    probability = np.asarray(delay_probability, dtype=float)
    severity = np.asarray(delayed_severity_prediction, dtype=float)
    if probability.shape != severity.shape:
        raise ValueError("Probability and severity arrays must have the same shape")
    if not np.logical_and(probability >= 0.0, probability <= 1.0).all():
        raise ValueError("Delay probabilities must be between zero and one")
    if not np.isfinite(severity).all() or not np.isfinite(non_delayed_reference):
        raise ValueError("Hurdle predictions require finite values")
    coherent_severity = np.maximum(severity, float(delay_threshold_minutes))
    if maximum_delay_minutes is not None:
        if maximum_delay_minutes <= delay_threshold_minutes:
            raise ValueError("maximum_delay_minutes must exceed the delay threshold")
        coherent_severity = np.minimum(coherent_severity, maximum_delay_minutes)
    return (
        probability * coherent_severity
        + (1.0 - probability) * float(non_delayed_reference)
    )


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
    arrival_hour = filed_arrival.dt.hour + filed_arrival.dt.minute / 60.0
    result["scheduled_arrival_hour_sin"] = np.sin(2 * np.pi * arrival_hour / 24.0)
    result["scheduled_arrival_hour_cos"] = np.cos(2 * np.pi * arrival_hour / 24.0)
    result["Duration_Band"] = np.where(
        result["scheduled_duration_min"] > 360.0,
        "LONG_HAUL_>6H",
        "SHORT_MEDIUM_<=6H",
    )
    if "Transatlantic_Direction" in result:
        direction = result["Transatlantic_Direction"].fillna("NON_TRANSATLANTIC")
        result["duration_x_europe_to_americas"] = result["scheduled_duration_min"] * (
            direction == "EUROPE_TO_AMERICAS"
        ).astype(float)
        result["duration_x_americas_to_europe"] = result["scheduled_duration_min"] * (
            direction == "AMERICAS_TO_EUROPE"
        ).astype(float)
    return result


def haul_direction_segment_metrics(
    frame: pd.DataFrame,
    y_true: Sequence[float],
    predictions: Sequence[float],
    model: str,
    training_scope: str,
) -> pd.DataFrame:
    """Publish errors by haul band and transatlantic direction."""

    y = np.asarray(y_true, dtype=float)
    pred = np.asarray(predictions, dtype=float)
    duration = np.asarray(frame["scheduled_duration_min"], dtype=float)
    direction = frame.get(
        "Transatlantic_Direction",
        pd.Series("NON_TRANSATLANTIC", index=frame.index),
    ).fillna("NON_TRANSATLANTIC").to_numpy()
    masks = {
        "short_medium_<=6h": duration <= 360.0,
        "long_haul_>6h": duration > 360.0,
        "short_haul_<=3h": duration <= 180.0,
        "medium_haul_3_6h": (duration > 180.0) & (duration <= 360.0),
        "europe_to_americas": direction == "EUROPE_TO_AMERICAS",
        "americas_to_europe": direction == "AMERICAS_TO_EUROPE",
    }
    rows = []
    for name, mask in masks.items():
        if not mask.any():
            continue
        error = y[mask] - pred[mask]
        absolute_error = np.abs(error)
        rows.append(
            {
                "model": model,
                "training_scope": training_scope,
                "segment": name,
                "rows": int(mask.sum()),
                "MAE": float(absolute_error.mean()),
                "RMSE": float(np.sqrt(np.square(error).mean())),
                "median_absolute_error": float(np.median(absolute_error)),
                "p90_absolute_error": float(np.quantile(absolute_error, 0.9)),
            }
        )
    return pd.DataFrame(rows)


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


def delay_classification_metrics(
    y_true_minutes: Sequence[float],
    scores: Sequence[float],
    model: str,
    evaluation_scope: str,
    *,
    delay_threshold_minutes: float = 15.0,
    decision_threshold: float = 0.5,
    scores_are_probabilities: bool = True,
) -> pd.DataFrame:
    """Measure whether an arrival exceeds the operational delay threshold.

    Probability models use ``decision_threshold`` (normally 0.5). A regression
    model can also be evaluated as a classifier by passing predicted minutes and
    setting ``scores_are_probabilities=False``; in that case the operational
    delay threshold is used for the binary decision.
    """

    y_minutes = np.asarray(y_true_minutes, dtype=float)
    score_array = np.asarray(scores, dtype=float)
    if y_minutes.shape != score_array.shape:
        raise ValueError("y_true_minutes and scores must have the same shape")
    if not np.isfinite(y_minutes).all() or not np.isfinite(score_array).all():
        raise ValueError("Classification metrics require finite targets and scores")
    if scores_are_probabilities and not np.logical_and(
        score_array >= 0.0, score_array <= 1.0
    ).all():
        raise ValueError("Probability scores must be between zero and one")

    actual = y_minutes > delay_threshold_minutes
    threshold = (
        decision_threshold if scores_are_probabilities else delay_threshold_minutes
    )
    predicted = (
        score_array >= threshold if scores_are_probabilities else score_array > threshold
    )
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[False, True]).ravel()
    has_both_classes = np.unique(actual).size == 2
    return pd.DataFrame(
        [{
            "model": model,
            "evaluation_scope": evaluation_scope,
            "rows": int(actual.size),
            "delay_threshold_minutes": float(delay_threshold_minutes),
            "decision_threshold": float(threshold),
            "actual_delay_rate": float(actual.mean()),
            "predicted_delay_rate": float(predicted.mean()),
            "accuracy": float(accuracy_score(actual, predicted)),
            "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
            "precision": float(precision_score(actual, predicted, zero_division=0)),
            "recall": float(recall_score(actual, predicted, zero_division=0)),
            "specificity": float(tn / (tn + fp)) if tn + fp else np.nan,
            "f1": float(f1_score(actual, predicted, zero_division=0)),
            "roc_auc": (
                float(roc_auc_score(actual, score_array))
                if has_both_classes else np.nan
            ),
            "average_precision": (
                float(average_precision_score(actual, score_array))
                if has_both_classes else np.nan
            ),
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        }]
    )


def classification_threshold_table(
    y_true_minutes: Sequence[float],
    scores: Sequence[float],
    model: str,
    evaluation_scope: str,
    *,
    delay_threshold_minutes: float = 15.0,
    thresholds: Sequence[float] | None = None,
    false_negative_cost: float = 3.0,
    false_positive_cost: float = 1.0,
) -> pd.DataFrame:
    """Evaluate probability thresholds, including an explicit operational cost."""

    if thresholds is None:
        thresholds = np.linspace(0.05, 0.75, 71)
    rows = []
    for threshold in sorted({float(value) for value in thresholds} | {0.5}):
        current = delay_classification_metrics(
            y_true_minutes,
            scores,
            model,
            evaluation_scope,
            delay_threshold_minutes=delay_threshold_minutes,
            decision_threshold=threshold,
        ).iloc[0].to_dict()
        current["false_negative_cost"] = float(false_negative_cost)
        current["false_positive_cost"] = float(false_positive_cost)
        current["cost_per_flight"] = float(
            (
                false_negative_cost * current["false_negative"]
                + false_positive_cost * current["false_positive"]
            )
            / current["rows"]
        )
        rows.append(current)
    return pd.DataFrame(rows)


def haul_direction_classification_metrics(
    frame: pd.DataFrame,
    y_true_minutes: Sequence[float],
    scores: Sequence[float],
    model: str,
    evaluation_scope: str,
    **metric_options,
) -> pd.DataFrame:
    """Publish OTP15 classification metrics by haul and direction."""

    duration = np.asarray(frame["scheduled_duration_min"], dtype=float)
    direction = frame.get(
        "Transatlantic_Direction",
        pd.Series("NON_TRANSATLANTIC", index=frame.index),
    ).fillna("NON_TRANSATLANTIC").to_numpy()
    y = np.asarray(y_true_minutes, dtype=float)
    score_array = np.asarray(scores, dtype=float)
    masks = {
        "short_medium_<=6h": duration <= 360.0,
        "long_haul_>6h": duration > 360.0,
        "short_haul_<=3h": duration <= 180.0,
        "medium_haul_3_6h": (duration > 180.0) & (duration <= 360.0),
        "europe_to_americas": direction == "EUROPE_TO_AMERICAS",
        "americas_to_europe": direction == "AMERICAS_TO_EUROPE",
    }
    rows = []
    for segment, mask in masks.items():
        if not mask.any():
            continue
        current = delay_classification_metrics(
            y[mask], score_array[mask], model, evaluation_scope, **metric_options
        )
        current.insert(2, "segment", segment)
        rows.append(current)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


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


@dataclass
class MixedCategoricalRidgePreprocessor:
    """One-hot low-cardinality fields and hash high-cardinality fields."""

    low_cardinality_columns: Sequence[str]
    high_cardinality_columns: Sequence[str]
    numeric_columns: Sequence[str]
    hash_features: int = 1 << 15
    numeric_medians: pd.Series | None = None
    scaler: StandardScaler = field(default_factory=lambda: StandardScaler(with_mean=False))
    encoder: OneHotEncoder = field(
        default_factory=lambda: OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    )
    hasher: FeatureHasher = field(init=False)

    def __post_init__(self) -> None:
        self.low_cardinality_columns = list(self.low_cardinality_columns)
        self.high_cardinality_columns = list(self.high_cardinality_columns)
        self.numeric_columns = list(self.numeric_columns)
        self.hasher = FeatureHasher(
            n_features=self.hash_features,
            input_type="string",
            alternate_sign=True,
        )

    def _hash_tokens(self, frame: pd.DataFrame):
        categorical = frame[self.high_cardinality_columns].fillna("__MISSING__").astype(str)
        columns = self.high_cardinality_columns
        return (
            [f"{column}={value}" for column, value in zip(columns, row)]
            for row in categorical.itertuples(index=False, name=None)
        )

    def fit_transform(self, frame: pd.DataFrame):
        low = frame[self.low_cardinality_columns].fillna("__MISSING__").astype(str)
        low_matrix = self.encoder.fit_transform(low)
        high_matrix = self.hasher.transform(self._hash_tokens(frame))
        self.numeric_medians = frame[self.numeric_columns].median()
        if self.numeric_medians.isna().any():
            missing = self.numeric_medians[self.numeric_medians.isna()].index.tolist()
            raise ValueError(f"Numeric columns contain no train values: {missing}")
        numeric = frame[self.numeric_columns].fillna(self.numeric_medians).to_numpy(dtype=float)
        numeric_matrix = sparse.csr_matrix(self.scaler.fit_transform(numeric))
        return sparse.hstack([low_matrix, high_matrix, numeric_matrix], format="csr")

    def transform(self, frame: pd.DataFrame):
        if self.numeric_medians is None:
            raise RuntimeError("The preprocessor must be fitted before transform")
        low = frame[self.low_cardinality_columns].fillna("__MISSING__").astype(str)
        low_matrix = self.encoder.transform(low)
        high_matrix = self.hasher.transform(self._hash_tokens(frame))
        numeric = frame[self.numeric_columns].fillna(self.numeric_medians).to_numpy(dtype=float)
        numeric_matrix = sparse.csr_matrix(self.scaler.transform(numeric))
        return sparse.hstack([low_matrix, high_matrix, numeric_matrix], format="csr")

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
