#!/usr/bin/env python3
"""Capture an ignored real-job snapshot for manual career-profile labelling."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from api.filters import evaluate_hard_filters
from api.normalization import normalize_job
from api.sources.jobspy import fetch_jobs

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "evaluation" / "career-profile-real-world.json"
QUERY_SPECS = (
    ("automation_data", "automation engineer"),
    ("automation_data", "RPA developer"),
    ("automation_data", "python integration developer"),
    ("technical_project_management", "IT project manager"),
    ("technical_project_management", "technical project coordinator"),
    ("technical_project_management", "implementation project manager"),
    ("process_consulting", "business process analyst"),
    ("process_consulting", "process consultant"),
    ("process_consulting", "continuous improvement specialist"),
    ("data_bi", "data engineer"),
    ("data_bi", "business intelligence analyst"),
    ("data_bi", "analytics engineer"),
    ("multi_profile", "data automation consultant"),
    ("multi_profile", "business analyst automation"),
    ("no_profile_fit", "supply chain planner"),
    ("no_profile_fit", "HR payroll specialist"),
    ("no_profile_fit", "mechanical design engineer"),
    ("no_profile_fit", "frontend developer"),
    ("no_profile_fit", "sales account executive"),
    ("no_profile_fit", "procurement specialist"),
    ("no_profile_fit", "quality engineer"),
    ("no_profile_fit", "field operations associate"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--results-per-query", type=int, default=3)
    parser.add_argument("--target-per-query", type=int, default=2)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--location", default="Karlsruhe")
    parser.add_argument("--country", default="Germany")
    parser.add_argument("--hours-old", type=int, default=336)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:60] or "job"


def main() -> None:
    args = _parse_args()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise FileExistsError(f"snapshot already exists: {output_path}")

    cases: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()

    for group_hint, query in QUERY_SPECS:
        if len(cases) >= args.limit:
            break
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
        except Exception as exc:  # Capture should retain partial results.
            failures.append({"query": query, "error": str(exc)})
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
            ):
                continue
            seen_ids.add(job.id)
            seen_urls.add(job.url)
            seen_title_company.add(title_company)
            case_id = f"real-{len(cases) + 1:02d}-{_slug(job.title)}"
            cases.append(
                {
                    "id": case_id,
                    "group": group_hint,
                    "title": job.title,
                    "description": job.description,
                    "company": job.company,
                    "source": job.source,
                    "description_status": job.description_status,
                    "discovery_query": query,
                    "expected_primary": [],
                    "acceptable_secondary": [],
                    "taxonomy_fit": "unlabelled",
                }
            )
            accepted_for_query += 1
            if accepted_for_query >= args.target_per_query or len(cases) >= args.limit:
                break
        time.sleep(1.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "cases": len(cases),
                "description_available": sum(
                    case["description_status"] == "available" for case in cases
                ),
                "title_only": sum(
                    case["description_status"] == "missing" for case in cases
                ),
                "group_hints": {
                    group: sum(case["group"] == group for case in cases)
                    for group, _query in QUERY_SPECS
                },
                "failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
