#!/usr/bin/env python3
"""
api/scraper.py
Scrapes job postings via python-jobspy, driven entirely by config.yaml.
Returns a ScrapeResponse JSON to stdout.
Run via python -m api.scraper.
"""

import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import yaml

from .compatibility import to_v1_job_result
from .embeddings import get_semantic_classifier
from .filters import apply_filter_result, evaluate_hard_filters
from .models import Job, JobResult, ScrapeResponse
from .normalization import clean_string, merge_search_queries, normalize_job
from .observability import build_description_stats
from .scorer import apply_pre_score, calculate_pre_score
from .sources.jobspy import fetch_jobs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)

LEVEL_MAP = {
    "internship": "Entry",
    "entry level": "Entry",
    "entry-level": "Entry",
    "associate": "Entry",
    "junior": "Entry",
    "mid-senior level": "Mid",
    "mid level": "Mid",
    "mid-level": "Mid",
    "mid": "Mid",
    "senior": "Senior",
    "director": "Senior",
    "executive": "Senior",
    "c-suite": "Senior",
    "vice president": "Senior",
}

_LEVEL_ENTRY_PATTERN = re.compile(
    r"\b(junior|jr\.?|entry[- ]level|trainee|absolvent|berufseinsteiger)\b",
    re.IGNORECASE,
)
_LEVEL_SENIOR_PATTERN = re.compile(
    r"\b(senior|sr\.?|principal|lead|staff|head of|director)\b",
    re.IGNORECASE,
)
_LEVEL_MID_PATTERN = re.compile(
    r"\b(mid[- ]level|mid[- ]senior)\b",
    re.IGNORECASE,
)


def _clean_str(value) -> str:
    """Normalize scraper cell values: strip, collapse whitespace, reject 'nan'/'none'/'null'."""
    return clean_string(value)


def load_config() -> dict:
    config_path = ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def company_in_watchlist(company_name: str, watchlist: list[str]) -> bool:
    if not company_name:
        return False
    name_lower = company_name.lower()
    return any(w.lower() in name_lower or name_lower in w.lower() for w in watchlist)


def map_level(raw_level: str | None) -> str:
    if not raw_level:
        return "Unknown"
    return LEVEL_MAP.get(raw_level.strip().lower(), "Unknown")


def infer_level(raw_level: str | None, title: str) -> str:
    mapped_level = map_level(raw_level)
    if mapped_level != "Unknown":
        return mapped_level

    if _LEVEL_ENTRY_PATTERN.search(title):
        return "Entry"
    if _LEVEL_SENIOR_PATTERN.search(title):
        return "Senior"
    if _LEVEL_MID_PATTERN.search(title):
        return "Mid"
    return "Unknown"


def run_scrape() -> ScrapeResponse:
    cfg = load_config()

    search_cfg: dict = cfg["search"]
    query_groups: list[dict] = search_cfg["query_groups"]
    locations: list[dict] = search_cfg["locations"]
    results_per_query: int = int(search_cfg.get("results_per_query", 50))
    hours_old: int = int(search_cfg.get("hours_old", 168))
    linkedin_fetch_description: bool = bool(
        search_cfg.get("linkedin_fetch_description", False)
    )
    watchlist: list[str] = [c["name"] for c in cfg.get("companies", [])]
    signals: dict = cfg.get("signals", {})
    pre_score_config: dict = cfg.get("pre_score", {})
    semantic_classifier = get_semantic_classifier(cfg.get("embeddings"))
    config_excludes = cfg.get("hard_filters", {}).get("excluded_title_terms", [])

    seen_urls: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()
    canonical_jobs_by_url: dict[str, Job] = {}
    hard_filtered_jobs_by_id: dict[str, Job] = {}
    observed_jobs_by_id: dict[str, Job] = {}
    hard_filter_counts: Counter[str] = Counter()
    all_jobs: list[JobResult] = []
    total_raw = 0
    failed_searches = 0

    for query_group in query_groups:
        discovery_group: str = query_group["name"]
        queries: list[str] = query_group["queries"]

        for query in queries:
            for loc in locations:
                city: str = loc["city"]
                country: str = loc["country"]
                is_remote: bool = loc.get("is_remote", False)
                radius_km: int = loc.get("radius_km", 0)

                try:
                    raw_jobs = fetch_jobs(
                        search_query=query,
                        location=city,
                        country=country,
                        results_wanted=results_per_query,
                        hours_old=hours_old,
                        radius_km=radius_km,
                        is_remote=is_remote,
                        linkedin_fetch_description=linkedin_fetch_description,
                    )
                except RuntimeError:
                    raise
                except (ConnectionError, TimeoutError, OSError) as exc:
                    log.warning("Search failed (network) [%s / %s / %s]: %s", discovery_group, query, city, exc)
                    failed_searches += 1
                    time.sleep(3.0)
                    continue
                except (ValueError, KeyError) as exc:
                    log.warning("Search failed (data) [%s / %s / %s]: %s", discovery_group, query, city, exc)
                    failed_searches += 1
                    time.sleep(1.5)
                    continue
                except Exception:
                    log.exception("Search failed (unexpected) [%s / %s / %s]", discovery_group, query, city)
                    failed_searches += 1
                    time.sleep(1.5)
                    continue

                if not raw_jobs:
                    time.sleep(1.5)
                    continue

                total_raw += len(raw_jobs)

                for raw_job in raw_jobs:
                    canonical_job = normalize_job(raw_job, query)
                    observed_job = observed_jobs_by_id.get(canonical_job.id)
                    if observed_job is None or (
                        observed_job.description_status == "missing"
                        and canonical_job.description_status == "available"
                    ):
                        observed_jobs_by_id[canonical_job.id] = canonical_job

                    raw_url = _clean_str(raw_job.get("job_url", ""))
                    if not raw_url:
                        continue

                    previous_rejection = hard_filtered_jobs_by_id.get(canonical_job.id)
                    if previous_rejection is not None:
                        hard_filtered_jobs_by_id[canonical_job.id] = merge_search_queries(
                            previous_rejection, canonical_job.search_queries
                        )
                        continue

                    if raw_url in seen_urls:
                        known_job = canonical_jobs_by_url.get(raw_url)
                        if known_job is not None:
                            canonical_jobs_by_url[raw_url] = merge_search_queries(
                                known_job, canonical_job.search_queries
                            )
                        continue

                    title = canonical_job.title
                    filter_result = evaluate_hard_filters(
                        canonical_job,
                        extra_excluded_title_terms=config_excludes,
                    )
                    canonical_job = apply_filter_result(canonical_job, filter_result)
                    if not filter_result.accepted:
                        hard_filtered_jobs_by_id[canonical_job.id] = canonical_job
                        hard_filter_counts.update(
                            reason.code for reason in filter_result.reasons
                        )
                        log.info(
                            "Hard filter rejected job_id=%s reasons=%s",
                            canonical_job.id,
                            [reason.model_dump() for reason in filter_result.reasons],
                        )
                        continue

                    company = canonical_job.company
                    job_level_raw = _clean_str(raw_job.get("job_level", "")) or None

                    dedup_key = (title.lower(), company.lower())
                    if dedup_key in seen_title_company:
                        continue

                    seen_urls.add(raw_url)
                    seen_title_company.add(dedup_key)

                    pre_score_result = calculate_pre_score(
                        canonical_job,
                        signals=signals,
                        pre_score_config=pre_score_config,
                    )
                    canonical_job = apply_pre_score(canonical_job, pre_score_result)
                    if semantic_classifier is not None:
                        canonical_job = semantic_classifier.classify(canonical_job)
                    canonical_jobs_by_url[raw_url] = canonical_job

                    job = to_v1_job_result(
                        canonical_job,
                        profile=discovery_group,
                        in_watchlist=company_in_watchlist(company, watchlist),
                        level=infer_level(job_level_raw, title),
                    )
                    all_jobs.append(job)

                time.sleep(1.5)

    all_jobs.sort(key=lambda j: j.score, reverse=True)

    log.info(
        "Scrape summary: raw=%d | kept=%d | hard_filtered=%d | failed=%d",
        total_raw,
        len(all_jobs),
        len(hard_filtered_jobs_by_id),
        failed_searches,
    )

    return ScrapeResponse(
        jobs=all_jobs,
        total_found=total_raw,
        total_after_filter=len(all_jobs),
        scraped_at=datetime.now(timezone.utc),
        profiles_searched=[group["name"] for group in query_groups],
        failed_searches=failed_searches,
        hard_filter_rejections=dict(hard_filter_counts),
        description_stats=build_description_stats(observed_jobs_by_id.values()),
    )


if __name__ == "__main__":
    try:
        response = run_scrape()
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    print(response.model_dump_json(indent=None))
