"""One subprocess boundary for all live-model adapters."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from core.config import inference_timeout, model_name


def run_model(prompt: str, schema: dict[str, Any] | None = None, model: str | None = None) -> str:
    command = ["ollama", "run", model or model_name(), prompt]
    if schema is not None:
        command.extend(["--format", json.dumps(schema)])
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=inference_timeout())
    return result.stdout


def ensure_model_available(model: str | None = None) -> None:
    selected = model or model_name()
    try:
        subprocess.run(["ollama", "show", selected], check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Ollama model {selected!r} is unavailable; start Ollama and pull the configured model") from exc
