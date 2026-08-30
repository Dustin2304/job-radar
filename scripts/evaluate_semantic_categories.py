#!/usr/bin/env python3
"""Run the V2.5.1 semantic validation against references and small live samples."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable

from api.embeddings import get_semantic_classifier
from api.filters import apply_filter_result, evaluate_hard_filters
from api.models import Job
from api.normalization import normalize_job
from api.scorer import apply_pre_score, calculate_pre_score
from api.scraper import load_config
from api.sources.jobspy import fetch_jobs

REFERENCE_TITLES = (
    "Junior Automation Engineer",
    "Data Engineer",
    "Business Process Analyst",
    "Supply Chain Planner",
    "IT Consultant Digital Transformation",
)

LIVE_QUERIES = (
    "process automation",
    "data engineer",
    "business process analyst",
    "supply chain planner",
    "IT consultant digital transformation",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Include a small JobSpy sample")
    parser.add_argument("--results-per-query", type=int, default=3)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--location", default="Karlsruhe")
    parser.add_argument("--country", default="Germany")
    parser.add_argument("--hours-old", type=int, default=336)
    return parser.parse_args()


def _reference_jobs() -> list[Job]:
    return [
        normalize_job(
            {
                "id": f"reference-{index}",
                "site": "linkedin",
                "title": title,
                "company": "Reference",
                "job_url": f"https://example.com/reference/{index}",
                "description": "",
            },
            "reference",
        )
        for index, title in enumerate(REFERENCE_TITLES)
    ]


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
        except Exception as exc:  # Validation utility should retain partial samples.
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
            job = apply_filter_result(job, filter_result)
            if filter_result.accepted:
                jobs.append(job)
            if len(jobs) >= args.limit:
                return jobs, failures
        time.sleep(1.5)

    return jobs, failures


def _evaluate(jobs: Iterable[Job], config: dict) -> list[dict[str, object]]:
    classifier = get_semantic_classifier(config.get("embeddings"))
    if classifier is None:
        raise RuntimeError("embeddings are disabled")

    results: list[dict[str, object]] = []
    for job in jobs:
        pre_score = calculate_pre_score(
            job,
            signals=config.get("signals", {}),
            pre_score_config=config.get("pre_score", {}),
        )
        classified = classifier.classify(apply_pre_score(job, pre_score))
        matches = classified.categories
        title_ranking = sorted(
            matches,
            key=lambda match: match.title_similarity,
            reverse=True,
        )
        description_ranking = sorted(
            (
                match
                for match in matches
                if match.description_similarity is not None
            ),
            key=lambda match: match.description_similarity or -1,
            reverse=True,
        )
        results.append(
            {
                "title": classified.title,
                "company": classified.company,
                "source": classified.source,
                "description_status": classified.description_status,
                "description_length": classified.description_length,
                "pre_score": classified.pre_score,
                "embedding_status": classified.embedding_status,
                "embedding_input": classified.embedding_input,
                "title_top": title_ranking[0].name if title_ranking else None,
                "description_top": (
                    description_ranking[0].name if description_ranking else None
                ),
                "combined_top": matches[0].name if matches else None,
                "categories": [
                    {
                        "name": match.name,
                        "combined": round(match.similarity, 4),
                        "title": round(match.title_similarity, 4),
                        "description": (
                            round(match.description_similarity, 4)
                            if match.description_similarity is not None
                            else None
                        ),
                    }
                    for match in matches[:3]
                ],
            }
        )
    return results


def main() -> None:
    args = _parse_args()
    config = load_config()
    live_jobs: list[Job] = []
    failures: list[dict[str, str]] = []
    if args.live:
        live_jobs, failures = _live_jobs(args)

    print(
        json.dumps(
            {
                "model": config["embeddings"]["model"],
                "dimensions": config["embeddings"]["dimensions"],
                "weights": {
                    "title": config["embeddings"]["title_weight"],
                    "description": config["embeddings"]["description_weight"],
                },
                "references": _evaluate(_reference_jobs(), config),
                "live": _evaluate(live_jobs, config),
                "live_failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
