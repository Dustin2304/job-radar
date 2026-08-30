import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from api.llm_benchmark import (
    LLMBenchmarkLabels,
    LLMBenchmarkSnapshot,
    ManualLLMBenchmarkLabel,
    benchmark_summary,
    load_llm_benchmark,
    validate_benchmark_freeze,
)
from api.normalization import normalize_job


RECOMMENDATIONS = ("strong_match", "review", "weak_match", "reject")


def job(index: int, *, description_available: bool):
    description = "Complete description" if description_available else ""
    return normalize_job(
        {
            "id": f"job-{index}",
            "site": "indeed" if description_available else "linkedin",
            "title": f"Benchmark Job {index}",
            "company": "Example GmbH",
            "job_url": f"https://example.com/jobs/{index}",
            "description": description,
        },
        "benchmark",
    )


def label(job_id: str, recommendation: str, *, title_only: bool = False):
    return {
        "id": job_id,
        "recommendation": recommendation,
        "fit_score": 75,
        "role_fit": 75,
        "experience_fit": 75,
        "skills_fit": 75,
        "seniority_fit": 75,
        "expected_strengths": ["process automation"],
        "expected_must_have_gaps": [],
        "expected_nice_to_have_gaps": ["Databricks"],
        "experience_requirement": None,
        "experience_gap": None if title_only else False,
        "edge_cases": ["title_only"] if title_only else ["nice_to_have_gap"],
        "notes": "Manual reference set before model inspection.",
    }


def write_balanced_dataset(tmp_path):
    jobs = []
    labels = []
    index = 0
    for recommendation in RECOMMENDATIONS:
        for _ in range(6):
            title_only = index >= 18
            current_job = job(index, description_available=not title_only)
            jobs.append(current_job.model_dump(mode="json"))
            labels.append(label(current_job.id, recommendation, title_only=title_only))
            index += 1

    jobs_path = tmp_path / "jobs.json"
    labels_path = tmp_path / "labels.json"
    jobs_path.write_text(
        json.dumps(
            {
                "benchmark_version": "v2.7.2",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "jobs": jobs,
            }
        ),
        encoding="utf-8",
    )
    labels_path.write_text(
        json.dumps(
            {
                "benchmark_version": "v2.7.2",
                "labelled_at": datetime.now(timezone.utc).isoformat(),
                "candidate_profile_sha256": "a" * 64,
                "model_outputs_inspected": False,
                "labels": labels,
            }
        ),
        encoding="utf-8",
    )
    return jobs_path, labels_path


def test_balanced_private_benchmark_loads_and_summarizes(tmp_path):
    jobs_path, labels_path = write_balanced_dataset(tmp_path)

    cases = load_llm_benchmark(jobs_path, labels_path)

    assert benchmark_summary(cases) == {
        "total": 24,
        "recommendations": {
            "strong_match": 6,
            "review": 6,
            "weak_match": 6,
            "reject": 6,
        },
        "description_status": {"available": 18, "missing": 6},
        "edge_cases": {"nice_to_have_gap": 18, "title_only": 6},
    }


def test_unbalanced_recommendations_are_rejected(tmp_path):
    jobs_path, labels_path = write_balanced_dataset(tmp_path)
    document = json.loads(labels_path.read_text(encoding="utf-8"))
    document["labels"][0]["recommendation"] = "review"
    labels_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="six cases per recommendation"):
        load_llm_benchmark(jobs_path, labels_path)


def test_title_only_tags_must_match_description_status(tmp_path):
    jobs_path, labels_path = write_balanced_dataset(tmp_path)
    document = json.loads(labels_path.read_text(encoding="utf-8"))
    document["labels"][18]["edge_cases"] = []
    labels_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="title_only tag"):
        load_llm_benchmark(jobs_path, labels_path)


def test_manual_labels_reject_overlapping_gap_types():
    payload = label("job-1", "review")
    payload["expected_must_have_gaps"] = ["Azure"]
    payload["expected_nice_to_have_gaps"] = ["Azure"]

    with pytest.raises(ValidationError, match="must-have and nice-to-have"):
        ManualLLMBenchmarkLabel.model_validate(payload)


def test_label_document_proves_models_were_not_inspected():
    with pytest.raises(ValidationError):
        LLMBenchmarkLabels.model_validate(
            {
                "benchmark_version": "v2.7.2",
                "labelled_at": datetime.now(timezone.utc),
                "candidate_profile_sha256": "a" * 64,
                "model_outputs_inspected": True,
                "labels": [],
            }
        )


def test_snapshot_rejects_duplicate_job_ids():
    duplicate = job(1, description_available=True)

    with pytest.raises(ValidationError, match="job IDs must be unique"):
        LLMBenchmarkSnapshot.model_validate(
            {
                "benchmark_version": "v2.7.2",
                "captured_at": datetime.now(timezone.utc),
                "jobs": [duplicate, duplicate],
            }
        )


def test_freeze_validation_rejects_changed_candidate_profile(tmp_path):
    jobs_path, labels_path = write_balanced_dataset(tmp_path)
    cases = load_llm_benchmark(jobs_path, labels_path)
    labels = LLMBenchmarkLabels.model_validate_json(
        labels_path.read_text(encoding="utf-8")
    )
    profile_path = tmp_path / "candidate-profile.yaml"
    profile_path.write_text("changed: true", encoding="utf-8")

    with pytest.raises(ValueError, match="candidate profile changed"):
        validate_benchmark_freeze(cases, labels, profile_path)
