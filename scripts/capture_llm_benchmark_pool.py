#!/usr/bin/env python3
"""Capture a private candidate pool for manual LLM benchmark selection."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from api.embeddings import get_semantic_classifier, get_semantic_profile_classifier
from api.filters import evaluate_hard_filters
from api.normalization import normalize_job
from api.scorer import apply_pre_score, calculate_pre_score
from api.scraper import load_config
from api.sources.jobspy import fetch_jobs

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "evaluation" / "llm-benchmark-pool.json"

FULL_DESCRIPTION_QUERIES = (
    "power platform",
    "power automate",
    "automation specialist",
    "data analyst",
    "business intelligence",
    "data engineer",
    "business analyst IT",
    "process analyst",
    "digital transformation consultant",
    "IT consultant",
    "python developer",
    "application developer",
    "reporting specialist",
    "technical project coordinator IT",
    "project coordinator IT",
    "process automation specialist",
    "supply chain analyst",
    "project manager automation",
    "cloud data engineer",
    "SAP consultant junior",
    "manufacturing process engineer",
    "revenue operations analyst",
    "quality process specialist",
    "frontend developer",
    "mechanical engineer",
    "sales operations specialist",
    "payroll specialist",
    "procurement specialist",
    "supply chain planner",
)

TITLE_ONLY_QUERIES = (
    "junior automation engineer",
    "junior data engineer",
    "junior business intelligence",
    "junior IT project manager",
    "junior process consultant",
    "junior supply chain analyst",
    "frontend developer",
    "sales account executive",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--results-per-query", type=int, default=4)
    parser.add_argument("--target-per-query", type=int, default=2)
    parser.add_argument("--limit", type=int, default=64)
    parser.add_argument("--location", default="Karlsruhe")
    parser.add_argument("--country", default="Germany")
    parser.add_argument("--hours-old", type=int, default=720)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise FileExistsError(f"benchmark pool already exists: {output_path}")

    config = load_config()
    semantic_classifier = get_semantic_classifier(config.get("embeddings"))
    profile_classifier = get_semantic_profile_classifier(config.get("embeddings"))
    jobs = []
    capture_hints: dict[str, dict[str, str]] = {}
    failures = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()

    query_specs = [
        (query, ("indeed",), "available") for query in FULL_DESCRIPTION_QUERIES
    ]
    query_specs.extend(
        (query, ("linkedin",), "missing") for query in TITLE_ONLY_QUERIES
    )

    for query, sites, intended_status in query_specs:
        if len(jobs) >= args.limit:
            break
        try:
            raw_jobs = fetch_jobs(
                search_query=query,
                location=args.location,
                country=args.country,
                results_wanted=args.results_per_query,
                hours_old=args.hours_old,
                radius_km=100,
                sites=sites,
                linkedin_fetch_description=False,
            )
        except Exception as exc:  # Preserve partial capture for manual inspection.
            failures.append({"query": query, "sites": list(sites), "error": str(exc)})
            continue

        accepted_for_query = 0
        for raw_job in raw_jobs:
            job = normalize_job(raw_job, query)
            title_company = (job.title.casefold(), job.company.casefold())
            if (
                job.id in seen_ids
                or job.url in seen_urls
                or title_company in seen_title_company
                or not job.url
                or not evaluate_hard_filters(job).accepted
                or job.description_status != intended_status
            ):
                continue

            score = calculate_pre_score(
                job,
                signals=config.get("signals", {}),
                pre_score_config=config.get("pre_score", {}),
            )
            job = apply_pre_score(job, score)
            if semantic_classifier is not None:
                job = semantic_classifier.classify(job)
            if profile_classifier is not None:
                job = profile_classifier.classify(job)

            seen_ids.add(job.id)
            seen_urls.add(job.url)
            seen_title_company.add(title_company)
            jobs.append(job)
            capture_hints[job.id] = {
                "query": query,
                "intended_description_status": intended_status,
            }
            accepted_for_query += 1
            if accepted_for_query >= args.target_per_query or len(jobs) >= args.limit:
                break
        time.sleep(0.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "benchmark_version": "v2.7.2",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "jobs": [job.model_dump(mode="json") for job in jobs],
                "capture_hints": capture_hints,
                "failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "jobs": len(jobs),
                "description_available": sum(
                    job.description_status == "available" for job in jobs
                ),
                "title_only": sum(job.description_status == "missing" for job in jobs),
                "embedding_success": sum(
                    job.embedding_status == "success"
                    and job.profile_embedding_status == "success"
                    for job in jobs
                ),
                "failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
