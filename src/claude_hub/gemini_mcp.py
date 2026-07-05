"""Local stdio MCP server exposing Gemini as a chat tool.

Runs as a subprocess of a Claude Code session (zero network, zero auth).
Register with:

    claude mcp add gemini -s user -- \\
        /home/claude/projects/claude-hub/venv/bin/python \\
        -m claude_hub.gemini_mcp

State: in-memory dict of named GeminiChat instances. Each named session
tracks its own Gemini session_id UUID.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from claude_hub.gemini_chat import GeminiChat


mcp = FastMCP("gemini-chat")

_sessions: dict[str, GeminiChat] = {}

GEMINI_TMP_DIR = Path.home() / ".gemini" / "tmp"
GEMINI_PROJECTS_JSON = Path.home() / ".gemini" / "projects.json"


def _get(session_name: str, model: str | None) -> GeminiChat:
    chat = _sessions.get(session_name)
    if chat is None or chat.model != model:
        chat = GeminiChat(model=model)
        _sessions[session_name] = chat
    return chat


@mcp.tool()
async def gemini_send(
    prompt: str,
    session_name: str = "default",
    model: str | None = None,
    reset: bool = False,
    session_id: str | None = None,
) -> dict:
    """Send a message to a persistent Gemini conversation and return its reply.

    Args:
        prompt: The message to send.
        session_name: Logical name for this conversation in the MCP server's
            memory. Different names run independent threads in parallel.
        model: Gemini model id. None (default) lets gemini pick its configured
            default. Pass an explicit id like "gemini-3-flash-preview" to pin.
        reset: If true, discard any existing session for session_name before
            sending — this prompt becomes turn 1 of a new Gemini session.
        session_id: If provided, attach session_name to this pre-existing
            Gemini session UUID and continue it. Use gemini_list_recent to
            discover UUIDs. Ignored if session_name is already attached to
            this session_id.

    Returns:
        {"reply": <text>, "session_name": str, "session_id": str, "model": str}
    """
    if reset:
        _sessions.pop(session_name, None)

    if session_id is not None:
        existing = _sessions.get(session_name)
        if existing is None or existing.session_id != session_id:
            _sessions[session_name] = GeminiChat(
                session_id=session_id, model=model
            )

    chat = _get(session_name, model)
    reply = await chat.send(prompt)
    return {
        "reply": reply,
        "session_name": session_name,
        "session_id": chat.session_id,
        "model": chat.model,
    }


@mcp.tool()
def gemini_list_sessions() -> list[dict]:
    """List all active Gemini chat sessions held in this MCP server's memory."""
    return [
        {
            "session_name": name,
            "session_id": chat.session_id,
            "model": chat.model,
        }
        for name, chat in _sessions.items()
    ]


@mcp.tool()
def gemini_reset(session_name: str = "default") -> dict:
    """Discard a named Gemini conversation. Next gemini_send starts fresh."""
    existed = _sessions.pop(session_name, None) is not None
    return {"session_name": session_name, "removed": existed}


@mcp.tool()
def gemini_list_recent(
    cwd: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """List recent Gemini sessions from the on-disk store.

    Gemini records sessions at ~/.gemini/tmp/<project_alias>/chats/
    session-<timestamp>-<hash>.json. Use this to discover session UUIDs
    you can pass to gemini_send(session_id=...).

    Args:
        cwd: If given, only return sessions whose recorded project matches.
            Looked up via ~/.gemini/projects.json.
        limit: Max entries to return (most recent first).

    Returns:
        List of {session_id, project_alias, started_at, last_updated, preview}.
    """
    if not GEMINI_TMP_DIR.exists():
        return []

    target_alias: str | None = None
    if cwd is not None:
        target_alias = _project_alias_for_cwd(cwd)
        if target_alias is None:
            return []

    files = sorted(
        GEMINI_TMP_DIR.glob("*/chats/session-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    results: list[dict] = []
    for path in files:
        if len(results) >= limit:
            break
        project_alias = path.parent.parent.name
        if target_alias is not None and project_alias != target_alias:
            continue
        meta = _read_session_meta(path)
        if not meta:
            continue
        results.append({
            "session_id": meta["session_id"],
            "project_alias": project_alias,
            "started_at": meta.get("started_at"),
            "last_updated": meta.get("last_updated"),
            "preview": meta.get("preview"),
            "path": str(path),
        })
    return results


def _project_alias_for_cwd(cwd: str) -> str | None:
    try:
        data = json.loads(GEMINI_PROJECTS_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    projects = data.get("projects") or {}
    return projects.get(cwd)


def _read_session_meta(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("sessionId"):
        return None
    preview: str | None = None
    for msg in data.get("messages") or []:
        if msg.get("type") == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("text"):
                        preview = block["text"].strip().replace("\n", " ")[:120]
                        break
            elif isinstance(content, str):
                preview = content.strip().replace("\n", " ")[:120]
            if preview:
                break
    return {
        "session_id": data["sessionId"],
        "started_at": data.get("startTime"),
        "last_updated": data.get("lastUpdated"),
        "preview": preview,
    }


if __name__ == "__main__":
    mcp.run()
