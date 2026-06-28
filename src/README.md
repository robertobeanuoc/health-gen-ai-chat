# src — MCP Servers & Chat Agent

This directory contains all four Python packages that make up the Health Gen AI Chat system.

## Packages

| Directory | FastMCP name | Role |
|---|---|---|
| [`mcp_semantic_healh_gen_ai_chat/`](mcp_semantic_healh_gen_ai_chat/) | `dbt_core_semantic_layer` | Reads dbt artifacts and exposes metrics, dimensions, and column schemas to the LLM |
| [`mcp_exec_health_gen_ai_chat/`](mcp_exec_health_gen_ai_chat/) | `mysql_execution_engine` | Executes read-only SQL queries against MySQL and returns JSON rows |
| [`mcp_visualization_health_gen_ai_chat/`](mcp_visualization_health_gen_ai_chat/) | `DashboardEngine` | Generates Vega-Lite v5 chart specifications from raw data |
| [`chat_agent/`](chat_agent/) | — | LLM agent + web UI. Terminal mode (`main.py`) uses Claude Opus 4.8. Web server (`server.py`) defaults to Claude Haiku 4.5, configurable via `CLAUDE_MODEL` |

## Running a server directly (for testing)

Each server speaks the MCP stdio transport. Start any one with:

```bash
# from the repo root
uv run python -m src.<package_name>.main
```

For example:

```bash
uv run python -m src.mcp_semantic_healh_gen_ai_chat.main
uv run python -m src.mcp_exec_health_gen_ai_chat.main
uv run python -m src.mcp_visualization_health_gen_ai_chat.main
```

You can then send JSON-RPC messages to stdin to test tool calls manually, or point an MCP inspector at the process.

## Starting the full agent

```bash
ANTHROPIC_API_KEY=sk-ant-... \
MYSQL_ALCHEMY_URI=mysql+pymysql://user:pass@host/db \
uv run python -m src.chat_agent.main
```

The agent starts all three MCP servers as child processes automatically.

## Reference documentation

- [docs/mcp-semantic.md](../docs/mcp-semantic.md)
- [docs/mcp-exec.md](../docs/mcp-exec.md)
- [docs/mcp-visualization.md](../docs/mcp-visualization.md)
- [docs/how-to-use.md](../docs/how-to-use.md)
