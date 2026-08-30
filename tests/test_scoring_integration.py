from api.models import JobResult
from api.scorer import score_job

SIGNALS = {
    "role_terms": [
        {"points": 35, "terms": ["ai engineer"]},
        {"points": 25, "terms": ["python developer"]},
    ],
    "technologies": [
        {"points": 12, "terms": ["llm"]},
        {"points": 8, "terms": ["python", "fastapi"]},
    ],
    "junior_title_terms": ["junior", "entry", "trainee"],
}
LEGACY_SCORING = {
    "base_points": 30,
    "technology_points_cap": 25,
    "watchlist_bonus": 8,
    "junior_bonus": 5,
}


def make_job(title: str, profile: str, description: str = "") -> JobResult:
    return JobResult(
        title=title,
        company="Example Corp",
        location="Karlsruhe, Germany",
        url="https://example.com/job",
        source="linkedin",
        date_posted="2026-04-21",
        is_remote=False,
        description=description,
        level="Entry",
        profile=profile,
        in_watchlist=False,
        skills_required=[],
    )


def calculate(job: JobResult):
    return score_job(job, signals=SIGNALS, legacy_scoring=LEGACY_SCORING)


def test_score_is_not_changed_by_legacy_discovery_group():
    core_job = make_job(
        "AI Engineer", "AI & Data Engineering", description="Python and LLM"
    )
    fallback_job = core_job.model_copy(
        update={"profile": "Logistics & Operations"}
    )

    core_score, _ = calculate(core_job)
    fallback_score, _ = calculate(fallback_job)

    assert fallback_score == core_score


def test_score_job_ai_title_keeps_positive_signals():
    job = make_job(
        "AI Engineer", "AI & Data Engineering", description="Python and LLM"
    )

    score, reason = calculate(job)

    assert score > LEGACY_SCORING["base_points"]
    assert "Ai Engineer" in reason


def test_job_without_positive_signal_keeps_neutral_legacy_score():
    job = make_job("Business Process Analyst", "Discovery")

    score, reason = calculate(job)

    assert score == LEGACY_SCORING["base_points"]
    assert reason == "Entry-Level"
