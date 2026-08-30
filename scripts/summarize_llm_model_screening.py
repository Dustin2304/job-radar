#!/usr/bin/env python3
"""Aggregate repeated model-screening runs and recommend benchmark finalists."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import yaml

from api.llm_benchmark import LLMBenchmarkLabels, load_llm_benchmark, validate_benchmark_freeze
from api.llm_model_screening import ModelBenchmarkObservation, model_screening_metrics
from api.llm_prompt_calibration import load_prompt_calibration_subset

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "llm_benchmark.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def metric_value(metrics: dict[str, object], name: str, default: float) -> float:
    value = metrics.get(name)
    return default if value is None else float(value)


def finalist_ids(metrics: dict[str, dict[str, object]], count: int) -> list[str]:
    practical = [
        (key.removeprefix("model:").removesuffix(":all"), values)
        for key, values in metrics.items()
        if key.endswith(":all")
        and metric_value(values, "failure_rate", 1) <= 0.25
        and metric_value(values, "timeout_rate", 1) <= 0.25
        and values.get("candidate_hallucination_count") == 0
    ]
    practical.sort(
        key=lambda item: (
            item[1].get("large_recommendation_errors", 0),
            -metric_value(item[1], "recommendation_accuracy", 0),
            metric_value(item[1], "mean_ordinal_error", float("inf")),
            -metric_value(item[1], "recommendation_stability", 0),
            metric_value(item[1], "median_latency_seconds", float("inf")),
        )
    )
    return [model_id for model_id, _ in practical[:count]]


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    prompt_config = config["prompt_calibration"]
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

    documents = [
        json.loads(path.resolve().read_text(encoding="utf-8")) for path in args.inputs
    ]
    expected = documents[0]
    for document in documents:
        for field in ("prompt_family", "prompt_sha256", "runtime_profiles", "case_ids"):
            if document.get(field) != expected.get(field):
                raise ValueError(f"screening inputs disagree on {field}")

    observations = [
        ModelBenchmarkObservation.model_validate(item)
        for document in documents
        for item in document.get("observations", [])
    ]
    keys = [
        (item.model_id, item.case_id, item.run_index) for item in observations
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("screening inputs contain duplicate model/case/run observations")

    metrics: dict[str, dict[str, object]] = {}
    absent = config["known_absent_candidate_skills"]
    for model_id in sorted({item.model_id for item in observations}):
        selected = [item for item in observations if item.model_id == model_id]
        metrics[f"model:{model_id}:all"] = model_screening_metrics(
            selected, cases, known_absent_candidate_skills=absent
        )

    count = int(config["model_screening"].get("finalist_count", 2))
    output = {
        "benchmark_version": "v2.7.2b-2",
        "phase": "model_screening_summary",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": [str(path) for path in args.inputs],
        "prompt_family": expected["prompt_family"],
        "prompt_sha256": expected["prompt_sha256"],
        "run_indices": sorted({item.run_index for item in observations}),
        "metrics": metrics,
        "recommended_finalists": finalist_ids(metrics, count),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
