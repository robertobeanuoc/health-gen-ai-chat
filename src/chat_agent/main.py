#!/usr/bin/env python3
"""
Health Gen AI Chat Agent

Connects Claude Opus to three MCP servers:
  - mcp_semantic: dbt semantic layer (list metrics, dimensions, columns)
  - mcp_exec:     read-only MySQL query execution
  - mcp_visualization: Vega-Lite chart generation

Run:
    ANTHROPIC_API_KEY=... MYSQL_ALCHEMY_URI=... python -m src.chat_agent.main

The agent prints a JSON block with key "vega_spec" when it produces a chart.
The companion index.html detects this and renders it with vega-embed.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import anthropic
from anthropic import AsyncAnthropic

# ---------------------------------------------------------------------------
# MCP server process definitions
# ---------------------------------------------------------------------------
SRC = Path(__file__).parent.parent

MCP_SERVERS = {
    "mcp_semantic": {
        "command": "python",
        "args": ["-m", "mcp_semantic_healh_gen_ai_chat.main"],
        "cwd": str(SRC),
        "env": {
            **os.environ,
            "DBT_MANIFEST_PATH": os.getenv(
                "DBT_MANIFEST_PATH",
                str(SRC.parent / "dbt_health_gen_ai_chat" / "target" / "manifest.json"),
            ),
            "DBT_SEMANTIC_MANIFEST_PATH": os.getenv(
                "DBT_SEMANTIC_MANIFEST_PATH",
                str(SRC.parent / "dbt_health_gen_ai_chat" / "target" / "semantic_manifest.json"),
            ),
        },
    },
    "mcp_exec": {
        "command": "python",
        "args": ["-m", "mcp_exec_health_gen_ai_chat.main"],
        "cwd": str(SRC),
        "env": {**os.environ},
    },
    "mcp_visualization": {
        "command": "python",
        "args": ["-m", "mcp_visualization_health_gen_ai_chat.main"],
        "cwd": str(SRC),
        "env": {**os.environ},
    },
}

SYSTEM_PROMPT = """You are a health data analyst with access to three tools via MCP:

1. **mcp_semantic** — Explore the dbt semantic layer:
   - `list_local_metrics()` — list all defined metrics
   - `get_dimensions_by_semantic_model()` — list dimensions per semantic model
   - `get_model_lineage(model_name)` — get upstream dependencies for a model
   - `get_table_columns(model_name)` — get column names and types for a model

2. **mcp_exec** — Execute read-only SQL against MySQL:
   - `execute_read_query(sql_query)` — run a SELECT query and return JSON rows

3. **mcp_visualization** — Generate Vega-Lite chart specs:
   - `generate_vega_chart(data, chart_type, x_axis, y_axis, y_type)` — produce a chart

Workflow:
- First discover available models/columns using the semantic tools.
- Write and execute a SQL query to fetch the data.
- If visualization is appropriate, call generate_vega_chart with the query results.
- When returning a chart, output a JSON block like:
  ```json
  {"vega_spec": <the full Vega-Lite spec object>}
  ```
  This lets the web UI render the chart automatically.

Always prefer precise, read-only queries. Explain your reasoning briefly before each tool call."""


async def run_agent_turn(
    client: AsyncAnthropic,
    messages: list[dict],
    tools: list[dict],
) -> tuple[str, list[dict]]:
    """Run one agentic turn (may involve multiple tool calls) and return assistant text."""

    while True:
        response = await client.messages.create(
            model="claude-opus-4-8",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
        )

        # Append assistant message
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            # Collect text output
            text_parts = [b.text for b in assistant_content if b.type == "text"]
            return "\n".join(text_parts), messages

        # Process tool calls
        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            print(f"  [tool] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}...)", flush=True)
            # Tools are executed by the MCP client — results come back via the SDK
            # (The MCP client integration replaces tool_use blocks with real results.)
            # Here we build the tool_result message manually for the agentic loop.
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": "[MCP tool executed — result injected by SDK]",
            })

        messages.append({"role": "user", "content": tool_results})


async def main_mcp():
    """Main loop using the Anthropic SDK MCP client integration."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client = AsyncAnthropic(api_key=api_key)

    print("Health Gen AI Chat — type 'quit' to exit.\n")

    # Build MCP server configs for the SDK
    mcp_server_configs = []
    for name, cfg in MCP_SERVERS.items():
        mcp_server_configs.append(
            anthropic.types.beta.BetaMCPServerStdioParams(
                name=name,
                command=cfg["command"],
                args=cfg["args"],
                env=cfg.get("env"),
            )
        )

    messages: list[dict] = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            response = await client.beta.messages.create(
                model="claude-opus-4-8",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                mcp_servers=mcp_server_configs,
                betas=["mcp-client-2025-04-04"],
                thinking={"type": "adaptive"},
            )

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
            reply = "\n".join(text_parts)
            print(f"\nAssistant: {reply}\n")

        except anthropic.APIError as e:
            print(f"API error: {e}", file=sys.stderr)
            messages.pop()  # Remove the failed user turn


if __name__ == "__main__":
    asyncio.run(main_mcp())
