"""Explainable deterministic pre-score for canonical jobs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .models import Job, PreScoreResult, ScoreComponent


def _contains_term(text: str, term: object) -> bool:
    normalized = str(term).strip()
    if not normalized:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized)}(?!\w)",
        text,
        re.IGNORECASE,
    ) is not None


def _configured_signals(
    definitions: object,
    *,
    title: str,
    description: str,
) -> tuple[list[str], list[str]]:
    """Return canonical signal names matched in title and description."""
    if not isinstance(definitions, Sequence) or isinstance(definitions, str):
        return [], []

    title_matches: list[str] = []
    description_matches: list[str] = []
    for definition in definitions:
        if not isinstance(definition, Mapping):
            continue
        name = str(definition.get("name", "")).strip()
        terms = definition.get("terms", [])
        if not name or not isinstance(terms, Sequence) or isinstance(terms, str):
            continue
        if any(_contains_term(title, term) for term in terms):
            title_matches.append(name)
        elif any(_contains_term(description, term) for term in terms):
            description_matches.append(name)
    return title_matches, description_matches


def _seniority_component(job: Job, config: Mapping[str, object]) -> ScoreComponent:
    max_score = float(config.get("max_score", 25))
    positive_terms = config.get("positive_title_terms", [])
    if not isinstance(positive_terms, Sequence) or isinstance(positive_terms, str):
        positive_terms = []

    matches = [
        str(term)
        for term in positive_terms
        if _contains_term(job.title, term)
    ]
    if matches:
        return ScoreComponent(
            score=min(float(config.get("explicit_junior_score", 25)), max_score),
            max_score=max_score,
            matched_signals=matches,
            notes=["explicit junior or entry-level signal in title"],
        )
    return ScoreComponent(
        score=min(float(config.get("neutral_score", 17)), max_score),
        max_score=max_score,
        notes=["no explicit seniority signal; neutral score applied"],
    )


def _technology_component(
    job: Job,
    definitions: object,
    config: Mapping[str, object],
) -> ScoreComponent:
    max_score = float(config.get("max_score", 30))
    title_matches, description_matches = _configured_signals(
        definitions,
        title=job.title,
        description=job.description,
    )
    matches = title_matches + description_matches
    score = min(
        len(matches) * float(config.get("points_per_match", 5)),
        max_score,
    )
    notes = [f"title: {name}" for name in title_matches]
    notes.extend(f"description: {name}" for name in description_matches)
    if not matches:
        notes.append("no configured technology signal found")
    return ScoreComponent(
        score=score,
        max_score=max_score,
        matched_signals=matches,
        notes=notes,
    )


def _role_component(
    job: Job,
    definitions: object,
    config: Mapping[str, object],
) -> ScoreComponent:
    max_score = float(config.get("max_score", 25))
    title_matches, description_matches = _configured_signals(
        definitions,
        title=job.title,
        description=job.description,
    )
    score = min(
        len(title_matches) * float(config.get("title_points_per_match", 6))
        + len(description_matches)
        * float(config.get("description_points_per_match", 3)),
        max_score,
    )
    matches = title_matches + description_matches
    notes = [f"title: {name}" for name in title_matches]
    notes.extend(f"description: {name}" for name in description_matches)
    if not matches:
        notes.append("no configured role signal found")
    return ScoreComponent(
        score=score,
        max_score=max_score,
        matched_signals=matches,
        notes=notes,
    )


def _matches_any(text: str, terms: object) -> bool:
    if not isinstance(terms, Sequence) or isinstance(terms, str):
        return False
    return any(_contains_term(text, term) for term in terms)


def _location_component(job: Job, config: Mapping[str, object]) -> ScoreComponent:
    max_score = float(config.get("max_score", 20))
    location = job.location or ""
    work_model_text = " ".join(
        part for part in (location, job.remote_type or "", job.description) if part
    )
    preferred = _matches_any(location, config.get("preferred_location_terms", []))
    remote = job.is_remote or _matches_any(
        work_model_text, config.get("remote_terms", [])
    )
    hybrid = _matches_any(work_model_text, config.get("hybrid_terms", []))

    if remote:
        score = float(config.get("remote_score", 20))
        notes = ["remote work model detected"]
        signals = ["remote"]
    elif not location and not hybrid:
        score = float(config.get("unknown_score", 10))
        notes = ["location and work model unknown; neutral score applied"]
        signals = []
    elif preferred and hybrid:
        score = float(config.get("preferred_hybrid_score", 20))
        notes = ["hybrid role in preferred region"]
        signals = ["preferred_region", "hybrid"]
    elif preferred:
        score = float(config.get("preferred_onsite_score", 17))
        notes = ["onsite role in preferred region"]
        signals = ["preferred_region", "onsite"]
    elif hybrid:
        score = float(config.get("other_hybrid_score", 10))
        notes = ["hybrid role outside preferred region"]
        signals = ["hybrid"]
    else:
        score = float(config.get("other_onsite_score", 5))
        notes = ["onsite role outside preferred region"]
        signals = ["onsite"]

    return ScoreComponent(
        score=min(score, max_score),
        max_score=max_score,
        matched_signals=signals,
        notes=notes,
    )


def calculate_pre_score(
    job: Job,
    *,
    signals: Mapping[str, object],
    pre_score_config: Mapping[str, object],
) -> PreScoreResult:
    """Calculate and retain four independently explainable score components."""
    seniority = _seniority_component(
        job, _mapping(pre_score_config.get("seniority"))
    )
    technologies = _technology_component(
        job,
        signals.get("technologies", []),
        _mapping(pre_score_config.get("technologies")),
    )
    role = _role_component(
        job,
        signals.get("role_terms", []),
        _mapping(pre_score_config.get("role")),
    )
    location = _location_component(
        job, _mapping(pre_score_config.get("location"))
    )
    total = seniority.score + technologies.score + role.score + location.score
    return PreScoreResult(
        total=round(total, 2),
        seniority=seniority,
        technologies=technologies,
        role=role,
        location=location,
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def apply_pre_score(job: Job, result: PreScoreResult) -> Job:
    """Attach a pre-score result to a copy of a canonical job."""
    return job.model_copy(
        update={
            "pre_score": result.total,
            "pre_score_components": result,
        }
    )


def summarize_pre_score(result: PreScoreResult | None) -> str:
    if result is None:
        return "Pre-score unavailable"
    return (
        f"Seniority {result.seniority.score:g}/{result.seniority.max_score:g}, "
        f"Technologies {result.technologies.score:g}/{result.technologies.max_score:g}, "
        f"Role {result.role.score:g}/{result.role.max_score:g}, "
        f"Location {result.location.score:g}/{result.location.max_score:g}"
    )


__all__ = [
    "apply_pre_score",
    "calculate_pre_score",
    "summarize_pre_score",
]
