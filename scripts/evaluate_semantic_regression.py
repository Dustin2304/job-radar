#!/usr/bin/env python3
"""Evaluate semantic category rankings against a persisted labelled dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from api.embeddings import get_semantic_classifier, load_category_definitions
from api.normalization import normalize_job
from api.scraper import load_config
from api.semantic_benchmark import (
    SemanticRegressionCase,
    calculate_regression_metrics,
    load_regression_cases,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "tests" / "fixtures" / "semantic_categories.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Labelled JSON dataset; defaults to the committed regression fixture",
    )
    return parser.parse_args()


def _classify_case(case: SemanticRegressionCase, classifier):
    job = normalize_job(
        {
            "id": f"semantic-regression-{case.id}",
            "site": "linkedin",
            "title": case.title,
            "company": "Semantic Regression Fixture",
            "job_url": f"https://example.invalid/semantic-regression/{case.id}",
            "description": case.evaluation_text,
        },
        "semantic regression",
    )
    classified = classifier.classify(job)
    if classified.embedding_status != "success":
        raise RuntimeError(
            f"embedding failed for {case.id}: {classified.embedding_status}"
        )
    return classified


def main() -> None:
    args = _parse_args()
    dataset_path = args.dataset.resolve()
    categories = load_category_definitions()
    cases = load_regression_cases(
        dataset_path,
        category_names=list(categories),
    )

    config = load_config()
    classifier = get_semantic_classifier(config.get("embeddings"))
    if classifier is None:
        raise RuntimeError("embeddings are disabled")

    rankings: dict[str, list[str]] = {}
    results: list[dict[str, object]] = []
    for case in cases:
        classified = _classify_case(case, classifier)
        ranking = [match.name for match in classified.categories]
        rankings[case.id] = ranking
        expected = set(case.expected_primary)
        best_primary_rank = min(
            (ranking.index(name) + 1 for name in expected if name in ranking),
            default=None,
        )
        results.append(
            {
                "id": case.id,
                "group": case.group,
                "title": case.title,
                "taxonomy_fit": case.taxonomy_fit,
                "expected_primary": case.expected_primary,
                "acceptable_secondary": case.acceptable_secondary,
                "top1_correct": (
                    ranking[0] in expected if case.taxonomy_fit == "matched" else None
                ),
                "top2_recalled": (
                    bool(expected.intersection(ranking[:2]))
                    if case.taxonomy_fit == "matched"
                    else None
                ),
                "best_primary_rank": best_primary_rank,
                "categories": [
                    {
                        "name": match.name,
                        "similarity": round(match.similarity, 4),
                        "title_similarity": round(match.title_similarity, 4),
                        "description_similarity": (
                            round(match.description_similarity, 4)
                            if match.description_similarity is not None
                            else None
                        ),
                    }
                    for match in classified.categories[:3]
                ],
            }
        )

    regressions = [
        {
            "id": result["id"],
            "title": result["title"],
            "expected_primary": result["expected_primary"],
            "best_primary_rank": result["best_primary_rank"],
            "top_categories": [
                category["name"] for category in result["categories"]
            ],
        }
        for result in results
        if result["taxonomy_fit"] == "matched" and not result["top1_correct"]
    ]
    payload = {
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "model": config["embeddings"]["model"],
        "dimensions": config["embeddings"]["dimensions"],
        "weights": {
            "title": config["embeddings"]["title_weight"],
            "description": config["embeddings"]["description_weight"],
        },
        "metrics": calculate_regression_metrics(cases, rankings),
        "regressions": regressions,
        "cases": results,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
