# MCP Visualization Server — `DashboardEngine`

**Package:** `src/mcp_visualization_health_gen_ai_chat`  
**Transport:** stdio  
**FastMCP name:** `DashboardEngine`

## Overview

The Visualization MCP server is the **chart generation layer**. It takes raw JSON data (typically the output of `execute_read_query`) and a set of chart parameters, and returns a [Vega-Lite v5](https://vega.github.io/vega-lite/) specification as a JSON string. The specification can be rendered directly in a browser using `vega-embed`, or in any other Vega-Lite-compatible renderer.

```
execute_read_query result (JSON rows)
  └── generate_vega_chart(data, chart_type, x_axis, y_axis)
        └── Vega-Lite v5 spec (JSON string)
              └── vega-embed in browser → rendered chart
```

## Configuration

This server has no environment variables. It is stateless and requires no external connections.

## Starting the server

```bash
# Standalone
cd src
python -m mcp_visualization_health_gen_ai_chat.main
```

> The server is normally started automatically by the chat agent.

## Tools

### `generate_vega_chart(data, chart_type, x_axis, y_axis, y_type="quantitative")`

Produces a Vega-Lite v5 chart specification from raw data.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `data` | `list[dict]` | required | Rows of data — the direct output of `execute_read_query` parsed as a Python list |
| `chart_type` | `str` | required | Vega-Lite mark type: `"bar"`, `"line"`, `"point"`, `"area"`, `"tick"`, `"rect"` |
| `x_axis` | `str` | required | Key name from each row object to use on the X axis |
| `y_axis` | `str` | required | Key name from each row object to use on the Y axis |
| `y_type` | `str` | `"quantitative"` | Vega-Lite encoding type for the Y axis |

**Y-axis encoding types:**

| Value | Use when |
|---|---|
| `"quantitative"` | Numeric data (glucose values, distances, averages) |
| `"temporal"` | Date or datetime values on the Y axis (rare) |
| `"ordinal"` | Ordered categories (low/medium/high, 1st/2nd/3rd) |
| `"nominal"` | Unordered categories (activity type, sport type) |

**Returns:** A JSON string containing the complete Vega-Lite v5 specification.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "description": "Dynamic chart of type bar",
  "data": {
    "values": [
      { "day": "2024-03-01", "avg_glucose": 105.3 },
      { "day": "2024-03-02", "avg_glucose": 98.7 }
    ]
  },
  "mark": "bar",
  "encoding": {
    "x": { "field": "day", "type": "nominal" },
    "y": { "field": "avg_glucose", "type": "quantitative" }
  }
}
```

> The X axis always uses `"nominal"` encoding. If the X field contains dates, use `chart_type: "line"` and let Vega-Lite handle temporal ordering naturally.

## Chart type reference

| `chart_type` | Best for |
|---|---|
| `"bar"` | Comparing discrete categories (activity types, days of week) |
| `"line"` | Time-series trends (glucose over days, distance over months) |
| `"point"` | Scatter plots (correlation between two numeric fields) |
| `"area"` | Cumulative or filled time series |
| `"tick"` | Distribution of values along a single axis |

## Rendering the spec

### In the web UI (`index.html`)

The companion `src/chat_agent/index.html` automatically detects when the assistant's reply contains a Vega-Lite spec and renders it with `vega-embed`. The assistant wraps the spec in a JSON block:

```json
{"vega_spec": { ... vega-lite spec ... }}
```

The UI strips this block from the text and renders the chart in-place.

### Manually in a browser

```html
<div id="chart"></div>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<script>
  const spec = /* paste the JSON string returned by generate_vega_chart */;
  vegaEmbed('#chart', JSON.parse(spec));
</script>
```

### In Python (for testing)

```python
import json, altair as alt, pandas as pd

spec_str = generate_vega_chart(data, "line", "day", "avg_glucose")
spec = json.loads(spec_str)
chart = alt.Chart.from_dict(spec)
chart.show()  # opens in browser
```

## Example: glucose trend

```python
# After execute_read_query returns this data:
data = [
    {"day": "2024-03-01", "avg_glucose": 105.3},
    {"day": "2024-03-02", "avg_glucose": 98.7},
    {"day": "2024-03-03", "avg_glucose": 112.1},
]

spec = generate_vega_chart(
    data=data,
    chart_type="line",
    x_axis="day",
    y_axis="avg_glucose",
    y_type="quantitative"
)
```

## Example: activity type breakdown

```python
data = [
    {"activity_type": "Run", "total_km": 142.5},
    {"activity_type": "Ride", "total_km": 890.0},
    {"activity_type": "Swim", "total_km": 12.3},
]

spec = generate_vega_chart(
    data=data,
    chart_type="bar",
    x_axis="activity_type",
    y_axis="total_km",
    y_type="quantitative"
)
```

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastmcp` | ≥ 2.0.0 | MCP server framework |

No external runtime dependencies beyond the standard library and FastMCP.
