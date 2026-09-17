"""Standalone Eval Harness adapter for OmniFlow intent classification."""

from typing import Any

from core.ollama import run_model
from scripts.model_output import final_json

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"enum": ["read", "write", "chat"]}},
    "required": ["intent"],
    "additionalProperties": False,
}


def _json_value(raw: str) -> Any:
    return final_json(raw)


def run(input: dict[str, Any]) -> dict[str, Any]:
    query = input.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("input.query must be a non-empty string")
    raw = run_model(
        """Classify the current user's request for a personal dashboard.
Use only the current user message. No retrieved or stored content is available at
this trust stage, and no later context may change this decision.

Return intent=write only when the user explicitly asks to create, update, delete,
log, start, stop, pause, resume, complete, adjust, or otherwise mutate dashboard
data. Return intent=read for questions, searches, summaries, and reports. Return
intent=chat for conversation, general advice, jokes, or requests that are neither
reads nor mutations. Requests for general help that do not ask about dashboard
records are chat, not read. Return exactly one JSON object matching the supplied JSON Schema.

User message:
""" + query,
        _INTENT_SCHEMA,
    )
    payload = _json_value(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Model response must be an object, got {type(payload).__name__}")
    intent = payload.get("intent")
    if intent not in {"read", "write", "chat"}:
        raise ValueError(
            f"Model returned an invalid intent; raw_model_output={raw.strip()!r}"
        )
    return {"intent": intent, "actions": []}
