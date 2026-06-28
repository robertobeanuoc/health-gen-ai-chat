#!/usr/bin/env python3
"""
FastAPI HTTP wrapper around the Health Gen AI Chat agent.

Serves:
  POST /api/sessions          — create a new chat session
  GET  /api/sessions          — list all sessions
  GET  /api/sessions/{id}     — get session with full message history
  PATCH /api/sessions/{id}    — rename a session
  DELETE /api/sessions/{id}   — delete a session and its messages
  POST /api/chat              — send a message within a session
  GET  /                      — serves index.html and static assets

Start:
    uv run uvicorn src.chat_agent.server:app --reload --port 8000

Required environment variables:
    ANTHROPIC_API_KEY    — Anthropic API key
    MYSQL_ALCHEMY_URI    — SQLAlchemy connection URL for MySQL
"""

import hashlib
import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import get_system_prompt
from .crud import (
    add_message,
    create_session,
    delete_session,
    get_session,
    get_session_history,
    list_sessions,
    update_session_title,
)
from .database import get_db, init_db
from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    SessionDetail,
    SessionOut,
    SessionSummary,
    UpdateSessionRequest,
)

_HERE = Path(__file__).parent
_SRC = _HERE.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Health Gen AI Chat", version="0.1.0", lifespan=lifespan)

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


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------

@app.post("/api/sessions", response_model=SessionOut, status_code=201)
async def create_new_session(req: CreateSessionRequest, db=Depends(get_db)):
    session = await create_session(db, title=req.title)
    return session


@app.get("/api/sessions", response_model=list[SessionSummary])
async def get_sessions(db=Depends(get_db)):
    rows = await list_sessions(db)
    return [
        SessionSummary(
            id=row.Session.id,
            title=row.Session.title,
            created_at=row.Session.created_at,
            updated_at=row.Session.updated_at,
            message_count=row.message_count,
        )
        for row in rows
    ]


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(session_id: str, db=Depends(get_db)):
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@app.patch("/api/sessions/{session_id}", response_model=SessionOut)
async def rename_session(session_id: str, req: UpdateSessionRequest, db=Depends(get_db)):
    session = await update_session_title(db, session_id, req.title)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@app.delete("/api/sessions/{session_id}", status_code=204)
async def remove_session(session_id: str, db=Depends(get_db)):
    deleted = await delete_session(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found.")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db=Depends(get_db)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set.")

    session = await get_session(db, req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    history = await get_session_history(db, req.session_id)
    history.append({"role": "user", "content": req.content})

    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        async with _mcp_tools() as tools:
            runner = client.beta.messages.tool_runner(
                model="claude-opus-4-8",
                max_tokens=4096,
                system=get_system_prompt(),
                messages=history,
                tools=tools,
                thinking={"type": "adaptive"},
            )
            message = await runner.until_done()
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text_parts = [b.text for b in message.content if hasattr(b, "text") and b.type == "text"]
    reply = "\n".join(text_parts)
    vega_spec = _extract_vega_spec(message.content)

    await add_message(db, req.session_id, "user", req.content)
    await add_message(db, req.session_id, "assistant", reply, vega_spec=vega_spec)

    return ChatResponse(reply=reply, vega_spec=vega_spec)


@app.get("/")
async def serve_ui(request: Request):
    content = (_HERE / "index.html").read_bytes()
    etag = f'"{hashlib.md5(content).hexdigest()}"'

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache",
            "ETag": etag,
        },
    )


# Serve the web UI — must be mounted last so API routes take priority
app.mount("/", StaticFiles(directory=str(_HERE), html=True), name="static")
