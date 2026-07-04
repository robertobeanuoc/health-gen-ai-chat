#!/usr/bin/env python3
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# stdio is the MCP transport's wire protocol — logs must go to stderr, never stdout.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# MCP server initialization
mcp = FastMCP("DashboardEngine")

# =============================================================================
# Chart capabilities and limits
#
# The Streamlit renderer builds each chart with Plotly from the full dataset
# (no server-side downsampling), so a chart type that draws one mark per row
# (bar, pie, scatter) becomes unreadable or freezes the browser tab well
# before a memory limit is hit. Aggregate/binned chart types (line, area,
# heatmap, histogram) scale much further. These limits keep chart choice
# honest about that difference and let the MCP server refuse bad combinations
# instead of silently returning a dashboard that will crash on render.
# =============================================================================


@dataclass
class ChartCapability:
    name: str
    max_data_points: int
    max_categories: int
    supports_large_data: bool
    typical_render_time_ms: int
    description: str


CHART_CAPABILITIES: dict[str, ChartCapability] = {
    "pie": ChartCapability(
        name="Pie Chart",
        max_data_points=50,
        max_categories=50,
        supports_large_data=False,
        typical_render_time_ms=100,
        description="Circle, max 50 slices",
    ),
    "bar": ChartCapability(
        name="Bar Chart",
        max_data_points=1_000,
        max_categories=1_000,
        supports_large_data=False,
        typical_render_time_ms=150,
        description="Bars, good for categories",
    ),
    "scatter": ChartCapability(
        name="Scatter Plot",
        max_data_points=10_000,
        max_categories=100,
        supports_large_data=True,
        typical_render_time_ms=300,
        description="Scattered points, correlations",
    ),
    "line": ChartCapability(
        name="Line Chart",
        max_data_points=50_000,
        max_categories=10_000,
        supports_large_data=True,
        typical_render_time_ms=200,
        description="Lines with discrete points",
    ),
    "area": ChartCapability(
        name="Area Chart",
        max_data_points=50_000,
        max_categories=10_000,
        supports_large_data=True,
        typical_render_time_ms=250,
        description="Stacked areas",
    ),
    "histogram": ChartCapability(
        name="Histogram",
        max_data_points=1_000_000,
        max_categories=100,
        supports_large_data=True,
        typical_render_time_ms=300,
        description="Distributions, ideal for millions of points",
    ),
    "heatmap": ChartCapability(
        name="Heatmap",
        max_data_points=1_000_000,
        max_categories=1_000,
        supports_large_data=True,
        typical_render_time_ms=500,
        description="Color matrix, IDEAL for large volumes",
    ),
}

STREAMLIT_MAX_DATAFRAME_ROWS = 10_000
STREAMLIT_MAX_TABLE_ROWS = 50_000
MAX_MEMORY_PER_DASHBOARD_MB = 500
ACCEPTABLE_RENDER_TIME_MS = 2_000


def _validate_chart(chart_type: str, rows: int, categories: int | None = None) -> dict:
    """Check whether a chart type can handle a given data volume."""
    if chart_type not in CHART_CAPABILITIES:
        return {"valid": False, "message": f"Unsupported chart_type '{chart_type}'. Supported: {list(CHART_CAPABILITIES)}"}

    cap = CHART_CAPABILITIES[chart_type]

    if rows > cap.max_data_points:
        alternatives = [name for name in ("heatmap", "histogram") if name != chart_type]
        return {
            "valid": False,
            "message": f"{cap.name} supports max {cap.max_data_points:,} points, got {rows:,}.",
            "recommendation": f"Use: {' or '.join(alternatives)}",
        }

    if categories is not None and categories > cap.max_categories:
        return {"valid": False, "message": f"{cap.name} supports max {cap.max_categories:,} categories, got {categories:,}."}

    return {
        "valid": True,
        "message": f"{cap.name} can handle this data.",
        "render_time_ms": cap.typical_render_time_ms,
        "capability": asdict(cap),
    }


def _analyze_data(rows: int, numeric: int, categorical: int, categories: int | None = None) -> dict:
    """Recommend chart types based on data characteristics."""
    recommendations: dict = {
        "data_summary": {"rows": rows, "numeric_columns": numeric, "categorical_columns": categorical},
        "recommended": [],
        "not_recommended": [],
        "warnings": [],
        "suggestions": [],
    }

    if rows < 100:
        recommendations["warnings"].append("Small dataset (<100 rows)")

    if rows > 100_000:
        recommendations["warnings"].append(f"Large dataset ({rows:,} rows). Requires optimization.")

    if rows <= 1_000:
        recommendations["recommended"].extend([
            {"type": "bar", "reason": f"Perfect for {rows:,} rows"},
            {"type": "pie", "reason": "OK if <50 categories"},
            {"type": "line", "reason": "Good for series"},
        ])
    elif rows <= 50_000:
        recommendations["recommended"].extend([
            {"type": "line", "reason": f"Ideal for {rows:,} points"},
            {"type": "scatter", "reason": "Correlations"},
        ])
        recommendations["not_recommended"].append({"type": "pie", "reason": "Not recommended for >1000 rows"})
        recommendations["not_recommended"].append({"type": "bar", "reason": "Not recommended for >1000 rows"})
    else:
        recommendations["recommended"].extend([
            {"type": "heatmap", "reason": f"EXCELLENT for {rows:,} points"},
            {"type": "histogram", "reason": "Ideal for distributions"},
        ])
        recommendations["not_recommended"].extend([
            {"type": "bar", "reason": f"{rows:,} rows is too many for bars"},
            {"type": "pie", "reason": "Doesn't support this volume"},
            {"type": "scatter", "reason": "Too slow for >50k points"},
        ])
        recommendations["suggestions"].append("Consider aggregation or sampling to reduce to <100k rows")

    if categories is not None:
        recommendations["recommended"] = [
            r for r in recommendations["recommended"] if categories <= CHART_CAPABILITIES[r["type"]].max_categories
        ]

    return recommendations


@mcp.tool()
def get_system_capabilities() -> str:
    """
    Returns the chart types the dashboard renderer supports, their data-volume
    limits, and Streamlit rendering limits. Call this before recommending or
    validating a chart for an unfamiliar or large dataset.
    """
    lines = ["Chart capabilities:"]
    for chart_type, cap in CHART_CAPABILITIES.items():
        large = "supports large data" if cap.supports_large_data else "small data only"
        lines.append(f"  - {chart_type} ({cap.name}): max {cap.max_data_points:,} points, {large} — {cap.description}")
    lines.append("")
    lines.append("Streamlit limits:")
    lines.append(f"  - DataFrame (recommended): {STREAMLIT_MAX_DATAFRAME_ROWS:,} rows")
    lines.append(f"  - Table with scrolling: {STREAMLIT_MAX_TABLE_ROWS:,} rows")
    lines.append(f"  - Memory per dashboard: {MAX_MEMORY_PER_DASHBOARD_MB} MB")
    lines.append(f"  - Acceptable render time: {ACCEPTABLE_RENDER_TIME_MS:,} ms")
    lines.append("")
    lines.append("Recommendations by volume:")
    lines.append("  - <1K rows:      any chart")
    lines.append("  - 1K-50K rows:   line, scatter (not pie/bar)")
    lines.append("  - 50K-1M rows:   heatmap, histogram (best)")
    lines.append("  - >1M rows:      aggregate first, then heatmap/histogram")
    return "\n".join(lines)


@mcp.tool()
def recommend_visualization(
    rows: int,
    numeric_columns: int,
    categorical_columns: int,
    unique_categories: int | None = None,
) -> str:
    """
    Recommends chart types for a dataset based on row count and column mix,
    before you commit to building a dashboard.

    Args:
        rows: Number of rows in the result set.
        numeric_columns: Count of numeric columns available for encoding.
        categorical_columns: Count of categorical columns available for encoding.
        unique_categories: Distinct values in the field you'd use for the X axis, if known.
    """
    return json.dumps(_analyze_data(rows, numeric_columns, categorical_columns, unique_categories), indent=2)


@mcp.tool()
def validate_chart(chart_type: str, rows: int, categories: int | None = None) -> str:
    """
    Validates whether a chart type can handle a data volume before calling
    build_dashboard. build_dashboard also runs this check on every chart it's
    given and will refuse to build a chart that fails it, but calling this
    first lets you pick the right chart_type up front.

    Args:
        chart_type: One of 'pie', 'bar', 'scatter', 'line', 'area', 'histogram', 'heatmap'.
        rows: Number of data points the chart would be built from.
        categories: Distinct values on the categorical axis, if known.
    """
    return json.dumps(_validate_chart(chart_type, rows, categories), indent=2)


@mcp.tool()
def check_memory(rows: int, columns: int) -> str:
    """
    Estimates memory usage (in MB) for a dataset, assuming 8 bytes per cell.

    Args:
        rows: Number of rows.
        columns: Number of columns.
    """
    mb = (rows * columns * 8) / (1024 * 1024)
    return json.dumps(
        {
            "estimated_mb": round(mb, 2),
            "limit_mb": MAX_MEMORY_PER_DASHBOARD_MB,
            "ok": mb <= MAX_MEMORY_PER_DASHBOARD_MB,
        },
        indent=2,
    )


@mcp.tool()
def build_dashboard(
    title: str,
    charts: list[dict],
    description: str | None = None,
    metrics: list[dict] | None = None,
    tables: list[dict] | None = None,
) -> str:
    """
    Builds a dashboard configuration for the Streamlit renderer. Validates
    every chart against its data-volume limits first — see
    get_system_capabilities/validate_chart for the limits — and refuses to
    build a dashboard containing a chart that would be unreadable or would
    freeze the browser, instead of silently returning a broken config.

    Args:
        title: Dashboard title.
        charts: List of {"type": <pie|bar|scatter|line|area|histogram|heatmap>,
            "title": str, "data": {"x": [...], "y": [...]}}. For histogram,
            only "x" (the values to bin) is required.
        description: Optional dashboard subtitle/summary.
        metrics: Optional list of {"title": str, "value": ..., "delta": ...,
            "delta_color": "positive"|"negative"|None} KPI tiles.
        tables: Optional list of {"title": str, "columns": [...], "data": [{...}, ...]}.
    """
    logger.info("build_dashboard called | title=%s charts=%d", title, len(charts))

    for chart in charts:
        chart_type = chart.get("type")
        data = chart.get("data", {})
        x_values = data.get("x", [])
        rows = len(x_values)
        categories = len(set(x_values)) if x_values and chart_type in ("pie", "bar") else None

        validation = _validate_chart(chart_type, rows, categories)
        if not validation["valid"]:
            logger.warning("build_dashboard rejected | chart=%s | %s", chart.get("title"), validation["message"])
            return json.dumps(
                {"error": f"Chart '{chart.get('title', chart_type)}' rejected: {validation['message']}",
                 "recommendation": validation.get("recommendation")},
                indent=2,
            )

    dashboard = {
        "title": title,
        "description": description,
        "metrics": metrics or [],
        "charts": charts,
        "tables": tables or [],
    }
    return json.dumps(dashboard, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
