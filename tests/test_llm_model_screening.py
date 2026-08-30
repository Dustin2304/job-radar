from api.llm_model_screening import select_runtime_effort


def metrics(**overrides):
    values = {
        "failure_rate": 0.0,
        "timeout_rate": 0.0,
        "median_latency_seconds": 20.0,
        "candidate_hallucination_count": 0,
        "recommendation_accuracy": 0.75,
        "mean_ordinal_error": 0.0,
    }
    values.update(overrides)
    return values


def test_runtime_selection_preserves_zero_ordinal_error():
    selected = select_runtime_effort(
        {
            "minimal": metrics(mean_ordinal_error=0.0),
            "low": metrics(mean_ordinal_error=0.5),
        },
        max_failure_rate=0.25,
        max_median_latency_seconds=120,
    )

    assert selected == "minimal"


def test_runtime_selection_rejects_impractical_profiles():
    selected = select_runtime_effort(
        {
            "none": metrics(failure_rate=0.5),
            "minimal": metrics(median_latency_seconds=121),
            "low": metrics(candidate_hallucination_count=1),
        },
        max_failure_rate=0.25,
        max_median_latency_seconds=120,
    )

    assert selected is None
