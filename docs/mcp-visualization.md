# MCP Visualization Server — `DashboardEngine`

**Package:** `src/mcp_visualization_health_gen_ai_chat`
**Transport:** stdio
**FastMCP name:** `DashboardEngine`

## Overview

The Visualization MCP server is the **dashboard building layer**. It takes raw JSON data (typically the output of `execute_read_query`) and builds a dashboard configuration — metrics, charts, tables — after validating that each chart type can actually handle the data volume it's given. It does not generate or execute any Python code, and it does not render anything itself.

```
execute_read_query result (JSON rows)
  └── recommend_visualization(rows, ...) / validate_chart(chart_type, rows)
        └── build_dashboard(title, charts, ...)
              └── dashboard config (JSON), validated against chart-capability limits
                    └── persisted on the assistant message by src/chat_agent/server.py
                          └── Streamlit iframe (streamlit_dashboard.py) fetches and renders it
```

This two-step "validate, then build" flow exists because a chart type that draws one mark per row (bar, pie, scatter) becomes unreadable — or freezes the Streamlit/Plotly render — well before an aggregate or binned chart type (line, area, heatmap, histogram) does. `build_dashboard` enforces this itself; it will refuse to build a chart that fails validation rather than silently returning a spec that crashes on render.

## Configuration

This server has no environment variables. It is stateless and requires no external connections.

## Starting the server

```bash
# Standalone (from repo root)
uv run python -m src.mcp_visualization_health_gen_ai_chat.main
```

> The server is normally started automatically by the chat agent.

## Chart capabilities

| `chart_type` | Max data points | Max categories | Handles large volumes | Best for |
|---|---|---|---|---|
| `pie` | 50 | 50 | No | Small category breakdowns |
| `bar` | 1,000 | 1,000 | No | Comparing discrete categories |
| `scatter` | 10,000 | 100 | Yes | Correlation between two numeric fields |
| `line` | 50,000 | 10,000 | Yes | Time-series trends |
| `area` | 50,000 | 10,000 | Yes | Cumulative or filled time series |
| `histogram` | 1,000,000 | 100 | Yes (excellent) | Distributions over millions of points |
| `heatmap` | 1,000,000 | 1,000 | Yes (excellent) | Density of two large numeric fields |

Streamlit rendering limits: a `st.dataframe` table is recommended up to 10,000 rows, a scrollable table up to 50,000 rows, and 500 MB per dashboard is treated as the memory ceiling — see `get_system_capabilities()` for the live values.

## Tools

### `get_system_capabilities()`

Returns the chart types above, their limits, and the Streamlit rendering limits as plain text. Call this first when working with an unfamiliar or large dataset.

### `recommend_visualization(rows, numeric_columns, categorical_columns, unique_categories=None)`

Recommends chart types for a dataset based on row count and column mix, before committing to a specific chart.

**Returns:** JSON with `recommended`, `not_recommended`, `warnings`, and `suggestions`.

```json
{
  "data_summary": {"rows": 2000000, "numeric_columns": 8, "categorical_columns": 7},
  "recommended": [
    {"type": "heatmap", "reason": "EXCELLENT for 2,000,000 points"},
    {"type": "histogram", "reason": "Ideal for distributions"}
  ],
  "not_recommended": [
    {"type": "bar", "reason": "2,000,000 rows is too many for bars"},
    {"type": "pie", "reason": "Doesn't support this volume"},
    {"type": "scatter", "reason": "Too slow for >50k points"}
  ],
  "warnings": ["Large dataset (2,000,000 rows). Requires optimization."],
  "suggestions": ["Consider aggregation or sampling to reduce to <100k rows"]
}
```

### `validate_chart(chart_type, rows, categories=None)`

Checks whether a specific chart type can handle a data volume. `build_dashboard` runs this same check on every chart internally, so calling this first is optional — it just lets you pick the right `chart_type` up front instead of getting a rejection back from `build_dashboard`.

```json
{
  "valid": false,
  "message": "Bar Chart supports max 1,000 points, got 2,000,000.",
  "recommendation": "Use: heatmap or histogram"
}
```

### `check_memory(rows, columns)`

Estimates memory usage in MB for a dataset (8 bytes/cell), and whether it fits under the 500 MB per-dashboard ceiling.

### `build_dashboard(title, charts, description=None, metrics=None, tables=None)`

Builds the dashboard configuration. Validates every chart in `charts` against the capability table above; if any chart fails, returns `{"error": ..., "recommendation": ...}` instead of a dashboard.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `title` | `str` | Dashboard title |
| `charts` | `list[dict]` | `{"type": <pie\|bar\|scatter\|line\|area\|histogram\|heatmap>, "title": str, "data": {"x": [...], "y": [...]}}`. For `histogram`, only `x` (the values to bin) is required. |
| `description` | `str \| None` | Optional subtitle/summary |
| `metrics` | `list[dict] \| None` | `{"title": str, "value": ..., "delta": ..., "delta_color": "positive"\|"negative"\|None}` KPI tiles |
| `tables` | `list[dict] \| None` | `{"title": str, "columns": [...], "data": [{...}, ...]}` |

**Returns:** the dashboard config as a JSON string.

```json
{
  "title": "Glucose trend — last 7 days",
  "description": "Daily average glucose, aggregated by day",
  "metrics": [
    {"title": "Avg glucose", "value": "104.2 mg/dL", "delta": "-3.1", "delta_color": "positive"}
  ],
  "charts": [
    {
      "type": "line",
      "title": "Daily average glucose",
      "data": {
        "x": ["2024-03-01", "2024-03-02", "2024-03-03"],
        "y": [105.3, 98.7, 112.1]
      }
    }
  ],
  "tables": []
}
```

## Rendering the dashboard

Unlike the previous Vega-Lite version, this server doesn't return something the browser can render directly. The chat backend (`src/chat_agent/server.py`) scans the assistant's tool results for the `build_dashboard` output, persists it on that assistant message (`Message.dashboard`), and exposes it at:

```
GET /api/messages/{message_id}/dashboard
```

The web UI (`src/chat_agent/index.html`) embeds an iframe for any assistant message that has a dashboard, pointing at the Streamlit renderer:

```
http://localhost:8501/?embed=true&message_id=<id>
```

`src/chat_agent/streamlit_dashboard.py` fetches that message's dashboard config from the chat backend (`CHAT_API_BASE_URL`, default `http://localhost:8000`) and renders metrics/charts/tables with Plotly. Because each assistant message gets its own iframe scoped to its own `message_id`, a single chat session can accumulate any number of dashboards — one per message that built one — not just the most recent one.

## Example: glucose trend

```python
data = [
    {"day": "2024-03-01", "avg_glucose": 105.3},
    {"day": "2024-03-02", "avg_glucose": 98.7},
    {"day": "2024-03-03", "avg_glucose": 112.1},
]

build_dashboard(
    title="Glucose trend — last 3 days",
    charts=[{
        "type": "line",
        "title": "Daily average glucose",
        "data": {"x": [r["day"] for r in data], "y": [r["avg_glucose"] for r in data]},
    }],
)
```

## Example: activity type breakdown

```python
data = [
    {"activity_type": "Run", "total_km": 142.5},
    {"activity_type": "Ride", "total_km": 890.0},
    {"activity_type": "Swim", "total_km": 12.3},
]

build_dashboard(
    title="Activity breakdown",
    charts=[{
        "type": "bar",
        "title": "Total km by activity type",
        "data": {"x": [r["activity_type"] for r in data], "y": [r["total_km"] for r in data]},
    }],
)
```

## Example: large dataset rejected and redirected

```python
validate_chart("bar", rows=2_000_000)
# → {"valid": false, "message": "Bar Chart supports max 1,000 points, got 2,000,000.",
#    "recommendation": "Use: heatmap or histogram"}

build_dashboard(
    title="Raw glucose readings — last 3 months",
    charts=[{"type": "histogram", "title": "Glucose distribution", "data": {"x": all_readings}}],
)
```

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastmcp` | ≥ 2.0.0 | MCP server framework |

The Streamlit renderer (a separate process, `src/chat_agent/streamlit_dashboard.py`) depends on `streamlit`, `plotly`, `pandas`, and `requests` — see the root `pyproject.toml`.
