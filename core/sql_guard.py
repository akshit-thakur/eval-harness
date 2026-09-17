"""PostgreSQL-aware safety checks for generated read queries.

Relation discovery is delegated to sqlglot's maintained PostgreSQL parser.
Database-level read-only transactions and timeouts in ``core.db`` remain
independent protections.
"""

from __future__ import annotations

from typing import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.tokens import TokenType


_WRITE_NODE_NAMES = {
    "Alter", "Command", "Copy", "Create", "Delete", "Drop", "Insert",
    "Merge", "Refresh", "Set", "Truncate", "Update", "Vacuum",
}


def _identifier_key(identifier: exp.Expression | None) -> tuple[str, bool] | None:
    if identifier is None:
        return None
    name = getattr(identifier, "name", None)
    if not isinstance(name, str):
        return None
    quoted = bool(identifier.args.get("quoted"))
    return (name if quoted else name.lower(), quoted)


def _table_key(table: exp.Table) -> tuple[str, bool]:
    table_key = _identifier_key(table.this)
    if table_key is None:
        raise ValueError(f"could not resolve relation {table.sql()!r}")
    name, quoted = table_key
    schema_key = _identifier_key(table.args.get("db"))
    catalog_key = _identifier_key(table.args.get("catalog"))
    if catalog_key is not None:
        raise ValueError(f"cross-database relation is not allowed: {table.sql()}")
    if schema_key is not None and schema_key[0] != "public":
        return (f"{schema_key[0]}.{name}", schema_key[1] or quoted)
    return (name, quoted)


def _physical_relations(expression: exp.Expression) -> Iterable[tuple[str, bool]]:
    """Yield tables selected from every scope, excluding CTE/derived sources.

    ``selected_sources`` distinguishes a physical ``Table`` source from a
    CTE ``Scope`` source.  Walking all scopes also catches tables in nested
    subqueries and CTE bodies, while preserving CTE shadowing.
    """
    for scope in traverse_scope(expression):
        for _alias, (_reference, source) in scope.selected_sources.items():
            if isinstance(source, exp.Table):
                yield _table_key(source)


def _postgres_identifier_normalized(sql: str) -> str:
    """Fold unquoted identifiers as PostgreSQL does, preserving quoted case."""
    tokenizer = Postgres.Tokenizer()
    pieces: list[str] = []
    cursor = 0
    for token in tokenizer.tokenize(sql):
        if token.token_type != TokenType.VAR:
            continue
        pieces.append(sql[cursor:token.start])
        pieces.append(token.text.lower())
        cursor = token.end + 1
    if not pieces:
        return sql
    pieces.append(sql[cursor:])
    return "".join(pieces)


def validate_read_query(sql: str, allowed_tables: set[str] | None = None) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("generated SQL must be a non-empty string")
    try:
        statements = sqlglot.parse(_postgres_identifier_normalized(sql), read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"generated SQL is not valid PostgreSQL: {exc}") from exc
    if len(statements) != 1:
        raise ValueError("generated SQL must contain exactly one statement")
    expression = statements[0]
    if not isinstance(expression, exp.Select):
        raise ValueError("generated SQL must be a SELECT or read-only WITH query")
    if any(isinstance(node, exp.Into) for node in expression.walk()):
        raise ValueError("SELECT INTO is not a read-only query")
    writes = sorted({node.__class__.__name__ for node in expression.walk() if node.__class__.__name__ in _WRITE_NODE_NAMES})
    if writes:
        raise ValueError(f"generated SQL contains writable operation(s): {', '.join(writes)}")
    if allowed_tables is not None:
        allowed = {name.lower() for name in allowed_tables}
        relations = set(_physical_relations(expression))
        disallowed = sorted(name for name, quoted in relations if (name not in allowed if quoted else name.lower() not in allowed))
        if disallowed:
            raise ValueError(f"generated SQL references disallowed relation(s): {', '.join(disallowed)}")
    return sql.strip().rstrip(";") + ";"
