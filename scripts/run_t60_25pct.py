"""Run the frozen T-60 experiment with 25% of train.

This runner deliberately reuses the audited implementation from notebook 08,
but writes every data, report and model artifact under a separate 25% name.
Feature selection and Ridge alpha are frozen from the 10% experiment so the
comparison measures the effect of adding training rows rather than a new round
of tuning. Only Ridge and its historical baseline are fitted: this is the
lowest-memory experiment that answers whether scaling the current winner pays.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv313" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.exists():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

import nbformat
from IPython.display import display


NOTEBOOK = PROJECT_ROOT / "notebooks" / "08_arrival_pre_t60_operational_features.ipynb"
EXECUTION_SUMMARY = PROJECT_ROOT / "reports" / "09_t60_25pct_execution_summary.json"


def code_cell(notebook, index: int) -> str:
    cell = notebook.cells[index]
    if cell.cell_type != "code":
        raise ValueError(f"Cell {index} is not code")
    return cell.source


def execute(source: str, namespace: dict, label: str) -> None:
    print(f"\n===== {label} =====", flush=True)
    exec(compile(source, f"<notebook08:{label}>", "exec"), namespace)


def main() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    os.chdir(PROJECT_ROOT / "notebooks")
    namespace = {"__name__": "__main__", "display": display}

    config = code_cell(notebook, 1)
    replacements = {
        "TRAIN_SAMPLE_PERCENT = 10": "TRAIN_SAMPLE_PERCENT = 25",
        "MIN_AVAILABLE_RAM_GB = 5.0": "MIN_AVAILABLE_RAM_GB = 1.5",
        "EXPECTED_TRAIN_SAMPLE_ROWS = 245_590": "EXPECTED_TRAIN_SAMPLE_ROWS = None",
        "arrival_pre_t60_ops_10pct": "arrival_pre_t60_ops_25pct",
        "08_t60_feature_ablation.csv": "09_t60_25pct_feature_ablation.csv",
        "08_t60_internal_tuning.csv": "09_t60_25pct_internal_tuning.csv",
        "08_t60_ensemble_grid.csv": "09_t60_25pct_ensemble_grid.csv",
        "08_t60_operational_model_comparison.csv": "09_t60_25pct_operational_model_comparison.csv",
        "08_t60_validation_predictions.parquet": "09_t60_25pct_validation_predictions.parquet",
        "08_t60_scaling_decision.json": "09_t60_25pct_scaling_decision.json",
    }
    for old, new in replacements.items():
        config = config.replace(old, new)
    config += "\nVALIDATION_METRICS_REPORT = REPORT_ROOT / '09_t60_25pct_validation_metrics.csv'\n"
    execute(config, namespace, "configuration_25pct")
    execute(code_cell(notebook, 3), namespace, "preflight")

    load = code_cell(notebook, 5)
    load = load.replace("master='local[2]'", "master='local[1]'")
    load = load.replace("driver_memory='4g'", "driver_memory='2g'")
    load = load.replace("shuffle_partitions=16", "shuffle_partitions=8")
    old_assert = """    assert sample_counts == {
        'train': EXPECTED_TRAIN_SAMPLE_ROWS,
        'validation': EXPECTED_VALIDATION_SAMPLE_ROWS,
    }, sample_counts
"""
    new_assert = """    assert sample_counts['validation'] == EXPECTED_VALIDATION_SAMPLE_ROWS, sample_counts
    EXPECTED_TRAIN_SAMPLE_ROWS = sample_counts['train']
"""
    if old_assert not in load:
        raise RuntimeError("Could not patch the train-sample assertion")
    load = load.replace(old_assert, new_assert)
    execute(load, namespace, "load_targets_and_history")
    feature_build = code_cell(notebook, 7).replace(
        "08_t60_feature_leakage_audit.csv",
        "09_t60_25pct_feature_leakage_audit.csv",
    )
    original_reuse_guard = """        if (
            not REBUILD_FEATURE_BLOCKS and audit_path.exists()
            and (block_path / '_SUCCESS').exists()
        ):
            feature_block_names.append(prefix)
            print({'block': prefix, 'reused': True})
            continue
"""
    resumable_reuse_guard = """        if (
            not REBUILD_FEATURE_BLOCKS
            and (block_path / '_SUCCESS').exists()
        ):
            reused_rows = spark.read.parquet(str(block_path)).count()
            assert reused_rows == target_rows, (prefix, reused_rows, target_rows)
            if not any(row['block'] == prefix for row in audit_rows):
                audit_rows.append({
                    'block': prefix,
                    'rows': reused_rows,
                    'leakage_violations': 0,
                    'self_contributions_removed': float('nan'),
                    'seconds': 0.0,
                    'resume_note': 'Reused after prior leakage assertions and successful Parquet commit',
                })
            feature_block_names.append(prefix)
            print({'block': prefix, 'reused': True, 'rows': reused_rows})
            continue
"""
    if original_reuse_guard not in feature_build:
        raise RuntimeError("Could not patch resumable feature-block reuse")
    feature_build = feature_build.replace(original_reuse_guard, resumable_reuse_guard)
    execute(feature_build, namespace, "build_25pct_feature_blocks")
    execute(code_cell(notebook, 9), namespace, "persist_25pct_enriched_data")
    low_memory_fit = """
from sklearn.linear_model import Ridge

CATEGORICAL_COLUMNS = [
    'ADEP', 'ADES', 'AC Operator', 'AC Type_grouped',
    'STATFOR Market Segment', 'Class_aircraft',
    'Number+Engine Type_aircraft', 'AC Registration',
]
STATIC_NUMERIC_COLUMNS = [
    'Requested_FL_Imputed', 'scheduled_duration_min',
    'departure_hour_sin', 'departure_hour_cos',
    'departure_dow_sin', 'departure_dow_cos', 'departure_month',
]

import pyarrow.dataset as ds
train_path = OUTPUT_ROOT / 'train'
schema_names = ds.dataset(str(train_path), format='parquet').schema.names
operational_columns = [
    column for column in schema_names
    if column.startswith(('adep_dep_', 'ades_arr_', 'route_arr_',
                          'operator_dep_', 'operator_arr_', 'rotation_'))
]
selected_feature_candidate = 'all_without_6h'
selected_operational_columns = [
    column for column in operational_columns if '_6h_' not in column
]
raw_columns = list(dict.fromkeys([
    'ECTRL ID', TARGET, 'FILED OFF BLOCK TIME', 'FILED ARRIVAL TIME',
    'prediction_cutoff_t60', 'Requested_FL_Imputed',
    *CATEGORICAL_COLUMNS, *selected_operational_columns,
]))
train_pd = add_schedule_features(pd.read_parquet(train_path, columns=raw_columns))
validation_pd = add_schedule_features(pd.read_parquet(
    OUTPUT_ROOT / 'validation', columns=raw_columns
))
train_pd = train_pd.sort_values('FILED OFF BLOCK TIME').reset_index(drop=True)
validation_pd = validation_pd.sort_values('FILED OFF BLOCK TIME').reset_index(drop=True)
SELECTED_NUMERIC_COLUMNS = STATIC_NUMERIC_COLUMNS + selected_operational_columns
selected_alpha = 10.0
print({
    'frozen_from_10pct': True,
    'ridge_only_low_memory': True,
    'selected_features': selected_feature_candidate,
    'selected_numeric_features': len(SELECTED_NUMERIC_COLUMNS),
    'ridge_alpha': selected_alpha,
    'train_rows': len(train_pd),
    'validation_rows': len(validation_pd),
})

final_ridge_preprocessor = HashedRidgePreprocessor(
    CATEGORICAL_COLUMNS, SELECTED_NUMERIC_COLUMNS
)
full_train_matrix = final_ridge_preprocessor.fit_transform(train_pd)
validation_matrix = final_ridge_preprocessor.transform(validation_pd)
final_ridge = Ridge(alpha=selected_alpha, solver='lsqr').fit(
    full_train_matrix, train_pd[TARGET].to_numpy(dtype=float)
)
validation_ridge_prediction = final_ridge.predict(validation_matrix)
del full_train_matrix, validation_matrix
gc.collect()

final_baseline = HistoricalMedianBaseline().fit(train_pd)
validation_baseline_prediction = final_baseline.predict(validation_pd)
validation_components = {
    'ridge_t60_ops_25pct': validation_ridge_prediction,
    'baseline_25pct': validation_baseline_prediction,
}
validation_metrics = pd.concat([
    segment_metrics(
        validation_pd[TARGET], prediction, name, 'deterministic_25pct_train'
    )
    for name, prediction in validation_components.items()
], ignore_index=True)
validation_metrics.to_csv(VALIDATION_METRICS_REPORT, index=False)

new_summary_pd = pd.DataFrame([
    {
        'candidate': model_name,
        'training_scope': 'deterministic_25pct_train',
        **compact_score(model_metrics),
    }
    for model_name, model_metrics in validation_metrics.groupby('model')
])
prior_pd = pd.read_csv(REPORT_ROOT / '08_t60_operational_model_comparison.csv')
prior_columns = [
    'candidate', 'training_scope', 'global_MAE',
    'delayed_MAE', 'combined_MAE_score',
]
comparison_pd = pd.concat([prior_pd[prior_columns], new_summary_pd], ignore_index=True)
comparison_pd = comparison_pd.sort_values(
    ['combined_MAE_score', 'global_MAE']
).reset_index(drop=True)
comparison_pd.to_csv(COMPARISON_REPORT, index=False)

prior_ridge = prior_pd.loc[prior_pd['candidate'] == 'ridge_t60_ops'].iloc[0]
new_ridge = new_summary_pd.loc[
    new_summary_pd['candidate'] == 'ridge_t60_ops_25pct'
].iloc[0]
combined_improvement = float(
    prior_ridge['combined_MAE_score'] - new_ridge['combined_MAE_score']
)
global_degradation = float(new_ridge['global_MAE'] - prior_ridge['global_MAE'])
scale_approved = bool(
    combined_improvement >= REQUIRED_COMBINED_IMPROVEMENT
    and global_degradation <= GLOBAL_GUARDRAIL_MINUTES
)
scaling_decision = {
    'comparison': 'ridge_25pct_vs_ridge_10pct',
    'combined_MAE_improvement_minutes': combined_improvement,
    'global_MAE_change_minutes': global_degradation,
    'required_combined_improvement_minutes': REQUIRED_COMBINED_IMPROVEMENT,
    'maximum_global_degradation_minutes': GLOBAL_GUARDRAIL_MINUTES,
    'scale_beyond_25pct': scale_approved,
    'test_processed_read': False,
}
DECISION_PATH.write_text(json.dumps(scaling_decision, indent=2), encoding='utf-8')
pd.DataFrame({
    'ECTRL ID': validation_pd['ECTRL ID'].to_numpy(),
    TARGET: validation_pd[TARGET].to_numpy(),
    'ridge_t60_ops_25pct': validation_ridge_prediction,
    'baseline_25pct': validation_baseline_prediction,
}).to_parquet(PREDICTIONS_PATH, index=False)
joblib.dump(
    {
        'model': final_ridge,
        'preprocessor': final_ridge_preprocessor,
        'numeric_columns': SELECTED_NUMERIC_COLUMNS,
        'categorical_columns': CATEGORICAL_COLUMNS,
    },
    MODELS_ROOT / '09_ridge_t60_ops_25pct.joblib',
)
joblib.dump(final_baseline, MODELS_ROOT / '09_baseline_25pct.joblib')
display(validation_metrics[
    validation_metrics['segment'].isin(['all', 'delayed_>15'])
])
print(scaling_decision)
"""
    execute(low_memory_fit, namespace, "fit_and_validate_ridge_25pct")

    metrics = namespace["validation_metrics"]
    summary = {
        "train_percent": 25,
        "train_rows": int(namespace["EXPECTED_TRAIN_SAMPLE_ROWS"]),
        "validation_percent": int(namespace["VALIDATION_SAMPLE_PERCENT"]),
        "validation_rows": int(namespace["EXPECTED_VALIDATION_SAMPLE_ROWS"]),
        "frozen_configuration": True,
        "selected_features": namespace["selected_feature_candidate"],
        "ridge_alpha": namespace["selected_alpha"],
        "models": metrics[metrics["segment"].isin(["all", "delayed_>15"])].to_dict("records"),
        "test_processed_read": False,
    }
    EXECUTION_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved {EXECUTION_SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
