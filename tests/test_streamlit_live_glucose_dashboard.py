"""
Full-chain live test for the glucose dashboard: discovers the glucose
semantic model through mcp_semantic, runs a real aggregated query through
mcp_exec against the actual database, builds a dashboard from that data
through mcp_visualization's build_dashboard, serves it, and boots a real
Streamlit server to view it — the same sequence of tool calls a chat turn
makes, just driven directly instead of through the LLM.

Requires a live MySQL connection (skipped otherwise, see mysql_env in
conftest.py). Unlike the other Streamlit tests, this one intentionally does
NOT use fixed/fake data — the point is to exercise the real semantic layer
and real data end to end.

By default this only checks the dashboard renders; it doesn't linger. Run
with `--show-dashboard` to also print the live URL and pause so you can open
it in a browser yourself:

    uv run pytest tests/test_streamlit_live_glucose_dashboard.py --show-dashboard -s
"""

import json
import sys

import pytest
import requests

from conftest import run_stub_chat_backend, run_streamlit_server

sys.path.insert(0, "src")

from mcp_exec_health_gen_ai_chat.main import execute_read_query  # noqa: E402
from mcp_semantic_healh_gen_ai_chat.main import get_table_columns  # noqa: E402
from mcp_visualization_health_gen_ai_chat.main import build_dashboard  # noqa: E402

MESSAGE_ID = "live-glucose-dashboard"


@pytest.fixture(scope="module")
def glucose_semantic_model(mysql_env, dbt_manifests) -> dict:
    """
    Step 1 of the chat flow: discover the glucose view's columns through the
    semantic layer (mcp_semantic), exactly as get_table_columns is meant to
    be used before writing SQL.
    """
    model = json.loads(get_table_columns("view_glucose_register"))
    assert model["columns"], "get_table_columns returned no columns for view_glucose_register"
    return model


@pytest.fixture(scope="module")
def glucose_dashboard(glucose_semantic_model) -> dict:
    """
    Steps 2-3: run a real, aggregated query (per the system prompt's "always
    aggregate" rule) against the real database, then build a dashboard from
    the real result rows through the real validation tool.
    """
    rows = json.loads(
        execute_read_query(
            "SELECT glucose_timestamp_day AS day, ROUND(AVG(glucose_value), 1) AS avg_glucose "
            "FROM view_glucose_register "
            "WHERE glucose_timestamp_day IS NOT NULL "
            "GROUP BY glucose_timestamp_day "
            "ORDER BY glucose_timestamp_day DESC "
            "LIMIT 28"
        )
    )
    assert isinstance(rows, list), f"query failed: {rows}"
    assert rows, "no glucose data available to build a dashboard from"

    days = [str(r["day"]) for r in reversed(rows)]
    averages = [r["avg_glucose"] for r in reversed(rows)]

    column_names = [c["name"] for c in glucose_semantic_model["columns"]]
    result = json.loads(
        build_dashboard(
            title="Average Glucose per Day (live)",
            description=(
                f"Built from view_glucose_register's real columns "
                f"({', '.join(column_names)}), aggregated over the last {len(days)} recorded days."
            ),
            charts=[{"type": "line", "title": "Average glucose per day", "data": {"x": days, "y": averages}}],
            metrics=[{"title": "Days shown", "value": len(days)}],
        )
    )
    assert "error" not in result, f"build_dashboard rejected real data: {result}"
    return result


@pytest.fixture(scope="module")
def live_streamlit_server(glucose_dashboard):
    with run_stub_chat_backend({MESSAGE_ID: glucose_dashboard}) as backend_url:
        with run_streamlit_server(backend_url) as server_url:
            yield server_url


def test_live_glucose_dashboard_renders(live_streamlit_server, show_dashboard):
    url = f"{live_streamlit_server}/?message_id={MESSAGE_ID}"
    response = requests.get(url, timeout=10)
    assert response.status_code == 200

    if show_dashboard:
        print(f"\n{'=' * 70}\nLive glucose dashboard: {url}\n{'=' * 70}")
        try:
            input("Press Enter here once you've checked it in the browser to continue... ")
        except EOFError:
            import time

            time.sleep(60)
