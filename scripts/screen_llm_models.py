#!/usr/bin/env python3
"""Screen configured local models on the frozen eight-job benchmark subset."""

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
    model_screening_metrics,
)
from api.llm_prompt_calibration import load_prompt_calibration_subset
from api.lm_studio_runtime import available_models, prepare_exclusive_model

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "llm_benchmark.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--profiles-from", type=Path)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--run-index", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_profiles(args, screening) -> list[ModelRuntimeProfile]:
    if args.profiles_from:
        document = json.loads(args.profiles_from.resolve().read_text(encoding="utf-8"))
        values = document["selected_runtime_profiles"]
    else:
        values = screening["runtime_profiles"]
    profiles = [ModelRuntimeProfile.model_validate(item) for item in values]
    if not profiles:
        raise ValueError("model screening requires calibrated runtime profiles")
    return profiles


def grouped_metrics(observations, cases, absent_skills):
    metrics: dict[str, object] = {}
    for model_id in sorted({item.model_id for item in observations}):
        selected = [item for item in observations if item.model_id == model_id]
        metrics[f"model:{model_id}:all"] = model_screening_metrics(
            selected, cases, known_absent_candidate_skills=absent_skills
        )
        for status, label in (("available", "full_description"), ("missing", "title_only")):
            case_ids = {
                case.job.id for case in cases if case.job.description_status == status
            }
            subset = [item for item in selected if item.case_id in case_ids]
            if subset:
                metrics[f"model:{model_id}:{label}"] = model_screening_metrics(
                    subset,
                    cases,
                    known_absent_candidate_skills=absent_skills,
                )
    return metrics


def write_result(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.run_index < 1:
        raise ValueError("run index must be positive")
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    runtime = config["runtime"]
    screening = config["model_screening"]
    prompt_config = config["prompt_calibration"]
    frozen_prompt = prompt_config["frozen_benchmark_prompt"]
    if screening["prompt_family"] != frozen_prompt["family"]:
        raise ValueError("model screening must use the frozen benchmark prompt")
    if evaluation_prompt_sha256(frozen_prompt["family"]) != frozen_prompt["sha256"]:
        raise ValueError("frozen benchmark prompt hash does not match implementation")

    jobs_path = absolute(prompt_config["jobs_path"])
    labels_path = absolute(prompt_config["labels_path"])
    subset_path = absolute(prompt_config["subset_path"])
    profile_path = ROOT / "config" / "candidate_profile.yaml"
    all_cases = load_llm_benchmark(jobs_path, labels_path)
    labels = LLMBenchmarkLabels.model_validate_json(labels_path.read_text(encoding="utf-8"))
    validate_benchmark_freeze(all_cases, labels, profile_path)
    cases = load_prompt_calibration_subset(
        subset_path, all_cases, jobs_path, labels_path
    )
    if args.case_ids:
        requested = set(args.case_ids)
        unknown = sorted(requested - {case.job.id for case in cases})
        if unknown:
            raise ValueError(f"cases are not in the frozen subset: {unknown}")
        cases = [case for case in cases if case.job.id in requested]

    profiles = load_profiles(args, screening)
    if args.models:
        requested_models = set(args.models)
        unknown_models = sorted(requested_models - {item.model_id for item in profiles})
        if unknown_models:
            raise ValueError(f"models do not have calibrated profiles: {unknown_models}")
        profiles = [item for item in profiles if item.model_id in requested_models]
    local_models = available_models(runtime["base_url"])
    missing = sorted({item.model_id for item in profiles} - local_models.keys())
    if missing:
        raise RuntimeError(f"calibrated local models are unavailable: {missing}")

    timestamp = datetime.now(timezone.utc)
    output_path = args.output or absolute(screening["results_dir"]) / (
        f"model-screening-run-{args.run_index}-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    document: dict[str, object] = {
        "benchmark_version": "v2.7.2b-2",
        "phase": "model_screening",
        "started_at": timestamp.isoformat(),
        "run_index": args.run_index,
        "prompt_family": frozen_prompt["family"],
        "prompt_sha256": frozen_prompt["sha256"],
        "runtime_profiles": [item.model_dump(mode="json") for item in profiles],
        "case_ids": [case.job.id for case in cases],
        "observations": [],
        "metrics": {},
    }
    if args.dry_run:
        document["planned_evaluations"] = len(profiles) * len(cases)
        print(json.dumps(document, indent=2, ensure_ascii=False))
        return

    observations: list[ModelBenchmarkObservation] = []
    if args.resume and output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        for field in (
            "run_index",
            "prompt_family",
            "prompt_sha256",
            "runtime_profiles",
            "case_ids",
        ):
            if previous.get(field) != document[field]:
                raise ValueError(f"cannot resume: {field} differs from current plan")
        observations = [
            ModelBenchmarkObservation.model_validate(item)
            for item in previous.get("observations", [])
        ]
    completed = {(item.model_id, item.case_id, item.run_index) for item in observations}
    candidate_profile = load_candidate_profile(profile_path)
    for profile in profiles:
        prepare_exclusive_model(
            profile.model_id,
            base_url=profile.base_url,
            context_length=profile.context_length,
            gpu_offload=runtime["gpu_offload"],
            parallel_requests=runtime["parallel_requests"],
        )
        for case in cases:
            key = (profile.model_id, case.job.id, args.run_index)
            if key in completed:
                continue
            observation = evaluate_model_case(
                phase="model_screening",
                profile=profile,
                case=case,
                candidate_profile=candidate_profile,
                run_index=args.run_index,
            )
            observations.append(observation)
            document["observations"] = [
                item.model_dump(mode="json") for item in observations
            ]
            document["metrics"] = grouped_metrics(
                observations, cases, config["known_absent_candidate_skills"]
            )
            write_result(output_path, document)
            print(
                f"{profile.model_id} reasoning={profile.reasoning_effort} "
                f"case={case.job.id} run={args.run_index} status={observation.status} "
                f"latency={observation.latency_seconds:.2f}s",
                flush=True,
            )

    document["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_result(output_path, document)
    print(json.dumps({"output": str(output_path), "metrics": document["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
