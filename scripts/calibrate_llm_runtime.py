#!/usr/bin/env python3
"""Calibrate one practical reasoning/runtime profile per local model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import yaml

from api.llm_benchmark import LLMBenchmarkLabels, load_llm_benchmark, validate_benchmark_freeze
from api.llm_evaluation import evaluation_prompt_sha256, load_candidate_profile
from api.llm_model_screening import (
    ModelBenchmarkObservation,
    ModelRuntimeProfile,
    evaluate_model_case,
    load_runtime_calibration_subset,
    model_screening_metrics,
    select_runtime_effort,
)
from api.llm_prompt_calibration import load_prompt_calibration_subset
from api.lm_studio_runtime import available_models, prepare_exclusive_model

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "llm_benchmark.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--effort", action="append", dest="efforts")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--context-length", type=int)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def write_result(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


def metrics_and_profiles(
    observations,
    cases,
    config,
    models,
    efforts,
):
    absent_skills = config["known_absent_candidate_skills"]
    runtime = config["runtime"]
    calibration = config["runtime_calibration"]
    context_length = calibration.get("context_length", runtime["context_length"])
    limits = calibration["practical_limits"]
    metrics: dict[str, object] = {}
    selected_profiles = []
    for model_id in models:
        by_effort = {}
        for effort in efforts:
            selected = [
                item
                for item in observations
                if item.model_id == model_id and item.reasoning_effort == effort
            ]
            if selected:
                current = model_screening_metrics(
                    selected,
                    cases,
                    known_absent_candidate_skills=absent_skills,
                )
                metrics[f"model:{model_id}:reasoning:{effort}"] = current
                by_effort[effort] = current
        chosen = select_runtime_effort(
            by_effort,
            max_failure_rate=float(limits["max_failure_rate"]),
            max_median_latency_seconds=float(
                limits["max_median_latency_seconds"]
            ),
        )
        if chosen is not None:
            selected_profiles.append(
                ModelRuntimeProfile(
                    model_id=model_id,
                    base_url=runtime["base_url"],
                    reasoning_effort=chosen,
                    context_length=context_length,
                    temperature=runtime["temperature"],
                    max_output_tokens=calibration["max_output_tokens"],
                    timeout_seconds=calibration["timeout_seconds"],
                    schema_enforcement="client_pydantic",
                ).model_dump(mode="json")
            )
    return metrics, selected_profiles


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    runtime = config["runtime"]
    calibration = config["runtime_calibration"]
    if args.context_length is not None:
        if args.context_length < 1:
            raise ValueError("context length must be positive")
        calibration["context_length"] = args.context_length
    context_length = calibration.get("context_length", runtime["context_length"])
    if args.max_output_tokens is not None:
        if args.max_output_tokens < 1:
            raise ValueError("max output tokens must be positive")
        calibration["max_output_tokens"] = args.max_output_tokens
    if args.timeout_seconds is not None:
        if args.timeout_seconds <= 0:
            raise ValueError("timeout seconds must be positive")
        calibration["timeout_seconds"] = args.timeout_seconds
    prompt_config = config["prompt_calibration"]
    frozen_prompt = prompt_config["frozen_benchmark_prompt"]
    if calibration["prompt_family"] != frozen_prompt["family"]:
        raise ValueError("runtime calibration must use the frozen benchmark prompt")
    if evaluation_prompt_sha256(frozen_prompt["family"]) != frozen_prompt["sha256"]:
        raise ValueError("frozen benchmark prompt hash does not match implementation")

    jobs_path = absolute(prompt_config["jobs_path"])
    labels_path = absolute(prompt_config["labels_path"])
    prompt_subset_path = absolute(prompt_config["subset_path"])
    profile_path = ROOT / "config" / "candidate_profile.yaml"
    all_cases = load_llm_benchmark(jobs_path, labels_path)
    labels = LLMBenchmarkLabels.model_validate_json(labels_path.read_text(encoding="utf-8"))
    validate_benchmark_freeze(all_cases, labels, profile_path)
    prompt_cases = load_prompt_calibration_subset(
        prompt_subset_path, all_cases, jobs_path, labels_path
    )
    cases = load_runtime_calibration_subset(
        absolute(calibration["subset_path"]),
        prompt_subset_path,
        prompt_cases,
        jobs_path,
        labels_path,
    )
    if args.case_ids:
        requested = set(args.case_ids)
        unknown = sorted(requested - {case.job.id for case in cases})
        if unknown:
            raise ValueError(f"cases are not in the runtime subset: {unknown}")
        cases = [case for case in cases if case.job.id in requested]

    configured_models = {item["id"]: item for item in config["candidate_models"]}
    models = args.models or list(configured_models)
    unknown_models = sorted(set(models) - configured_models.keys())
    if unknown_models:
        raise ValueError(f"models are not configured: {unknown_models}")
    efforts = args.efforts or list(calibration["reasoning_efforts"])
    unknown_efforts = sorted(
        set(efforts) - {"none", "minimal", "low", "medium", "high"}
    )
    if unknown_efforts:
        raise ValueError(f"unsupported reasoning efforts: {unknown_efforts}")
    local_models = available_models(runtime["base_url"])
    missing = sorted(set(models) - local_models.keys())
    if missing:
        raise RuntimeError(f"configured local models are unavailable: {missing}")

    timestamp = datetime.now(timezone.utc)
    output_path = args.output or absolute(calibration["results_dir"]) / (
        f"runtime-calibration-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    document: dict[str, object] = {
        "benchmark_version": "v2.7.2b-2",
        "phase": "runtime_calibration",
        "started_at": timestamp.isoformat(),
        "runtime": {
            **runtime,
            "context_length": context_length,
            "max_output_tokens": calibration["max_output_tokens"],
            "timeout_seconds": calibration["timeout_seconds"],
            "reasoning_setting": "per_model_calibrated",
            "seed_control": "unsupported_by_responses_endpoint",
        },
        "models": [configured_models[model] for model in models],
        "reasoning_efforts": efforts,
        "prompt_family": frozen_prompt["family"],
        "prompt_sha256": frozen_prompt["sha256"],
        "case_ids": [case.job.id for case in cases],
        "schema_enforcement": "client_pydantic",
        "observations": [],
        "metrics": {},
        "selected_runtime_profiles": [],
    }
    if args.dry_run:
        document["planned_evaluations"] = len(models) * len(efforts) * len(cases)
        print(json.dumps(document, indent=2, ensure_ascii=False))
        return

    observations: list[ModelBenchmarkObservation] = []
    if args.resume and output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        for field in (
            "runtime",
            "models",
            "reasoning_efforts",
            "prompt_family",
            "prompt_sha256",
            "case_ids",
        ):
            if previous.get(field) != document[field]:
                raise ValueError(f"cannot resume: {field} differs from current plan")
        observations = [
            ModelBenchmarkObservation.model_validate(item)
            for item in previous.get("observations", [])
        ]
    completed = {
        (item.model_id, item.reasoning_effort, item.case_id, item.run_index)
        for item in observations
    }
    candidate_profile = load_candidate_profile(profile_path)
    for model_id in models:
        prepare_exclusive_model(
            model_id,
            base_url=runtime["base_url"],
            context_length=context_length,
            gpu_offload=runtime["gpu_offload"],
            parallel_requests=runtime["parallel_requests"],
        )
        for effort in efforts:
            profile = ModelRuntimeProfile(
                model_id=model_id,
                base_url=runtime["base_url"],
                reasoning_effort=effort,
                context_length=context_length,
                temperature=runtime["temperature"],
                max_output_tokens=calibration["max_output_tokens"],
                timeout_seconds=calibration["timeout_seconds"],
                schema_enforcement="client_pydantic",
            )
            for case in cases:
                key = (model_id, effort, case.job.id, 1)
                if key in completed:
                    continue
                observation = evaluate_model_case(
                    phase="runtime_calibration",
                    profile=profile,
                    case=case,
                    candidate_profile=candidate_profile,
                    run_index=1,
                )
                observations.append(observation)
                metrics, profiles = metrics_and_profiles(
                    observations, cases, config, models, efforts
                )
                document["observations"] = [
                    item.model_dump(mode="json") for item in observations
                ]
                document["metrics"] = metrics
                document["selected_runtime_profiles"] = profiles
                write_result(output_path, document)
                print(
                    f"{model_id} reasoning={effort} case={case.job.id} "
                    f"status={observation.status} latency={observation.latency_seconds:.2f}s "
                    f"tokens={observation.output_tokens}",
                    flush=True,
                )

    document["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_result(output_path, document)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "selected_runtime_profiles": document["selected_runtime_profiles"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
