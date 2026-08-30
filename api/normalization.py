"""Normalize source-specific job data into the canonical internal model."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Job

_MISSING_TEXT = {"", "<na>", "n/a", "nan", "none", "null"}
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {"ref", "refid", "trackingid", "trk"}


def clean_string(value: object) -> str:
    """Return a compact string while treating common dataframe nulls as empty."""
    if value is None:
        return ""

    try:
        if bool(value != value):
            return ""
    except (TypeError, ValueError):
        pass

    cleaned = re.sub(r"\s+", " ", str(value).strip())
    if cleaned.casefold() in _MISSING_TEXT:
        return ""
    return cleaned


def canonicalize_url(value: object) -> str:
    """Normalize a URL without removing query parameters that may identify a job."""
    url = clean_string(value)
    if not url:
        return ""

    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url.rstrip("/")

    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
        and not key.casefold().startswith(_TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def normalize_source(value: object) -> str:
    source = clean_string(value).casefold()
    return source or "unknown"


def _normalize_identity_part(value: object) -> str:
    return clean_string(value).casefold()


def build_job_id(
    *,
    source: str,
    source_id: str | None,
    canonical_url: str,
    company: str,
    title: str,
    location: str | None,
) -> str:
    """Prefer a source-native ID, otherwise hash stable normalized fields."""
    normalized_source = normalize_source(source)
    normalized_source_id = clean_string(source_id)
    if normalized_source_id:
        return f"{normalized_source}:{normalized_source_id}"

    identity = "\x1f".join(
        (
            normalized_source,
            canonicalize_url(canonical_url),
            _normalize_identity_part(company),
            _normalize_identity_part(title),
            _normalize_identity_part(location),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{normalized_source}:sha256:{digest}"


def _normalize_bool(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    try:
        if bool(value != value):
            return False
    except (TypeError, ValueError):
        return False
    return bool(value)


def _first_value(raw_job: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = raw_job.get(key)
        if clean_string(value):
            return value
    return None


def normalize_job(raw_job: Mapping[str, object], search_query: str) -> Job:
    """Convert one raw JobSpy record into a canonical ``Job``."""
    source = normalize_source(raw_job.get("site"))
    source_id = clean_string(_first_value(raw_job, "id", "job_id")) or None
    url = canonicalize_url(_first_value(raw_job, "job_url", "job_url_direct", "url"))
    title = clean_string(raw_job.get("title"))
    company = clean_string(raw_job.get("company"))
    location = clean_string(raw_job.get("location")) or None
    description = clean_string(raw_job.get("description"))
    raw_description_source = clean_string(raw_job.get("_description_source"))
    if not description:
        description_status = "missing"
        description_source = "unknown"
    else:
        description_status = "available"
        description_source = (
            raw_description_source
            if raw_description_source in {"search_result", "detail_fetch"}
            else "search_result"
        )

    query = clean_string(search_query)
    return Job(
        id=build_job_id(
            source=source,
            source_id=source_id,
            canonical_url=url,
            company=company,
            title=title,
            location=location,
        ),
        source_id=source_id,
        title=title,
        company=company,
        description=description,
        description_status=description_status,
        description_length=len(description),
        description_source=description_source,
        url=url,
        location=location,
        is_remote=_normalize_bool(raw_job.get("is_remote")),
        remote_type=clean_string(raw_job.get("remote_type")) or None,
        source=source,
        date_posted=clean_string(raw_job.get("date_posted")) or None,
        search_queries=[query] if query else [],
    )


def merge_search_queries(job: Job, queries: Iterable[str]) -> Job:
    """Return a copy with unique discovery queries merged in encounter order."""
    merged = list(job.search_queries)
    seen = {query.casefold() for query in merged}
    for value in queries:
        query = clean_string(value)
        if query and query.casefold() not in seen:
            merged.append(query)
            seen.add(query.casefold())
    return job.model_copy(update={"search_queries": merged})


__all__ = [
    "build_job_id",
    "canonicalize_url",
    "clean_string",
    "merge_search_queries",
    "normalize_job",
    "normalize_source",
]
