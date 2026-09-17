"""Compare ground_truth (human) to actual (from the runner/script)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.db import fetch, scalar_count


@dataclass
class EvalResult:
    passed: bool
    reason: str


JudgeFn = Callable[[Any, Any], Any]


class EvaluationError(RuntimeError):
    """An evaluation-stage failure, distinct from an answer mismatch."""


def evaluate(
    mode: str,
    ground_truth: Any,
    actual: Any,
    judge: Optional[JudgeFn] = None,
) -> EvalResult:
    if mode == "exact":
        return _exact(ground_truth, actual)
    if mode == "query_result":
        return _query_result(ground_truth, actual)
    if mode == "fuzzy":
        if judge is not None:
            return _from_judge(judge(ground_truth, actual))
        return _exact(
            ground_truth,
            actual,
            reason_prefix="llm_judge fallback exact match",
        )
    raise ValueError(f"unknown evaluation mode: {mode}")


def _exact(ground_truth: Any, actual: Any, reason_prefix: str = "exact match") -> EvalResult:
    passed = ground_truth == actual
    if passed:
        return EvalResult(passed=True, reason=f"{reason_prefix}: ground_truth == actual")
    return EvalResult(
        passed=False,
        reason=f"{reason_prefix}: ground_truth != actual (see log for both payloads)",
    )


def _query_result(ground_truth: Any, actual: Any) -> EvalResult:
    if not isinstance(ground_truth, dict) or not isinstance(actual, dict):
        return EvalResult(False, "query_result requires ground_truth and actual objects")

    sql = ground_truth.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return EvalResult(False, "ground_truth must include a non-empty sql field")

    if "count" not in actual:
        return EvalResult(False, "actual must include a count field")

    try:
        expected = scalar_count(fetch(sql))
    except Exception as exc:
        raise EvaluationError(f"reference query failed: {type(exc).__name__}: {exc}") from exc
    got = actual["count"]
    if isinstance(got, bool) or not isinstance(got, int) or got < 0:
        return EvalResult(False, "query_result actual.count must be a non-negative integer")
    if expected == got:
        return EvalResult(
            passed=True,
            reason=f"query_result match on current database (not semantic equivalence): ground_truth sql -> {expected!r}, actual count -> {got!r}",
        )
    return EvalResult(
        passed=False,
        reason=f"query_result mismatch: ground_truth sql -> {expected!r}, actual count -> {got!r}",
    )


def _from_judge(raw: Any) -> EvalResult:
    if isinstance(raw, EvalResult):
        if type(raw.passed) is not bool or not isinstance(raw.reason, str):
            raise TypeError("EvalResult judge verdict requires a boolean passed and string reason")
        return raw
    if isinstance(raw, bool):
        return EvalResult(
            passed=raw,
            reason="llm_judge: pass" if raw else "llm_judge: fail",
        )
    if isinstance(raw, dict):
        if set(raw) - {"passed", "pass", "reason"}:
            raise TypeError("judge verdict contains unknown fields")
        fields = [key for key in ("passed", "pass") if key in raw]
        if len(fields) != 1 or not isinstance(raw[fields[0]], bool):
            raise TypeError("judge verdict must contain exactly one boolean pass/passed field")
        if "reason" in raw and not isinstance(raw["reason"], str):
            raise TypeError("judge verdict reason must be a string")
        passed = raw[fields[0]]
        reason = raw.get("reason", "llm_judge")
        return EvalResult(passed=passed, reason=reason)
    raise TypeError("judge() must return EvalResult, bool, or {pass/passed, reason}")
