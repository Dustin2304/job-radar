from api.normalization import normalize_job
from api.observability import build_description_stats


def make_job(job_id: str, source: str, description):
    return normalize_job(
        {
            "id": job_id,
            "site": source,
            "title": "Example Role",
            "company": "Example GmbH",
            "location": "Karlsruhe, Germany",
            "job_url": f"https://example.com/jobs/{job_id}",
            "description": description,
        },
        "example query",
    )


def test_description_stats_count_available_and_missing_by_source():
    stats = build_description_stats(
        [
            make_job("indeed-1", "indeed", "Full description"),
            make_job("indeed-2", "indeed", ""),
            make_job("linkedin-1", "linkedin", None),
        ]
    )

    assert stats.model_dump() == {
        "total": 3,
        "available": 1,
        "missing": 2,
        "by_source": {
            "indeed": {"available": 1, "missing": 1},
            "linkedin": {"available": 0, "missing": 1},
        },
    }


def test_description_stats_deduplicate_jobs_and_prefer_available_record():
    missing = make_job("same-job", "linkedin", None)
    available = make_job("same-job", "linkedin", "Fetched detail description")

    stats = build_description_stats([missing, available, missing])

    assert stats.total == 1
    assert stats.available == 1
    assert stats.missing == 0
