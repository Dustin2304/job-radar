#!/usr/bin/env python3
"""Compare prompt families while keeping model, cases, and runtime explicit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

import yaml

from api.llm_benchmark import LLMBenchmarkLabels, load_llm_benchmark, validate_benchmark_freeze
from api.llm_evaluation import (
    LMStudioChatClient,
    PROMPT_INSTRUCTIONS,
    SHARED_SYSTEM_PROMPT,
    StructuredJobEvaluator,
    load_candidate_profile,
)
from api.llm_prompt_calibration import (
    PromptCalibrationObservation,
    calibration_metrics,
    load_prompt_calibration_subset,
    sha256_file,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "llm_benchmark.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--prompt", action="append", dest="prompts")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--runs", type=int)
    parser.add_argument("--run-index", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-model-management", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def available_model_ids(base_url: str) -> set[str]:
    with urlopen(f"{base_url.rstrip('/')}/models", timeout=10) as response:
        document = json.load(response)
    return {item["id"] for item in document["data"]}


def loaded_model_ids(base_url: str) -> set[str]:
    server_root = base_url.rstrip("/").removesuffix("/v1")
    with urlopen(f"{server_root}/api/v1/models", timeout=10) as response:
        document = json.load(response)
    return {
        instance["id"]
        for model in document["models"]
        for instance in model.get("loaded_instances", [])
    }


def load_model(model_id: str, runtime: dict[str, object]) -> None:
    if model_id in loaded_model_ids(str(runtime["base_url"])):
        return
    command = [
        "lms", "load", model_id,
        "--gpu", str(runtime["gpu_offload"]),
        "-c", str(runtime["context_length"]),
        "--parallel", str(runtime["parallel_requests"]),
        "--identifier", model_id,
        "-y",
    ]
    subprocess.run(command, check=True)


def prompt_hashes(prompts: list[str]) -> dict[str, str]:
    return {
        prompt: hashlib.sha256(
            f"{SHARED_SYSTEM_PROMPT}\n{PROMPT_INSTRUCTIONS[prompt]}".encode("utf-8")
        ).hexdigest()
        for prompt in prompts
    }


def grouped_metrics(observations, cases, absent_skills):
    result: dict[str, object] = {}
    prompts = sorted({item.prompt_family for item in observations})
    models = sorted({item.model_id for item in observations})
    for prompt in prompts:
        selected = [item for item in observations if item.prompt_family == prompt]
        result[f"prompt:{prompt}:all_models"] = calibration_metrics(
            selected, cases, known_absent_candidate_skills=absent_skills
        )
        for model in models:
            selected_model = [item for item in selected if item.model_id == model]
            if selected_model:
                result[f"prompt:{prompt}:model:{model}"] = calibration_metrics(
                    selected_model, cases, known_absent_candidate_skills=absent_skills
                )
    return result


def write_result(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    runtime = config["runtime"]
    calibration = config["prompt_calibration"]
    jobs_path = absolute(calibration["jobs_path"])
    labels_path = absolute(calibration["labels_path"])
    subset_path = absolute(calibration["subset_path"])
    profile_path = ROOT / "config" / "candidate_profile.yaml"

    cases = load_llm_benchmark(jobs_path, labels_path)
    labels = LLMBenchmarkLabels.model_validate_json(labels_path.read_text(encoding="utf-8"))
    validate_benchmark_freeze(cases, labels, profile_path)
    cases = load_prompt_calibration_subset(
        subset_path, cases, jobs_path, labels_path
    )
    if args.case_ids:
        requested_ids = set(args.case_ids)
        unknown_ids = sorted(requested_ids - {case.job.id for case in cases})
        if unknown_ids:
            raise ValueError(f"cases are not in the frozen subset: {unknown_ids}")
        cases = [case for case in cases if case.job.id in requested_ids]
    profile = load_candidate_profile(profile_path)

    configured_models = {item["id"]: item for item in calibration["anchor_models"]}
    models = args.models or list(configured_models)
    unknown_models = sorted(set(models) - configured_models.keys())
    if unknown_models:
        raise ValueError(f"models are not configured: {unknown_models}")
    prompts = args.prompts or list(calibration["prompts"])
    unknown_prompts = sorted(set(prompts) - PROMPT_INSTRUCTIONS.keys())
    if unknown_prompts:
        raise ValueError(f"unknown prompt families: {unknown_prompts}")
    frozen_prompt = calibration.get("frozen_benchmark_prompt")
    if frozen_prompt and frozen_prompt["family"] in prompts:
        family = frozen_prompt["family"]
        current_hash = prompt_hashes([family])[family]
        if current_hash != frozen_prompt["sha256"]:
            raise ValueError("frozen benchmark prompt changed after calibration")
    runs = args.runs or int(calibration["runs_per_case"])
    if runs < 1:
        raise ValueError("runs must be positive")
    if args.run_index is not None and args.run_index < 1:
        raise ValueError("run index must be positive")
    run_indices = (
        [args.run_index]
        if args.run_index is not None
        else list(range(1, runs + 1))
    )

    base_url = str(runtime["base_url"])
    available = available_model_ids(base_url)
    missing = sorted(set(models) - available)
    if missing:
        raise RuntimeError(f"configured LM Studio model IDs are unavailable: {missing}")

    timestamp = datetime.now(timezone.utc)
    output_path = args.output or absolute(calibration["results_dir"]) / (
        f"prompt-calibration-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    document: dict[str, object] = {
        "benchmark_version": "v2.7.2b-1",
        "started_at": timestamp.isoformat(),
        "runtime": runtime,
        "models": [configured_models[model] for model in models],
        "prompts": prompts,
        "prompt_sha256": prompt_hashes(prompts),
        "runs_per_case": runs,
        "run_indices": run_indices,
        "case_ids": [case.job.id for case in cases],
        "freeze": {
            "candidate_profile_sha256": sha256_file(profile_path),
            "jobs_sha256": sha256_file(jobs_path),
            "labels_sha256": sha256_file(labels_path),
        },
        "observations": [],
        "metrics": {},
    }
    if args.dry_run:
        document["planned_evaluations"] = (
            len(models) * len(prompts) * len(cases) * len(run_indices)
        )
        print(json.dumps(document, indent=2, ensure_ascii=False))
        return

    observations: list[PromptCalibrationObservation] = []
    if args.resume and output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        for field in (
            "runtime", "prompts", "runs_per_case", "run_indices", "case_ids", "freeze"
        ):
            if previous.get(field) != document[field]:
                raise ValueError(f"cannot resume: {field} differs from current plan")
        if previous.get("models") != document["models"]:
            raise ValueError("cannot resume: configured models differ from current plan")
        observations = [
            PromptCalibrationObservation.model_validate(item)
            for item in previous.get("observations", [])
        ]
        document["observations"] = previous.get("observations", [])
        document["metrics"] = previous.get("metrics", {})
    completed = {
        (item.model_id, item.prompt_family, item.case_id, item.run_index)
        for item in observations
    }
    for model_id in models:
        if not args.no_model_management:
            load_model(model_id, runtime)
        for prompt in prompts:
            for case in cases:
                for run_index in run_indices:
                    key = (model_id, prompt, case.job.id, run_index)
                    if key in completed:
                        continue
                    client = LMStudioChatClient(
                        base_url=base_url,
                        model=model_id,
                        timeout_seconds=float(runtime["timeout_seconds"]),
                        temperature=float(runtime["temperature"]),
                        max_tokens=int(runtime["max_output_tokens"]),
                        seed=int(runtime["base_seed"]) + run_index - 1,
                    )
                    evaluator = StructuredJobEvaluator(client, prompt_family=prompt)
                    started = time.perf_counter()
                    diagnostic = evaluator.evaluate_with_diagnostics(case.job, profile)
                    latency = time.perf_counter() - started
                    result = diagnostic.result
                    observation = PromptCalibrationObservation(
                        model_id=model_id,
                        prompt_family=prompt,
                        case_id=case.job.id,
                        run_index=run_index,
                        status=result.status,
                        evaluation=result.evaluation,
                        attempts=diagnostic.attempts,
                        first_pass_valid=diagnostic.first_pass_valid,
                        latency_seconds=latency,
                        error=result.error,
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
                        f"{model_id} {prompt} {case.job.id} run={run_index} "
                        f"status={result.status} latency={latency:.2f}s",
                        flush=True,
                    )

    document["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_result(output_path, document)
    print(json.dumps({"output": str(output_path), "metrics": document["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
