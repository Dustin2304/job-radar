import pytest

from api import lm_studio_runtime


def model_document(*, loaded_context=None, maximum=262144):
    instances = []
    if loaded_context is not None:
        instances.append(
            {"id": "model-a", "config": {"context_length": loaded_context}}
        )
    return {
        "model-a": {
            "key": "model-a",
            "max_context_length": maximum,
            "loaded_instances": instances,
        }
    }


def test_ensure_model_reloads_when_context_differs(monkeypatch):
    calls = []
    documents = iter([model_document(loaded_context=12288), model_document(loaded_context=12288)])
    monkeypatch.setattr(lm_studio_runtime, "available_models", lambda base_url: next(documents))
    monkeypatch.setattr(
        lm_studio_runtime.subprocess,
        "run",
        lambda command, check: calls.append(command),
    )

    lm_studio_runtime.ensure_model_loaded(
        "model-a",
        base_url="http://localhost:1234/v1",
        context_length=65536,
        gpu_offload="max",
        parallel_requests=1,
    )

    assert calls[0] == ["lms", "unload", "model-a"]
    assert calls[1][0:3] == ["lms", "load", "model-a"]
    assert calls[1][calls[1].index("-c") + 1] == "65536"


def test_ensure_model_rejects_context_above_model_limit(monkeypatch):
    monkeypatch.setattr(
        lm_studio_runtime,
        "available_models",
        lambda base_url: model_document(maximum=32768),
    )

    with pytest.raises(ValueError, match="exceeds"):
        lm_studio_runtime.ensure_model_loaded(
            "model-a",
            base_url="http://localhost:1234/v1",
            context_length=65536,
            gpu_offload="max",
            parallel_requests=1,
        )
