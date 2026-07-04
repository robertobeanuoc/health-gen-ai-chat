#!/usr/bin/env python3
"""
Health Gen AI Chat Agent

Connects Claude Opus to three MCP servers:
  - mcp_semantic: dbt semantic layer (list metrics, dimensions, columns)
  - mcp_exec:     read-only MySQL query execution
  - mcp_visualization: dashboard building (capabilities, recommendations, validation)

Run:
    ANTHROPIC_API_KEY=... MYSQL_ALCHEMY_URI=... python -m src.chat_agent.main

When the agent calls build_dashboard, the server persists the resulting
dashboard config on the assistant message. The companion index.html embeds a
Streamlit iframe (src/chat_agent/streamlit_dashboard.py) that fetches and
renders it.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import anthropic
from anthropic import AsyncAnthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import get_system_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP server process definitions
# ---------------------------------------------------------------------------
SRC = Path(__file__).parent.parent

# Load the project-root .env (the same file docker-compose.yml reads) before
# MCP_SERVERS captures os.environ below.
load_dotenv(SRC.parent / ".env")

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



async def run_agent_turn(
    client: AsyncAnthropic,
    messages: list[dict],
    tools: list[dict],
) -> tuple[str, list[dict]]:
    """Run one agentic turn (may involve multiple tool calls) and return assistant text."""

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=get_system_prompt(),
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

    messages: list[dict] = []

    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        sessions = []
        for cfg in MCP_SERVERS.values():
            params = StdioServerParameters(
                command=cfg["command"],
                args=cfg["args"],
                env=cfg.get("env"),
                cwd=cfg.get("cwd"),
            )
            logger.info("connecting to MCP server | command=%s args=%s", cfg["command"], cfg["args"])
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions.append(session)

        tools = []
        for session in sessions:
            result = await session.list_tools()
            for t in result.tools:
                tools.append(async_mcp_tool(t, session))
        logger.info("MCP tools loaded | count=%d", len(tools))

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
            logger.info("user turn started | content_length=%d", len(user_input))

            try:
                runner = client.beta.messages.tool_runner(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=get_system_prompt(),
                    messages=messages,
                    tools=tools,
                    thinking={"type": "adaptive"},
                    # Auto-caches the last cacheable block (system + tools + accumulated
                    # messages), so repeated tool-calling rounds and later user turns reuse
                    # the cached prefix instead of paying full price on the growing history.
                    cache_control={"type": "ephemeral"},
                )
                response = await runner.until_done()

                usage = response.usage
                print(
                    f"  [usage] input={usage.input_tokens} output={usage.output_tokens} "
                    f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0) or 0} "
                    f"cache_read={getattr(usage, 'cache_read_input_tokens', 0) or 0}",
                    flush=True,
                )

                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
                reply = "\n".join(text_parts)
                print(f"\nAssistant: {reply}\n")

            except anthropic.APIError as e:
                logger.error("Anthropic API error during chat turn: %s", e)
                print(f"API error: {e}", file=sys.stderr)
                messages.pop()


if __name__ == "__main__":
    asyncio.run(main_mcp())
