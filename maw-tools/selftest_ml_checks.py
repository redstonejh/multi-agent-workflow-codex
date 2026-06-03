#!/usr/bin/env python3
"""Self-test the stdlib ML validation checks."""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ML_CHECKS = ROOT / "examples" / "ml_problems" / "ml_checks.py"
CLASSIFICATION_RUN = ROOT / "examples" / "ml_problems" / "classification" / "run.py"


def load_ml_checks():
    spec = importlib.util.spec_from_file_location("ml_checks_selftest_target", ML_CHECKS)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ml_checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_json(command: list[str]) -> tuple[int, dict, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "stdout": proc.stdout}
    return proc.returncode, data, proc.stdout, proc.stderr


def main() -> int:
    checks = []
    ml = load_ml_checks()

    ece = ml.expected_calibration_error([0.0, 0.5, 1.0], [False, True, True], bins=2)
    checks.append(
        {
            "name": "ece_bin_ties_are_deterministic",
            "passed": ece["passed"] is True and math.isclose(ece["ece"], 0.166667, abs_tol=0.000001) and [item["count"] for item in ece["bin_summaries"]] == [1, 2],
            "result": ece,
        }
    )

    single_seed = ml.multi_seed_check([0.82])
    checks.append(
        {
            "name": "single_seed_rejected_by_default",
            "passed": single_seed["passed"] is False and "Need at least 2 seeds, got 1" in single_seed["reasons"],
            "result": single_seed,
        }
    )

    negative_calibration = ml.calibration_check({"confidences": [0.8], "correct": [True]}, max_ece=-0.1)
    checks.append(
        {
            "name": "negative_calibration_threshold_rejected",
            "passed": negative_calibration["passed"] is False and negative_calibration["status"] == "invalid",
            "result": negative_calibration,
        }
    )

    nonfinite_quality = ml.data_quality_check({"row_count": 10, "missing_values": {}, "duplicate_rows": 0}, max_missing_rate=math.inf)
    checks.append(
        {
            "name": "nonfinite_data_quality_threshold_rejected",
            "passed": nonfinite_quality["passed"] is False and nonfinite_quality["status"] == "invalid",
            "result": nonfinite_quality,
        }
    )

    missing_fit = ml.fit_diagnosis("classification", {"train_score": 0.9}, {})
    checks.append(
        {
            "name": "missing_fit_metrics_fail_clearly",
            "passed": missing_fit["passed"] is False and missing_fit["status"] == "invalid" and "validation_score" in missing_fit["missing_metrics"],
            "result": missing_fit,
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        clean = tmp / "clean.json"
        run_proc = subprocess.run([sys.executable, str(CLASSIFICATION_RUN), "--output", str(clean)], capture_output=True, text=True)
        output = tmp / "leakage-audit.json"
        validate_code, validate_data, validate_stdout, validate_stderr = run_json([sys.executable, str(ML_CHECKS), "validate", str(clean), "--output", str(output)])
        checks.append(
            {
                "name": "validate_writes_leakage_artifact",
                "passed": run_proc.returncode == 0 and validate_code == 0 and output.is_file() and json.loads(output.read_text(encoding="utf-8"))["passed"] is True,
                "stdout": validate_stdout.strip(),
                "stderr": validate_stderr.strip(),
            }
        )

        resistance = tmp / "regression-resistance.json"
        resistance_code, resistance_data, resistance_stdout, resistance_stderr = run_json(
            [sys.executable, str(ML_CHECKS), "regression-resistance", "--result-file", str(clean), "--output", str(resistance)]
        )
        mutation_names = {item.get("name") for item in resistance_data.get("mutations", [])}
        missing_metric = next((item for item in resistance_data.get("mutations", []) if item.get("name") == "missing_metric"), {})
        checks.append(
            {
                "name": "regression_resistance_catches_missing_metric",
                "passed": resistance_code == 0 and resistance_data.get("passed") is True and "missing_metric" in mutation_names and missing_metric.get("caught") is True,
                "stdout": resistance_stdout.strip(),
                "stderr": resistance_stderr.strip(),
            }
        )


    shuffled_a = ml.shuffled_label_check("classification", 0.86, [0.49, 0.50, 0.51, 0.52] * 10, alpha=0.05)
    shuffled_b = ml.shuffled_label_check("classification", 0.86, [0.49, 0.50, 0.51, 0.52] * 10, alpha=0.05)
    shuffled_bad = ml.shuffled_label_check("classification", 0.86, [0.86, 0.87, 0.88, 0.89] * 10, alpha=0.05)
    checks.append({"name": "shuffled_label_permutation_p_value_gates_deterministically", "passed": shuffled_a["passed"] is True and shuffled_bad["passed"] is False and shuffled_a["permutation_p_value"] == shuffled_b["permutation_p_value"], "result": shuffled_a})

    multi_a = ml.multi_seed_check([0.81, 0.82, 0.83, 0.82], min_score=0.75, max_cv=0.05, seed=7)
    multi_b = ml.multi_seed_check([0.81, 0.82, 0.83, 0.82], min_score=0.75, max_cv=0.05, seed=7)
    multi_bad = ml.multi_seed_check([0.70, 0.95, 0.82, 1.00], min_score=0.70, max_cv=0.05, seed=7)
    checks.append({"name": "multi_seed_cv_and_bootstrap_ci_gate_deterministically", "passed": multi_a["passed"] is True and multi_bad["passed"] is False and multi_a["metrics"]["bootstrap_mean_ci"] == multi_b["metrics"]["bootstrap_mean_ci"] and "coefficient_of_variation" in multi_a["metrics"], "result": multi_a})

    baseline_a = ml.baseline_comparison({"model_score": [0.84, 0.85, 0.86, 0.85, 0.84], "baseline_score": [0.78, 0.79, 0.80, 0.79, 0.78]}, min_improvement=0.03, seed=11)
    baseline_b = ml.baseline_comparison({"model_score": [0.84, 0.85, 0.86, 0.85, 0.84], "baseline_score": [0.78, 0.79, 0.80, 0.79, 0.78]}, min_improvement=0.03, seed=11)
    baseline_bad = ml.baseline_comparison({"model_score": [0.82, 0.83, 0.84, 0.83, 0.82], "baseline_score": [0.80, 0.81, 0.82, 0.81, 0.80]}, min_improvement=0.03, seed=11)
    checks.append({"name": "baseline_bootstrap_ci_lower_bound_gates_deterministically", "passed": baseline_a["passed"] is True and baseline_bad["passed"] is False and baseline_a["bootstrap_ci"] == baseline_b["bootstrap_ci"], "result": baseline_a})

    calibration_stats = ml.calibration_check({"confidences": [0.9, 0.8, 0.2, 0.1], "correct": [True, True, False, False]}, max_ece=0.25, bins=2)
    checks.append({"name": "calibration_reports_brier_mce_and_bias_note", "passed": calibration_stats["passed"] is True and "brier_score" in calibration_stats and "maximum_calibration_error" in calibration_stats and "equal-width" in calibration_stats["ece_bias_note"], "result": calibration_stats})


    clean_leakage = ml._base_leakage_result()
    clean_validation = ml.validate_result(clean_leakage)
    checks.append({"name": "clean_extended_leakage_data_passes", "passed": clean_validation["passed"] is True, "result": clean_validation})
    for kind, failed_check in [
        ("content_duplicate", "content_duplicate_leakage"),
        ("group", "group_entity_leakage"),
        ("temporal", "temporal_leakage"),
        ("correlation", "high_feature_target_correlation"),
    ]:
        clean_case, mutant_case = ml._leakage_case_results(kind)
        failed = {item["check"] for item in mutant_case["checks"] if not item["passed"]}
        checks.append({"name": f"planted_{failed_check}_is_caught", "passed": clean_case["passed"] is True and mutant_case["passed"] is False and failed_check in failed, "result": mutant_case})
    drift_clean = ml.drift_check({"train": {"x": [1, 2, 3, 4, 5]}, "test": {"x": [1.1, 2.1, 3.1, 4.1, 5.1]}}, max_psi=5.0, max_ks=0.5)
    drift_bad = ml.drift_check({"train": {"x": [1, 1, 1, 2, 2]}, "test": {"x": [10, 11, 12, 13, 14]}}, max_psi=0.2, max_ks=0.2)
    checks.append({"name": "distribution_drift_gate_passes_clean_and_fails_shift", "passed": drift_clean["passed"] is True and drift_bad["passed"] is False and "psi" in drift_bad["features"][0] and "ks_statistic" in drift_bad["features"][0], "result": drift_bad})


    imbalanced = {"labels": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1], "predictions": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "scores": [0.05, 0.04, 0.03, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.05]}
    imbalanced_metrics = ml.classification_metrics(imbalanced, min_metric=0.6, metric_name="macro_f1")
    checks.append({"name": "imbalanced_majority_accuracy_does_not_pass_macro_f1", "passed": imbalanced_metrics["passed"] is False and imbalanced_metrics["metrics"]["accuracy"] == 0.9 and imbalanced_metrics["metrics"]["macro_f1"] < 0.6 and "confusion_matrix" in imbalanced_metrics, "result": imbalanced_metrics})
    subgroup = ml.classification_metrics({"labels": [0,0,1,1], "predictions": [0,0,0,1], "subgroups": ["a","a","b","b"]}, metric_name="macro_f1", min_slice_metric=0.7, max_slice_gap=0.2)
    checks.append({"name": "slice_metrics_gate_minimum_and_gap", "passed": subgroup["passed"] is False and bool(subgroup["slice_metrics"]), "result": subgroup})
    shuffled_imb = ml.shuffled_label_check("classification", 0.91, [0.90] * 40, labels=[0]*9+[1], alpha=0.05, min_real_margin=0.02)
    checks.append({"name": "shuffled_label_uses_majority_chance_rate", "passed": shuffled_imb["chance_score"] == 0.9 and shuffled_imb["passed"] is False, "result": shuffled_imb})
    base_majority = ml.baseline_comparison({"model_score": 0.91, "labels": [0]*9+[1]}, baseline_metric="majority_baseline", min_improvement=0.02)
    checks.append({"name": "baseline_derives_majority_class_rate", "passed": base_majority["baseline_value"] == 0.9 and base_majority["baseline_source"] == "majority_class_rate", "result": base_majority})
    for hard_name, expected in [("imbalanced_majority_model.json", "classification_metrics"), ("content_duplicate_leaky.json", "content_duplicate_leakage"), ("temporal_leak.json", "temporal_leakage")]:
        data = json.loads((ROOT / "examples" / "ml_problems" / "hard_examples" / hard_name).read_text(encoding="utf-8"))
        report = ml.validate_result(data)
        failed = {item["check"] for item in report["checks"] if not item["passed"]}
        checks.append({"name": f"hard_example_{hard_name}_is_caught", "passed": report["passed"] is False and expected in failed, "result": report})

    ok = sum(1 for item in checks if item["passed"])
    result = {"passed": ok == len(checks), "assertions": len(checks), "ok": ok, "results": checks}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1



if __name__ == "__main__":
    raise SystemExit(main())
