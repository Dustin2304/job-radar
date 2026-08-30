import pandas as pd

from api.scraper import (
    EXCLUDE_TITLE_KEYWORDS,
    _clean_str,
    _compile_exclude_pattern,
    infer_level,
    run_scrape,
)


def test_clean_str_handles_nan_variants():
    assert _clean_str("nan") == ""
    assert _clean_str("None") == ""
    assert _clean_str(None) == ""
    assert _clean_str(float("nan")) == ""
    assert _clean_str(" Hello   World ") == "Hello World"


def test_exclude_pattern_word_boundaries():
    pattern = _compile_exclude_pattern(EXCLUDE_TITLE_KEYWORDS)

    assert pattern.search("Senior Engineer")
    assert pattern.search("Sr. Developer")
    assert pattern.search("Praktikum Backend")
    assert not pattern.search("Leadership Platform Engineer")
    assert pattern.search("Experienced Python Developer")


def test_infer_level_from_title():
    assert infer_level(None, "Junior Python Developer") == "Entry"
    assert infer_level(None, "Senior Data Engineer") == "Senior"
    assert infer_level("associate", "Principal Engineer") == "Entry"


def test_clean_str_strips_pandas_nan():
    assert _clean_str(pd.NA) == ""


def test_run_scrape_keeps_v1_response_contract(monkeypatch):
    monkeypatch.setattr(
        "api.scraper.load_config",
        lambda: {
            "profiles": [
                {
                    "name": "Software Development",
                    "weight": 1.0,
                    "keywords": ["Python Developer"],
                }
            ],
            "locations": [
                {"city": "Karlsruhe", "country": "Germany", "radius_km": 100}
            ],
            "companies": [],
            "scoring": {"threshold_it": 50, "threshold_non_it": 60},
            "filters": {"exclude_title_keywords": []},
        },
    )
    monkeypatch.setattr(
        "api.scraper.fetch_jobs",
        lambda **kwargs: [
            {
                "id": "job-1",
                "site": "linkedin",
                "title": "Junior Python Developer",
                "company": "Example GmbH",
                "location": "Karlsruhe, Germany",
                "job_url": "https://example.com/jobs/1",
                "description": "Python backend development with FastAPI.",
                "date_posted": "2026-08-30",
                "is_remote": False,
            }
        ],
    )
    monkeypatch.setattr("api.scraper.time.sleep", lambda _seconds: None)

    response = run_scrape()

    assert response.total_found == 1
    assert response.total_after_filter == 1
    assert response.failed_searches == 0
    assert response.jobs[0].model_dump().keys() == {
        "title",
        "company",
        "location",
        "url",
        "source",
        "date_posted",
        "is_remote",
        "description",
        "level",
        "profile",
        "in_watchlist",
        "skills_required",
        "score",
        "score_reason",
    }
    assert response.jobs[0].title == "Junior Python Developer"
