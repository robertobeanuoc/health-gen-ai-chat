#!/usr/bin/env python3
import logging
import os
import json
import sys
from pathlib import Path

import sqlglot
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from sqlglot import exp
from sqlglot.errors import ParseError

load_dotenv(Path(__file__).parent.parent.parent / ".env")
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

# stdio is the MCP transport's wire protocol — logs must go to stderr, never stdout.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("mysql_execution_engine")

# Query results flow back into the LLM's own context (as a tool_result) and get
# resent on every subsequent tool-calling round of the same chat turn, so an
# unaggregated result of even a few tens of thousands of rows can blow past the
# model's context window well before it blows up any chart-rendering limit.
# This caps rows returned to the LLM, independent of the SQL it wrote — it must
# aggregate or bucket further (e.g. GROUP BY a time bucket or value range)
# rather than pulling raw per-record data at this scale.
MAX_RESULT_ROWS = 1000

# Schemas that expose database structure rather than application data — the dbt
# semantic layer (mcp_semantic) is the only source of truth for table/column
# names, so querying these directly would let the model bypass it.
_FORBIDDEN_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}

_engine = None


def _validate_select_query(sql_query: str) -> str | None:
    """
    Parses sql_query with sqlglot (MySQL dialect) and returns an error message if
    it isn't a single, safe read-only SELECT — or None if it's fine to execute.

    Real parsing replaces fragile substring/keyword matching: a column named e.g.
    "last_updated" can't false-positive on the substring "UPDATE", multi-statement
    injection (`SELECT ...; DROP TABLE ...;`) is caught structurally as a Block
    instead of by scanning for keywords, and schema-introspection statements
    (SHOW, DESCRIBE) are identified by their real AST node type rather than by
    string-prefix guessing.
    """
    try:
        parsed = sqlglot.parse_one(sql_query, dialect="mysql")
    except ParseError as exc:
        return f"SQL parse error: {exc}"

    if not isinstance(parsed, exp.Select):
        return (
            f"Security error: only single, read-only SELECT statements are allowed "
            f"(got '{type(parsed).__name__}')."
        )

    for table in parsed.find_all(exp.Table):
        if table.db.lower() in _FORBIDDEN_SCHEMAS or table.name.lower() in _FORBIDDEN_SCHEMAS:
            return (
                "Security error: querying database-structure schemas (information_schema, "
                "performance_schema, mysql, sys) directly is not allowed. Use the mcp_semantic "
                "tools (get_table_columns, get_model_lineage, get_dimensions_by_semantic_model) "
                "instead — they are the source of truth for table and column names, not the "
                "raw database schema."
            )

    return None


def _build_url() -> URL:
    host = os.getenv("MYSQL_HOST", "")
    user = os.getenv("MYSQL_USER", "")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "")
    missing = [name for name, val in [("MYSQL_HOST", host), ("MYSQL_USER", user), ("MYSQL_PASSWORD", password), ("MYSQL_DATABASE", database)] if not val]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    return URL.create(
        "mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=database,
    )


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_build_url(), pool_pre_ping=True)
    return _engine

@mcp.tool()
def execute_read_query(sql_query: str) -> str:
    """
    Executes read-only SQL statements (DQL) on the MySQL database engine.
    Accepts any valid SELECT query generated from the semantic layer.
    """
    logger.info("execute_read_query called | sql=%s", sql_query)

    validation_error = _validate_select_query(sql_query)
    if validation_error:
        logger.warning("execute_read_query rejected | reason=%s | sql=%s", validation_error, sql_query)
        return validation_error

    try:
        with _get_engine().connect() as connection:
            result = connection.execute(text(sql_query))

            columns = result.keys()
            fetched = [dict(zip(columns, row)) for row in result.fetchmany(MAX_RESULT_ROWS + 1)]

            if len(fetched) > MAX_RESULT_ROWS:
                logger.warning("execute_read_query truncated — exceeds row cap | query_chars=%d", len(sql_query))
                return json.dumps({
                    "error": (
                        f"Query returned more than {MAX_RESULT_ROWS} rows. Aggregate or bucket the "
                        "data further in SQL (e.g. GROUP BY a time bucket or a value range) instead "
                        "of fetching raw per-record data at this scale."
                    ),
                    "row_limit": MAX_RESULT_ROWS,
                }, ensure_ascii=False)

            logger.info("execute_read_query succeeded | rows=%d", len(fetched))
            return json.dumps(fetched, default=str, ensure_ascii=False)

    except SQLAlchemyError as e:
        logger.exception("execute_read_query failed | sql=%s", sql_query)
        return f"Execution error in MySQL database: {str(e)}"

if __name__ == "__main__":
    mcp.run()