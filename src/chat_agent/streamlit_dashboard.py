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

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

CHAT_API_BASE_URL = os.getenv("CHAT_API_BASE_URL", "http://localhost:8000")


@st.cache_data(ttl=None, show_spinner=False)
def fetch_dashboard(message_id: str) -> dict | None:
    url = f"{CHAT_API_BASE_URL}/api/messages/{message_id}/dashboard"
    response = requests.get(url, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
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
                st.warning(f"Unsupported chart type: {chart_type}")
                continue

            fig.update_layout(xaxis_title=None, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
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

if not message_id:
    st.info("Waiting for a dashboard — pass ?message_id=<id> in the URL.")
else:
    try:
        config = fetch_dashboard(message_id)
    except requests.RequestException as exc:
        st.error(f"Could not reach the chat backend at {CHAT_API_BASE_URL}: {exc}")
        config = None

    if config is None:
        st.info("No dashboard found for this message.")
    else:
        st.title(config.get("title", "Dashboard"))
        if config.get("description"):
            st.caption(config["description"])

        render_metrics(config.get("metrics", []))
        render_charts(config.get("charts", []))
        render_tables(config.get("tables", []))
