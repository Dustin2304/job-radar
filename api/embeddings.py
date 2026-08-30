"""Additive semantic category classification through an embedding service."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from .models import CategoryMatch, Job

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATEGORIES_PATH = ROOT / "config" / "categories.yaml"

EmbeddingStatus = Literal["success", "unavailable", "error"]


class EmbeddingServiceUnavailable(ConnectionError):
    """Raised when the configured local embedding service cannot be reached."""


class EmbeddingResponseError(RuntimeError):
    """Raised when the service rejects a request or returns invalid data."""


class EmbeddingClient(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingSettings:
    enabled: bool
    base_url: str
    model: str
    dimensions: int
    title_weight: float
    description_weight: float
    instruction: str
    timeout_seconds: float

    @classmethod
    def from_config(cls, config: Mapping[str, object] | None) -> "EmbeddingSettings":
        values = config or {}
        title_weight = float(values.get("title_weight", 0.4))
        description_weight = float(values.get("description_weight", 0.6))
        if title_weight < 0 or description_weight < 0:
            raise ValueError("embedding weights must not be negative")
        if title_weight + description_weight <= 0:
            raise ValueError("at least one embedding weight must be positive")

        dimensions = int(values.get("dimensions", 1024))
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")

        return cls(
            enabled=bool(values.get("enabled", False)),
            base_url=str(values.get("base_url", "http://localhost:1234/v1")).rstrip("/"),
            model=str(values.get("model", "")).strip(),
            dimensions=dimensions,
            title_weight=title_weight,
            description_weight=description_weight,
            instruction=str(
                values.get(
                    "instruction",
                    "Given a job posting, identify the semantic role categories that best describe it",
                )
            ).strip(),
            timeout_seconds=float(values.get("timeout_seconds", 30)),
        )


class LMStudioEmbeddingClient:
    """Small dependency-free client for LM Studio's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps(
            {
                "input": list(texts),
                "model": self.model,
                "dimensions": self.dimensions,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingResponseError(
                f"embedding service returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise EmbeddingServiceUnavailable(
                f"embedding service is unavailable at {self.base_url}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EmbeddingResponseError("embedding service returned invalid JSON") from exc

        try:
            rows = sorted(body["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingResponseError("embedding response has an invalid shape") from exc

        if len(vectors) != len(texts):
            raise EmbeddingResponseError("embedding response count does not match input count")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise EmbeddingResponseError(
                f"embedding response does not use {self.dimensions} dimensions"
            )
        return vectors


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("cosine similarity requires non-empty vectors of equal length")
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine similarity is undefined for a zero vector")
    return max(-1.0, min(1.0, dot_product / (left_norm * right_norm)))


def load_category_definitions(
    path: Path = DEFAULT_CATEGORIES_PATH,
) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    raw_categories = document.get("categories", {})
    if not isinstance(raw_categories, Mapping) or not raw_categories:
        raise ValueError("categories.yaml must define at least one category")

    categories: dict[str, str] = {}
    for name, definition in raw_categories.items():
        if not isinstance(definition, Mapping):
            raise ValueError(f"category {name!r} must be a mapping")
        description = str(definition.get("description", "")).strip()
        if not description:
            raise ValueError(f"category {name!r} requires a description")
        categories[str(name)] = description
    return categories


class SemanticCategoryClassifier:
    """Classify canonical jobs while keeping category vectors only in memory."""

    def __init__(
        self,
        *,
        client: EmbeddingClient,
        categories: Mapping[str, str],
        settings: EmbeddingSettings,
        failure_retry_seconds: float = 30,
    ) -> None:
        self.client = client
        self.categories = dict(categories)
        self.settings = settings
        self.failure_retry_seconds = failure_retry_seconds
        self._category_vectors: dict[str, list[float]] | None = None
        self._last_failure: tuple[float, EmbeddingStatus] | None = None

    def _query_text(self, text: str) -> str:
        if not self.settings.instruction:
            return text
        return f"Instruct: {self.settings.instruction}\nQuery:{text}"

    def _failure_in_cooldown(self) -> EmbeddingStatus | None:
        if self._last_failure is None:
            return None
        failed_at, status = self._last_failure
        if time.monotonic() - failed_at < self.failure_retry_seconds:
            return status
        self._last_failure = None
        return None

    def _get_category_vectors(self) -> dict[str, list[float]]:
        if self._category_vectors is None:
            vectors = self.client.embed(list(self.categories.values()))
            self._category_vectors = dict(zip(self.categories, vectors, strict=True))
        return self._category_vectors

    def classify(self, job: Job) -> Job:
        embedding_input = (
            "title_and_description"
            if job.description_status == "available" and job.description
            else "title_only"
        )
        base_update = {
            "categories": [],
            "embedding_input": embedding_input,
            "embedding_model": self.client.model,
        }

        cooldown_status = self._failure_in_cooldown()
        if cooldown_status is not None:
            return job.model_copy(
                update={**base_update, "embedding_status": cooldown_status}
            )

        try:
            category_vectors = self._get_category_vectors()
            job_texts = [self._query_text(job.title)]
            if embedding_input == "title_and_description":
                job_texts.append(self._query_text(job.description))
            job_vectors = self.client.embed(job_texts)

            title_vector = job_vectors[0]
            description_vector = job_vectors[1] if len(job_vectors) == 2 else None
            matches: list[CategoryMatch] = []
            for name, category_vector in category_vectors.items():
                title_similarity = cosine_similarity(title_vector, category_vector)
                description_similarity = (
                    cosine_similarity(description_vector, category_vector)
                    if description_vector is not None
                    else None
                )
                if description_similarity is None:
                    combined = title_similarity
                else:
                    weight_total = (
                        self.settings.title_weight + self.settings.description_weight
                    )
                    combined = (
                        self.settings.title_weight * title_similarity
                        + self.settings.description_weight * description_similarity
                    ) / weight_total
                matches.append(
                    CategoryMatch(
                        name=name,
                        similarity=combined,
                        title_similarity=title_similarity,
                        description_similarity=description_similarity,
                    )
                )
        except EmbeddingServiceUnavailable:
            status: EmbeddingStatus = "unavailable"
            self._last_failure = (time.monotonic(), status)
            return job.model_copy(update={**base_update, "embedding_status": status})
        except (EmbeddingResponseError, ValueError, KeyError, TypeError):
            status = "error"
            self._last_failure = (time.monotonic(), status)
            return job.model_copy(update={**base_update, "embedding_status": status})

        matches.sort(key=lambda match: match.similarity, reverse=True)
        return job.model_copy(
            update={
                **base_update,
                "categories": matches,
                "embedding_status": "success",
            }
        )


_CLASSIFIER_CACHE: dict[tuple[object, ...], SemanticCategoryClassifier] = {}


def get_semantic_classifier(
    config: Mapping[str, object] | None,
) -> SemanticCategoryClassifier | None:
    settings = EmbeddingSettings.from_config(config)
    if not settings.enabled:
        return None
    if not settings.model:
        raise ValueError("an embedding model is required when embeddings are enabled")

    categories = load_category_definitions()
    key = (
        settings,
        tuple(categories.items()),
    )
    classifier = _CLASSIFIER_CACHE.get(key)
    if classifier is None:
        client = LMStudioEmbeddingClient(
            base_url=settings.base_url,
            model=settings.model,
            dimensions=settings.dimensions,
            timeout_seconds=settings.timeout_seconds,
        )
        classifier = SemanticCategoryClassifier(
            client=client,
            categories=categories,
            settings=settings,
        )
        _CLASSIFIER_CACHE[key] = classifier
    return classifier


__all__ = [
    "EmbeddingResponseError",
    "EmbeddingServiceUnavailable",
    "EmbeddingSettings",
    "LMStudioEmbeddingClient",
    "SemanticCategoryClassifier",
    "cosine_similarity",
    "get_semantic_classifier",
    "load_category_definitions",
]
