from datetime import datetime, timezone

from api.main import jobs_stats
from api.models import DescriptionSourceStats, DescriptionStats, ScrapeResponse


def test_stats_endpoint_exposes_description_availability(monkeypatch):
    cached = ScrapeResponse(
        jobs=[],
        total_found=3,
        total_after_filter=0,
        scraped_at=datetime.now(timezone.utc),
        profiles_searched=["Discovery"],
        description_stats=DescriptionStats(
            total=3,
            available=2,
            missing=1,
            by_source={
                "indeed": DescriptionSourceStats(available=2, missing=0),
                "linkedin": DescriptionSourceStats(available=0, missing=1),
            },
        ),
    )
    monkeypatch.setattr("api.main.read_cache", lambda: cached)

    response = jobs_stats()

    assert response.description_stats == cached.description_stats
    assert response.description_stats.by_source["linkedin"].missing == 1
