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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import yaml

from .compatibility import to_v1_job_result
from .models import Job, JobResult, ScrapeResponse
from .normalization import clean_string, merge_search_queries, normalize_job
from .scorer import score_job
from .sources.jobspy import fetch_jobs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)

HOURS_OLD = 168
RESULTS_PER_SEARCH = 50
NON_IT_PROFILES = {
    "Sales & Business Development",
    "Marketing & Content",
    "Logistics & Operations",
}

EXCLUDE_TITLE_KEYWORDS = [
    "senior",
    "(senior)",
    "sr.",
    "sr ",
    "lead",
    "tech lead",
    "team lead",
    "principal",
    "staff engineer",
    "head of",
    "director",
    "vp ",
    "c-level",
    "cto",
    "cio",
    "cpo",
    "cso",
    "chief",
    "vice president",
    "expert",
    "experienced",
    "werkstudent",
    "werkstudierende",
    "working student",
    "praktikum",
    "praktikant",
    "internship",
    "intern",
    "pflichtpraktikum",
    "praxissemester",
    "hiwi",
    "tutor",
    "thesis",
    "bachelor thesis",
    "master thesis",
    "abschlussarbeit",
    "duales studium",
    "ausbildung",
    "trainee",
    "apprentice",
    "helpdesk",
    "help desk",
    "it support",
    "it-support",
    "1st level",
    "2nd level",
    "3rd level",
    "first level",
    "second level",
    "systemadministrator",
    "sysadmin",
    "system administrator",
    "it administrator",
    "it-administrator",
    "sap berater",
    "sap consultant",
    "sap-berater",
    "salesforce",
    "servicenow",
    "oracle consultant",
    "sharepoint",
    "steuerberater",
    "wirtschaftsprüfer",
    "steuerfachangestellte",
    "außendienst",
    "sales manager",
    "vertriebsmitarbeiter",
    "pflegefachkraft",
    "krankenpflege",
    "medizinische fachangestellte",
    "fahrer",
    "lkw",
    "kraftfahrer",
    "freelance only",
    "selbstständig",
    "freiberuflich",
]

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


def _compile_exclude_pattern(keywords: list[str]) -> re.Pattern[str]:
    parts: list[str] = []
    for keyword in keywords:
        escaped = re.escape(keyword)
        if re.fullmatch(r"[A-Za-zÄÖÜäöüß0-9]+", keyword):
            parts.append(rf"\b{escaped}\b")
        else:
            parts.append(rf"(?<![a-zäöüß0-9]){escaped}(?![a-zäöüß0-9])")
    return re.compile("|".join(parts), re.IGNORECASE)


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

    profiles: list[dict] = cfg["profiles"]
    locations: list[dict] = cfg["locations"]
    watchlist: list[str] = [c["name"] for c in cfg.get("companies", [])]
    scoring_cfg: dict = cfg.get("scoring", {})
    threshold_it: int = scoring_cfg.get("threshold_it", 0)
    threshold_non_it: int = scoring_cfg.get("threshold_non_it", threshold_it)

    config_excludes = [kw.lower() for kw in cfg.get("filters", {}).get("exclude_title_keywords", [])]
    all_exclude_keywords = list(set(EXCLUDE_TITLE_KEYWORDS + config_excludes))
    exclude_pattern = _compile_exclude_pattern(all_exclude_keywords)

    seen_urls: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()
    canonical_jobs_by_url: dict[str, Job] = {}
    all_jobs: list[JobResult] = []
    total_raw = 0
    failed_searches = 0
    dropped_by_score = 0
    dropped_by_profile_mismatch = 0

    for profile in profiles:
        profile_name: str = profile["name"]
        profile_weight: float = float(profile.get("weight", 1.0))
        keywords: list[str] = profile["keywords"]
        profile_keywords_lower = [kw.lower() for kw in keywords]

        for keyword in keywords:
            for loc in locations:
                city: str = loc["city"]
                country: str = loc["country"]
                is_remote: bool = loc.get("is_remote", False)
                radius_km: int = loc.get("radius_km", 0)

                try:
                    raw_jobs = fetch_jobs(
                        search_query=keyword,
                        location=city,
                        country=country,
                        results_wanted=RESULTS_PER_SEARCH,
                        hours_old=HOURS_OLD,
                        radius_km=radius_km,
                        is_remote=is_remote,
                    )
                except RuntimeError:
                    raise
                except (ConnectionError, TimeoutError, OSError) as exc:
                    log.warning("Search failed (network) [%s / %s / %s]: %s", profile_name, keyword, city, exc)
                    failed_searches += 1
                    time.sleep(3.0)
                    continue
                except (ValueError, KeyError) as exc:
                    log.warning("Search failed (data) [%s / %s / %s]: %s", profile_name, keyword, city, exc)
                    failed_searches += 1
                    time.sleep(1.5)
                    continue
                except Exception:
                    log.exception("Search failed (unexpected) [%s / %s / %s]", profile_name, keyword, city)
                    failed_searches += 1
                    time.sleep(1.5)
                    continue

                if not raw_jobs:
                    time.sleep(1.5)
                    continue

                total_raw += len(raw_jobs)

                for raw_job in raw_jobs:
                    raw_url = _clean_str(raw_job.get("job_url", ""))
                    if not raw_url:
                        continue

                    canonical_job = normalize_job(raw_job, keyword)
                    if raw_url in seen_urls:
                        known_job = canonical_jobs_by_url.get(raw_url)
                        if known_job is not None:
                            canonical_jobs_by_url[raw_url] = merge_search_queries(
                                known_job, canonical_job.search_queries
                            )
                        continue

                    title = canonical_job.title
                    if exclude_pattern.search(title):
                        continue

                    # Positive profile match: title must contain at least one profile keyword.
                    if not any(profile_keyword in title.lower() for profile_keyword in profile_keywords_lower):
                        dropped_by_profile_mismatch += 1
                        continue

                    company = canonical_job.company
                    job_level_raw = _clean_str(raw_job.get("job_level", "")) or None

                    dedup_key = (title.lower(), company.lower())
                    if dedup_key in seen_title_company:
                        continue

                    seen_urls.add(raw_url)
                    seen_title_company.add(dedup_key)
                    canonical_jobs_by_url[raw_url] = canonical_job

                    job = to_v1_job_result(
                        canonical_job,
                        profile=profile_name,
                        in_watchlist=company_in_watchlist(company, watchlist),
                        level=infer_level(job_level_raw, title),
                    )
                    score, reason = score_job(job, weight=profile_weight)
                    job.score = score
                    job.score_reason = reason

                    threshold = threshold_non_it if profile_name in NON_IT_PROFILES else threshold_it
                    if job.score < threshold:
                        dropped_by_score += 1
                        continue

                    all_jobs.append(job)

                time.sleep(1.5)

    all_jobs.sort(key=lambda j: j.score, reverse=True)

    log.info(
        "Scrape summary: raw=%d | kept=%d | dropped_score=%d | dropped_profile=%d | failed=%d",
        total_raw,
        len(all_jobs),
        dropped_by_score,
        dropped_by_profile_mismatch,
        failed_searches,
    )

    return ScrapeResponse(
        jobs=all_jobs,
        total_found=total_raw,
        total_after_filter=len(all_jobs),
        scraped_at=datetime.now(timezone.utc),
        profiles_searched=[p["name"] for p in profiles],
        failed_searches=failed_searches,
    )


if __name__ == "__main__":
    try:
        response = run_scrape()
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    print(response.model_dump_json(indent=None))
