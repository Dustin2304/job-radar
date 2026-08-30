#!/usr/bin/env python3
"""Run the frozen 24-job benchmark for calibrated finalist profiles."""

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
    select_default_model,
)
from api.lm_studio_runtime import available_models, prepare_exclusive_model

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "llm_benchmark.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--seed-from", action="append", type=Path, dest="seed_paths")
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


def grouped_metrics(observations, cases, absent_skills):
    metrics: dict[str, dict[str, object]] = {}
    for model_id in sorted({item.model_id for item in observations}):
        selected = [item for item in observations if item.model_id == model_id]
        metrics[model_id] = model_screening_metrics(
            selected, cases, known_absent_candidate_skills=absent_skills
        )
    return metrics


def grouped_segment_metrics(observations, cases, absent_skills):
    segments = {
        "full_description": [
            case for case in cases if case.job.description_status != "missing"
        ],
        "title_only": [
            case for case in cases if case.job.description_status == "missing"
        ],
    }
    return {
        segment: grouped_metrics(
            [
                item
                for item in observations
                if item.case_id in {case.job.id for case in selected}
            ],
            selected,
            absent_skills,
        )
        for segment, selected in segments.items()
    }


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    runtime = config["runtime"]
    benchmark = config["final_benchmark"]
    prompt_config = config["prompt_calibration"]
    frozen_prompt = prompt_config["frozen_benchmark_prompt"]
    if benchmark["prompt_family"] != frozen_prompt["family"]:
        raise ValueError("final benchmark must use the frozen benchmark prompt")
    if evaluation_prompt_sha256(frozen_prompt["family"]) != frozen_prompt["sha256"]:
        raise ValueError("frozen benchmark prompt hash does not match implementation")

    jobs_path = absolute(prompt_config["jobs_path"])
    labels_path = absolute(prompt_config["labels_path"])
    profile_path = ROOT / "config" / "candidate_profile.yaml"
    cases = load_llm_benchmark(jobs_path, labels_path)
    labels = LLMBenchmarkLabels.model_validate_json(labels_path.read_text(encoding="utf-8"))
    validate_benchmark_freeze(cases, labels, profile_path)
    if args.case_ids:
        requested = set(args.case_ids)
        unknown = sorted(requested - {case.job.id for case in cases})
        if unknown:
            raise ValueError(f"cases are not in the frozen benchmark: {unknown}")
        cases = [case for case in cases if case.job.id in requested]

    profiles = [
        ModelRuntimeProfile.model_validate(item) for item in benchmark["runtime_profiles"]
    ]
    if args.models:
        requested = set(args.models)
        unknown = sorted(requested - {profile.model_id for profile in profiles})
        if unknown:
            raise ValueError(f"models do not have finalist profiles: {unknown}")
        profiles = [profile for profile in profiles if profile.model_id in requested]
    local_models = available_models(runtime["base_url"])
    missing = sorted({profile.model_id for profile in profiles} - local_models.keys())
    if missing:
        raise RuntimeError(f"finalist models are unavailable: {missing}")

    runs = int(benchmark["runs_per_case"])
    run_indices = list(range(1, runs + 1))
    timestamp = datetime.now(timezone.utc)
    output_path = args.output or absolute(benchmark["results_dir"]) / (
        f"final-benchmark-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    document: dict[str, object] = {
        "benchmark_version": "v2.7.2b-3",
        "phase": "final_benchmark",
        "started_at": timestamp.isoformat(),
        "prompt_family": frozen_prompt["family"],
        "prompt_sha256": frozen_prompt["sha256"],
        "runtime_profiles": [profile.model_dump(mode="json") for profile in profiles],
        "case_ids": [case.job.id for case in cases],
        "run_indices": run_indices,
        "seed_sources": [str(path) for path in (args.seed_paths or [])],
        "observations": [],
        "metrics": {},
        "segment_metrics": {},
        "default_model_recommendation": None,
    }
    observations: list[ModelBenchmarkObservation] = []
    if args.resume and output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        for field in (
            "prompt_family",
            "prompt_sha256",
            "runtime_profiles",
            "case_ids",
            "run_indices",
        ):
            if previous.get(field) != document[field]:
                raise ValueError(f"cannot resume: {field} differs from current plan")
        observations = [
            ModelBenchmarkObservation.model_validate(item)
            for item in previous.get("observations", [])
        ]
        document["started_at"] = previous.get("started_at", document["started_at"])
        document["seed_sources"] = previous.get("seed_sources", [])
        document["observations"] = [
            item.model_dump(mode="json") for item in observations
        ]
        document["metrics"] = grouped_metrics(
            observations, cases, config["known_absent_candidate_skills"]
        )
        document["segment_metrics"] = grouped_segment_metrics(
            observations, cases, config["known_absent_candidate_skills"]
        )
    elif args.seed_paths:
        profile_by_model = {
            profile.model_id: profile.model_dump(mode="json") for profile in profiles
        }
        allowed_cases = {case.job.id for case in cases}
        for seed_path in args.seed_paths:
            seed = json.loads(seed_path.resolve().read_text(encoding="utf-8"))
            for field in ("prompt_family", "prompt_sha256"):
                if seed.get(field) != document[field]:
                    raise ValueError(f"seed input disagrees on {field}")
            seed_profiles = {
                item["model_id"]: item for item in seed.get("runtime_profiles", [])
            }
            for model_id, profile in profile_by_model.items():
                if seed_profiles.get(model_id) != profile:
                    raise ValueError(
                        f"seed runtime profile differs for finalist {model_id}"
                    )
            for item in seed.get("observations", []):
                observation = ModelBenchmarkObservation.model_validate(item)
                if (
                    observation.model_id in profile_by_model
                    and observation.case_id in allowed_cases
                    and observation.run_index in run_indices
                ):
                    observations.append(observation)
        seed_keys = [
            (item.model_id, item.case_id, item.run_index) for item in observations
        ]
        if len(seed_keys) != len(set(seed_keys)):
            raise ValueError("seed inputs contain duplicate finalist observations")
        document["observations"] = [
            item.model_dump(mode="json") for item in observations
        ]
        document["metrics"] = grouped_metrics(
            observations, cases, config["known_absent_candidate_skills"]
        )
        document["segment_metrics"] = grouped_segment_metrics(
            observations, cases, config["known_absent_candidate_skills"]
        )

    if args.dry_run:
        total = len(profiles) * len(cases) * runs
        document["planned_evaluations"] = total
        document["seeded_evaluations"] = len(observations)
        document["remaining_evaluations"] = total - len(observations)
        print(json.dumps(document, indent=2, ensure_ascii=False))
        return
    completed = {
        (item.model_id, item.case_id, item.run_index) for item in observations
    }
    candidate_profile = load_candidate_profile(profile_path)
    for profile in profiles:
        remaining_for_profile = any(
            (profile.model_id, case.job.id, run_index) not in completed
            for run_index in run_indices
            for case in cases
        )
        if not remaining_for_profile:
            continue
        prepare_exclusive_model(
            profile.model_id,
            base_url=profile.base_url,
            context_length=profile.context_length,
            gpu_offload=runtime["gpu_offload"],
            parallel_requests=runtime["parallel_requests"],
        )
        for run_index in run_indices:
            for case in cases:
                key = (profile.model_id, case.job.id, run_index)
                if key in completed:
                    continue
                observation = evaluate_model_case(
                    phase="final_benchmark",
                    profile=profile,
                    case=case,
                    candidate_profile=candidate_profile,
                    run_index=run_index,
                )
                observations.append(observation)
                document["observations"] = [
                    item.model_dump(mode="json") for item in observations
                ]
                document["metrics"] = grouped_metrics(
                    observations, cases, config["known_absent_candidate_skills"]
                )
                document["segment_metrics"] = grouped_segment_metrics(
                    observations, cases, config["known_absent_candidate_skills"]
                )
                write_result(output_path, document)
                print(
                    f"{profile.model_id} case={case.job.id} run={run_index} "
                    f"status={observation.status} latency={observation.latency_seconds:.2f}s",
                    flush=True,
                )

    selection = benchmark["selection"]
    model_id, reason = select_default_model(
        document["metrics"],
        efficiency_preference=selection["efficiency_preference"],
        similar_accuracy_margin=float(selection["similar_accuracy_margin"]),
        material_large_error_difference=int(
            selection["material_large_error_difference"]
        ),
        max_failure_rate=float(selection["max_failure_rate"]),
        max_timeout_rate=float(selection["max_timeout_rate"]),
        max_candidate_hallucinations=int(
            selection["max_candidate_hallucinations"]
        ),
    )
    document["default_model_recommendation"] = {
        "model_id": model_id,
        "reason": reason,
    }
    document["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_result(output_path, document)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "default_model_recommendation": document[
                    "default_model_recommendation"
                ],
                "metrics": document["metrics"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
