#!/usr/bin/env python3
"""
FastAPI HTTP wrapper around the Health Gen AI Chat agent.

Serves:
  POST /api/chat  — receives {messages: [...]} and returns {reply: "..."}
  GET  /          — serves index.html and static assets from this directory

Start:
    uv run uvicorn src.chat_agent.server:app --reload --port 8000

Required environment variables:
    ANTHROPIC_API_KEY    — Anthropic API key
    MYSQL_ALCHEMY_URI    — SQLAlchemy connection URL for MySQL
"""

import os
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .main import SYSTEM_PROMPT

app = FastAPI(title="Health Gen AI Chat", version="0.1.0")

_HERE = Path(__file__).parent
_SRC = _HERE.parent


def _mcp_servers() -> list[anthropic.types.beta.BetaMCPServerStdioParams]:
    """Build the three MCP server configs, forwarding the current environment."""
    env = dict(os.environ)
    return [
        anthropic.types.beta.BetaMCPServerStdioParams(
            name="mcp_semantic",
            command="python",
            args=["-m", "src.mcp_semantic_healh_gen_ai_chat.main"],
            env=env,
        ),
        anthropic.types.beta.BetaMCPServerStdioParams(
            name="mcp_exec",
            command="python",
            args=["-m", "src.mcp_exec_health_gen_ai_chat.main"],
            env=env,
        ),
        anthropic.types.beta.BetaMCPServerStdioParams(
            name="mcp_visualization",
            command="python",
            args=["-m", "src.mcp_visualization_health_gen_ai_chat.main"],
            env=env,
        ),
    ]


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(req: ChatRequest) -> JSONResponse:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set.")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        response = await client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=req.messages,
            mcp_servers=_mcp_servers(),
            betas=["mcp-client-2025-04-04"],
            thinking={"type": "adaptive"},
        )
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text = "\n".join(b.text for b in response.content if hasattr(b, "text"))
    return JSONResponse({"reply": text})


# Serve the web UI — must be mounted last so /api/chat takes priority
app.mount("/", StaticFiles(directory=str(_HERE), html=True), name="static")
