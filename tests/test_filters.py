import pytest

from api.filters import apply_filter_result, evaluate_hard_filters
from api.normalization import normalize_job


def make_job(title: str):
    return normalize_job(
        {
            "id": title.casefold().replace(" ", "-"),
            "site": "linkedin",
            "title": title,
            "company": "Example GmbH",
            "location": "Karlsruhe, Germany",
            "job_url": f"https://example.com/jobs/{title.casefold().replace(' ', '-')}",
            "description": "Full job description",
        },
        "process automation",
    )


@pytest.mark.parametrize(
    ("title", "expected_code", "expected_value"),
    [
        ("Director Data Engineering", "excluded_seniority", "Director"),
        ("Head of Automation", "excluded_seniority", "Head of"),
        ("VP Digital Transformation", "excluded_seniority", "VP"),
        ("Working Student Power BI", "excluded_employment_type", "Working Student"),
        ("Werkstudent Prozessmanagement", "excluded_employment_type", "Werkstudent"),
        ("Software Engineering Internship", "excluded_employment_type", "Internship"),
        ("Praktikant Data Analytics", "excluded_employment_type", "Praktikant"),
        ("Ausbildung Fachinformatik", "excluded_employment_type", "Ausbildung"),
        ("IT Apprentice", "excluded_employment_type", "Apprentice"),
    ],
)
def test_clear_exclusions_return_structured_reasons(
    title, expected_code, expected_value
):
    result = evaluate_hard_filters(make_job(title))

    assert result.accepted is False
    assert result.reasons[0].model_dump() == {
        "code": expected_code,
        "field": "title",
        "value": expected_value,
    }


@pytest.mark.parametrize(
    "title",
    [
        "Junior Digital Transformation Consultant",
        "Business Process Analyst",
        "SAP Consultant",
        "Supply Chain Project Manager",
        "Experienced Process Consultant",
        "Leadership Platform Engineer",
        "Trainee Data Engineer",
    ],
)
def test_plausible_or_semantic_roles_are_not_hard_rejected(title):
    result = evaluate_hard_filters(make_job(title))

    assert result.accepted is True
    assert result.reasons == []


def test_matching_is_case_insensitive_and_does_not_duplicate_overlapping_terms():
    result = evaluate_hard_filters(make_job("SR. DATA ENGINEER"))

    assert result.accepted is False
    assert len(result.reasons) == 1
    assert result.reasons[0].code == "excluded_seniority"


def test_multiple_independent_reasons_are_retained_on_job():
    job = make_job("Senior Working Student Data Engineer")
    result = evaluate_hard_filters(job)

    filtered_job = apply_filter_result(job, result)

    assert result.accepted is False
    assert {reason.code for reason in result.reasons} == {
        "excluded_seniority",
        "excluded_employment_type",
    }
    assert filtered_job.hard_filter_passed is False
    assert filtered_job.rejection_reasons == result.reasons
    assert job.hard_filter_passed is True


def test_additional_configured_term_is_explainable():
    result = evaluate_hard_filters(
        make_job("Freelance Only Data Engineer"),
        extra_excluded_title_terms=["freelance only"],
    )

    assert result.reasons[0].model_dump() == {
        "code": "excluded_title_term",
        "field": "title",
        "value": "Freelance Only",
    }
