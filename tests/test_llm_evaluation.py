from collections.abc import Mapping, Sequence
from io import BytesIO
import json

import pytest
from pydantic import ValidationError

from api.llm_evaluation import (
    LLMEvaluationSettings,
    LLMServiceUnavailable,
    LMStudioChatClient,
    StructuredJobEvaluator,
    build_evaluation_messages,
    get_structured_job_evaluator,
    load_candidate_profile,
)
from api.models import LLMEvaluation
from api.normalization import normalize_job


def canonical_job(*, description: str = "Build automation workflows with Python."):
    return normalize_job(
        {
            "id": "job-1",
            "site": "linkedin",
            "title": "Junior Automation Engineer",
            "company": "Example GmbH",
            "location": "Karlsruhe",
            "job_url": "https://example.com/jobs/1",
            "description": description,
        },
        "automation",
    )


def valid_evaluation(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "evaluation_status": "complete",
        "fit_score": 82,
        "recommendation": "strong_match",
        "role_fit": 88,
        "experience_fit": 70,
        "skills_fit": 84,
        "seniority_fit": 90,
        "matched_requirements": ["Python"],
        "missing_requirements": [],
        "nice_to_have_gaps": ["Databricks"],
        "concerns": [],
        "experience_requirement": "2-3 years preferred",
        "experience_gap": False,
        "summary": "Strong role and skills alignment.",
    }
    payload.update(overrides)
    return payload


class QueueChatClient:
    model = "test-chat-model"

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[list[Mapping[str, str]]] = []

    def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.calls.append(list(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_candidate_profile_separates_facts_from_preferences():
    profile = load_candidate_profile()

    assert profile.facts.education[0].degree == "Bachelor International Management"
    assert {item.area for item in profile.facts.experience} == {
        "process_automation",
        "application_development",
        "data_reporting",
    }
    assert profile.preferences.target_seniority == ["junior", "entry_level"]
    assert "automation" in profile.preferences.target_directions


def test_llm_evaluation_schema_rejects_invalid_scores_and_unknown_fields():
    with pytest.raises(ValidationError):
        LLMEvaluation.model_validate(valid_evaluation(fit_score=101))

    with pytest.raises(ValidationError):
        LLMEvaluation.model_validate(valid_evaluation(candidate_knows_sap=True))

    incomplete = valid_evaluation()
    del incomplete["missing_requirements"]
    with pytest.raises(ValidationError):
        LLMEvaluation.model_validate(incomplete)


def test_prompt_contains_full_description_and_existing_analysis():
    description = "Start " + ("relevant detail " * 80) + "END-OF-DESCRIPTION"
    job = canonical_job(description=description).model_copy(
        update={"pre_score": 67.0}
    )

    messages = build_evaluation_messages(job, load_candidate_profile())

    assert len(messages) == 2
    assert "Only information in CANDIDATE PROFILE / facts" in messages[0]["content"]
    assert "END-OF-DESCRIPTION" in messages[1]["content"]
    assert '"pre_score": 67.0' in messages[1]["content"]
    assert '"required_evaluation_status": "complete"' in messages[1]["content"]


def test_missing_description_requires_preliminary_evaluation():
    messages = build_evaluation_messages(
        canonical_job(description=""), load_candidate_profile()
    )

    assert '"description_status": "missing"' in messages[1]["content"]
    assert '"required_evaluation_status": "preliminary"' in messages[1]["content"]
    assert "do not invent requirements" in messages[1]["content"]


def test_lm_studio_client_requests_strict_json_schema(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return BytesIO(
            json.dumps(
                {
                    "choices": [
                        {"message": {"content": json.dumps(valid_evaluation())}}
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("api.llm_evaluation.urlopen", fake_urlopen)
    client = LMStudioChatClient(
        base_url="http://localhost:1234/v1/",
        model="test-model",
        timeout_seconds=12,
        temperature=0,
    )

    content = client.complete([{"role": "user", "content": "Evaluate"}])

    assert json.loads(content)["fit_score"] == 82
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    schema_config = captured["payload"]["response_format"]["json_schema"]
    assert schema_config["strict"] is True
    assert schema_config["schema"]["additionalProperties"] is False
    assert set(schema_config["schema"]["required"]) == set(valid_evaluation())


def test_invalid_output_is_retried_once_then_validated_without_repair():
    client = QueueChatClient(
        [
            "fit_score: 82",
            json.dumps(valid_evaluation()),
        ]
    )
    evaluator = StructuredJobEvaluator(client)

    result = evaluator.evaluate(canonical_job(), load_candidate_profile())

    assert result.status == "success"
    assert result.evaluation is not None
    assert result.evaluation.fit_score == 82
    assert len(client.calls) == 2
    assert client.calls[1][-2]["content"] == "fit_score: 82"
    assert "corrected JSON object only" in client.calls[1][-1]["content"]


def test_invalid_output_after_retry_returns_nonfatal_error():
    client = QueueChatClient(["not json", "still not json"])

    result = StructuredJobEvaluator(client).evaluate(
        canonical_job(), load_candidate_profile()
    )

    assert result.status == "error"
    assert result.evaluation is None
    assert "after one retry" in (result.error or "")
    assert len(client.calls) == 2


def test_service_outage_returns_unavailable_without_retrying():
    client = QueueChatClient([LLMServiceUnavailable("LM Studio is down")])

    result = StructuredJobEvaluator(client).evaluate(
        canonical_job(), load_candidate_profile()
    )

    assert result.status == "unavailable"
    assert result.evaluation is None
    assert result.error == "LM Studio is down"
    assert len(client.calls) == 1


def test_preliminary_status_is_enforced_for_missing_descriptions():
    client = QueueChatClient(
        [
            json.dumps(valid_evaluation()),
            json.dumps(valid_evaluation(evaluation_status="preliminary")),
        ]
    )

    result = StructuredJobEvaluator(client).evaluate(
        canonical_job(description=""), load_candidate_profile()
    )

    assert result.status == "success"
    assert result.evaluation is not None
    assert result.evaluation.evaluation_status == "preliminary"
    assert "Correct evaluation_status" in client.calls[1][-1]["content"]


def test_evaluator_factory_is_disabled_until_a_model_is_selected():
    assert get_structured_job_evaluator({"enabled": False}) is None

    with pytest.raises(ValueError, match="model is required"):
        get_structured_job_evaluator({"enabled": True, "model": ""})


def test_llm_settings_validate_timeout_and_temperature():
    with pytest.raises(ValueError, match="timeout"):
        LLMEvaluationSettings.from_config({"timeout_seconds": 0})
    with pytest.raises(ValueError, match="temperature"):
        LLMEvaluationSettings.from_config({"temperature": 2.1})
