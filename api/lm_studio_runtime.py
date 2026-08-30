"""Read and prepare local LM Studio model instances for reproducible benchmarks."""

from __future__ import annotations

import json
import subprocess
from urllib.request import urlopen


def available_models(base_url: str) -> dict[str, dict[str, object]]:
    server_root = base_url.rstrip("/").removesuffix("/v1")
    with urlopen(f"{server_root}/api/v1/models", timeout=10) as response:
        document = json.load(response)
    return {
        model["key"]: model
        for model in document["models"]
        if model.get("type") == "llm"
    }


def loaded_model_ids(base_url: str) -> set[str]:
    return {
        instance["id"]
        for model in available_models(base_url).values()
        for instance in model.get("loaded_instances", [])
    }


def loaded_model_context_length(model_id: str, base_url: str) -> int | None:
    """Return the context length of a loaded model instance, if present."""

    for model in available_models(base_url).values():
        for instance in model.get("loaded_instances", []):
            if instance.get("id") == model_id:
                value = instance.get("config", {}).get("context_length")
                return int(value) if value is not None else None
    return None


def ensure_model_loaded(
    model_id: str,
    *,
    base_url: str,
    context_length: int,
    gpu_offload: str,
    parallel_requests: int,
) -> None:
    model = available_models(base_url).get(model_id)
    if model is None:
        raise ValueError(f"model is not available in LM Studio: {model_id}")
    max_context = model.get("max_context_length")
    if max_context is not None and context_length > int(max_context):
        raise ValueError(
            f"requested context {context_length} exceeds {model_id} maximum "
            f"of {max_context}"
        )
    loaded_context = loaded_model_context_length(model_id, base_url)
    if loaded_context is not None:
        if loaded_context == context_length:
            return
        subprocess.run(["lms", "unload", model_id], check=True)
    subprocess.run(
        [
            "lms",
            "load",
            model_id,
            "--gpu",
            gpu_offload,
            "-c",
            str(context_length),
            "--parallel",
            str(parallel_requests),
            "--identifier",
            model_id,
            "-y",
        ],
        check=True,
    )


def prepare_exclusive_model(
    model_id: str,
    *,
    base_url: str,
    context_length: int,
    gpu_offload: str,
    parallel_requests: int,
) -> None:
    """Keep embedding instances intact while unloading other chat models."""

    models = available_models(base_url)
    loaded_llms = {
        instance["id"]
        for model in models.values()
        for instance in model.get("loaded_instances", [])
    }
    for instance_id in sorted(loaded_llms - {model_id}):
        subprocess.run(["lms", "unload", instance_id], check=True)
    ensure_model_loaded(
        model_id,
        base_url=base_url,
        context_length=context_length,
        gpu_offload=gpu_offload,
        parallel_requests=parallel_requests,
    )


__all__ = [
    "available_models",
    "ensure_model_loaded",
    "loaded_model_context_length",
    "loaded_model_ids",
    "prepare_exclusive_model",
]
