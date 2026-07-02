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
    ANTHROPIC_API_KEY  — Anthropic API key
    MYSQL_HOST         — MySQL hostname
    MYSQL_USER         — MySQL username
    MYSQL_PASSWORD     — MySQL password
    MYSQL_DATABASE     — MySQL database name
    MYSQL_PORT         — MySQL port (default: 3306)
"""

import hashlib
import json
import logging
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
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

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_SRC = _HERE.parent

# (mtime_ns, etag, content, last_modified) — recomputed only when the file changes
_index_cache: tuple | None = None


def _index_response_data() -> tuple[str, bytes, str]:
    global _index_cache
    path = _HERE / "index.html"
    mtime_ns = path.stat().st_mtime_ns
    if _index_cache is None or _index_cache[0] != mtime_ns:
        content = path.read_bytes()
        etag = f'"{hashlib.md5(content).hexdigest()}"'
        last_modified = datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        _index_cache = (mtime_ns, etag, content, last_modified)
    _, etag, content, last_modified = _index_cache
    return etag, content, last_modified


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
    logger.info("create_new_session called | title=%s", req.title)
    session = await create_session(db, title=req.title)
    return session


@app.get("/api/sessions", response_model=list[SessionSummary])
async def get_sessions(db=Depends(get_db)):
    logger.debug("get_sessions called")
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
    logger.debug("get_session_detail called | session_id=%s", session_id)
    session = await get_session(db, session_id)
    if not session:
        logger.warning("get_session_detail — session not found | session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@app.patch("/api/sessions/{session_id}", response_model=SessionOut)
async def rename_session(session_id: str, req: UpdateSessionRequest, db=Depends(get_db)):
    logger.info("rename_session called | session_id=%s title=%s", session_id, req.title)
    session = await update_session_title(db, session_id, req.title)
    if not session:
        logger.warning("rename_session — session not found | session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@app.delete("/api/sessions/{session_id}", status_code=204)
async def remove_session(session_id: str, db=Depends(get_db)):
    logger.info("remove_session called | session_id=%s", session_id)
    deleted = await delete_session(db, session_id)
    if not deleted:
        logger.warning("remove_session — session not found | session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found.")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db=Depends(get_db)):
    logger.info("chat called | session_id=%s content_length=%d", req.session_id, len(req.content))

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("chat — ANTHROPIC_API_KEY is not set")
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set.")

    session = await get_session(db, req.session_id)
    if not session:
        logger.warning("chat — session not found | session_id=%s", req.session_id)
        raise HTTPException(status_code=404, detail="Session not found.")

    history = await get_session_history(db, req.session_id)
    history.append({"role": "user", "content": req.content})

    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        async with _mcp_tools() as tools:
            runner = client.beta.messages.tool_runner(
                model=model,
                max_tokens=4096,
                system=get_system_prompt(),
                messages=history,
                tools=tools,
                thinking={"type": "adaptive"},
                # Auto-caches the last cacheable block (system + tools + accumulated
                # messages), so repeated tool-calling rounds and later chat turns in the
                # same session reuse the cached prefix instead of paying full price.
                cache_control={"type": "ephemeral"},
            )
            message = await runner.until_done()
    except anthropic.APIError as exc:
        logger.error("chat — Anthropic API error | session_id=%s | error=%s", req.session_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    usage = message.usage
    logger.info(
        "chat usage session=%s model=%s input_tokens=%d output_tokens=%d "
        "cache_creation_input_tokens=%d cache_read_input_tokens=%d",
        req.session_id,
        model,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
    )

    text_parts = [b.text for b in message.content if hasattr(b, "text") and b.type == "text"]
    reply = "\n".join(text_parts)
    vega_spec = _extract_vega_spec(message.content)

    await add_message(db, req.session_id, "user", req.content)
    await add_message(db, req.session_id, "assistant", reply, vega_spec=vega_spec)

    return ChatResponse(reply=reply, vega_spec=vega_spec)


@app.get("/")
async def serve_ui(request: Request):
    etag, content, last_modified = _index_response_data()

    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "no-cache", "Last-Modified": last_modified},
        )

    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache",
            "ETag": etag,
            "Last-Modified": last_modified,
        },
    )


# Serve the web UI — must be mounted last so API routes take priority
app.mount("/", StaticFiles(directory=str(_HERE), html=True), name="static")
