import pandas as pd

from api.scraper import (
    _clean_str,
    infer_level,
    run_scrape,
)


def test_clean_str_handles_nan_variants():
    assert _clean_str("nan") == ""
    assert _clean_str("None") == ""
    assert _clean_str(None) == ""
    assert _clean_str(float("nan")) == ""
    assert _clean_str(" Hello   World ") == "Hello World"


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
            "search": {
                "query_groups": [
                    {
                        "name": "Software Development",
                        "queries": ["Python Developer"],
                    }
                ],
                "locations": [
                    {"city": "Karlsruhe", "country": "Germany", "radius_km": 100}
                ],
                "results_per_query": 50,
                "hours_old": 168,
            },
            "companies": [],
            "hard_filters": {"excluded_title_terms": []},
            "signals": {
                "role_terms": [{"points": 25, "terms": ["python developer"]}],
                "technologies": [{"points": 8, "terms": ["python", "fastapi"]}],
                "junior_title_terms": ["junior"],
            },
            "legacy_scoring": {
                "base_points": 30,
                "technology_points_cap": 25,
                "watchlist_bonus": 8,
                "junior_bonus": 5,
            },
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
            },
            {
                "id": "job-2",
                "site": "indeed",
                "title": "Director Python Developer",
                "company": "Example AG",
                "location": "Karlsruhe, Germany",
                "job_url": "https://example.com/jobs/2",
                "description": "Python leadership role.",
                "date_posted": "2026-08-30",
                "is_remote": False,
            },
        ],
    )
    monkeypatch.setattr("api.scraper.time.sleep", lambda _seconds: None)

    response = run_scrape()

    assert response.total_found == 2
    assert response.total_after_filter == 1
    assert response.failed_searches == 0
    assert response.hard_filter_rejections == {"excluded_seniority": 1}
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


def test_discovered_jobs_do_not_require_query_term_in_title(monkeypatch):
    monkeypatch.setattr(
        "api.scraper.load_config",
        lambda: {
            "search": {
                "query_groups": [
                    {
                        "name": "Broad Digital Roles",
                        "queries": ["process automation"],
                    }
                ],
                "locations": [{"city": "Karlsruhe", "country": "Germany"}],
                "results_per_query": 10,
                "hours_old": 168,
            },
            "companies": [],
            "hard_filters": {"excluded_title_terms": []},
            "signals": {
                "role_terms": [],
                "technologies": [],
                "junior_title_terms": ["junior"],
            },
            "legacy_scoring": {"base_points": 30, "junior_bonus": 5},
        },
    )
    titles = [
        "Junior Consultant Digital Transformation",
        "Business Process Analyst",
        "Supply Chain Digitalization Specialist",
        "SAP Process Consultant",
        "Director Process Automation",
    ]
    monkeypatch.setattr(
        "api.scraper.fetch_jobs",
        lambda **kwargs: [
            {
                "id": f"job-{index}",
                "site": "linkedin",
                "title": title,
                "company": "Example GmbH",
                "location": "Karlsruhe, Germany",
                "job_url": f"https://example.com/jobs/{index}",
                "description": "",
            }
            for index, title in enumerate(titles)
        ],
    )
    monkeypatch.setattr("api.scraper.time.sleep", lambda _seconds: None)

    response = run_scrape()

    assert [job.title for job in response.jobs] == titles[:4]
    assert all(job.score in {30, 35} for job in response.jobs)
    assert response.hard_filter_rejections == {"excluded_seniority": 1}
