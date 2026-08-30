"""Structured local-LLM evaluation foundation for canonical jobs."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from pydantic import ValidationError

from .models import CandidateProfile, Job, LLMEvaluation, LLMEvaluationAttempt

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_PROFILE_PATH = ROOT / "config" / "candidate_profile.yaml"

PromptFamily = Literal["minimal", "evidence_first", "conservative"]

SHARED_SYSTEM_PROMPT = """You evaluate whether applying to a job is worthwhile for one candidate.

Only CANDIDATE PROFILE / facts, skills, and professional_strengths contain factual
candidate information. CANDIDATE PROFILE / preferences describes desired roles, not
candidate capabilities. Follow evaluation_guidance without turning it into new facts.
Never infer candidate skills or experience from the job description, semantic matches,
or deterministic analysis. Keep the deterministic pre-score, semantic similarities,
and your own fit score conceptually separate. Return only JSON matching the supplied
schema. Do not output chain-of-thought or any text outside the JSON object.
"""

PROMPT_INSTRUCTIONS: dict[PromptFamily, str] = {
    "minimal": """Evaluate the job against the candidate using the provided profile,
job data, existing analysis, and evaluation guidance.""",
    "evidence_first": """Use this internal evaluation order without exposing your
reasoning: (1) identify relevant job requirements, (2) separate mandatory from
preferred requirements, (3) match requirements only against explicit candidate facts,
(4) identify unsupported or missing requirements, (5) assess experience and seniority,
(6) assess overall role fit, and (7) produce the structured evaluation.""",
    "conservative": """Use the evidence-first order. Treat a missing mandatory
requirement as a significant negative factor and a missing nice-to-have as a limited
negative factor. Candidate facts not explicitly present are unknown or missing.
Preferred experience above the candidate level is a concern, not an automatic reject.
A mandatory multi-year experience gap is a strong negative factor. Missing descriptions
require a preliminary evaluation. Never infer a related skill as direct experience.""",
}


def evaluation_prompt_sha256(prompt_family: PromptFamily) -> str:
    content = f"{SHARED_SYSTEM_PROMPT}\n{PROMPT_INSTRUCTIONS[prompt_family]}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class LLMServiceUnavailable(ConnectionError):
    """Raised when the configured local chat service cannot be reached."""


class LLMResponseError(RuntimeError):
    """Raised when the chat service rejects a request or returns an invalid shape."""


class ChatClient(Protocol):
    model: str

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str: ...


@dataclass(frozen=True)
class LLMRequestStats:
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    time_to_first_token_seconds: float | None = None


@dataclass(frozen=True)
class EvaluationDiagnostics:
    result: LLMEvaluationAttempt
    attempts: int
    first_pass_valid: bool


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
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        request_body: dict[str, object] = {
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
        if self.max_tokens is not None:
            request_body["max_tokens"] = self.max_tokens
        if self.seed is not None:
            request_body["seed"] = self.seed
        payload = json.dumps(request_body).encode("utf-8")
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


class LMStudioResponsesClient:
    """LM Studio Responses client with configurable native reasoning effort.

    LM Studio currently returns Responses structured-output requests as text, so the
    unchanged schema is supplied to the model and validation remains entirely in the
    existing ``StructuredJobEvaluator``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        reasoning_effort: Literal["none", "minimal", "low", "medium", "high"],
        timeout_seconds: float = 60,
        temperature: float = 0.1,
        max_output_tokens: int = 2000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.request_stats: list[LLMRequestStats] = []

    def reset_stats(self) -> None:
        self.request_stats.clear()

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        system_messages = [
            message["content"] for message in messages if message["role"] == "system"
        ]
        input_messages = [
            dict(message) for message in messages if message["role"] != "system"
        ]
        schema = LLMEvaluation.model_json_schema()
        instructions = "\n\n".join(system_messages) + (
            "\n\nReturn JSON conforming exactly to this unchanged schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        request_body: dict[str, object] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_messages,
            "reasoning": {"effort": self.reasoning_effort},
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "job_evaluation",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        request = Request(
            f"{self.base_url}/responses",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMResponseError(
                f"responses service returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMServiceUnavailable(
                f"responses service timed out or is unavailable at {self.base_url}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LLMResponseError("responses service returned invalid JSON") from exc

        usage = body.get("usage") or {}
        output_details = usage.get("output_tokens_details") or {}
        self.request_stats.append(
            LLMRequestStats(
                output_tokens=usage.get("output_tokens"),
                reasoning_tokens=output_details.get("reasoning_tokens"),
            )
        )
        if body.get("status") != "completed":
            raise LLMResponseError(
                f"responses request did not complete: {body.get('incomplete_details')}"
            )

        output_texts = [
            content.get("text")
            for item in body.get("output", [])
            if item.get("type") == "message"
            for content in item.get("content", [])
            if content.get("type") == "output_text"
        ]
        content = "".join(value for value in output_texts if isinstance(value, str))
        if not content.strip():
            raise LLMResponseError("responses output text is empty")
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
    job: Job,
    candidate_profile: CandidateProfile,
    *,
    prompt_family: PromptFamily = "conservative",
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
        {
            "role": "system",
            "content": f"{SHARED_SYSTEM_PROMPT}\n{PROMPT_INSTRUCTIONS[prompt_family]}",
        },
        {
            "role": "user",
            "content": f"{instruction}\n\nINPUT\n{json.dumps(payload, ensure_ascii=False)}",
        },
    ]


class StructuredJobEvaluator:
    """Validate untrusted model output and retry invalid output exactly once."""

    def __init__(
        self,
        client: ChatClient,
        *,
        prompt_family: PromptFamily = "conservative",
    ) -> None:
        self.client = client
        self.prompt_family = prompt_family

    def evaluate(
        self, job: Job, candidate_profile: CandidateProfile
    ) -> LLMEvaluationAttempt:
        return self.evaluate_with_diagnostics(job, candidate_profile).result

    def evaluate_with_diagnostics(
        self, job: Job, candidate_profile: CandidateProfile
    ) -> EvaluationDiagnostics:
        messages = build_evaluation_messages(
            job, candidate_profile, prompt_family=self.prompt_family
        )
        validation_error: str | None = None
        for attempt in range(2):
            try:
                content = self.client.complete(messages)
            except LLMServiceUnavailable as exc:
                return EvaluationDiagnostics(
                    result=LLMEvaluationAttempt(
                        status="unavailable", model=self.client.model, error=str(exc)
                    ),
                    attempts=attempt + 1,
                    first_pass_valid=False,
                )
            except LLMResponseError as exc:
                return EvaluationDiagnostics(
                    result=LLMEvaluationAttempt(
                        status="error", model=self.client.model, error=str(exc)
                    ),
                    attempts=attempt + 1,
                    first_pass_valid=False,
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

            return EvaluationDiagnostics(
                result=LLMEvaluationAttempt(
                    status="success", model=self.client.model, evaluation=evaluation
                ),
                attempts=attempt + 1,
                first_pass_valid=attempt == 0,
            )

        return EvaluationDiagnostics(
            result=LLMEvaluationAttempt(
                status="error",
                model=self.client.model,
                error=(
                    "LLM output failed schema validation after one retry: "
                    f"{validation_error}"
                ),
            ),
            attempts=2,
            first_pass_valid=False,
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
    "EvaluationDiagnostics",
    "LLMEvaluationSettings",
    "LLMResponseError",
    "LLMRequestStats",
    "LLMServiceUnavailable",
    "LMStudioChatClient",
    "LMStudioResponsesClient",
    "PROMPT_INSTRUCTIONS",
    "PromptFamily",
    "SHARED_SYSTEM_PROMPT",
    "StructuredJobEvaluator",
    "build_evaluation_messages",
    "evaluation_prompt_sha256",
    "get_structured_job_evaluator",
    "load_candidate_profile",
]
