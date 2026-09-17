"""Call the named script for each loaded case and send ground_truth + actual to evaluator."""

from __future__ import annotations

import importlib
import hashlib
import traceback
from pathlib import Path
from typing import Any

from core.evaluator import evaluate
from core.loader import load_cases, validate_case_payload
from core.run_log import RunLog
from core.config import inference_config
from core.loader import LoaderError
from core.ollama import ensure_model_available
from core.schema_contract import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent

# Filename wiring only. Not a product registry.
SCRIPTS = {
    "intent": {
        "questions": ROOT / "data" / "intent_question.json",
        "ground_truth": ROOT / "data" / "intent_ground_truth.json",
        "module": "scripts.intent_test",
        "mode": "exact",
    },
    "sql": {
        "questions": ROOT / "data" / "sql_test_questions.json",
        "ground_truth": ROOT / "data" / "sql_ground_truth.json",
        "module": "scripts.sql_test",
        "mode": "query_result",
    },
    "llm_judge": {
        "questions": ROOT / "data" / "llm_test_questions.json",
        "ground_truth": ROOT / "data" / "llm_ground_truth.json",
        "module": "scripts.llm_judge_test",
        "mode": "fuzzy",
    },
}


def _evaluator_label(mode: str, judge: Any) -> str:
    if mode == "exact":
        return "core.evaluator.evaluate (exact JSON equality)"
    if mode == "query_result":
        return "core.evaluator.evaluate (run ground_truth sql, compare count to actual)"
    if judge is not None:
        return f"core.evaluator.evaluate (fuzzy via {judge.__module__}.judge)"
    return "core.evaluator.evaluate (fuzzy fallback: exact JSON equality)"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _log_case_header(log: RunLog, name: str, spec: dict[str, Any], case: dict[str, Any]) -> None:
    log.section(f"{name} / case {case['id']}")
    log.field("questions_file", _display_path(spec["questions"]))
    log.field("ground_truth_file", _display_path(spec["ground_truth"]))
    log.field("script_module", spec["module"])
    log.field("script_entrypoint", f"{spec['module']}.run(input)")
    log.field("eval_mode", spec["mode"])
    log.block("input (from questions file, passed to script)", case["input"])
    log.block("ground_truth (from ground truth file, expected output)", case["ground_truth"])


def _log_evaluation(
    log: RunLog,
    result: str,
    reason: str,
    evaluator: str,
    actual: Any = None,
    exc: BaseException | None = None,
) -> None:
    log.line("")
    log.line("--- evaluation ---")
    log.field("checked_by", evaluator)
    if isinstance(actual, dict) and actual.get("sql"):
        log.field("generated_sql", str(actual["sql"]))
    if actual is not None:
        log.block("actual (returned by script)", actual)
    if exc is not None:
        log.field("script_error", f"{type(exc).__name__}: {exc}")
        log.line("traceback:")
        log.line(traceback.format_exc().rstrip())
    log.field("result", result)
    log.field("reason", reason)


def run_script(name: str, log: RunLog, case_id: str | None = None) -> dict[str, int]:
    if name not in SCRIPTS:
        raise LoaderError(f"unknown script: {name}")
    spec = SCRIPTS[name]
    cases = load_cases(spec["questions"], spec["ground_truth"])
    if case_id is not None:
        matches = [case for case in cases if str(case["id"]) == case_id]
        if len(matches) > 1:
            raise ValueError(f"case id {case_id} is ambiguous; IDs preserve their original JSON types")
        cases = matches
        if not matches:
            raise ValueError(f"no case with id {case_id} in script {name}")
    module = importlib.import_module(spec["module"])
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise AttributeError(f"{spec['module']} must define run(input)")

    judge = getattr(module, "judge", None)
    if judge is not None and not callable(judge):
        judge = None
    evaluator = _evaluator_label(spec["mode"], judge)
    if spec["mode"] == "fuzzy" and judge is None:
        raise LoaderError(f"{name} requires a callable judge(input, actual) before model calls")
    if name in {"intent", "sql", "llm_judge"}:
        ensure_model_available()

    log.section(f"script {name}")
    log.field("cases_loaded", str(len(cases)))
    log.field("evaluator", evaluator)
    log.field("inference_config", str(inference_config()))
    log.record({
        "type": "manifest",
        "suite": name,
        "mode": spec["mode"],
        "questions": _display_path(spec["questions"]),
        "ground_truth": _display_path(spec["ground_truth"]),
        "model": inference_config()["model"],
        "inference": inference_config(),
        "judge_configured": judge is not None,
        "schema_version": SCHEMA_VERSION,
        "questions_sha256": _sha256(spec["questions"]),
        "ground_truth_sha256": _sha256(spec["ground_truth"]),
        "seed_sha256": _sha256(ROOT / "db" / "seed_test_data.sql"),
    })

    totals = {"total": len(cases), "passed": 0, "failed": 0, "errors": 0}

    for case in cases:
        try:
            validate_case_payload(name, case)
        except Exception as exc:
            _log_case_header(log, name, spec, case)
            _log_evaluation(
                log,
                result="ERROR",
                reason="case compatibility validation failed",
                evaluator=evaluator,
                exc=exc,
            )
            totals["errors"] += 1
            log.record({
                "suite": name,
                "case_id": case["id"],
                "status": "ERROR",
                "stage": "validate",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        _log_case_header(log, name, spec, case)
        log.line("")
        log.line("running script...")
        actual = None
        try:
            actual = run_fn(case["input"])
        except Exception as exc:
            _log_evaluation(
                log,
                result="ERROR",
                reason="script raised before returning actual",
                evaluator=evaluator,
                exc=exc,
            )
            totals["errors"] += 1
            log.record({"suite": name, "case_id": case["id"], "status": "ERROR", "stage": "run", "actual": actual, "error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            if spec["mode"] == "fuzzy":
                verdict = evaluate(
                    spec["mode"],
                    case["ground_truth"],
                    actual,
                    judge=lambda truth, got: judge(case["input"], truth, got),
                )
            else:
                verdict = evaluate(spec["mode"], case["ground_truth"], actual, judge=None)
        except Exception as exc:
            _log_evaluation(log, result="ERROR", reason="evaluation raised", evaluator=evaluator, actual=actual, exc=exc)
            totals["errors"] += 1
            log.record({"suite": name, "case_id": case["id"], "status": "ERROR", "stage": "evaluate", "actual": actual, "error": f"{type(exc).__name__}: {exc}"})
            continue
        _log_evaluation(
            log,
            result="PASS" if verdict.passed else "FAIL",
            reason=verdict.reason,
            evaluator=evaluator,
            actual=actual,
        )
        status = "PASS" if verdict.passed else "FAIL"
        totals["passed" if verdict.passed else "failed"] += 1
        log.record({"suite": name, "case_id": case["id"], "status": status, "stage": "evaluate", "actual": actual, "reason": verdict.reason})
    return totals
