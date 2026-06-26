#!/usr/bin/env python3
"""
FastAPI HTTP wrapper around the Health Gen AI Chat agent.

Serves:
  POST /api/chat  — receives {messages: [...]} and returns {reply, vega_spec}
  GET  /          — serves index.html and static assets from this directory

The vega_spec field is populated directly from the generate_vega_chart tool
result, not parsed from the assistant's text. This guarantees charts always
render regardless of how the LLM phrases its response.

Start:
    uv run uvicorn src.chat_agent.server:app --reload --port 8000

Required environment variables:
    ANTHROPIC_API_KEY    — Anthropic API key
    MYSQL_ALCHEMY_URI    — SQLAlchemy connection URL for MySQL
"""

import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import anthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from .main import SYSTEM_PROMPT

app = FastAPI(title="Health Gen AI Chat", version="0.1.0")

_HERE = Path(__file__).parent
_SRC = _HERE.parent

_SERVER_DEFS = [
    StdioServerParameters(
        command="python",
        args=["-m", "mcp_semantic_healh_gen_ai_chat.main"],
        cwd=str(_SRC),
    ),
    StdioServerParameters(
        command="python",
        args=["-m", "mcp_exec_health_gen_ai_chat.main"],
        cwd=str(_SRC),
    ),
    StdioServerParameters(
        command="python",
        args=["-m", "mcp_visualization_health_gen_ai_chat.main"],
        cwd=str(_SRC),
    ),
]


@asynccontextmanager
async def _mcp_tools():
    """Start all MCP servers as stdio subprocesses and yield runnable tool wrappers."""
    env = dict(os.environ)
    server_defs = [
        StdioServerParameters(
            command="python",
            args=["-m", "mcp_semantic_healh_gen_ai_chat.main"],
            env=env,
            cwd=str(_SRC),
        ),
        StdioServerParameters(
            command="python",
            args=["-m", "mcp_exec_health_gen_ai_chat.main"],
            env=env,
            cwd=str(_SRC),
        ),
        StdioServerParameters(
            command="python",
            args=["-m", "mcp_visualization_health_gen_ai_chat.main"],
            env=env,
            cwd=str(_SRC),
        ),
    ]

    async with AsyncExitStack() as stack:
        tools = []
        for server_def in server_defs:
            read, write = await stack.enter_async_context(stdio_client(server_def))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            result = await session.list_tools()
            for t in result.tools:
                tools.append(async_mcp_tool(t, session))
        yield tools


def _extract_vega_spec(content: list) -> dict | None:
    """
    Scan all response content blocks for a generate_vega_chart tool result
    and return the parsed Vega-Lite spec, or None if no chart was produced.
    """
    for block in content:
        block_type = getattr(block, "type", None)

        # Structured tool_result block
        if block_type == "tool_result":
            raw = getattr(block, "content", None) or getattr(block, "output", None)
            if isinstance(raw, str):
                try:
                    spec = json.loads(raw)
                    if isinstance(spec, dict) and "$schema" in spec and "vega" in spec.get("$schema", ""):
                        return spec
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(raw, list):
                for item in raw:
                    text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
                    if text:
                        try:
                            spec = json.loads(text)
                            if isinstance(spec, dict) and "$schema" in spec and "vega" in spec.get("$schema", ""):
                                return spec
                        except (json.JSONDecodeError, TypeError):
                            pass

        # Text block — LLM may have echoed the spec in its reply
        if block_type == "text":
            text = getattr(block, "text", "")
            for match in re.finditer(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text):
                try:
                    spec = json.loads(match.group(1))
                    if isinstance(spec, dict) and "$schema" in spec and "vega" in spec.get("$schema", ""):
                        return spec
                    if isinstance(spec, dict) and "vega_spec" in spec:
                        return spec["vega_spec"]
                except (json.JSONDecodeError, TypeError):
                    pass

    return None


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(req: ChatRequest) -> JSONResponse:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set.")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        async with _mcp_tools() as tools:
            runner = client.beta.messages.tool_runner(
                model="claude-opus-4-8",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=req.messages,
                tools=tools,
                thinking={"type": "adaptive"},
            )
            message = await runner.until_done()
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text_parts = [b.text for b in message.content if hasattr(b, "text") and b.type == "text"]
    reply = "\n".join(text_parts)
    vega_spec = _extract_vega_spec(message.content)

    return JSONResponse({"reply": reply, "vega_spec": vega_spec})


# Serve the web UI — must be mounted last so /api/chat takes priority
app.mount("/", StaticFiles(directory=str(_HERE), html=True), name="static")
