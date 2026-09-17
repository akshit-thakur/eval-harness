"""Parse a model's final JSON response without accepting reasoning as output."""

from __future__ import annotations

import json
import re
from typing import Any

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_THINK_RE = re.compile(
    r"\A<(?P<tag>think|redacted_thinking)>.*?</(?P=tag)>\s*",
    re.IGNORECASE | re.DOTALL,
)
_THINKING_TRACE_RE = re.compile(
    r"^Thinking\.\.\..*?\.\.\.done thinking\.\s*",
    re.IGNORECASE | re.DOTALL,
)
_FENCE_RE = re.compile(r"\A```(?:json|sql)?[ \t]*\n(.*?)\n```\Z", re.IGNORECASE | re.DOTALL)


def final_json(raw: str) -> Any:
    cleaned = _ANSI_RE.sub("", raw).strip()
    # Only leading wrappers are reasoning. Tags inside JSON strings are data
    # (including SQL literals) and must retain their exact contents.
    while True:
        stripped = _THINK_RE.sub("", cleaned, count=1).strip()
        stripped = _THINKING_TRACE_RE.sub("", stripped, count=1).strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    if cleaned.lower().startswith("thinking..."):
        raise ValueError("model response has an unfinished thinking trace")
    fence = _FENCE_RE.fullmatch(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        preview = raw if len(raw) <= 2000 else raw[:2000] + "...[truncated]"
        raise ValueError(
            f"Model response was not valid final JSON ({exc}); raw_model_output={preview!r}"
        ) from exc
