"""Temporary rule-based score using configured positive evidence only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import JobResult


def _match_signals(
    text: str,
    groups: Sequence[Mapping[str, object]],
) -> tuple[int, list[str]]:
    """Return points and matches for configured positive signal groups."""
    total = 0
    matched: list[str] = []
    text_lower = text.casefold()
    for group in groups:
        points = int(group.get("points", 0))
        terms = group.get("terms", [])
        if not isinstance(terms, Sequence) or isinstance(terms, str):
            continue
        for value in terms:
            term = str(value).casefold()
            if term and term in text_lower:
                total += points
                matched.append(term)
                break
    return total, matched


def _build_reason(
    role_matches: list[str],
    technology_matches: list[str],
    watchlist: bool,
    level: str,
) -> str:
    parts: list[str] = []

    if role_matches:
        parts.append(role_matches[0].title())

    for term in technology_matches[:2]:
        label = term.upper() if len(term) <= 4 else term.title()
        if label.casefold() not in [part.casefold() for part in parts]:
            parts.append(label)

    if watchlist:
        parts.append("Watchlist")
    if level in ("Entry", "Mid"):
        parts.append(level + "-Level")

    return ", ".join(parts[:5]) or "No clear match"


def score_job(
    job: JobResult,
    *,
    signals: Mapping[str, object],
    legacy_scoring: Mapping[str, object],
) -> tuple[int, str]:
    """Return the temporary legacy score without using it as an acceptance gate."""
    role_groups = signals.get("role_terms", [])
    technology_groups = signals.get("technologies", [])
    junior_title_terms = signals.get("junior_title_terms", [])

    if not isinstance(role_groups, Sequence):
        role_groups = []
    if not isinstance(technology_groups, Sequence):
        technology_groups = []
    if not isinstance(junior_title_terms, Sequence) or isinstance(
        junior_title_terms, str
    ):
        junior_title_terms = []

    role_points, role_matches = _match_signals(job.title, role_groups)
    technology_points, technology_matches = _match_signals(
        job.description or "", technology_groups
    )
    technology_points = min(
        technology_points,
        int(legacy_scoring.get("technology_points_cap", 25)),
    )

    raw = int(legacy_scoring.get("base_points", 30))
    raw += role_points + technology_points

    if job.in_watchlist:
        raw += int(legacy_scoring.get("watchlist_bonus", 8))
    title = job.title.casefold()
    if any(str(term).casefold() in title for term in junior_title_terms):
        raw += int(legacy_scoring.get("junior_bonus", 5))

    score = max(0, min(100, raw))
    reason = _build_reason(
        role_matches,
        technology_matches,
        job.in_watchlist,
        job.level,
    )
    return score, reason


__all__ = ["score_job"]
