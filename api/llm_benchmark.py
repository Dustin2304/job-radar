"""Schemas and validation for the private real-world LLM benchmark."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Job

Recommendation = Literal["strong_match", "review", "weak_match", "reject"]
EdgeCase = Literal[
    "experience_preferred",
    "experience_required",
    "must_have_gap",
    "nice_to_have_gap",
    "generic_title",
    "misleading_title",
    "title_only",
]

EXPECTED_RECOMMENDATION_COUNTS = {
    "strong_match": 6,
    "review": 6,
    "weak_match": 6,
    "reject": 6,
}
EXPECTED_DESCRIPTION_COUNTS = {"available": 18, "missing": 6}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMBenchmarkSnapshot(StrictModel):
    benchmark_version: Literal["v2.7.2"]
    captured_at: datetime
    jobs: list[Job] = Field(min_length=1)

    @model_validator(mode="after")
    def job_ids_are_unique(self):
        ids = [job.id for job in self.jobs]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark job IDs must be unique")
        return self


class ManualLLMBenchmarkLabel(StrictModel):
    id: str = Field(min_length=1)
    recommendation: Recommendation
    fit_score: int = Field(ge=0, le=100)
    role_fit: int = Field(ge=0, le=100)
    experience_fit: int = Field(ge=0, le=100)
    skills_fit: int = Field(ge=0, le=100)
    seniority_fit: int = Field(ge=0, le=100)
    expected_strengths: list[str]
    expected_must_have_gaps: list[str]
    expected_nice_to_have_gaps: list[str]
    experience_requirement: str | None
    experience_gap: bool | None
    edge_cases: list[EdgeCase]
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def lists_are_consistent(self):
        for field_name in (
            "expected_strengths",
            "expected_must_have_gaps",
            "expected_nice_to_have_gaps",
            "edge_cases",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if set(self.expected_must_have_gaps) & set(
            self.expected_nice_to_have_gaps
        ):
            raise ValueError("must-have and nice-to-have gaps must not overlap")
        return self


class LLMBenchmarkLabels(StrictModel):
    benchmark_version: Literal["v2.7.2"]
    labelled_at: datetime
    candidate_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_outputs_inspected: Literal[False]
    labels: list[ManualLLMBenchmarkLabel] = Field(min_length=1)

    @model_validator(mode="after")
    def label_ids_are_unique(self):
        ids = [label.id for label in self.labels]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark label IDs must be unique")
        return self


class LLMBenchmarkCase(StrictModel):
    job: Job
    manual: ManualLLMBenchmarkLabel


def load_llm_benchmark(
    jobs_path: Path, labels_path: Path
) -> list[LLMBenchmarkCase]:
    """Load the frozen private benchmark and enforce its deliberate balance."""

    snapshot = LLMBenchmarkSnapshot.model_validate_json(
        jobs_path.read_text(encoding="utf-8")
    )
    label_document = LLMBenchmarkLabels.model_validate_json(
        labels_path.read_text(encoding="utf-8")
    )
    if snapshot.benchmark_version != label_document.benchmark_version:
        raise ValueError("benchmark job and label versions do not match")

    jobs_by_id = {job.id: job for job in snapshot.jobs}
    labels_by_id = {label.id: label for label in label_document.labels}
    if jobs_by_id.keys() != labels_by_id.keys():
        missing_labels = sorted(jobs_by_id.keys() - labels_by_id.keys())
        unknown_labels = sorted(labels_by_id.keys() - jobs_by_id.keys())
        raise ValueError(
            "benchmark job/label IDs differ: "
            f"missing_labels={missing_labels}, unknown_labels={unknown_labels}"
        )

    recommendation_counts = Counter(
        label.recommendation for label in label_document.labels
    )
    if dict(recommendation_counts) != EXPECTED_RECOMMENDATION_COUNTS:
        raise ValueError(
            "benchmark must contain six cases per recommendation: "
            f"{dict(recommendation_counts)}"
        )

    description_counts = Counter(job.description_status for job in snapshot.jobs)
    if dict(description_counts) != EXPECTED_DESCRIPTION_COUNTS:
        raise ValueError(
            "benchmark must contain 18 complete and 6 title-only cases: "
            f"{dict(description_counts)}"
        )

    for label in label_document.labels:
        job = jobs_by_id[label.id]
        has_title_only_tag = "title_only" in label.edge_cases
        if has_title_only_tag != (job.description_status == "missing"):
            raise ValueError(
                f"case {job.id!r} title_only tag does not match description status"
            )

    return [
        LLMBenchmarkCase(job=job, manual=labels_by_id[job.id])
        for job in snapshot.jobs
    ]


def benchmark_summary(cases: list[LLMBenchmarkCase]) -> dict[str, object]:
    return {
        "total": len(cases),
        "recommendations": dict(
            Counter(case.manual.recommendation for case in cases)
        ),
        "description_status": dict(
            Counter(case.job.description_status for case in cases)
        ),
        "edge_cases": dict(
            Counter(edge for case in cases for edge in case.manual.edge_cases)
        ),
    }


def validate_benchmark_freeze(
    cases: list[LLMBenchmarkCase],
    labels: LLMBenchmarkLabels,
    candidate_profile_path: Path,
) -> None:
    """Ensure the labelled pool still uses the frozen pre-LLM inputs."""

    profile_hash = hashlib.sha256(candidate_profile_path.read_bytes()).hexdigest()
    if profile_hash != labels.candidate_profile_sha256:
        raise ValueError("candidate profile changed after benchmark labelling")

    for case in cases:
        job = case.job
        if job.embedding_status != "success" or job.profile_embedding_status != "success":
            raise ValueError(f"case {job.id!r} does not have successful embeddings")
        if job.llm_score is not None or job.llm_recommendation is not None:
            raise ValueError(f"case {job.id!r} already contains an LLM result")

    category_models = {case.job.embedding_model for case in cases}
    profile_models = {case.job.profile_embedding_model for case in cases}
    if len(category_models) != 1 or None in category_models:
        raise ValueError("benchmark category embedding model is not frozen")
    if profile_models != category_models:
        raise ValueError("category and profile embedding models differ")


__all__ = [
    "EXPECTED_DESCRIPTION_COUNTS",
    "EXPECTED_RECOMMENDATION_COUNTS",
    "LLMBenchmarkCase",
    "LLMBenchmarkLabels",
    "LLMBenchmarkSnapshot",
    "ManualLLMBenchmarkLabel",
    "benchmark_summary",
    "load_llm_benchmark",
    "validate_benchmark_freeze",
]
