from collections.abc import Sequence
from io import BytesIO
import json

import pytest

from api.compatibility import to_v1_job_result
from api.embeddings import (
    EmbeddingServiceUnavailable,
    EmbeddingSettings,
    LMStudioEmbeddingClient,
    SemanticCategoryClassifier,
    cosine_similarity,
    load_category_definitions,
)
from api.normalization import normalize_job


class QueueEmbeddingClient:
    model = "test-embedding-model"

    def __init__(self, responses: list[list[list[float]] | Exception]):
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def settings(**overrides) -> EmbeddingSettings:
    values = {
        "enabled": True,
        "base_url": "http://localhost:1234/v1",
        "model": "test-embedding-model",
        "dimensions": 2,
        "title_weight": 0.4,
        "description_weight": 0.6,
        "instruction": "Classify this job by semantic role category",
        "timeout_seconds": 1,
    }
    values.update(overrides)
    return EmbeddingSettings.from_config(values)


def job(*, title: str = "Automation Engineer", description: str = ""):
    return normalize_job(
        {
            "id": title,
            "site": "linkedin",
            "title": title,
            "company": "Example GmbH",
            "job_url": f"https://example.com/jobs/{title.replace(' ', '-').lower()}",
            "description": description,
        },
        "test query",
    )


def test_cosine_similarity_uses_vector_direction():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0)
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1)


def test_title_only_categories_are_sorted_and_category_vectors_are_cached():
    client = QueueEmbeddingClient(
        [
            [[1, 0], [0, 1]],
            [[0.8, 0.2]],
            [[0.1, 0.9]],
        ]
    )
    classifier = SemanticCategoryClassifier(
        client=client,
        categories={"automation": "Automation roles", "data": "Data roles"},
        settings=settings(),
    )

    automation_job = classifier.classify(job())
    data_job = classifier.classify(job(title="Data Engineer"))

    assert automation_job.embedding_input == "title_only"
    assert automation_job.embedding_status == "success"
    assert automation_job.embedding_model == client.model
    assert [match.name for match in automation_job.categories] == ["automation", "data"]
    assert all(match.description_similarity is None for match in automation_job.categories)
    assert automation_job.categories[0].similarity == pytest.approx(
        automation_job.categories[0].title_similarity
    )
    assert data_job.categories[0].name == "data"
    assert client.calls[0] == ["Automation roles", "Data roles"]
    assert len(client.calls) == 3


def test_title_and_description_similarities_use_configured_weighting():
    client = QueueEmbeddingClient(
        [
            [[1, 0], [0, 1]],
            [[1, 0], [0, 1]],
        ]
    )
    classifier = SemanticCategoryClassifier(
        client=client,
        categories={"automation": "Automation roles", "data": "Data roles"},
        settings=settings(),
    )

    classified = classifier.classify(
        job(description="Build ETL pipelines and cloud data platforms.")
    )

    assert classified.embedding_input == "title_and_description"
    assert [match.name for match in classified.categories] == ["data", "automation"]
    matches = {match.name: match for match in classified.categories}
    assert matches["automation"].title_similarity == pytest.approx(1)
    assert matches["automation"].description_similarity == pytest.approx(0)
    assert matches["automation"].similarity == pytest.approx(0.4)
    assert matches["data"].title_similarity == pytest.approx(0)
    assert matches["data"].description_similarity == pytest.approx(1)
    assert matches["data"].similarity == pytest.approx(0.6)


def test_embedding_service_failure_is_nonfatal_and_visible_in_v1_result():
    client = QueueEmbeddingClient(
        [EmbeddingServiceUnavailable("LM Studio is not running")]
    )
    classifier = SemanticCategoryClassifier(
        client=client,
        categories={"automation": "Automation roles"},
        settings=settings(),
    )

    canonical_job = classifier.classify(job())
    result = to_v1_job_result(
        canonical_job,
        profile="Test",
        level="Entry",
        in_watchlist=False,
    )

    assert canonical_job.title == "Automation Engineer"
    assert canonical_job.embedding_status == "unavailable"
    assert canonical_job.categories == []
    assert result.embedding_status == "unavailable"
    assert result.categories == []


def test_invalid_embedding_vectors_mark_job_as_error_without_dropping_it():
    client = QueueEmbeddingClient([[[0, 0]], [[1, 0]]])
    classifier = SemanticCategoryClassifier(
        client=client,
        categories={"automation": "Automation roles"},
        settings=settings(),
    )

    classified = classifier.classify(job())

    assert classified.title == "Automation Engineer"
    assert classified.embedding_status == "error"
    assert classified.categories == []


def test_api_result_contains_similarities_but_no_raw_vectors():
    client = QueueEmbeddingClient([[[1, 0]], [[1, 0]]])
    classifier = SemanticCategoryClassifier(
        client=client,
        categories={"automation": "Automation roles"},
        settings=settings(),
    )
    canonical_job = classifier.classify(job())
    result = to_v1_job_result(
        canonical_job,
        profile="Test",
        level="Entry",
        in_watchlist=False,
    )

    payload = result.model_dump()
    assert payload["categories"][0] == {
        "name": "automation",
        "similarity": pytest.approx(1),
        "title_similarity": pytest.approx(1),
        "description_similarity": None,
    }
    assert "embedding" not in payload
    assert "vector" not in str(payload).lower()


def test_semantic_category_configuration_is_complete():
    categories = load_category_definitions()

    assert set(categories) == {
        "automation",
        "data",
        "business_intelligence",
        "process_management",
        "project_management",
        "supply_chain",
        "consulting",
    }
    assert all(description.strip() for description in categories.values())


def test_invalid_embedding_weights_are_rejected():
    with pytest.raises(ValueError):
        settings(title_weight=0, description_weight=0)


def test_lm_studio_client_uses_openai_compatible_embeddings_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return BytesIO(
            json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": [0, 1]},
                        {"index": 0, "embedding": [1, 0]},
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("api.embeddings.urlopen", fake_urlopen)
    client = LMStudioEmbeddingClient(
        base_url="http://localhost:1234/v1/",
        model="qwen-test",
        dimensions=2,
        timeout_seconds=7,
    )

    vectors = client.embed(["first", "second"])

    assert vectors == [[1, 0], [0, 1]]
    assert captured == {
        "url": "http://localhost:1234/v1/embeddings",
        "payload": {
            "input": ["first", "second"],
            "model": "qwen-test",
            "dimensions": 2,
        },
        "timeout": 7,
    }
