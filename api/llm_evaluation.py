"""Structured local-LLM evaluation foundation for canonical jobs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from pydantic import ValidationError

from .models import CandidateProfile, Job, LLMEvaluation, LLMEvaluationAttempt

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_PROFILE_PATH = ROOT / "config" / "candidate_profile.yaml"

SYSTEM_PROMPT = """You evaluate whether applying to a job is worthwhile for one candidate.

Only information in CANDIDATE PROFILE / facts is factual candidate information.
CANDIDATE PROFILE / preferences describes desired roles, not candidate capabilities.
Never infer candidate skills or experience from the job description, semantic matches,
or deterministic analysis. If a mandatory requirement is unsupported by candidate
facts, list it under missing_requirements. Do not treat nice-to-have requirements as
mandatory; list unsupported optional requirements only under nice_to_have_gaps.
Distinguish mandatory experience wording from preferences such as "ideally" or
"preferred". Keep the deterministic pre-score, semantic similarities, and your own
fit score conceptually separate. Return only JSON matching the supplied schema.
"""


class LLMServiceUnavailable(ConnectionError):
    """Raised when the configured local chat service cannot be reached."""


class LLMResponseError(RuntimeError):
    """Raised when the chat service rejects a request or returns an invalid shape."""


class ChatClient(Protocol):
    model: str

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str: ...


@dataclass(frozen=True)
class LLMEvaluationSettings:
    enabled: bool
    base_url: str
    model: str
    timeout_seconds: float
    temperature: float

    @classmethod
    def from_config(
        cls, config: Mapping[str, object] | None
    ) -> "LLMEvaluationSettings":
        values = config or {}
        timeout_seconds = float(values.get("timeout_seconds", 60))
        temperature = float(values.get("temperature", 0.1))
        if timeout_seconds <= 0:
            raise ValueError("LLM timeout must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("LLM temperature must be between 0 and 2")
        return cls(
            enabled=bool(values.get("enabled", False)),
            base_url=str(values.get("base_url", "http://localhost:1234/v1")).rstrip("/"),
            model=str(values.get("model", "")).strip(),
            timeout_seconds=timeout_seconds,
            temperature=temperature,
        )


class LMStudioChatClient:
    """Dependency-free client using LM Studio's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 60,
        temperature: float = 0.1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": list(messages),
                "temperature": self.temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "job_evaluation",
                        "strict": True,
                        "schema": LLMEvaluation.model_json_schema(),
                    },
                },
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMResponseError(
                f"chat service returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMServiceUnavailable(
                f"chat service is unavailable at {self.base_url}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LLMResponseError("chat service returned invalid JSON") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("chat response has an invalid shape") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("chat response content is empty")
        return content


def load_candidate_profile(
    path: Path = DEFAULT_CANDIDATE_PROFILE_PATH,
) -> CandidateProfile:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    return CandidateProfile.model_validate(document)


def _pre_score_payload(job: Job) -> dict[str, object] | None:
    if job.pre_score_components is None:
        return None
    return job.pre_score_components.model_dump(mode="json")


def build_evaluation_messages(
    job: Job, candidate_profile: CandidateProfile
) -> list[dict[str, str]]:
    evaluation_mode = (
        "complete" if job.description_status == "available" else "preliminary"
    )
    payload = {
        "candidate_profile": candidate_profile.model_dump(mode="json"),
        "job": {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "remote_type": job.remote_type,
            "full_description": job.description,
        },
        "deterministic_analysis": {
            "pre_score": job.pre_score,
            "components": _pre_score_payload(job),
        },
        "semantic_categories": [
            {"name": match.name, "similarity": match.similarity}
            for match in job.categories
        ],
        "career_profile_matches": [
            {"name": match.name, "similarity": match.similarity}
            for match in job.profile_matches
        ],
        "data_quality": {
            "description_status": job.description_status,
            "description_length": job.description_length,
        },
        "required_evaluation_status": evaluation_mode,
    }
    if evaluation_mode == "preliminary":
        instruction = (
            "The description is missing. Evaluate only the available title and "
            "metadata and set evaluation_status to preliminary. Express the limited "
            "evidence in concerns; do not invent requirements."
        )
    else:
        instruction = (
            "Use the full description and set evaluation_status to complete. "
            "Separate mandatory gaps from optional nice-to-have gaps."
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{instruction}\n\nINPUT\n{json.dumps(payload, ensure_ascii=False)}",
        },
    ]


class StructuredJobEvaluator:
    """Validate untrusted model output and retry invalid output exactly once."""

    def __init__(self, client: ChatClient) -> None:
        self.client = client

    def evaluate(
        self, job: Job, candidate_profile: CandidateProfile
    ) -> LLMEvaluationAttempt:
        messages = build_evaluation_messages(job, candidate_profile)
        validation_error: str | None = None
        for attempt in range(2):
            try:
                content = self.client.complete(messages)
            except LLMServiceUnavailable as exc:
                return LLMEvaluationAttempt(
                    status="unavailable", model=self.client.model, error=str(exc)
                )
            except LLMResponseError as exc:
                return LLMEvaluationAttempt(
                    status="error", model=self.client.model, error=str(exc)
                )

            try:
                evaluation = LLMEvaluation.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                validation_error = str(exc)
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "The response did not validate against the schema. "
                                "Return a corrected JSON object only."
                            ),
                        },
                    ]
                    continue
                break

            required_status = (
                "complete"
                if job.description_status == "available"
                else "preliminary"
            )
            if evaluation.evaluation_status != required_status:
                validation_error = (
                    f"evaluation_status must be {required_status!r} for this job"
                )
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": f"Correct evaluation_status to {required_status!r}.",
                        },
                    ]
                    continue
                break

            return LLMEvaluationAttempt(
                status="success", model=self.client.model, evaluation=evaluation
            )

        return LLMEvaluationAttempt(
            status="error",
            model=self.client.model,
            error=f"LLM output failed schema validation after one retry: {validation_error}",
        )


def get_structured_job_evaluator(
    config: Mapping[str, object] | None,
) -> StructuredJobEvaluator | None:
    settings = LLMEvaluationSettings.from_config(config)
    if not settings.enabled:
        return None
    if not settings.model:
        raise ValueError("an LLM model is required when LLM evaluation is enabled")
    return StructuredJobEvaluator(
        LMStudioChatClient(
            base_url=settings.base_url,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
        )
    )


__all__ = [
    "DEFAULT_CANDIDATE_PROFILE_PATH",
    "LLMEvaluationSettings",
    "LLMResponseError",
    "LLMServiceUnavailable",
    "LMStudioChatClient",
    "StructuredJobEvaluator",
    "build_evaluation_messages",
    "get_structured_job_evaluator",
    "load_candidate_profile",
]
