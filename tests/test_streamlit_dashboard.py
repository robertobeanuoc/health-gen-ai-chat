"""
Tests for the Streamlit dashboard renderer, using Streamlit's own AppTest
harness (streamlit.testing.v1). Dashboard configs are built by calling the
real build_dashboard tool from mcp_visualization_health_gen_ai_chat — not
hand-written JSON — so these tests exercise the actual validation path a
chat turn goes through (fixed x/y data in -> build_dashboard validates and
shapes it -> Streamlit renders it), while `requests.get` is still mocked so
nothing touches the real chat backend or database.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, "src")

from mcp_visualization_health_gen_ai_chat.main import build_dashboard  # noqa: E402

APP_PATH = str(Path("src/chat_agent/streamlit_dashboard.py").resolve())

# Fixed input datasets for every supported chart type (mirrors CHART_CAPABILITIES
# in mcp_visualization_health_gen_ai_chat/main.py) — small enough to pass every
# chart type's data-volume limit comfortably.
CHART_INPUTS = {
    "pie": {"x": ["a", "b", "c"], "y": [1, 2, 3]},
    "bar": {"x": ["mon", "tue", "wed"], "y": [10, 20, 15]},
    "scatter": {"x": [1, 2, 3], "y": [4, 1, 6]},
    "line": {"x": ["d1", "d2", "d3"], "y": [100, 110, 105]},
    "area": {"x": ["d1", "d2", "d3"], "y": [5, 8, 6]},
    "histogram": {"x": [1, 2, 2, 3, 3, 3, 4]},
    "heatmap": {"x": [1, 1, 2, 2], "y": [1, 2, 1, 2]},
}


def _build(title: str, charts: list[dict], **kwargs) -> dict:
    """Calls the real build_dashboard MCP tool and returns the parsed config."""
    result = json.loads(build_dashboard(title=title, charts=charts, **kwargs))
    assert "error" not in result, f"build_dashboard rejected fixture data: {result}"
    return result


def _chart(chart_type: str, title: str | None = None) -> dict:
    return {"type": chart_type, "title": title or chart_type, "data": CHART_INPUTS[chart_type]}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")


def _run_with_dashboard(message_id: str, dashboard: dict | None, status_code: int = 200) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.query_params["message_id"] = message_id
    with patch("requests.get", return_value=_FakeResponse(status_code, dashboard)):
        at.run()
    return at


def test_no_message_id_shows_waiting_state():
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run()
    assert not at.exception
    assert any("Waiting for a dashboard" in i.value for i in at.info)


def test_missing_dashboard_shows_not_found_state():
    at = _run_with_dashboard("msg-404", dashboard=None, status_code=404)
    assert not at.exception
    assert any("No dashboard found" in i.value for i in at.info)


def test_backend_unreachable_shows_error():
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.query_params["message_id"] = "msg-unreachable"
    import requests

    with patch("requests.get", side_effect=requests.ConnectionError("refused")):
        at.run()
    assert not at.exception
    assert any("Could not reach the chat backend" in e.value for e in at.error)


@pytest.mark.parametrize("chart_type", list(CHART_INPUTS))
def test_each_chart_type_renders_without_error(chart_type):
    dashboard = _build(f"{chart_type} dashboard", [_chart(chart_type)])
    at = _run_with_dashboard(f"msg-{chart_type}", dashboard)

    assert not at.exception
    assert not at.get("error")  # render_charts' per-chart try/except surfaces failures as st.error
    assert at.title[0].value == f"{chart_type} dashboard"
    assert len(at.get("plotly_chart")) == 1


def test_build_dashboard_rejects_a_chart_type_it_cant_handle():
    """
    build_dashboard validates chart_type/data volume itself — a bar chart
    over more rows than CHART_CAPABILITIES allows must be rejected before it
    ever reaches Streamlit, not silently passed through.
    """
    huge_bar = {"type": "bar", "title": "too big", "data": {"x": [str(i) for i in range(2000)]}}
    result = json.loads(build_dashboard(title="bad", charts=[huge_bar]))
    assert "error" in result


def test_unsupported_chart_type_warns_instead_of_crashing():
    """
    build_dashboard already refuses an unknown chart_type (covered above), so
    this dashboard could never come from the real MCP tool — it's a
    hand-built payload testing Streamlit's own defensive fallback for any
    dashboard JSON that reaches it some other way (e.g. an older stored one).
    """
    dashboard = {"title": "bad chart", "charts": [{"type": "not-a-real-type", "title": "x", "data": {"x": [1]}}]}
    at = _run_with_dashboard("msg-unsupported", dashboard)

    assert not at.exception
    assert any("Unsupported chart type" in w.value for w in at.warning)


def test_full_dashboard_renders_metrics_charts_and_tables():
    message_id = "msg-full"
    dashboard = _build(
        f"Full dashboard {message_id}",
        [_chart(t) for t in CHART_INPUTS],
        description="A dashboard exercising every supported chart type at once.",
        metrics=[
            {"title": "Average", "value": "120 mg/dL", "delta": "-5", "delta_color": "positive"},
            {"title": "Max", "value": "180 mg/dL", "delta": "+10", "delta_color": "negative"},
        ],
        tables=[{"title": "Raw readings", "columns": ["day", "value"], "data": [{"day": "d1", "value": 100}]}],
    )
    at = _run_with_dashboard(message_id, dashboard)

    assert not at.exception
    assert not at.get("error")
    assert at.title[0].value == f"Full dashboard {message_id}"
    assert len(at.metric) == 2
    assert len(at.get("plotly_chart")) == len(CHART_INPUTS)
    assert len(at.dataframe) == 1


def test_chart_with_no_data_is_skipped_silently():
    dashboard = _build("empty", [{"type": "bar", "title": "empty bar", "data": {"x": [], "y": []}}])
    at = _run_with_dashboard("msg-empty", dashboard)

    assert not at.exception
    assert not at.get("error")
    assert len(at.get("plotly_chart")) == 0
