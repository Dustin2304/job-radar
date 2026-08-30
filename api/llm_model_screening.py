"""Runtime calibration and generic local-model screening primitives."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from statistics import fmean, median
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .llm_benchmark import LLMBenchmarkCase
from .llm_prompt_calibration import (
    PromptCalibrationObservation,
    calibration_metrics,
)
from .llm_evaluation import LMStudioResponsesClient, StructuredJobEvaluator
from .models import CandidateProfile, LLMEvaluation

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
SchemaEnforcement = Literal["server_json_schema", "client_pydantic"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeCalibrationSubset(StrictModel):
    benchmark_version: Literal["v2.7.2"]
    jobs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_subset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids: list[str] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def ids_are_unique(self):
        if len(set(self.case_ids)) != 4:
            raise ValueError("runtime calibration case IDs must be unique")
        return self


class ModelRuntimeProfile(StrictModel):
    model_id: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    transport: Literal["responses"] = "responses"
    reasoning_effort: ReasoningEffort
    context_length: int = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    schema_enforcement: SchemaEnforcement = "client_pydantic"


class ModelBenchmarkObservation(StrictModel):
    phase: Literal["runtime_calibration", "model_screening", "final_benchmark"]
    model_id: str = Field(min_length=1)
    reasoning_effort: ReasoningEffort
    case_id: str = Field(min_length=1)
    run_index: int = Field(ge=1)
    status: Literal["success", "unavailable", "error"]
    evaluation: LLMEvaluation | None = None
    attempts: int = Field(ge=1, le=2)
    first_pass_valid: bool
    timed_out: bool
    latency_seconds: float = Field(ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    time_to_first_token_seconds: float | None = Field(default=None, ge=0)
    schema_enforcement: SchemaEnforcement
    error: str | None = None

    @model_validator(mode="after")
    def result_matches_status(self):
        if (self.status == "success") != (self.evaluation is not None):
            raise ValueError("successful observations require exactly one evaluation")
        if self.timed_out and self.status == "success":
            raise ValueError("successful observations cannot be timeouts")
        return self


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runtime_calibration_subset(
    subset_path: Path,
    prompt_subset_path: Path,
    prompt_cases: list[LLMBenchmarkCase],
    jobs_path: Path,
    labels_path: Path,
) -> list[LLMBenchmarkCase]:
    subset = RuntimeCalibrationSubset.model_validate_json(
        subset_path.read_text(encoding="utf-8")
    )
    expected_hashes = {
        "jobs_sha256": sha256_file(jobs_path),
        "labels_sha256": sha256_file(labels_path),
        "prompt_subset_sha256": sha256_file(prompt_subset_path),
    }
    for field, expected in expected_hashes.items():
        if getattr(subset, field) != expected:
            raise ValueError(f"frozen runtime subset dependency changed: {field}")

    cases_by_id = {case.job.id: case for case in prompt_cases}
    unknown = sorted(set(subset.case_ids) - cases_by_id.keys())
    if unknown:
        raise ValueError(f"runtime calibration subset contains unknown IDs: {unknown}")
    selected = [cases_by_id[case_id] for case_id in subset.case_ids]
    recommendations = Counter(case.manual.recommendation for case in selected)
    if set(recommendations.values()) != {1} or len(recommendations) != 4:
        raise ValueError("runtime subset requires one case per recommendation class")
    if not any(case.job.description_status == "missing" for case in selected):
        raise ValueError("runtime subset requires a title-only case")
    edges = {edge for case in selected for edge in case.manual.edge_cases}
    for required in ("must_have_gap", "experience_required"):
        if required not in edges:
            raise ValueError(f"runtime subset requires edge case {required!r}")
    if not any(len(case.manual.edge_cases) >= 2 for case in selected):
        raise ValueError("runtime subset requires a multi/boundary case")
    return selected


def model_screening_metrics(
    observations: list[ModelBenchmarkObservation],
    cases: list[LLMBenchmarkCase],
    *,
    known_absent_candidate_skills: list[str],
) -> dict[str, object]:
    prompt_observations = [
        PromptCalibrationObservation(
            model_id=item.model_id,
            prompt_family="evidence_first",
            case_id=item.case_id,
            run_index=item.run_index,
            status=item.status,
            evaluation=item.evaluation,
            attempts=item.attempts,
            first_pass_valid=item.first_pass_valid,
            latency_seconds=item.latency_seconds,
            error=item.error,
        )
        for item in observations
    ]
    metrics = calibration_metrics(
        prompt_observations,
        cases,
        known_absent_candidate_skills=known_absent_candidate_skills,
    )
    output_tokens = [
        item.output_tokens for item in observations if item.output_tokens is not None
    ]
    reasoning_tokens = [
        item.reasoning_tokens
        for item in observations
        if item.reasoning_tokens is not None
    ]
    ttft = [
        item.time_to_first_token_seconds
        for item in observations
        if item.time_to_first_token_seconds is not None
    ]
    total = len(observations)
    metrics.update(
        {
            "timeout_count": sum(item.timed_out for item in observations),
            "timeout_rate": (
                sum(item.timed_out for item in observations) / total if total else None
            ),
            "median_output_tokens": median(output_tokens) if output_tokens else None,
            "mean_output_tokens": fmean(output_tokens) if output_tokens else None,
            "median_reasoning_tokens": (
                median(reasoning_tokens) if reasoning_tokens else None
            ),
            "mean_reasoning_tokens": (
                fmean(reasoning_tokens) if reasoning_tokens else None
            ),
            "median_time_to_first_token_seconds": median(ttft) if ttft else None,
        }
    )
    return metrics


def evaluate_model_case(
    *,
    phase: Literal["runtime_calibration", "model_screening", "final_benchmark"],
    profile: ModelRuntimeProfile,
    case: LLMBenchmarkCase,
    candidate_profile: CandidateProfile,
    run_index: int,
) -> ModelBenchmarkObservation:
    client = LMStudioResponsesClient(
        base_url=profile.base_url,
        model=profile.model_id,
        reasoning_effort=profile.reasoning_effort,
        timeout_seconds=profile.timeout_seconds,
        temperature=profile.temperature,
        max_output_tokens=profile.max_output_tokens,
    )
    evaluator = StructuredJobEvaluator(client, prompt_family="evidence_first")
    started = time.perf_counter()
    diagnostic = evaluator.evaluate_with_diagnostics(case.job, candidate_profile)
    latency = time.perf_counter() - started
    result = diagnostic.result
    output_tokens = [
        item.output_tokens
        for item in client.request_stats
        if item.output_tokens is not None
    ]
    reasoning_tokens = [
        item.reasoning_tokens
        for item in client.request_stats
        if item.reasoning_tokens is not None
    ]
    ttft = [
        item.time_to_first_token_seconds
        for item in client.request_stats
        if item.time_to_first_token_seconds is not None
    ]
    return ModelBenchmarkObservation(
        phase=phase,
        model_id=profile.model_id,
        reasoning_effort=profile.reasoning_effort,
        case_id=case.job.id,
        run_index=run_index,
        status=result.status,
        evaluation=result.evaluation,
        attempts=diagnostic.attempts,
        first_pass_valid=diagnostic.first_pass_valid,
        timed_out=(
            result.status == "unavailable"
            and "timed out" in (result.error or "").casefold()
        ),
        latency_seconds=latency,
        output_tokens=sum(output_tokens) if output_tokens else None,
        reasoning_tokens=sum(reasoning_tokens) if reasoning_tokens else None,
        time_to_first_token_seconds=(sum(ttft) if ttft else None),
        schema_enforcement=profile.schema_enforcement,
        error=result.error,
    )


def select_runtime_effort(
    metrics_by_effort: dict[ReasoningEffort, dict[str, object]],
    *,
    max_failure_rate: float,
    max_median_latency_seconds: float,
) -> ReasoningEffort | None:
    def metric_value(metrics: dict[str, object], name: str, default: float) -> float:
        value = metrics.get(name)
        return default if value is None else float(value)

    practical = [
        (effort, metrics)
        for effort, metrics in metrics_by_effort.items()
        if metric_value(metrics, "failure_rate", 0) <= max_failure_rate
        and metric_value(metrics, "timeout_rate", 0) <= max_failure_rate
        and metric_value(metrics, "median_latency_seconds", float("inf"))
        <= max_median_latency_seconds
        and metrics.get("candidate_hallucination_count") == 0
    ]
    if not practical:
        return None
    effort_order = {"none": 0, "minimal": 1, "low": 2, "medium": 3, "high": 4}
    practical.sort(
        key=lambda item: (
            -metric_value(item[1], "recommendation_accuracy", 0),
            metric_value(item[1], "mean_ordinal_error", float("inf")),
            metric_value(item[1], "failure_rate", 0),
            metric_value(item[1], "median_latency_seconds", float("inf")),
            effort_order[item[0]],
        )
    )
    return practical[0][0]


def select_default_model(
    metrics_by_model: dict[str, dict[str, object]],
    *,
    efficiency_preference: str,
    similar_accuracy_margin: float,
    material_large_error_difference: int,
    max_failure_rate: float,
    max_timeout_rate: float,
    max_candidate_hallucinations: int,
) -> tuple[str, str]:
    """Choose a configurable default after the full finalist benchmark."""

    if efficiency_preference not in metrics_by_model:
        raise ValueError("efficiency preference is not present in benchmark metrics")
    practical = {
        model_id: values
        for model_id, values in metrics_by_model.items()
        if metric_number(values, "failure_rate", 1) <= max_failure_rate
        and metric_number(values, "timeout_rate", 1) <= max_timeout_rate
        and int(values.get("candidate_hallucination_count", 0))
        <= max_candidate_hallucinations
    }
    if not practical:
        raise ValueError("no technically safe finalist completed the full benchmark")
    if len(practical) == 1:
        model_id = next(iter(practical))
        return model_id, "only_practical_finalist"

    efficient = practical.get(efficiency_preference)
    if efficient is None:
        raise ValueError("efficiency preference did not complete the benchmark safely")
    alternatives = {
        model_id: values
        for model_id, values in practical.items()
        if model_id != efficiency_preference
    }
    best_alternative_id, best_alternative = min(
        alternatives.items(),
        key=lambda item: (
            int(item[1].get("large_recommendation_errors", 0)),
            -metric_number(item[1], "recommendation_accuracy", 0),
            metric_number(item[1], "mean_ordinal_error", float("inf")),
        ),
    )
    error_reduction = int(efficient.get("large_recommendation_errors", 0)) - int(
        best_alternative.get("large_recommendation_errors", 0)
    )
    if error_reduction >= material_large_error_difference:
        return best_alternative_id, "materially_fewer_large_errors"

    accuracy_gap = metric_number(
        best_alternative, "recommendation_accuracy", 0
    ) - metric_number(efficient, "recommendation_accuracy", 0)
    if accuracy_gap > similar_accuracy_margin:
        return best_alternative_id, "meaningfully_higher_recommendation_accuracy"
    return efficiency_preference, "similar_quality_efficiency_preference"


def metric_number(metrics: dict[str, object], name: str, default: float) -> float:
    value = metrics.get(name)
    return default if value is None else float(value)


__all__ = [
    "ModelBenchmarkObservation",
    "ModelRuntimeProfile",
    "ReasoningEffort",
    "RuntimeCalibrationSubset",
    "load_runtime_calibration_subset",
    "evaluate_model_case",
    "model_screening_metrics",
    "select_runtime_effort",
    "select_default_model",
]
