"""Schema and metrics for the persisted semantic-category benchmark."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SemanticRegressionCase(BaseModel):
    """One manually labelled role used for semantic regression evaluation."""

    id: str = Field(min_length=1)
    group: str = Field(min_length=1)
    title: str = Field(min_length=1)
    semantic_summary: str = ""
    description: str = ""
    expected_primary: list[str] = Field(default_factory=list)
    acceptable_secondary: list[str] = Field(default_factory=list)
    taxonomy_fit: Literal["matched", "none"] = "matched"

    @model_validator(mode="after")
    def labels_are_consistent(self):
        if len(self.expected_primary) != len(set(self.expected_primary)):
            raise ValueError("expected_primary must not contain duplicates")
        if len(self.acceptable_secondary) != len(set(self.acceptable_secondary)):
            raise ValueError("acceptable_secondary must not contain duplicates")
        if set(self.expected_primary) & set(self.acceptable_secondary):
            raise ValueError("primary and secondary categories must not overlap")
        if self.taxonomy_fit == "matched" and not self.expected_primary:
            raise ValueError("matched cases require at least one expected primary")
        if self.taxonomy_fit == "none" and (
            self.expected_primary or self.acceptable_secondary
        ):
            raise ValueError("no-fit cases must not define category labels")
        if self.semantic_summary and self.description:
            raise ValueError("use either semantic_summary or description, not both")
        return self

    @property
    def evaluation_text(self) -> str:
        return self.semantic_summary or self.description


def load_regression_cases(
    path: Path,
    *,
    category_names: Sequence[str] | None = None,
) -> list[SemanticRegressionCase]:
    """Load and validate a semantic regression dataset."""

    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, list):
        raise ValueError("semantic regression dataset must be a JSON list")

    cases = [SemanticRegressionCase.model_validate(item) for item in document]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("semantic regression case IDs must be unique")

    if category_names is not None:
        known_categories = set(category_names)
        for case in cases:
            labels = set(case.expected_primary) | set(case.acceptable_secondary)
            unknown = labels - known_categories
            if unknown:
                raise ValueError(
                    f"case {case.id!r} uses unknown categories: {sorted(unknown)}"
                )
    return cases


def calculate_regression_metrics(
    cases: Sequence[SemanticRegressionCase],
    rankings: Mapping[str, Sequence[str]],
) -> dict[str, int | float]:
    """Calculate Top-1 accuracy, Top-2 recall, and best-primary mean rank."""

    matched_cases = [case for case in cases if case.taxonomy_fit == "matched"]
    top1_correct = 0
    top2_recalled = 0
    best_ranks: list[int] = []

    for case in cases:
        ranking = list(rankings.get(case.id, ()))
        if not ranking:
            raise ValueError(f"case {case.id!r} has no category ranking")
        if len(ranking) != len(set(ranking)):
            raise ValueError(f"case {case.id!r} ranking contains duplicates")
        if case.taxonomy_fit == "none":
            continue

        expected = set(case.expected_primary)
        top1_correct += ranking[0] in expected
        top2_recalled += bool(expected.intersection(ranking[:2]))
        ranks = [ranking.index(name) + 1 for name in expected if name in ranking]
        if not ranks:
            raise ValueError(f"case {case.id!r} has no expected category in ranking")
        best_ranks.append(min(ranks))

    matched_count = len(matched_cases)
    if not matched_count:
        raise ValueError("semantic regression dataset has no matched cases")

    return {
        "total_cases": len(cases),
        "matched_cases": matched_count,
        "no_fit_cases": len(cases) - matched_count,
        "top1_correct": top1_correct,
        "top1_accuracy": top1_correct / matched_count,
        "top2_recalled": top2_recalled,
        "top2_recall": top2_recalled / matched_count,
        "mean_best_primary_rank": sum(best_ranks) / len(best_ranks),
    }


__all__ = [
    "SemanticRegressionCase",
    "calculate_regression_metrics",
    "load_regression_cases",
]
