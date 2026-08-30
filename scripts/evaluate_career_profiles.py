#!/usr/bin/env python3
"""Evaluate career-profile matches against fixtures and an optional live sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from api.embeddings import (
    get_semantic_classifier,
    get_semantic_profile_classifier,
    load_career_profile_definitions,
)
from api.filters import apply_filter_result, evaluate_hard_filters
from api.models import Job
from api.normalization import normalize_job
from api.scorer import apply_pre_score, calculate_pre_score
from api.scraper import load_config
from api.semantic_benchmark import (
    SemanticRegressionCase,
    calculate_regression_metrics,
    load_regression_cases,
)
from api.sources.jobspy import fetch_jobs

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "tests" / "fixtures" / "career_profiles.json"
LIVE_QUERIES = (
    "process automation",
    "data engineer",
    "business process analyst",
    "IT project manager junior",
    "IT consultant digital transformation",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--results-per-query", type=int, default=3)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--location", default="Karlsruhe")
    parser.add_argument("--country", default="Germany")
    parser.add_argument("--hours-old", type=int, default=336)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit detailed fixture and live rankings from the JSON output",
    )
    return parser.parse_args()


def _case_job(case: SemanticRegressionCase) -> Job:
    return normalize_job(
        {
            "id": f"career-profile-{case.id}",
            "site": "linkedin",
            "title": case.title,
            "company": "Career Profile Fixture",
            "job_url": f"https://example.invalid/career-profile/{case.id}",
            "description": case.evaluation_text,
        },
        "career profile regression",
    )


def _live_jobs(args: argparse.Namespace) -> tuple[list[Job], list[dict[str, str]]]:
    jobs: list[Job] = []
    failures: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()

    for query in LIVE_QUERIES:
        try:
            raw_jobs = fetch_jobs(
                search_query=query,
                location=args.location,
                country=args.country,
                results_wanted=args.results_per_query,
                hours_old=args.hours_old,
                radius_km=100,
                sites=("indeed", "linkedin"),
                linkedin_fetch_description=False,
            )
        except Exception as exc:  # Evaluation retains partial live samples.
            failures.append({"query": query, "error": str(exc)})
            continue

        for raw_job in raw_jobs:
            job = normalize_job(raw_job, query)
            title_company = (job.title.casefold(), job.company.casefold())
            if (
                job.id in seen_ids
                or job.url in seen_urls
                or title_company in seen_title_company
                or not job.url
            ):
                continue
            seen_ids.add(job.id)
            seen_urls.add(job.url)
            seen_title_company.add(title_company)
            filter_result = evaluate_hard_filters(job)
            if filter_result.accepted:
                jobs.append(apply_filter_result(job, filter_result))
            if len(jobs) >= args.limit:
                return jobs, failures
        time.sleep(1.5)
    return jobs, failures


def _top_matches(matches, limit: int = 3) -> list[dict[str, object]]:
    return [
        {
            "name": match.name,
            "similarity": round(match.similarity, 4),
            "title_similarity": round(match.title_similarity, 4),
            "description_similarity": (
                round(match.description_similarity, 4)
                if match.description_similarity is not None
                else None
            ),
        }
        for match in matches[:limit]
    ]


def main() -> None:
    args = _parse_args()
    dataset_path = args.dataset.resolve()
    profiles = load_career_profile_definitions()
    cases = load_regression_cases(dataset_path, category_names=list(profiles))
    config = load_config()
    profile_classifier = get_semantic_profile_classifier(config.get("embeddings"))
    if profile_classifier is None:
        raise RuntimeError("embeddings are disabled")

    rankings: dict[str, list[str]] = {}
    results: list[dict[str, object]] = []
    for case in cases:
        classified = profile_classifier.classify(_case_job(case))
        if classified.profile_embedding_status != "success":
            raise RuntimeError(
                f"profile embedding failed for {case.id}: "
                f"{classified.profile_embedding_status}"
            )
        ranking = [match.name for match in classified.profile_matches]
        rankings[case.id] = ranking
        expected = set(case.expected_primary)
        best_rank = min(
            (ranking.index(name) + 1 for name in expected if name in ranking),
            default=None,
        )
        results.append(
            {
                "id": case.id,
                "group": case.group,
                "title": case.title,
                "taxonomy_fit": case.taxonomy_fit,
                "expected_primary": case.expected_primary,
                "acceptable_secondary": case.acceptable_secondary,
                "top1_correct": (
                    ranking[0] in expected if case.taxonomy_fit == "matched" else None
                ),
                "top2_recalled": (
                    bool(expected.intersection(ranking[:2]))
                    if case.taxonomy_fit == "matched"
                    else None
                ),
                "best_primary_rank": best_rank,
                "profiles": _top_matches(classified.profile_matches),
            }
        )

    live_results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    if args.live:
        category_classifier = get_semantic_classifier(config.get("embeddings"))
        if category_classifier is None:
            raise RuntimeError("embeddings are disabled")
        live_jobs, failures = _live_jobs(args)
        for job in live_jobs:
            pre_score = calculate_pre_score(
                job,
                signals=config.get("signals", {}),
                pre_score_config=config.get("pre_score", {}),
            )
            classified = category_classifier.classify(apply_pre_score(job, pre_score))
            classified = profile_classifier.classify(classified)
            live_results.append(
                {
                    "title": classified.title,
                    "company": classified.company,
                    "source": classified.source,
                    "description_status": classified.description_status,
                    "pre_score": classified.pre_score,
                    "embedding_status": classified.embedding_status,
                    "profile_embedding_status": classified.profile_embedding_status,
                    "categories": _top_matches(classified.categories),
                    "profiles": _top_matches(classified.profile_matches),
                }
            )

    regressions = [
        {
            "id": result["id"],
            "title": result["title"],
            "expected_primary": result["expected_primary"],
            "best_primary_rank": result["best_primary_rank"],
            "top_profiles": [profile["name"] for profile in result["profiles"]],
        }
        for result in results
        if result["taxonomy_fit"] == "matched" and not result["top1_correct"]
    ]
    live_summary = {
        "total": len(live_results),
        "description_available": sum(
            result["description_status"] == "available" for result in live_results
        ),
        "category_successes": sum(
            result["embedding_status"] == "success" for result in live_results
        ),
        "profile_successes": sum(
            result["profile_embedding_status"] == "success"
            for result in live_results
        ),
        "top_profile_distribution": dict(
            Counter(
                result["profiles"][0]["name"]
                for result in live_results
                if result["profiles"]
            )
        ),
        "rankings": [
            {
                "title": result["title"],
                "category_top": (
                    result["categories"][0]["name"]
                    if result["categories"]
                    else None
                ),
                "profile_top": (
                    result["profiles"][0]["name"] if result["profiles"] else None
                ),
                "profile_similarity": (
                    result["profiles"][0]["similarity"]
                    if result["profiles"]
                    else None
                ),
            }
            for result in live_results
        ],
    }
    print(
        json.dumps(
            {
                "dataset": str(dataset_path),
                "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                "model": config["embeddings"]["model"],
                "dimensions": config["embeddings"]["dimensions"],
                "weights": {
                    "title": config["embeddings"]["title_weight"],
                    "description": config["embeddings"]["description_weight"],
                },
                "metrics": calculate_regression_metrics(cases, rankings),
                "regressions": regressions,
                "cases": [] if args.summary_only else results,
                "live_summary": live_summary,
                "live": [] if args.summary_only else live_results,
                "live_failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
