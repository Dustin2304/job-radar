import pandas as pd

from api.sources import jobspy


def test_fetch_jobs_contains_jobspy_specific_parameters(monkeypatch):
    received = {}

    def fake_scrape_jobs(**kwargs):
        received.update(kwargs)
        return pd.DataFrame([{"id": "job-1", "title": "Data Engineer"}])

    monkeypatch.setattr(jobspy, "scrape_jobs", fake_scrape_jobs)

    jobs = jobspy.fetch_jobs(
        search_query="data engineer",
        location="Karlsruhe",
        country="Germany",
        results_wanted=50,
        hours_old=168,
        radius_km=100,
    )

    assert jobs == [{"id": "job-1", "title": "Data Engineer"}]
    assert received == {
        "site_name": ["indeed", "linkedin"],
        "search_term": "data engineer",
        "location": "Karlsruhe",
        "results_wanted": 50,
        "hours_old": 168,
        "country_indeed": "Germany",
        "description_format": "markdown",
        "verbose": 0,
        "distance": 62,
    }


def test_linkedin_detail_fetch_is_explicit_and_marks_raw_source(monkeypatch):
    received = {}

    def fake_scrape_jobs(**kwargs):
        received.update(kwargs)
        return pd.DataFrame(
            [
                {
                    "id": "linkedin-1",
                    "site": "linkedin",
                    "title": "Automation Engineer",
                    "description": "Full LinkedIn description",
                }
            ]
        )

    monkeypatch.setattr(jobspy, "scrape_jobs", fake_scrape_jobs)

    jobs = jobspy.fetch_jobs(
        search_query="automation",
        location="Karlsruhe",
        country="Germany",
        results_wanted=5,
        hours_old=168,
        sites=["linkedin"],
        linkedin_fetch_description=True,
    )

    assert received["site_name"] == ["linkedin"]
    assert received["linkedin_fetch_description"] is True
    assert jobs[0]["_description_source"] == "detail_fetch"
