import pandas as pd

from api.scraper import (
    _clean_str,
    infer_level,
    run_scrape,
)

TEST_SIGNALS = {
    "role_terms": [
        {"name": "digitalization", "terms": ["digital transformation", "digitalization"]},
        {"name": "process_analysis", "terms": ["business process analyst"]},
        {"name": "consulting", "terms": ["consultant"]},
        {"name": "supply_chain", "terms": ["supply chain"]},
    ],
    "technologies": [
        {"name": "python", "terms": ["python"]},
        {"name": "fastapi", "terms": ["fastapi"]},
    ],
}
TEST_PRE_SCORE = {
    "seniority": {
        "max_score": 25,
        "explicit_junior_score": 25,
        "neutral_score": 17,
        "positive_title_terms": ["junior"],
    },
    "technologies": {"max_score": 30, "points_per_match": 5},
    "role": {
        "max_score": 25,
        "title_points_per_match": 6,
        "description_points_per_match": 3,
    },
    "location": {
        "max_score": 20,
        "preferred_location_terms": ["karlsruhe"],
        "remote_terms": ["remote"],
        "hybrid_terms": ["hybrid"],
        "remote_score": 20,
        "preferred_hybrid_score": 20,
        "preferred_onsite_score": 17,
        "other_hybrid_score": 10,
        "other_onsite_score": 5,
        "unknown_score": 10,
    },
}


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
            "signals": TEST_SIGNALS,
            "pre_score": TEST_PRE_SCORE,
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
        "description_status",
        "description_length",
        "description_source",
        "level",
        "profile",
        "in_watchlist",
        "skills_required",
        "pre_score",
        "pre_score_components",
        "score",
        "score_reason",
    }
    assert response.jobs[0].title == "Junior Python Developer"
    assert response.jobs[0].pre_score is not None
    assert response.jobs[0].score == round(response.jobs[0].pre_score)
    assert response.jobs[0].pre_score_components is not None
    assert response.description_stats.model_dump() == {
        "total": 2,
        "available": 2,
        "missing": 0,
        "by_source": {
            "linkedin": {"available": 1, "missing": 0},
            "indeed": {"available": 1, "missing": 0},
        },
    }


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
            "signals": TEST_SIGNALS,
            "pre_score": TEST_PRE_SCORE,
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

    assert {job.title for job in response.jobs} == set(titles[:4])
    assert all(job.pre_score is not None for job in response.jobs)
    assert all(job.pre_score_components is not None for job in response.jobs)
    assert response.hard_filter_rejections == {"excluded_seniority": 1}
    assert response.description_stats.total == 5
    assert response.description_stats.available == 0
    assert response.description_stats.missing == 5
    assert response.description_stats.by_source["linkedin"].missing == 5
