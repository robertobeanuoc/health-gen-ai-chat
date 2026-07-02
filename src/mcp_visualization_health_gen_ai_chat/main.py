#!/usr/bin/env python3
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent.parent / ".env")

# stdio is the MCP transport's wire protocol — logs must go to stderr, never stdout.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# MCP server initialization
mcp = FastMCP("DashboardEngine")

@mcp.tool()
def generate_vega_chart(data: list[dict], chart_type: str, x_axis: str, y_axis: str, y_type: str = "quantitative") -> str:
    """
    Generates a chart specification from JSON data to build dashboards.

    Args:
        data: List of dictionaries containing the raw data.
        chart_type: Type of chart (e.g., 'bar', 'line', 'point').
        x_axis: JSON key name for the X-axis.
        y_axis: JSON key name for the Y-axis.
        y_type: Data type for the Y-axis ('nominal', 'ordinal', 'quantitative', 'temporal').
    """
    logger.info(
        "generate_vega_chart called | chart_type=%s x_axis=%s y_axis=%s y_type=%s rows=%d",
        chart_type, x_axis, y_axis, y_type, len(data),
    )
    try:
        # Declarative specification generation (Vega-Lite)
        vega_spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": f"Dynamic chart of type {chart_type}",
            "data": {
                "values": data
            },
            "mark": chart_type,
            "encoding": {
                "x": {"field": x_axis, "type": "nominal"},
                "y": {"field": y_axis, "type": y_type}
            }
        }

        return json.dumps(vega_spec, indent=2)
    except Exception as e:
        logger.error("generate_vega_chart failed | error=%s", e)
        return f"Error generating chart: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")