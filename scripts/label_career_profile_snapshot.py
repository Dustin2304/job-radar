#!/usr/bin/env python3
"""Apply a manual label map to an ignored real-job snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.embeddings import load_career_profile_definitions
from api.semantic_benchmark import SemanticRegressionCase

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = ROOT / "data" / "evaluation" / "career-profile-real-world.json"
DEFAULT_LABELS = ROOT / "data" / "evaluation" / "career-profile-real-world-labels.json"
DEFAULT_OUTPUT = (
    ROOT / "data" / "evaluation" / "career-profile-real-world-labelled.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    snapshot_path = args.snapshot.resolve()
    labels_path = args.labels.resolve()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise FileExistsError(f"labelled snapshot already exists: {output_path}")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    label_document = json.loads(labels_path.read_text(encoding="utf-8"))
    exclusions = set(label_document.get("exclude", []))
    labels = label_document.get("labels", {})
    snapshot_ids = {case["id"] for case in snapshot}
    unknown_ids = (set(labels) | exclusions) - snapshot_ids
    if unknown_ids:
        raise ValueError(f"label map contains unknown IDs: {sorted(unknown_ids)}")

    labelled: list[dict[str, object]] = []
    missing: list[str] = []
    profile_names = set(load_career_profile_definitions())
    for raw_case in snapshot:
        case_id = raw_case["id"]
        if case_id in exclusions:
            continue
        manual = labels.get(case_id)
        if manual is None:
            missing.append(case_id)
            continue
        case = {
            **raw_case,
            "group": manual["group"],
            "expected_primary": manual.get("expected_primary", []),
            "acceptable_secondary": manual.get("acceptable_secondary", []),
            "taxonomy_fit": manual["taxonomy_fit"],
        }
        validated = SemanticRegressionCase.model_validate(case)
        used_profiles = set(validated.expected_primary) | set(
            validated.acceptable_secondary
        )
        unknown_profiles = used_profiles - profile_names
        if unknown_profiles:
            raise ValueError(
                f"case {case_id!r} uses unknown profiles: {sorted(unknown_profiles)}"
            )
        labelled.append(case)
    if missing:
        raise ValueError(f"snapshot cases still need labels: {missing}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(labelled, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "labelled_cases": len(labelled),
                "excluded_duplicates": len(exclusions),
                "matched": sum(
                    case["taxonomy_fit"] == "matched" for case in labelled
                ),
                "no_fit": sum(case["taxonomy_fit"] == "none" for case in labelled),
                "description_available": sum(
                    case["description_status"] == "available" for case in labelled
                ),
                "title_only": sum(
                    case["description_status"] == "missing" for case in labelled
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
