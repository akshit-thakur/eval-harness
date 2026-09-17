"""Standalone Eval Harness adapter for OmniFlow SQL generation.

The schema facts below mirror the domain SQL and field names used by
api/app/mutations.py.  This file deliberately does not import the application.
"""

import json
from typing import Any

from core.db import fetch, scalar_count
from core.ollama import run_model
from core.schema_contract import TABLE_FIELDS, prompt_schema
from core.sql_guard import validate_read_query
from scripts.model_output import final_json

_SQL_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
    "additionalProperties": False,
}

def _json_value(raw: str) -> Any:
    return final_json(raw)


def _normalize_sql(sql: str) -> str:
    return f"{sql.strip().rstrip(';')};"


def run(input: dict[str, Any]) -> dict[str, Any]:
    question = input.get("question", input.get("query"))
    query_input = input.get("input", input)
    if not isinstance(question, str) or not question.strip():
        raise ValueError("input.question must be a non-empty string")
    if not isinstance(query_input, dict):
        raise ValueError("input.input must be an object")
    if query_input.get("intent") != "read":
        raise ValueError("sql_test.py only supports read intent")
    tables = query_input.get("tables")
    if not isinstance(tables, list) or not tables or any(table not in TABLE_FIELDS for table in tables):
        raise ValueError("input.input.tables must contain known table names")
    schema = prompt_schema(tables)
    prompt = f"""Generate one safe PostgreSQL query for the user's read question.
The input has already been classified as read. Use only the supplied tables and
their fields. Return exactly one JSON object: {{"sql":"SELECT ..."}}.
The query must return exactly one scalar count, using COUNT(*). Do not use vector
search, embeddings, hybrid retrieval, RRF, writes, or invented columns.
Use PostgreSQL boolean literals TRUE and FALSE. medication_plans.active is the
active flag column; do not use is_active.
Important domain rule: media_items has no completed boolean; completed media is
represented by status = 'completed'.

Question:
{question}

Classified SQL-generator input JSON:
{json.dumps({"intent": "read", "tables": tables}, separators=(",", ":"))}

Available schema:
{schema}"""
    generated = _json_value(run_model(prompt, _SQL_SCHEMA))
    if not isinstance(generated, dict):
        raise ValueError(f"model response must be an object, got {type(generated).__name__}")
    sql = generated.get("sql") if isinstance(generated, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError(
            f"Model did not return SQL; raw_model_output={generated!r}"
        )

    normalized = validate_read_query(sql, set(tables))
    rows = fetch(normalized)
    value = scalar_count(rows)
    return {"sql": normalized, "count": value}
