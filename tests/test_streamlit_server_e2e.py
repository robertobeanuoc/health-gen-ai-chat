"""
End-to-end smoke test: launches a real `streamlit run` subprocess for
src/chat_agent/streamlit_dashboard.py, using the exact same invocation
docker-compose.yml uses for the `streamlit` service, and checks it actually
comes up and serves a page.

This is deliberately separate from test_streamlit_dashboard.py's AppTest
suite: AppTest simulates a script run in-process and can assert on rendered
elements, but never boots a real server, so it can't catch a broken
subprocess invocation, port binding, or startup crash — the kind of failure
that would show up in Docker but not in the AppTest suite. A live server's
initial HTTP response is just the SPA shell before Streamlit's WebSocket
connects and runs the script (verified in this same repo's history — see
the debugging session that found `curl` only fetches that shell), so this
test only checks the server boots and serves *something*, not rendered
content; deep content assertions belong in the AppTest suite instead.

The backing chat API is a tiny fixed stdlib HTTP server, not the real
FastAPI backend/database, so this stays isolated from real data — the
dashboard it serves is still built via the real build_dashboard MCP tool,
just fetched over HTTP the same way the real Streamlit app does in production.
"""

import json
import sys

import pytest
import requests

from conftest import run_stub_chat_backend, run_streamlit_server

sys.path.insert(0, "src")

from mcp_visualization_health_gen_ai_chat.main import build_dashboard  # noqa: E402

FIXED_MESSAGE_ID = "e2e-fixed-message-id"


@pytest.fixture(scope="module")
def fixed_dashboard() -> dict:
    """A dashboard built via the real MCP validation tool, not hand-typed JSON."""
    result = json.loads(
        build_dashboard(
            title="E2E fixed dashboard",
            charts=[{"type": "bar", "title": "Fixed bar", "data": {"x": ["a", "b"], "y": [1, 2]}}],
        )
    )
    assert "error" not in result
    return result


@pytest.fixture(scope="module")
def streamlit_server(fixed_dashboard):
    with run_stub_chat_backend({FIXED_MESSAGE_ID: fixed_dashboard}) as backend_url:
        with run_streamlit_server(backend_url) as server_url:
            yield server_url


def test_streamlit_server_boots_and_serves_a_page(streamlit_server):
    response = requests.get(streamlit_server, timeout=10)
    assert response.status_code == 200
    assert "streamlit" in response.text.lower()


def test_streamlit_server_accepts_message_id_query_param(streamlit_server):
    response = requests.get(f"{streamlit_server}/?message_id={FIXED_MESSAGE_ID}", timeout=10)
    assert response.status_code == 200
