#!/usr/bin/env python3
"""Aggregate private prompt-calibration checkpoints across configured anchors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from api.llm_benchmark import load_llm_benchmark
from api.llm_prompt_calibration import (
    PromptCalibrationObservation,
    calibration_metrics,
    load_prompt_calibration_subset,
)

ROOT = Path(__file__).resolve().parent.parent


def absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--runs-per-case", type=int, default=1)
    parser.add_argument("--prompt", action="append", dest="prompts")
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config" / "llm_benchmark.yaml"
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    calibration = config["prompt_calibration"]
    jobs_path = absolute(calibration["jobs_path"])
    labels_path = absolute(calibration["labels_path"])
    cases = load_prompt_calibration_subset(
        absolute(calibration["subset_path"]),
        load_llm_benchmark(jobs_path, labels_path),
        jobs_path,
        labels_path,
    )
    configured_models = {item["id"] for item in calibration["anchor_models"]}
    prompts = args.prompts or list(calibration["prompts"])
    observations: list[PromptCalibrationObservation] = []
    for result_path in args.results:
        document = json.loads(result_path.resolve().read_text(encoding="utf-8"))
        observations.extend(
            PromptCalibrationObservation.model_validate(item)
            for item in document["observations"]
            if item["model_id"] in configured_models
            and item["prompt_family"] in prompts
        )

    expected = {
        (model, prompt, case.job.id, run_index)
        for model in configured_models
        for prompt in prompts
        for case in cases
        for run_index in range(1, args.runs_per_case + 1)
    }
    actual = {
        (item.model_id, item.prompt_family, item.case_id, item.run_index)
        for item in observations
    }
    if actual != expected:
        raise ValueError(
            f"calibration matrix is incomplete: missing={len(expected - actual)}, "
            f"unexpected={len(actual - expected)}"
        )

    metrics = {
        prompt: calibration_metrics(
            [item for item in observations if item.prompt_family == prompt],
            cases,
            known_absent_candidate_skills=config["known_absent_candidate_skills"],
        )
        for prompt in prompts
    }
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
