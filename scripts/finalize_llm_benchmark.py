#!/usr/bin/env python3
"""Freeze manually selected pool jobs into the private LLM benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.llm_benchmark import (
    LLMBenchmarkLabels,
    benchmark_summary,
    load_llm_benchmark,
    validate_benchmark_freeze,
)
from api.models import Job

ROOT = Path(__file__).resolve().parent.parent
EVALUATION_DIR = ROOT / "data" / "evaluation"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pool", type=Path, default=EVALUATION_DIR / "llm-benchmark-pool.json"
    )
    parser.add_argument(
        "--labels", type=Path, default=EVALUATION_DIR / "llm-benchmark-labels.json"
    )
    parser.add_argument(
        "--output", type=Path, default=EVALUATION_DIR / "llm-benchmark-jobs.json"
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise FileExistsError(f"frozen benchmark already exists: {output_path}")

    pool = json.loads(args.pool.resolve().read_text(encoding="utf-8"))
    label_document = LLMBenchmarkLabels.model_validate_json(
        args.labels.resolve().read_text(encoding="utf-8")
    )
    pool_jobs = {
        job.id: job for job in (Job.model_validate(item) for item in pool["jobs"])
    }
    selected_ids = [label.id for label in label_document.labels]
    missing = sorted(set(selected_ids) - pool_jobs.keys())
    if missing:
        raise ValueError(f"selected jobs are missing from capture pool: {missing}")

    snapshot = {
        "benchmark_version": label_document.benchmark_version,
        "captured_at": pool["captured_at"],
        "jobs": [pool_jobs[job_id].model_dump(mode="json") for job_id in selected_ids],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cases = load_llm_benchmark(output_path, args.labels.resolve())
    validate_benchmark_freeze(
        cases,
        label_document,
        ROOT / "config" / "candidate_profile.yaml",
    )
    print(json.dumps(benchmark_summary(cases), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
