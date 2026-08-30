"""Data-quality summaries for canonical jobs."""

from __future__ import annotations

from collections.abc import Iterable

from .models import DescriptionSourceStats, DescriptionStats, Job


def build_description_stats(jobs: Iterable[Job]) -> DescriptionStats:
    """Summarize description availability for unique canonical jobs by source."""
    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        existing = unique_jobs.get(job.id)
        if existing is None or (
            existing.description_status == "missing"
            and job.description_status == "available"
        ):
            unique_jobs[job.id] = job

    by_source: dict[str, DescriptionSourceStats] = {}
    available = 0
    missing = 0
    for job in unique_jobs.values():
        source_counts = by_source.setdefault(job.source, DescriptionSourceStats())
        if job.description_status == "available":
            available += 1
            source_counts.available += 1
        else:
            missing += 1
            source_counts.missing += 1

    return DescriptionStats(
        total=len(unique_jobs),
        available=available,
        missing=missing,
        by_source=by_source,
    )


__all__ = ["build_description_stats"]
