#!/usr/bin/env python3
import json
import os
from mcp.server.fastmcp import FastMCP

# MCP server initialization
mcp = FastMCP("dbt_core_semantic_layer")

# Default paths to dbt-core artifacts
MANIFEST_PATH = os.getenv("DBT_MANIFEST_PATH", "/Users/rbean/Documents/GitHub/health-gen-ai-chat/dbt_health_gen_ai_chat/target/manifest.json")
SEMANTIC_MANIFEST_PATH = os.getenv("DBT_SEMANTIC_MANIFEST_PATH", "/Users/rbean/Documents/GitHub/health-gen-ai-chat/dbt_health_gen_ai_chat/target/semantic_manifest.json")

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
        return f"Error reading metrics: {str(e)}"

@mcp.tool()
def get_dimensions_by_semantic_model() -> str:
    """
    Extracts available dimensions and their types defined in the semantic models
    within semantic_manifest.json.
    """
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
        return f"Error reading dimensions: {str(e)}"

@mcp.tool()
def get_model_lineage(model_name: str) -> str:
    """
    Queries the main manifest.json to retrieve metadata and dependencies (upstream nodes)
    of a specific dbt model.
    """
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
            return f"Model '{model_name}' not found in manifest.json."
            
        lineage = {
            "name": target_node.get("name"),
            "database": target_node.get("database"),
            "schema": target_node.get("schema"),
            "upstream_dependencies": target_node.get("depends_on", {}).get("nodes", [])
        }
        return json.dumps(lineage, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error processing lineage: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")