"""Explainable hard filters for clear, high-confidence job exclusions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import FilterReason, FilterResult, Job
from .normalization import clean_string

EXCLUDED_SENIORITY_TERMS = (
    "senior",
    "sr.",
    "sr",
    "lead",
    "principal",
    "staff engineer",
    "head of",
    "director",
    "vice president",
    "vp",
    "chief",
    "cto",
    "cio",
    "cpo",
    "cso",
)

EXCLUDED_EMPLOYMENT_TYPE_TERMS = (
    "working student",
    "werkstudent",
    "werkstudierende",
    "internship",
    "intern",
    "praktikant",
    "praktikum",
    "apprentice",
    "apprenticeship",
    "ausbildung",
    "duales studium",
)

_DEFAULT_TERM_CODES = {
    **{term.casefold(): "excluded_seniority" for term in EXCLUDED_SENIORITY_TERMS},
    **{
        term.casefold(): "excluded_employment_type"
        for term in EXCLUDED_EMPLOYMENT_TYPE_TERMS
    },
}


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def evaluate_hard_filters(
    job: Job,
    *,
    extra_excluded_title_terms: Iterable[str] = (),
) -> FilterResult:
    """Evaluate only high-confidence exclusions and return structured reasons."""
    reasons: list[FilterReason] = []
    terms: list[tuple[str, str]] = [
        (term, "excluded_seniority") for term in EXCLUDED_SENIORITY_TERMS
    ]
    terms.extend(
        (term, "excluded_employment_type")
        for term in EXCLUDED_EMPLOYMENT_TYPE_TERMS
    )

    configured_terms: set[str] = set()
    for value in extra_excluded_title_terms:
        term = clean_string(value)
        normalized = term.casefold()
        normalized_without_wrapping_punctuation = normalized.strip("()[]{}.,:; ")
        if (
            not term
            or normalized in configured_terms
            or normalized in _DEFAULT_TERM_CODES
            or normalized_without_wrapping_punctuation in _DEFAULT_TERM_CODES
        ):
            continue
        configured_terms.add(normalized)
        terms.append((term, "excluded_title_term"))

    seen_reasons: set[tuple[str, str]] = set()
    matched_spans: list[tuple[int, int]] = []
    for term, code in terms:
        match = _term_pattern(term).search(job.title)
        if match is None:
            continue
        if any(
            match.start() < existing_end and existing_start < match.end()
            for existing_start, existing_end in matched_spans
        ):
            continue
        reason_key = (code, match.group(0).casefold())
        if reason_key in seen_reasons:
            continue
        seen_reasons.add(reason_key)
        matched_spans.append(match.span())
        reasons.append(
            FilterReason(code=code, field="title", value=match.group(0))
        )

    return FilterResult(accepted=not reasons, reasons=reasons)


def apply_filter_result(job: Job, result: FilterResult) -> Job:
    """Attach a hard-filter decision to a canonical job without mutating it."""
    return job.model_copy(
        update={
            "hard_filter_passed": result.accepted,
            "rejection_reasons": list(result.reasons),
        }
    )


__all__ = [
    "EXCLUDED_EMPLOYMENT_TYPE_TERMS",
    "EXCLUDED_SENIORITY_TERMS",
    "apply_filter_result",
    "evaluate_hard_filters",
]
