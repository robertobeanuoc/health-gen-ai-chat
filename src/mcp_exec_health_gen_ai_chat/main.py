#!/usr/bin/env python3
import logging
import os
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

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

_engine = None


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
    logger.info("execute_read_query called | query_chars=%d", len(sql_query))

    # Strict restriction on write or structural modification commands
    check_query = sql_query.upper()
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "GRANT", "REPLACE", "TRUNCATE"]

    if any(keyword in check_query for keyword in forbidden_keywords):
        logger.warning("execute_read_query rejected — forbidden keyword | query=%s", sql_query[:300])
        return "Security error: Query contains forbidden keywords. Only SELECT processing is allowed."

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
        logger.exception("execute_read_query failed | query_chars=%d", len(sql_query))
        return f"Execution error in MySQL database: {str(e)}"

if __name__ == "__main__":
    mcp.run()