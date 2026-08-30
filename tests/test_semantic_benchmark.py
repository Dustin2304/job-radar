import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.embeddings import load_category_definitions
from api.semantic_benchmark import (
    SemanticRegressionCase,
    calculate_regression_metrics,
    load_regression_cases,
)

FIXTURE = Path(__file__).parent / "fixtures" / "semantic_categories.json"
CAREER_FIXTURE = Path(__file__).parent / "fixtures" / "career_profiles.json"


def test_committed_semantic_dataset_has_balanced_valid_cases():
    cases = load_regression_cases(
        FIXTURE,
        category_names=list(load_category_definitions()),
    )

    assert len(cases) == 30
    assert Counter(case.group for case in cases) == {
        "automation": 4,
        "data_bi": 4,
        "process_management": 4,
        "supply_chain": 4,
        "consulting": 3,
        "project_management": 3,
        "multi_category": 5,
        "no_taxonomy_fit": 3,
    }
    assert sum(len(case.expected_primary) > 1 for case in cases) == 5
    assert sum(case.taxonomy_fit == "none" for case in cases) == 3
    assert all(case.semantic_summary for case in cases)

    raw_cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert all("description" not in case for case in raw_cases)


def test_regression_metrics_exclude_no_fit_cases_from_ranking_accuracy():
    cases = [
        SemanticRegressionCase(
            id="exact",
            group="test",
            title="Exact",
            expected_primary=["data"],
            acceptable_secondary=["business_intelligence"],
        ),
        SemanticRegressionCase(
            id="top-two",
            group="test",
            title="Top two",
            expected_primary=["process_management"],
        ),
        SemanticRegressionCase(
            id="multi",
            group="test",
            title="Multi",
            expected_primary=["consulting", "automation"],
        ),
        SemanticRegressionCase(
            id="none",
            group="test",
            title="No fit",
            taxonomy_fit="none",
        ),
    ]
    rankings = {
        "exact": ["data", "business_intelligence", "consulting"],
        "top-two": ["business_intelligence", "process_management", "automation"],
        "multi": ["automation", "consulting", "data"],
        "none": ["project_management", "consulting", "data"],
    }

    metrics = calculate_regression_metrics(cases, rankings)

    assert metrics == {
        "total_cases": 4,
        "matched_cases": 3,
        "no_fit_cases": 1,
        "top1_correct": 2,
        "top1_accuracy": pytest.approx(2 / 3),
        "top2_recalled": 3,
        "top2_recall": 1.0,
        "mean_best_primary_rank": pytest.approx(4 / 3),
    }


def test_committed_career_profile_dataset_has_expected_coverage():
    cases = load_regression_cases(
        CAREER_FIXTURE,
        category_names=[
            "automation_data",
            "technical_project_management",
            "process_consulting",
            "data_bi",
        ],
    )

    assert len(cases) == 24
    assert Counter(case.group for case in cases) == {
        "automation_data": 4,
        "technical_project_management": 4,
        "process_consulting": 4,
        "data_bi": 4,
        "multi_profile": 6,
        "no_profile_fit": 2,
    }
    assert sum(len(case.expected_primary) > 1 for case in cases) == 6
    assert sum(case.taxonomy_fit == "none" for case in cases) == 2
    assert all(case.semantic_summary for case in cases)


def test_case_schema_rejects_labels_for_no_fit_case():
    with pytest.raises(ValidationError):
        SemanticRegressionCase(
            id="invalid",
            group="test",
            title="Invalid",
            taxonomy_fit="none",
            expected_primary=["automation"],
        )


def test_dataset_loader_rejects_unknown_category(tmp_path):
    dataset = tmp_path / "semantic.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "unknown",
                    "group": "test",
                    "title": "Unknown",
                    "expected_primary": ["not_configured"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown categories"):
        load_regression_cases(dataset, category_names=["automation"])
