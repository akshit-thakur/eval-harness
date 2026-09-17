from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from core.evaluator import EvaluationError, evaluate
from core.loader import LoaderError, load_cases
from core import runner
from core.run_log import RunLog
from core.schema_contract import TABLE_FIELDS
from core.sql_guard import validate_read_query


def test_sql_guard_rejects_returning_and_writable_cte_without_database():
    for sql in (
        "DELETE FROM tasks RETURNING id",
        "WITH changed AS (DELETE FROM tasks RETURNING id) SELECT COUNT(*) FROM changed",
        "SELECT COUNT(*) FROM recipes",
    ):
        if sql.startswith("SELECT"):
            with pytest.raises(ValueError):
                validate_read_query(sql, {"tasks"})
        else:
            with pytest.raises(ValueError):
                validate_read_query(sql, {"tasks"})


def test_sql_guard_does_not_treat_string_literals_as_statements():
    assert validate_read_query("SELECT COUNT(*) FROM tasks WHERE title = 'delete'", {"tasks"}).endswith(";")
    assert validate_read_query("SELECT COUNT(*) FROM tasks WHERE title = 'a;b'", {"tasks"}).endswith(";")


def test_sql_guard_parses_qualified_joins_nested_queries_and_cte_scope():
    assert validate_read_query(
        'SELECT COUNT(*) FROM public."tasks" AS t JOIN "public"."medications" m ON TRUE',
        {"tasks", "medications"},
    ).endswith(";")
    assert validate_read_query(
        "SELECT COUNT(*) FROM (SELECT id FROM tasks) nested, medications",
        {"tasks", "medications"},
    ).endswith(";")
    assert validate_read_query(
        "WITH task_rows AS (SELECT id FROM tasks) SELECT COUNT(*) FROM task_rows",
        {"tasks"},
    ).endswith(";")
    with pytest.raises(ValueError, match="disallowed relation.*recipes"):
        validate_read_query(
            "WITH task_rows AS (SELECT id FROM tasks) SELECT COUNT(*) FROM recipes",
            {"tasks"},
        )
    for sql in (
        "SELECT COUNT(*) FROM (tasks CROSS JOIN recipes)",
        "SELECT COUNT(*) FROM tasks WHERE COALESCE((SELECT COUNT(*) FROM recipes), 0) > 0",
        "WITH recipes AS (SELECT * FROM recipes) SELECT COUNT(*) FROM recipes",
        "WITH recipes AS (SELECT * FROM tasks) SELECT COUNT(*) FROM public.recipes",
    ):
        with pytest.raises(ValueError, match="disallowed relation.*recipes"):
            validate_read_query(sql, {"tasks"})
    assert validate_read_query(
        "WITH task_rows AS MATERIALIZED (SELECT * FROM public.\"tasks\") SELECT COUNT(*) FROM task_rows",
        {"tasks"},
    ).endswith(";")


def test_sql_guard_rejects_writable_ctes_and_schema_bypass():
    for sql in (
        "WITH changed AS (UPDATE tasks SET title = 'x' RETURNING id) SELECT COUNT(*) FROM changed",
        "SELECT COUNT(*) FROM other.tasks",
        "SELECT COUNT(*) FROM \"Tasks\"",
    ):
        with pytest.raises(ValueError):
            validate_read_query(sql, {"tasks"})


def test_sql_guard_applies_postgres_identifier_case_to_cte_scope():
    with pytest.raises(ValueError, match="disallowed relation.*recipes"):
        validate_read_query(
            'WITH "RECIPES" AS (SELECT * FROM tasks) SELECT COUNT(*) FROM RECIPES',
            {"tasks"},
        )
    assert validate_read_query(
        'WITH "RECIPES" AS (SELECT * FROM tasks) SELECT COUNT(*) FROM "RECIPES"',
        {"tasks"},
    ).endswith(";")
    assert validate_read_query(
        'WITH "recipes" AS (SELECT * FROM tasks) SELECT COUNT(*) FROM RECIPES',
        {"tasks"},
    ).endswith(";")
    assert validate_read_query(
        "WITH recipes AS (SELECT * FROM tasks) SELECT COUNT(*) FROM RECIPES",
        {"tasks"},
    ).endswith(";")
    with pytest.raises(ValueError, match="disallowed relation.*recipes"):
        validate_read_query(
            'WITH "RECIPES" AS (SELECT * FROM tasks) SELECT COUNT(*) FROM public."recipes"',
            {"tasks"},
        )


def test_sql_guard_rejects_select_into_but_allows_ordinary_select():
    for sql in (
        "SELECT COUNT(*) INTO copied_counts FROM tasks",
        "SELECT COUNT(*) INTO TEMP copied_counts FROM tasks",
    ):
        with pytest.raises(ValueError, match="SELECT INTO"):
            validate_read_query(sql, {"tasks"})
    assert validate_read_query("SELECT COUNT(*) FROM tasks", {"tasks"}).endswith(";")


def test_sql_count_contract_rejects_malformed_actuals(monkeypatch):
    # This test is about the output contract, so make successful reference DB
    # access explicit. A missing DB must be covered by the error-classification
    # test rather than accidentally making every malformed value an ERROR.
    monkeypatch.setattr("core.evaluator.fetch", lambda _sql: [{"count": 1}])
    truth = {"sql": "SELECT COUNT(*) FROM tasks"}
    for actual in ({"count": True}, {"count": -1}, {"count": "1"}, {"count": [1]}):
        result = evaluate("query_result", truth, actual)
        assert not result.passed


def test_sql_result_matching_does_not_claim_semantic_equivalence(monkeypatch):
    monkeypatch.setattr("core.evaluator.fetch", lambda _sql: [{"count": 2}])
    result = evaluate(
        "query_result",
        {"sql": "SELECT COUNT(*) FROM tasks WHERE completed = FALSE"},
        {"sql": "SELECT COUNT(*) FROM recipes", "count": 2},
    )
    assert result.passed
    assert "not semantic equivalence" in result.reason


def test_strict_judge_verdict():
    with pytest.raises(TypeError):
        evaluate("fuzzy", {}, {}, judge=lambda *_: {"passed": "false"})
    with pytest.raises(TypeError):
        evaluate("fuzzy", {}, {}, judge=lambda *_: {})


def test_grounded_judge_uses_question_ideal_and_untrusted_records(monkeypatch):
    from scripts import llm_judge_test

    seen = {}
    def fake_judge_model(prompt, schema, model):
        seen["prompt"] = prompt
        return '{"passed": true, "reason": "equivalent"}'

    monkeypatch.setattr(llm_judge_test, "run_model", fake_judge_model)
    case = {"query": "What is the title?", "results": [{"source_table": "tasks", "source_id": 1, "metadata": {"title": "Buy milk"}}]}
    verdict = llm_judge_test.judge(case, {"ideal_output": "Your task is Buy milk."}, {"answer": "The task is called Buy milk."})
    assert verdict["passed"] is True
    assert "What is the title?" in seen["prompt"]
    assert "UNTRUSTED DATA" in seen["prompt"]


def test_grounded_judge_distinguishes_quoted_content_mutations_and_negation(monkeypatch):
    from scripts.llm_judge_test import judge

    verdicts = iter([
        '{"passed": true, "reason": "quoted title is grounded"}',
        '{"passed": false, "reason": "unsupported mutation claim"}',
        '{"passed": true, "reason": "negated claim is safe"}',
    ])
    monkeypatch.setattr("scripts.llm_judge_test.run_model", lambda *args, **kwargs: next(verdicts))
    case = {"query": "What is the task?", "results": [{"source_table": "tasks", "source_id": 1, "metadata": {"title": "I completed the training"}}]}
    quoted = judge(
        case,
        {"ideal_output": "The task is titled I completed the training."},
        {"answer": "The task is titled \"I completed the training.\""},
    )
    unsupported = judge(
        case,
        {"ideal_output": "The task is titled I completed the training."},
        {"answer": "I completed the task for you."},
    )
    negated = judge(
        case,
        {"ideal_output": "The task is titled I completed the training."},
        {"answer": "I did not change the task; its title is I completed the training."},
    )
    assert quoted["passed"] is True
    assert unsupported["passed"] is False
    assert negated["passed"] is True


def test_grounded_judge_requires_strict_model_verdict(monkeypatch):
    from scripts.llm_judge_test import judge

    monkeypatch.setattr("scripts.llm_judge_test.run_model", lambda *args, **kwargs: '{"passed": "false", "reason": "bad type"}')
    with pytest.raises(TypeError):
        judge(
        {"query": "What is in this record?", "results": [{"source_table": "tasks", "source_id": 1, "metadata": {"title": "Buy milk"}}]},
        {"ideal_output": "It is a task."},
        {"answer": "I deleted the task for you."},
        )


def test_loader_preserves_distinct_id_types_and_reports_empty(tmp_path: Path):
    questions = tmp_path / "questions.json"
    truth = tmp_path / "truth.json"
    questions.write_text(json.dumps([{"id": 1}, {"id": "1"}]))
    truth.write_text(json.dumps([{"id": 1, "x": 1}, {"id": "1", "x": 2}]))
    cases = load_cases(questions, truth)
    assert [case["id"] for case in cases] == [1, "1"]

    questions.write_text("[]")
    truth.write_text("[]")
    assert load_cases(questions, truth) == []


def test_loader_rejects_unhashable_id(tmp_path: Path):
    questions = tmp_path / "questions.json"
    truth = tmp_path / "truth.json"
    questions.write_text(json.dumps([{"id": []}]))
    truth.write_text(json.dumps([{"id": []}]))
    with pytest.raises(LoaderError, match="JSON-scalar"):
        load_cases(questions, truth)


def test_malformed_sql_json_is_rejected_and_literals_are_preserved():
    from scripts.sql_test import _json_value

    payload = '{"sql":"SELECT * FROM tasks WHERE title = \\"A  B\\""}'
    assert _json_value(payload)["sql"] == 'SELECT * FROM tasks WHERE title = "A  B"'
    with pytest.raises(ValueError):
        _json_value('{"sql":"SELECT * FROM tasks')


def test_structured_adapters_use_final_json_after_thinking():
    from scripts.intent_test import _json_value as intent_json
    from scripts.sql_test import _json_value as sql_json

    intent_raw = 'Thinking...\nPossible: {"intent":"write"}\n...done thinking.\n{"intent":"read"}'
    sql_raw = 'Thinking...\nCandidate: {"sql":"SELECT 0"}\n...done thinking.\n{"sql":"SELECT COUNT(*) FROM tasks"}'
    assert intent_json(intent_raw) == {"intent": "read"}
    assert sql_json(sql_raw) == {"sql": "SELECT COUNT(*) FROM tasks"}


def test_structured_adapters_reject_unfinished_thinking_and_extra_objects():
    from scripts.intent_test import _json_value as intent_json
    from scripts.sql_test import _json_value as sql_json

    for parser in (intent_json, sql_json):
        with pytest.raises(ValueError, match="unfinished thinking"):
            parser('Thinking...\nMaybe {"intent":"write"}')
        with pytest.raises(ValueError, match="not valid final JSON"):
            parser('{"intent":"read"}\n{"intent":"write"}')


def test_structured_adapters_accept_tagged_thinking_and_fenced_final_json():
    from scripts.intent_test import _json_value as intent_json
    from scripts.sql_test import _json_value as sql_json

    assert intent_json('<think>{"intent":"write"}</think>```json\n{"intent":"read"}\n```') == {"intent": "read"}
    assert sql_json('<redacted_thinking>{"sql":"SELECT 0"}</redacted_thinking>{"sql":"SELECT COUNT(*) FROM tasks"}') == {"sql": "SELECT COUNT(*) FROM tasks"}


def test_final_json_preserves_reasoning_tags_inside_sql_literals():
    from scripts.sql_test import _json_value

    payload = {"sql": "SELECT COUNT(*) FROM tasks WHERE title = '<think>Buy milk</think>'"}
    raw = json.dumps(payload)
    assert _json_value(raw) == payload
    assert _json_value('<think>reasoning</think>' + raw) == payload
    for language in ("", "json", "sql"):
        assert _json_value(f'```{language}\n{raw}\n```') == payload


def test_seed_contains_every_advertised_table_and_column():
    seed = Path("db/seed_test_data.sql").read_text()
    for table, fields in TABLE_FIELDS.items():
        block = seed.split(f"CREATE TABLE {table} (", 1)[1].split(");", 1)[0]
        columns = {line.strip().split()[0] for line in block.splitlines() if line.strip() and not line.strip().startswith(")")}
        advertised = {field.split()[0] for field in fields.split(", ")}
        assert advertised <= columns, (table, advertised - columns)


def test_destructive_seed_is_not_a_normal_startup_dependency():
    compose = Path("docker-compose.yml").read_text()
    assert 'profiles: ["seed"]' in compose
    harness_block = compose.split("\n  harness:\n", 1)[1]
    assert "db-seed:" not in harness_block.split("\n  volumes:\n", 1)[0]


def test_runner_records_evaluator_errors_and_continues(tmp_path: Path, monkeypatch):
    questions = tmp_path / "q.json"
    truth = tmp_path / "t.json"
    questions.write_text(json.dumps([{"id": 1, "value": "error"}, {"id": 2, "value": "ok"}]))
    truth.write_text(json.dumps([{"id": 1, "value": "error"}, {"id": 2, "value": "ok"}]))
    module = types.ModuleType("tests.fake_adapter")
    module.run = lambda value: {"value": value["value"]}
    sys.modules[module.__name__] = module
    monkeypatch.setitem(runner.SCRIPTS, "fake", {"questions": questions, "ground_truth": truth, "module": module.__name__, "mode": "exact"})
    original_evaluate = runner.evaluate
    calls = {"n": 0}
    original_evaluate = runner.evaluate

    def evaluate_with_one_error(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ground truth unavailable")
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", evaluate_with_one_error)
    monkeypatch.setenv("EVAL_LOG_DIR", str(tmp_path))
    log = RunLog("test")
    try:
        summary = runner.run_script("fake", log)
    finally:
        log.close()
    assert summary == {"total": 2, "passed": 1, "failed": 0, "errors": 1}
    assert len(log.json_path.read_text().splitlines()) == 3


def test_reference_database_error_is_error_and_actual_is_preserved(tmp_path: Path, monkeypatch):
    questions = tmp_path / "q.json"
    truth = tmp_path / "t.json"
    questions.write_text(json.dumps([{"id": 1, "value": "db"}, {"id": 2, "value": "ok"}]))
    truth.write_text(json.dumps([{"id": 1}, {"id": 2}]))
    module = types.ModuleType("tests.db_error_adapter")
    module.run = lambda value: {"count": 1, "value": value["value"]}
    sys.modules[module.__name__] = module
    monkeypatch.setitem(runner.SCRIPTS, "db_error", {"questions": questions, "ground_truth": truth, "module": module.__name__, "mode": "query_result"})
    calls = {"n": 0}
    original_evaluate = runner.evaluate

    def fail_first_reference(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise EvaluationError("reference query failed: timeout")
        return original_evaluate("exact", {}, {})

    # The second case uses the same shape but a query_result adapter; make its
    # evaluator pass without accessing a real database.
    monkeypatch.setattr(runner, "evaluate", fail_first_reference)
    monkeypatch.setenv("EVAL_LOG_DIR", str(tmp_path))
    log = RunLog("db_error")
    try:
        summary = runner.run_script("db_error", log)
    finally:
        log.close()
    assert summary == {"total": 2, "passed": 1, "failed": 0, "errors": 1}
    records = [json.loads(line) for line in log.json_path.read_text().splitlines()]
    case_records = [record for record in records if record.get("case_id") == 1]
    assert case_records[0]["stage"] == "evaluate"
    assert case_records[0]["status"] == "ERROR"


def test_later_case_validation_error_does_not_discard_prior_result(tmp_path: Path, monkeypatch):
    questions = tmp_path / "q.json"
    truth = tmp_path / "t.json"
    questions.write_text(json.dumps([{"id": 1, "value": "ok"}, {"id": 2, "value": 7}]))
    truth.write_text(json.dumps([{"id": 1, "value": "ok"}, {"id": 2, "value": 7}]))
    module = types.ModuleType("tests.validation_adapter")
    module.run = lambda value: value
    sys.modules[module.__name__] = module
    monkeypatch.setitem(runner.SCRIPTS, "validation", {"questions": questions, "ground_truth": truth, "module": module.__name__, "mode": "exact"})
    monkeypatch.setattr(runner, "validate_case_payload", lambda suite, case: (_ for _ in ()).throw(LoaderError("unsupported shape")) if case["id"] == 2 else None)
    monkeypatch.setenv("EVAL_LOG_DIR", str(tmp_path))
    log = RunLog("validation")
    try:
        summary = runner.run_script("validation", log)
    finally:
        log.close()
    assert summary == {"total": 2, "passed": 1, "failed": 0, "errors": 1}
