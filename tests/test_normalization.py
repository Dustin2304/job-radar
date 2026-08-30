import pandas as pd

from api.compatibility import to_v1_job_result
from api.normalization import merge_search_queries, normalize_job


def make_raw_job(**overrides):
    raw_job = {
        "id": "native-123",
        "site": "linkedin",
        "title": "Process Automation Specialist",
        "company": "Example GmbH",
        "location": "Karlsruhe, Germany",
        "job_url": "https://www.linkedin.com/jobs/view/123/?utm_source=test",
        "description": "A" * 700,
        "date_posted": "2026-08-30",
        "is_remote": False,
    }
    raw_job.update(overrides)
    return raw_job


def test_normalize_job_preserves_canonical_fields_and_full_description():
    job = normalize_job(make_raw_job(), "process automation")

    assert job.title == "Process Automation Specialist"
    assert job.company == "Example GmbH"
    assert job.description == "A" * 700
    assert job.url == "https://www.linkedin.com/jobs/view/123"
    assert job.source == "linkedin"
    assert job.location == "Karlsruhe, Germany"
    assert job.search_queries == ["process automation"]


def test_normalize_job_handles_missing_values():
    job = normalize_job(
        make_raw_job(
            id=pd.NA,
            company=pd.NA,
            location=float("nan"),
            description=None,
            date_posted="None",
            is_remote=float("nan"),
        ),
        "data engineer",
    )

    assert job.source_id is None
    assert job.company == ""
    assert job.location is None
    assert job.description == ""
    assert job.date_posted is None
    assert job.is_remote is False


def test_source_native_id_is_preferred_and_stable():
    first = normalize_job(make_raw_job(), "data engineer")
    second = normalize_job(
        make_raw_job(description="The posting was edited after the first fetch."),
        "digital transformation",
    )

    assert first.id == "linkedin:native-123"
    assert second.id == first.id


def test_hash_id_is_stable_without_source_id_and_ignores_description():
    first = normalize_job(make_raw_job(id=None), "data engineer")
    second = normalize_job(
        make_raw_job(id=None, description="Updated description"),
        "data engineer",
    )

    assert first.id == second.id
    assert ":sha256:" in first.id


def test_different_jobs_receive_different_hash_ids():
    first = normalize_job(make_raw_job(id=None), "data engineer")
    second = normalize_job(
        make_raw_job(id=None, title="Business Process Analyst"),
        "data engineer",
    )

    assert first.id != second.id


def test_search_queries_can_be_merged_without_duplicates():
    job = normalize_job(make_raw_job(), "data engineer")

    merged = merge_search_queries(
        job,
        ["process automation", "Data Engineer", "digital transformation"],
    )

    assert merged.search_queries == [
        "data engineer",
        "process automation",
        "digital transformation",
    ]
    assert job.search_queries == ["data engineer"]


def test_v1_adapter_keeps_existing_contract_and_truncation():
    canonical_job = normalize_job(make_raw_job(), "process automation")

    result = to_v1_job_result(
        canonical_job,
        profile="IT Consulting & Business Interface",
        level="Entry",
        in_watchlist=True,
    )

    assert result.title == canonical_job.title
    assert result.company == canonical_job.company
    assert result.url == canonical_job.url
    assert result.source == "linkedin"
    assert result.profile == "IT Consulting & Business Interface"
    assert result.level == "Entry"
    assert result.in_watchlist is True
    assert result.description == "A" * 500
