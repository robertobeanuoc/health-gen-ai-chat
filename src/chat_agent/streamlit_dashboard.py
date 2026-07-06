#!/usr/bin/env python3
"""
Streamlit dashboard renderer.

Renders the dashboard config produced by the mcp_visualization server's
build_dashboard tool. Each assistant chat message that built a dashboard gets
its own iframe in index.html pointing here with ?message_id=<id> — this app
fetches that one dashboard from the chat backend and renders it, so a single
session can accumulate any number of dashboards, one per message.

Run:
    uv run streamlit run src/chat_agent/streamlit_dashboard.py --server.port 8501

Configuration:
    CHAT_API_BASE_URL — base URL of the FastAPI chat backend (default: http://localhost:8000)
"""

import logging
import os
import sys

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# stdout is Streamlit's own console output — logs go to stderr so they don't get
# mixed into it, matching the convention used by the other project entrypoints.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

CHAT_API_BASE_URL = os.getenv("CHAT_API_BASE_URL", "http://localhost:8000")


@st.cache_data(ttl=None, show_spinner=False)
def fetch_dashboard(message_id: str) -> dict | None:
    url = f"{CHAT_API_BASE_URL}/api/messages/{message_id}/dashboard"
    logger.info("fetch_dashboard called | message_id=%s url=%s", message_id, url)
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException:
        logger.exception("fetch_dashboard failed to reach chat backend | message_id=%s url=%s", message_id, url)
        raise
    if response.status_code == 404:
        logger.warning("fetch_dashboard — no dashboard found | message_id=%s", message_id)
        return None
    response.raise_for_status()
    logger.info("fetch_dashboard succeeded | message_id=%s status=%d", message_id, response.status_code)
    return response.json()


def render_metrics(metrics: list[dict]) -> None:
    if not metrics:
        return
    cols = st.columns(min(3, len(metrics)))
    for i, metric in enumerate(metrics):
        with cols[i % len(cols)]:
            delta_color = "off"
            if metric.get("delta_color") == "positive":
                delta_color = "normal"
            elif metric.get("delta_color") == "negative":
                delta_color = "inverse"
            st.metric(
                label=metric.get("title", ""),
                value=metric.get("value"),
                delta=metric.get("delta"),
                delta_color=delta_color,
            )


def render_charts(charts: list[dict]) -> None:
    for chart in charts:
        chart_type = chart.get("type")
        title = chart.get("title", "")
        data = chart.get("data", {})
        x_data = data.get("x", [])
        y_data = data.get("y", [])

        if not x_data:
            continue

        try:
            if chart_type == "line":
                fig = px.line(x=x_data, y=y_data, title=title, markers=True)
            elif chart_type == "bar":
                fig = px.bar(x=x_data, y=y_data, title=title)
            elif chart_type == "pie":
                fig = px.pie(values=y_data, names=x_data, title=title)
            elif chart_type == "scatter":
                fig = px.scatter(x=x_data, y=y_data, title=title)
            elif chart_type == "area":
                fig = px.area(x=x_data, y=y_data, title=title)
            elif chart_type == "histogram":
                fig = px.histogram(x=x_data, title=title)
            elif chart_type == "heatmap":
                fig = px.density_heatmap(x=x_data, y=y_data, title=title)
            else:
                logger.warning("render_charts — unsupported chart type=%s title=%s", chart_type, title)
                st.warning(f"Unsupported chart type: {chart_type}")
                continue

            # Plotly.js auto-detects a "date" axis type from date/time-looking string
            # values and applies its own tick parsing/formatting on top of them — the
            # same kind of silent reformatting the system prompt forbids the LLM from
            # doing to query results. Forcing "category" for string x values displays
            # exactly what execute_read_query returned, with no re-parsing.
            if chart_type not in ("pie", "histogram") and x_data and isinstance(x_data[0], str):
                fig.update_xaxes(type="category")

            fig.update_layout(xaxis_title=None, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            logger.exception("render_charts — failed to render chart | type=%s title=%s", chart_type, title)
            st.error(f"Error rendering '{title}': {exc}")


def render_tables(tables: list[dict]) -> None:
    for table in tables:
        title = table.get("title", "")
        rows = table.get("data", [])
        columns = table.get("columns") or (list(rows[0].keys()) if rows else [])

        if not rows:
            continue

        if title:
            st.subheader(title)
        st.dataframe(pd.DataFrame(rows)[columns], use_container_width=True)


message_id = st.query_params.get("message_id")
logger.info("page load | message_id=%s", message_id)

if not message_id:
    st.info("Waiting for a dashboard — pass ?message_id=<id> in the URL.")
else:
    try:
        config = fetch_dashboard(message_id)
    except requests.RequestException as exc:
        logger.error("could not reach chat backend | message_id=%s base_url=%s error=%s", message_id, CHAT_API_BASE_URL, exc)
        st.error(f"Could not reach the chat backend at {CHAT_API_BASE_URL}: {exc}")
        config = None

    if config is None:
        logger.warning("no dashboard to render | message_id=%s", message_id)
        st.info("No dashboard found for this message.")
    else:
        logger.info(
            "rendering dashboard | message_id=%s title=%s charts=%d metrics=%d tables=%d",
            message_id,
            config.get("title"),
            len(config.get("charts", [])),
            len(config.get("metrics", [])),
            len(config.get("tables", [])),
        )
        st.title(config.get("title", "Dashboard"))
        if config.get("description"):
            st.caption(config["description"])

        render_metrics(config.get("metrics", []))
        render_charts(config.get("charts", []))
        render_tables(config.get("tables", []))
