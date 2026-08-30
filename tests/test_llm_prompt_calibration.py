import json

import pytest

from api.llm_benchmark import LLMBenchmarkCase, ManualLLMBenchmarkLabel
from api.llm_prompt_calibration import (
    PromptCalibrationObservation,
    calibration_metrics,
    load_prompt_calibration_subset,
    sha256_file,
)
from api.models import LLMEvaluation
from api.normalization import normalize_job


CLASSES = ("strong_match", "review", "weak_match", "reject")
EDGES = (
    ["must_have_gap", "nice_to_have_gap", "experience_required"],
    ["nice_to_have_gap", "experience_preferred"],
    ["must_have_gap", "experience_preferred"],
    ["title_only", "generic_title"],
    ["must_have_gap", "nice_to_have_gap", "experience_required"],
    ["title_only", "misleading_title"],
    ["must_have_gap", "experience_required"],
    ["must_have_gap"],
)


def benchmark_cases():
    cases = []
    for index, edges in enumerate(EDGES):
        title_only = "title_only" in edges
        job = normalize_job(
            {
                "id": f"job-{index}",
                "site": "linkedin",
                "title": f"Job {index}",
                "company": "Example",
                "job_url": f"https://example.com/{index}",
                "description": "" if title_only else "Python and automation",
            },
            "benchmark",
        )
        manual = ManualLLMBenchmarkLabel.model_validate(
            {
                "id": job.id,
                "recommendation": CLASSES[index // 2],
                "fit_score": 80 - index * 8,
                "role_fit": 80,
                "experience_fit": 70,
                "skills_fit": 75,
                "seniority_fit": 85,
                "expected_strengths": ["Python"],
                "expected_must_have_gaps": ["SAP"] if "must_have_gap" in edges else [],
                "expected_nice_to_have_gaps": ["Databricks"] if "nice_to_have_gap" in edges else [],
                "experience_requirement": "2 years" if "experience_required" in edges else None,
                "experience_gap": None if title_only else "experience_required" in edges,
                "edge_cases": edges,
                "notes": "Manual benchmark reference.",
            }
        )
        cases.append(LLMBenchmarkCase(job=job, manual=manual))
    return cases


def write_subset(tmp_path, cases):
    jobs_path = tmp_path / "jobs.json"
    labels_path = tmp_path / "labels.json"
    jobs_path.write_text("frozen jobs", encoding="utf-8")
    labels_path.write_text("frozen labels", encoding="utf-8")
    subset_path = tmp_path / "subset.json"
    subset_path.write_text(
        json.dumps(
            {
                "benchmark_version": "v2.7.2",
                "jobs_sha256": sha256_file(jobs_path),
                "labels_sha256": sha256_file(labels_path),
                "case_ids": [case.job.id for case in cases],
            }
        ),
        encoding="utf-8",
    )
    return subset_path, jobs_path, labels_path


def evaluation(**overrides):
    payload = {
        "evaluation_status": "complete",
        "fit_score": 78,
        "recommendation": "strong_match",
        "role_fit": 80,
        "experience_fit": 70,
        "skills_fit": 75,
        "seniority_fit": 85,
        "matched_requirements": ["Python"],
        "missing_requirements": ["SAP"],
        "nice_to_have_gaps": ["Databricks platform"],
        "concerns": [],
        "experience_requirement": "2 years",
        "experience_gap": True,
        "summary": "Evidence-based assessment.",
    }
    payload.update(overrides)
    return LLMEvaluation.model_validate(payload)


def test_frozen_subset_is_balanced_and_covers_required_edges(tmp_path):
    cases = benchmark_cases()
    subset_path, jobs_path, labels_path = write_subset(tmp_path, cases)

    selected = load_prompt_calibration_subset(
        subset_path, cases, jobs_path, labels_path
    )

    assert [case.job.id for case in selected] == [case.job.id for case in cases]


def test_subset_rejects_changed_ground_truth_file(tmp_path):
    cases = benchmark_cases()
    subset_path, jobs_path, labels_path = write_subset(tmp_path, cases)
    labels_path.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="manual benchmark labels changed"):
        load_prompt_calibration_subset(subset_path, cases, jobs_path, labels_path)


def test_calibration_metrics_cover_quality_safety_and_operations():
    cases = benchmark_cases()
    observations = [
        PromptCalibrationObservation(
            model_id="model-a",
            prompt_family="evidence_first",
            case_id=cases[0].job.id,
            run_index=1,
            status="success",
            evaluation=evaluation(matched_requirements=["Python", "C#"]),
            attempts=1,
            first_pass_valid=True,
            latency_seconds=2,
        ),
        PromptCalibrationObservation(
            model_id="model-a",
            prompt_family="evidence_first",
            case_id=cases[0].job.id,
            run_index=2,
            status="success",
            evaluation=evaluation(fit_score=82),
            attempts=2,
            first_pass_valid=False,
            latency_seconds=4,
        ),
    ]

    metrics = calibration_metrics(
        observations, cases, known_absent_candidate_skills=["C#", "Azure"]
    )

    assert metrics["recommendation_accuracy"] == 1
    assert metrics["must_have_precision"] == 1
    assert metrics["must_have_recall"] == 1
    assert metrics["nice_to_have_precision"] == 1
    assert metrics["candidate_hallucination_count"] == 1
    assert metrics["first_pass_schema_rate"] == 0.5
    assert metrics["retry_rate"] == 0.5
    assert metrics["recommendation_stability"] == 1
    assert metrics["mean_fit_score_stddev"] == 2
