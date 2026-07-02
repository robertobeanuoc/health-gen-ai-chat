#!/usr/bin/env python3
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# stdio is the MCP transport's wire protocol — logs must go to stderr, never stdout.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# MCP server initialization
mcp = FastMCP("dbt_core_semantic_layer")

# Default paths to dbt-core artifacts. Anchored on this file's location (not on the
# process's cwd) so they resolve correctly regardless of how/where the server is
# launched from — local dev, `main.py`'s subprocess, `server.py`'s subprocess, or Docker.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DBT_TARGET = _PROJECT_ROOT / "dbt_health_gen_ai_chat" / "target"

MANIFEST_PATH = os.getenv("DBT_MANIFEST_PATH", str(_DBT_TARGET / "manifest.json"))
SEMANTIC_MANIFEST_PATH = os.getenv("DBT_SEMANTIC_MANIFEST_PATH", str(_DBT_TARGET / "semantic_manifest.json"))

def _load_json(file_path: str) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"dbt artifact not found at: {file_path}. Run 'dbt compile' or 'dbt parse'.")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

@mcp.tool()
def list_local_metrics() -> str:
    """
    Parses semantic_manifest.json to list all metrics defined
    in the local dbt-core project.
    """
    logger.info("list_local_metrics called")
    try:
        data = _load_json(SEMANTIC_MANIFEST_PATH)
        metrics = data.get("metrics", [])

        catalog = []
        for m in metrics:
            catalog.append({
                "name": m.get("name"),
                "description": m.get("description"),
                "type": m.get("type"),
                "expression": m.get("type_params", {}).get("measure", {}).get("name") if m.get("type_params") else None
            })
        return json.dumps(catalog, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("list_local_metrics failed | error=%s", e)
        return f"Error reading metrics: {str(e)}"

@mcp.tool()
def get_dimensions_by_semantic_model() -> str:
    """
    Extracts available dimensions and their types defined in the semantic models
    within semantic_manifest.json.
    """
    logger.info("get_dimensions_by_semantic_model called")
    try:
        data = _load_json(SEMANTIC_MANIFEST_PATH)
        semantic_models = data.get("semantic_models", [])

        dimensions = {}
        for sm in semantic_models:
            model_name = sm.get("name")
            dims = [{ "name": d.get("name"), "type": d.get("type") } for d in sm.get("dimensions", [])]
            dimensions[model_name] = dims

        return json.dumps(dimensions, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("get_dimensions_by_semantic_model failed | error=%s", e)
        return f"Error reading dimensions: {str(e)}"

@mcp.tool()
def get_model_lineage(model_name: str) -> str:
    """
    Queries the main manifest.json to retrieve metadata and dependencies (upstream nodes)
    of a specific dbt model.
    """
    logger.info("get_model_lineage called | model_name=%s", model_name)
    try:
        data = _load_json(MANIFEST_PATH)
        nodes = data.get("nodes", {})

        # Search for the node corresponding to the model
        target_node = None
        for node_id, node_info in nodes.items():
            if node_info.get("name") == model_name and node_info.get("resource_type") == "model":
                target_node = node_info
                break

        if not target_node:
            logger.warning("get_model_lineage — model not found | model_name=%s", model_name)
            return f"Model '{model_name}' not found in manifest.json."

        lineage = {
            "name": target_node.get("name"),
            "database": target_node.get("database"),
            "schema": target_node.get("schema"),
            "upstream_dependencies": target_node.get("depends_on", {}).get("nodes", [])
        }
        return json.dumps(lineage, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("get_model_lineage failed | model_name=%s | error=%s", model_name, e)
        return f"Error processing lineage: {str(e)}"

@mcp.tool()
def get_table_columns(model_name: str) -> str:
    """
    Returns the column names and data types for a specific dbt model by reading manifest.json.
    Use this before writing SQL to know which columns are available.
    """
    logger.info("get_table_columns called | model_name=%s", model_name)
    try:
        data = _load_json(MANIFEST_PATH)
        nodes = data.get("nodes", {})

        target_node = None
        for node_id, node_info in nodes.items():
            if node_info.get("name") == model_name and node_info.get("resource_type") == "model":
                target_node = node_info
                break

        if not target_node:
            # Also check sources
            sources = data.get("sources", {})
            for src_id, src_info in sources.items():
                if src_info.get("name") == model_name:
                    target_node = src_info
                    break

        if not target_node:
            logger.warning("get_table_columns — model/source not found | model_name=%s", model_name)
            return f"Model or source '{model_name}' not found in manifest.json."

        columns = target_node.get("columns", {})
        result = {
            "model": model_name,
            "database": target_node.get("database"),
            "schema": target_node.get("schema"),
            "columns": [
                {"name": col_name, "data_type": col_info.get("data_type", "unknown"), "description": col_info.get("description", "")}
                for col_name, col_info in columns.items()
            ]
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("get_table_columns failed | model_name=%s | error=%s", model_name, e)
        return f"Error reading columns: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")