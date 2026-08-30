from api.llm_model_screening import select_default_model, select_runtime_effort


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


def test_default_model_prefers_efficiency_for_similar_quality():
    selected, reason = select_default_model(
        {
            "small": metrics(
                recommendation_accuracy=0.72,
                large_recommendation_errors=2,
            ),
            "large": metrics(
                recommendation_accuracy=0.74,
                large_recommendation_errors=1,
            ),
        },
        efficiency_preference="small",
        similar_accuracy_margin=0.05,
        material_large_error_difference=2,
        max_failure_rate=0.02,
        max_timeout_rate=0.0,
        max_candidate_hallucinations=1,
    )

    assert selected == "small"
    assert reason == "similar_quality_efficiency_preference"


def test_default_model_prefers_materially_fewer_large_errors():
    selected, reason = select_default_model(
        {
            "small": metrics(large_recommendation_errors=3),
            "large": metrics(large_recommendation_errors=1),
        },
        efficiency_preference="small",
        similar_accuracy_margin=0.05,
        material_large_error_difference=2,
        max_failure_rate=0.02,
        max_timeout_rate=0.0,
        max_candidate_hallucinations=1,
    )

    assert selected == "large"
    assert reason == "materially_fewer_large_errors"


def test_default_model_allows_documented_small_failure_rates():
    selected, reason = select_default_model(
        {
            "small": metrics(
                failure_rate=0.014,
                large_recommendation_errors=5,
            ),
            "large": metrics(
                candidate_hallucination_count=1,
                large_recommendation_errors=2,
            ),
        },
        efficiency_preference="small",
        similar_accuracy_margin=0.05,
        material_large_error_difference=2,
        max_failure_rate=0.02,
        max_timeout_rate=0.0,
        max_candidate_hallucinations=1,
    )

    assert selected == "large"
    assert reason == "materially_fewer_large_errors"
