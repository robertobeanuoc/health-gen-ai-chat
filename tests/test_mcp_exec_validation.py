"""
Unit tests for the SQL validation layer in mcp_exec — the guard that decides
whether a query the LLM wrote is actually allowed to run against the
database. No live database connection is needed: _validate_select_query is a
pure function over the SQL text.
"""

import sys

sys.path.insert(0, "src")

from mcp_exec_health_gen_ai_chat.main import _validate_select_query  # noqa: E402

ALLOWED_QUERIES = [
    "SELECT * FROM view_glucose_register",
    "SELECT * FROM view_glucose_register ORDER BY glucose_timestamp_day DESC",
    "SELECT last_updated FROM view_glucose_register",  # substring "UPDATE" false-positive regression
    "SELECT COUNT(*) FROM view_glucose_register WHERE glucose_value > 180",
    "SELECT DATE(glucose_timestamp) AS day, AVG(glucose_value) FROM health_gen_ai_chat.view_glucose_register GROUP BY day",
    "WITH t AS (SELECT 1 AS x) SELECT * FROM t",
]

BLOCKED_STATEMENTS = [
    "INSERT INTO view_glucose_register VALUES (1)",
    "UPDATE view_glucose_register SET glucose_value = 1",
    "DELETE FROM view_glucose_register",
    "DROP TABLE view_glucose_register",
    "ALTER TABLE view_glucose_register ADD COLUMN x INT",
    "GRANT ALL ON view_glucose_register TO someone",
    "REPLACE INTO view_glucose_register VALUES (1)",
    "TRUNCATE TABLE view_glucose_register",
    "SHOW TABLES",
    "SHOW COLUMNS FROM view_glucose_register",
    "DESCRIBE view_glucose_register",
    "DESC view_glucose_register",
    "SELECT * FROM view_glucose_register; DROP TABLE view_glucose_register;",
]

BLOCKED_SCHEMAS = [
    "SELECT * FROM information_schema.columns",
    "SELECT * FROM information_schema.tables WHERE table_schema = 'health_gen_ai_chat'",
    "SELECT col FROM t WHERE x IN (SELECT column_name FROM information_schema.columns)",
    "SELECT * FROM performance_schema.events_statements_history",
    "SELECT * FROM mysql.user",
    "SELECT * FROM sys.version",
]


def test_allowed_queries_pass():
    for sql in ALLOWED_QUERIES:
        assert _validate_select_query(sql) is None, f"expected allowed: {sql}"


def test_write_and_structural_statements_are_blocked():
    for sql in BLOCKED_STATEMENTS:
        error = _validate_select_query(sql)
        assert error is not None, f"expected blocked: {sql}"
        assert "SELECT statements are allowed" in error


def test_schema_introspection_is_blocked():
    for sql in BLOCKED_SCHEMAS:
        error = _validate_select_query(sql)
        assert error is not None, f"expected blocked: {sql}"
        assert "database-structure schemas" in error


def test_malformed_sql_is_rejected_with_parse_error():
    error = _validate_select_query("this is not sql at all !!!")
    assert error is not None
    assert "parse error" in error.lower()


def test_column_named_like_a_forbidden_keyword_is_not_blocked():
    """
    Regression test for the bug the sqlglot rewrite fixed: naive substring
    matching on "UPDATE"/"DELETE"/etc. used to reject legitimate columns
    whose name merely contains one of those words.
    """
    for column in ["last_updated", "deleted_flag", "insertion_order", "replacement_value"]:
        sql = f"SELECT {column} FROM view_glucose_register"
        assert _validate_select_query(sql) is None, f"false positive on column: {column}"
