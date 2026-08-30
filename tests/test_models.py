from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from api.models import (
    DescriptionSourceStats,
    DescriptionStats,
    JobResult,
    PreScoreResult,
    ScoreComponent,
    ScrapeResponse,
)


def test_scrape_response_default_failed_searches():
    response = ScrapeResponse(
        jobs=[],
        total_found=0,
        total_after_filter=0,
        scraped_at=datetime.now(timezone.utc),
        profiles_searched=[],
    )

    assert response.failed_searches == 0


def test_scrape_response_accepts_failed_searches():
    response = ScrapeResponse(
        jobs=[],
        total_found=0,
        total_after_filter=0,
        scraped_at=datetime.now(timezone.utc),
        profiles_searched=[],
        failed_searches=3,
    )

    assert response.failed_searches == 3


def test_job_result_score_defaults():
    job = JobResult(
        title="Python Developer",
        company="Example GmbH",
        location="Berlin, Germany",
        url="https://example.com/jobs/1",
        source="linkedin",
        date_posted="2026-04-21",
        is_remote=True,
        description="Backend role with Python focus.",
        level="Mid",
        profile="Software Engineering",
        in_watchlist=False,
        skills_required=[],
    )

    assert job.score == 0
    assert job.score_reason == ""


def test_job_result_description_max_length():
    with pytest.raises(ValidationError):
        JobResult(
            title="Python Developer",
            company="Example GmbH",
            location="Berlin, Germany",
            url="https://example.com/jobs/1",
            source="indeed",
            date_posted="2026-04-21",
            is_remote=False,
            description="x" * 600,
            level="Mid",
            profile="Software Engineering",
            in_watchlist=False,
            skills_required=[],
        )


def test_score_component_rejects_score_above_maximum():
    with pytest.raises(ValidationError):
        ScoreComponent(score=31, max_score=30)


def test_pre_score_total_must_equal_components():
    with pytest.raises(ValidationError):
        PreScoreResult(
            total=99,
            seniority=ScoreComponent(score=25, max_score=25),
            technologies=ScoreComponent(score=30, max_score=30),
            role=ScoreComponent(score=25, max_score=25),
            location=ScoreComponent(score=20, max_score=20),
        )


def test_description_stats_reject_inconsistent_source_totals():
    with pytest.raises(ValidationError):
        DescriptionStats(
            total=2,
            available=1,
            missing=1,
            by_source={
                "linkedin": DescriptionSourceStats(available=0, missing=1)
            },
        )
