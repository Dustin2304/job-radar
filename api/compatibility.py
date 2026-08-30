"""Temporary adapters that keep the V1 API contract available during V2 work."""

from __future__ import annotations

from typing import Literal, cast

from .models import Job, JobResult
from .scorer import summarize_pre_score


def to_v1_job_result(
    job: Job,
    *,
    profile: str,
    level: str,
    in_watchlist: bool,
) -> JobResult:
    """Adapt a canonical job to the response consumed by the current n8n workflow."""
    source = job.source if job.source in {"indeed", "linkedin"} else "indeed"
    return JobResult(
        title=job.title,
        company=job.company,
        location=job.location or "",
        url=job.url,
        source=cast(Literal["indeed", "linkedin"], source),
        date_posted=job.date_posted or "",
        is_remote=job.is_remote,
        description=job.description[:500],
        level=level,
        profile=profile,
        in_watchlist=in_watchlist,
        skills_required=[],
        pre_score=job.pre_score,
        pre_score_components=job.pre_score_components,
        score=round(job.pre_score or 0),
        score_reason=summarize_pre_score(job.pre_score_components),
    )


__all__ = ["to_v1_job_result"]
