"""Runtime configuration shared by adapters and run manifests."""

from __future__ import annotations

import os

DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_TIMEOUT_SECONDS = 180


def model_name() -> str:
    return os.getenv("OLLAMA_REASONER_MODEL", DEFAULT_MODEL)


def inference_timeout() -> int:
    return int(os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))


def inference_config() -> dict[str, object]:
    return {"model": model_name(), "timeout_seconds": inference_timeout(), "retries": 0}
