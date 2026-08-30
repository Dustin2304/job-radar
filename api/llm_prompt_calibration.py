"""Frozen prompt-calibration subset, observations, and benchmark metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import re
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .llm_benchmark import EdgeCase, LLMBenchmarkCase
from .llm_evaluation import PromptFamily
from .models import LLMEvaluation

RECOMMENDATION_ORDER = {
    "reject": 0,
    "weak_match": 1,
    "review": 2,
    "strong_match": 3,
}
REQUIRED_EDGE_CASES: set[EdgeCase] = {
    "must_have_gap",
    "nice_to_have_gap",
    "experience_required",
    "experience_preferred",
    "title_only",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptCalibrationSubset(StrictModel):
    benchmark_version: Literal["v2.7.2"]
    jobs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids: list[str] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def ids_are_unique(self):
        if len(set(self.case_ids)) != 8:
            raise ValueError("prompt calibration case IDs must be unique")
        return self


class PromptCalibrationObservation(StrictModel):
    model_id: str = Field(min_length=1)
    prompt_family: PromptFamily
    case_id: str = Field(min_length=1)
    run_index: int = Field(ge=1)
    status: Literal["success", "unavailable", "error"]
    evaluation: LLMEvaluation | None = None
    attempts: int = Field(ge=1, le=2)
    first_pass_valid: bool
    latency_seconds: float = Field(ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def result_matches_status(self):
        if (self.status == "success") != (self.evaluation is not None):
            raise ValueError("successful observations require exactly one evaluation")
        return self


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prompt_calibration_subset(
    subset_path: Path,
    cases: list[LLMBenchmarkCase],
    jobs_path: Path,
    labels_path: Path,
) -> list[LLMBenchmarkCase]:
    subset = PromptCalibrationSubset.model_validate_json(
        subset_path.read_text(encoding="utf-8")
    )
    if subset.jobs_sha256 != sha256_file(jobs_path):
        raise ValueError("frozen benchmark jobs changed after subset selection")
    if subset.labels_sha256 != sha256_file(labels_path):
        raise ValueError("manual benchmark labels changed after subset selection")

    cases_by_id = {case.job.id: case for case in cases}
    unknown = sorted(set(subset.case_ids) - cases_by_id.keys())
    if unknown:
        raise ValueError(f"prompt calibration subset contains unknown IDs: {unknown}")
    selected = [cases_by_id[case_id] for case_id in subset.case_ids]

    counts = Counter(case.manual.recommendation for case in selected)
    if set(counts.values()) != {2} or set(counts) != set(RECOMMENDATION_ORDER):
        raise ValueError("prompt calibration subset requires two cases per class")
    covered = {edge for case in selected for edge in case.manual.edge_cases}
    missing_edges = sorted(REQUIRED_EDGE_CASES - covered)
    if missing_edges:
        raise ValueError(f"prompt calibration subset misses edge cases: {missing_edges}")
    boundary_cases = sum(len(case.manual.edge_cases) >= 2 for case in selected)
    if boundary_cases == 0:
        raise ValueError("prompt calibration subset requires a multi/boundary case")
    return selected


def _terms_match(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9+#.]+", value.casefold()))

    a, b = normalize(left), normalize(right)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    a_tokens, b_tokens = set(a.split()), set(b.split())
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens) >= 0.5


def _set_counts(predicted: list[str], expected: list[str]) -> tuple[int, int, int]:
    matched_expected: set[int] = set()
    true_positive = 0
    for prediction in predicted:
        match = next(
            (
                index
                for index, reference in enumerate(expected)
                if index not in matched_expected and _terms_match(prediction, reference)
            ),
            None,
        )
        if match is not None:
            matched_expected.add(match)
            true_positive += 1
    return true_positive, len(predicted) - true_positive, len(expected) - true_positive


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def calibration_metrics(
    observations: list[PromptCalibrationObservation],
    cases: list[LLMBenchmarkCase],
    *,
    known_absent_candidate_skills: list[str],
) -> dict[str, object]:
    cases_by_id = {case.job.id: case for case in cases}
    successful = [item for item in observations if item.status == "success"]
    rec_exact = ordinal_total = large_errors = 0
    score_errors: dict[str, list[float]] = defaultdict(list)
    experience_correct = experience_total = 0
    preliminary_correct = preliminary_total = title_only_invented = 0
    must_tp = must_fp = must_fn = nice_tp = nice_fp = nice_fn = 0
    hallucinations: list[dict[str, str]] = []

    for item in successful:
        case = cases_by_id[item.case_id]
        manual, evaluation = case.manual, item.evaluation
        assert evaluation is not None
        distance = abs(
            RECOMMENDATION_ORDER[evaluation.recommendation]
            - RECOMMENDATION_ORDER[manual.recommendation]
        )
        rec_exact += distance == 0
        ordinal_total += distance
        large_errors += distance >= 2
        for name in (
            "fit_score",
            "role_fit",
            "experience_fit",
            "skills_fit",
            "seniority_fit",
        ):
            score_errors[name].append(
                abs(getattr(evaluation, name) - getattr(manual, name))
            )
        if manual.experience_gap is not None:
            experience_total += 1
            experience_correct += evaluation.experience_gap == manual.experience_gap
        counts = _set_counts(
            evaluation.missing_requirements, manual.expected_must_have_gaps
        )
        must_tp += counts[0]
        must_fp += counts[1]
        must_fn += counts[2]
        counts = _set_counts(
            evaluation.nice_to_have_gaps, manual.expected_nice_to_have_gaps
        )
        nice_tp += counts[0]
        nice_fp += counts[1]
        nice_fn += counts[2]
        if case.job.description_status == "missing":
            preliminary_total += 1
            preliminary_correct += evaluation.evaluation_status == "preliminary"
            title_only_invented += bool(
                evaluation.missing_requirements or evaluation.nice_to_have_gaps
            )
        for skill in known_absent_candidate_skills:
            if any(
                _terms_match(skill, value)
                for value in evaluation.matched_requirements
            ):
                hallucinations.append({"case_id": item.case_id, "skill": skill})

    total = len(observations)
    success_total = len(successful)
    latencies = [item.latency_seconds for item in observations]
    groups: dict[
        tuple[str, str, str], list[PromptCalibrationObservation]
    ] = defaultdict(list)
    for item in successful:
        groups[(item.model_id, item.prompt_family, item.case_id)].append(item)
    repeated = [items for items in groups.values() if len(items) > 1]
    stable = sum(
        len({item.evaluation.recommendation for item in items if item.evaluation}) == 1
        for items in repeated
    )
    score_stddevs = [
        pstdev([item.evaluation.fit_score for item in items if item.evaluation])
        for items in repeated
    ]

    return {
        "evaluations": total,
        "successful": success_total,
        "recommendation_accuracy": _ratio(rec_exact, success_total),
        "mean_ordinal_error": _ratio(ordinal_total, success_total),
        "large_recommendation_errors": large_errors,
        "score_mae": {
            name: fmean(values) if values else None for name, values in score_errors.items()
        },
        "experience_gap_accuracy": _ratio(experience_correct, experience_total),
        "must_have_precision": _ratio(must_tp, must_tp + must_fp),
        "must_have_recall": _ratio(must_tp, must_tp + must_fn),
        "nice_to_have_precision": _ratio(nice_tp, nice_tp + nice_fp),
        "nice_to_have_recall": _ratio(nice_tp, nice_tp + nice_fn),
        "candidate_hallucination_count": len(hallucinations),
        "candidate_hallucinations": hallucinations,
        "preliminary_status_accuracy": _ratio(preliminary_correct, preliminary_total),
        "title_only_invented_gap_rate": _ratio(title_only_invented, preliminary_total),
        "first_pass_schema_rate": _ratio(
            sum(item.first_pass_valid for item in observations), total
        ),
        "retry_rate": _ratio(
            sum(item.attempts > 1 for item in observations), total
        ),
        "failure_rate": _ratio(total - success_total, total),
        "median_latency_seconds": median(latencies) if latencies else None,
        "mean_latency_seconds": fmean(latencies) if latencies else None,
        "recommendation_stability": _ratio(stable, len(repeated)),
        "mean_fit_score_stddev": fmean(score_stddevs) if score_stddevs else None,
    }


__all__ = [
    "PromptCalibrationObservation",
    "PromptCalibrationSubset",
    "calibration_metrics",
    "load_prompt_calibration_subset",
    "sha256_file",
]
