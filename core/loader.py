"""Entry point: load cases, dispatch to runner, print row-by-row results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

class LoaderError(ValueError):
    pass


def validate_case_payload(suite: str, case: dict[str, Any]) -> None:
    """Validate adapter-facing shapes without judging user-authored semantics."""
    value = case["input"]
    loc = f"{suite} case {case['id']} input"
    if not isinstance(value, dict):
        raise LoaderError(f"{loc} must be an object")
    if suite in {"intent", "llm_judge"} and (not isinstance(value.get("query"), str) or not value["query"].strip()):
        raise LoaderError(f"{loc}.query must be a non-empty string")
    if suite == "sql":
        if not isinstance(value.get("question"), str) or not value["question"].strip():
            raise LoaderError(f"{loc}.question must be a non-empty string")
        nested = value.get("input")
        if not isinstance(nested, dict):
            raise LoaderError(f"{loc}.input must be an object")
        tables = nested.get("tables")
        if nested.get("intent") != "read" or not isinstance(tables, list) or not tables or not all(isinstance(item, str) for item in tables):
            raise LoaderError(f"{loc}.input must contain intent=read and a non-empty string tables list")
    if suite == "llm_judge":
        records = value.get("results", value.get("context"))
        if not isinstance(records, list):
            raise LoaderError(f"{loc}.results must be a list")
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise LoaderError(f"{loc}.results[{index}] must be an object")
            for field in ("source_table", "source_id", "metadata"):
                if field not in record:
                    raise LoaderError(f"{loc}.results[{index}] missing {field}")
            if not isinstance(record["metadata"], dict):
                raise LoaderError(f"{loc}.results[{index}].metadata must be an object")


def _id_key(value: Any) -> tuple[str, str]:
    """Hashable identity that preserves both value type and display value."""
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        raise LoaderError(f"case id must be JSON-scalar, got {type(value).__name__}")
    try:
        return (type(value).__name__, json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError):
        raise LoaderError(f"case id must be JSON-scalar, got {type(value).__name__}")


def load_cases(questions_path: Path, ground_truth_path: Path) -> list[dict[str, Any]]:
    questions = _read_list(questions_path)
    truths = _index_by_id(_read_list(ground_truth_path), ground_truth_path)

    loaded: list[dict[str, Any]] = []
    if not questions and truths:
        raise LoaderError(f"{ground_truth_path} has unmatched ids: {list(truths)}")
    if not questions:
        return []
    seen: set[tuple[str, str]] = set()
    for index, question in enumerate(questions):
        loc = f"{questions_path}[{index}]"
        if not isinstance(question, dict) or "id" not in question:
            raise LoaderError(f"{loc} must be an object with an id")
        if "actual" in question:
            raise LoaderError(f"{loc} must not include 'actual'; it comes from the runner")

        case_id = question["id"]
        key = _id_key(case_id)
        if key in seen:
            raise LoaderError(f"{loc} duplicate id: {case_id}")
        seen.add(key)

        truth_key = _id_key(case_id)
        if truth_key not in truths:
            raise LoaderError(f"{loc} has no matching ground truth id {case_id}")
        truth = truths[truth_key]
        if "actual" in truth:
            raise LoaderError(
                f"{ground_truth_path} id {case_id} must not include 'actual'"
            )

        payload = {key: value for key, value in question.items() if key != "id"}
        ground_truth = {key: value for key, value in truth.items() if key != "id"}
        loaded.append(
            {
                "id": case_id,
                "input": payload,
                "ground_truth": ground_truth,
            }
        )

    unused = [key for key in truths if key not in seen]
    if unused:
        raise LoaderError(f"{ground_truth_path} has unmatched ids: {unused}")
    return loaded


def _read_list(path: Path) -> list[Any]:
    if not path.exists():
        raise LoaderError(f"data file not found: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise LoaderError(f"data file is empty: {path}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LoaderError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise LoaderError(f"{path} must be a JSON array")
    return payload


def _index_by_id(items: list[Any], path: Path) -> dict[Any, dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for index, item in enumerate(items):
        loc = f"{path}[{index}]"
        if not isinstance(item, dict) or "id" not in item:
            raise LoaderError(f"{loc} must be an object with an id")
        case_id = item["id"]
        key = _id_key(case_id)
        if key in indexed:
            raise LoaderError(f"{loc} duplicate id: {case_id}")
        indexed[key] = item
    return indexed


def main(argv: list[str] | None = None) -> int:
    from core.runner import SCRIPTS, run_script

    parser = argparse.ArgumentParser(description="eval-harness: loader -> runner -> evaluator")
    parser.add_argument(
        "--script",
        choices=[*SCRIPTS, "all"],
        default="all",
        help="which project script to run (default: all, independently)",
    )
    parser.add_argument(
        "--case-id",
        help="run only this case id (string; e.g. 8)",
    )
    args = parser.parse_args(argv)
    if args.case_id is not None and args.script == "all":
        parser.error("--case-id requires a single --script (not all)")

    from core.run_log import RunLog

    names = list(SCRIPTS) if args.script == "all" else [args.script]
    log_label = f"{args.script}_case{args.case_id}" if args.case_id else args.script
    log = RunLog(log_label)
    status = 0
    totals = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "no_results": 0}
    try:
        for name in names:
            try:
                if name == "sql":
                    from core.db import validate_database_contract

                    validate_database_contract()
                summary = run_script(name, log, case_id=args.case_id)
            except (LoaderError, ValueError, AttributeError, RuntimeError) as exc:
                print(f"{name}: configuration/execution error: {exc}", file=sys.stderr)
                log.section(f"script {name} ERROR")
                log.field("error", str(exc))
                summary = {"total": 0, "passed": 0, "failed": 0, "errors": 1}
                # A suite could not be evaluated at all. Keep this distinct
                # from status 1, which means cases ran and failed/errored.
                status = max(status, 2)
            for key in ("total", "passed", "failed", "errors"):
                totals[key] += summary[key]
            if summary["errors"] or summary["failed"] or summary["total"] == 0:
                status = max(status, 1)
    finally:
        log.close()
    if totals["total"] == 0:
        status = max(status, 1)
        totals["no_results"] = 1
    print(f"totals={totals}; log saved to {log.path}; jsonl={log.json_path}; exit_status={status}", file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
