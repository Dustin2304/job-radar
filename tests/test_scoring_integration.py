import json
from pathlib import Path

import pytest

from api.filters import evaluate_hard_filters
from api.normalization import normalize_job
from api.scorer import calculate_pre_score
from api.scraper import load_config

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "scoring_jobs.json"


@pytest.fixture(scope="module")
def scoring_config():
    config = load_config()
    return config["signals"], config["pre_score"]


def test_representative_job_fixtures(scoring_config):
    signals, pre_score_config = scoring_config
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for fixture in fixtures:
        job = normalize_job(fixture["raw_job"], "fixture query")
        filter_result = evaluate_hard_filters(job)

        if "expected_hard_filter" in fixture:
            assert filter_result.accepted is False, fixture["name"]
            assert fixture["expected_hard_filter"] in {
                reason.code for reason in filter_result.reasons
            }
            continue

        assert filter_result.accepted is True, fixture["name"]
        result = calculate_pre_score(
            job,
            signals=signals,
            pre_score_config=pre_score_config,
        )
        expected_range = fixture["expected_total"]
        assert expected_range["min"] <= result.total <= expected_range["max"], fixture[
            "name"
        ]
        assert set(result.technologies.matched_signals) >= set(
            fixture["expected_technologies"]
        )
        assert set(result.role.matched_signals) >= set(fixture["expected_roles"])


def test_technology_matches_are_unique_and_capped(scoring_config):
    signals, pre_score_config = scoring_config
    job = normalize_job(
        {
            "id": "technology-cap",
            "site": "linkedin",
            "title": "Junior Automation Engineer",
            "company": "Example GmbH",
            "location": "Karlsruhe, Germany",
            "job_url": "https://example.com/jobs/technology-cap",
            "description": (
                "Python, Power Automate, Power Platform, n8n, Azure, SQL, REST APIs, "
                "ETL, Power BI, Databricks, Azure Data Factory and Docker."
            ),
        },
        "automation",
    )

    result = calculate_pre_score(
        job,
        signals=signals,
        pre_score_config=pre_score_config,
    )

    assert result.technologies.score == 30
    assert result.technologies.max_score == 30
    assert len(result.technologies.matched_signals) == len(
        set(result.technologies.matched_signals)
    )


def test_title_role_match_is_stronger_than_description_match(scoring_config):
    signals, pre_score_config = scoring_config
    title_job = normalize_job(
        {
            "id": "title-role",
            "site": "linkedin",
            "title": "Automation Specialist",
            "company": "Example GmbH",
            "job_url": "https://example.com/jobs/title-role",
            "description": "",
        },
        "automation",
    )
    description_job = normalize_job(
        {
            "id": "description-role",
            "site": "linkedin",
            "title": "Specialist",
            "company": "Example GmbH",
            "job_url": "https://example.com/jobs/description-role",
            "description": "Work on automation initiatives.",
        },
        "automation",
    )

    title_result = calculate_pre_score(
        title_job, signals=signals, pre_score_config=pre_score_config
    )
    description_result = calculate_pre_score(
        description_job, signals=signals, pre_score_config=pre_score_config
    )

    assert title_result.role.score == 6
    assert description_result.role.score == 3


@pytest.mark.parametrize(
    ("location", "is_remote", "remote_type", "expected_score"),
    [
        ("Berlin, Germany", True, None, 20),
        ("Karlsruhe, Germany", False, "Hybrid", 20),
        ("Karlsruhe, Germany", False, None, 17),
        ("Berlin, Germany", False, "Hybrid", 10),
        (None, False, None, 10),
        ("Berlin, Germany", False, None, 5),
    ],
)
def test_location_component_uses_neutral_unknown_score(
    scoring_config, location, is_remote, remote_type, expected_score
):
    signals, pre_score_config = scoring_config
    job = normalize_job(
        {
            "id": f"location-{expected_score}-{location}-{remote_type}",
            "site": "indeed",
            "title": "Specialist",
            "company": "Example GmbH",
            "location": location,
            "is_remote": is_remote,
            "remote_type": remote_type,
            "job_url": "https://example.com/jobs/location",
            "description": "",
        },
        "specialist",
    )

    result = calculate_pre_score(
        job, signals=signals, pre_score_config=pre_score_config
    )

    assert result.location.score == expected_score
    assert result.total <= 100
