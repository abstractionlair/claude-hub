"""Local stdio MCP server exposing Codex as a chat tool.

Runs as a subprocess of a Claude Code session (zero network, zero auth).
Register with:

    claude mcp add codex -s user -- \\
        /home/claude/projects/claude-hub/venv/bin/python \\
        -m claude_hub.codex_mcp

State: an in-memory dict of named CodexChat instances, keyed by session_name.
Lives for the lifetime of the MCP server subprocess — which Claude Code spawns
on first tool use and keeps alive for the duration of its session. Each named
session tracks its own Codex thread_id, so multiple independent conversations
can run in parallel.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from claude_hub.codex_chat import CodexChat


mcp = FastMCP("codex-chat")

_sessions: dict[str, CodexChat] = {}

CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def _get(session_name: str, model: str | None) -> CodexChat:
    chat = _sessions.get(session_name)
    if chat is None or chat.model != model:
        chat = CodexChat(model=model)
        _sessions[session_name] = chat
    return chat


@mcp.tool()
async def codex_send(
    prompt: str,
    session_name: str = "default",
    model: str | None = None,
    reset: bool = False,
    thread_id: str | None = None,
) -> dict:
    """Send a message to a persistent Codex conversation and return its reply.

    Args:
        prompt: The message to send.
        session_name: Logical name for this conversation in the MCP server's
            memory. Different names run independent threads in parallel.
        model: Codex model id. None (default) lets codex pick its configured
            default — picks up new model versions without a code change.
        reset: If true, discard any existing thread for session_name before
            sending — this prompt becomes turn 1 of a new Codex thread.
        thread_id: If provided, attach session_name to this pre-existing
            Codex thread UUID and continue it. Use codex_list_recent to
            discover UUIDs of sessions started earlier or by other tools
            (TUI, other Claude sessions, etc). Ignored if the current
            session_name is already attached to this thread_id.

    Returns:
        {"reply": <text>, "session_name": str, "thread_id": str, "model": str}
    """
    if reset:
        _sessions.pop(session_name, None)

    if thread_id is not None:
        existing = _sessions.get(session_name)
        if existing is None or existing.thread_id != thread_id:
            _sessions[session_name] = CodexChat(
                thread_id=thread_id, model=model
            )

    chat = _get(session_name, model)
    reply = await chat.send(prompt)
    return {
        "reply": reply,
        "session_name": session_name,
        "thread_id": chat.thread_id,
        "model": chat.model,
    }


@mcp.tool()
def codex_list_recent(
    cwd: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """List recent Codex sessions from the on-disk store.

    Codex records every session (exec or interactive TUI, this project or
    others) at ~/.codex/sessions/YYYY/MM/DD/. Use this to discover thread
    UUIDs you can pass to codex_send(thread_id=...).

    Args:
        cwd: If given, only return sessions whose recorded cwd matches.
        limit: Max entries to return (most recent first).

    Returns:
        List of {thread_id, cwd, started_at, originator, preview}.
        `preview` is the first user message, truncated — useful for humans
        picking from a list.
    """
    if not CODEX_SESSIONS_DIR.exists():
        return []

    files = sorted(
        CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    results: list[dict] = []
    for path in files:
        if len(results) >= limit:
            break
        meta, preview = _read_session_head(path)
        if not meta:
            continue
        if cwd is not None and meta.get("cwd") != cwd:
            continue
        results.append({
            "thread_id": meta.get("id"),
            "cwd": meta.get("cwd"),
            "started_at": meta.get("timestamp"),
            "originator": meta.get("originator"),
            "preview": preview,
            "path": str(path),
        })
    return results


def _read_session_head(path: Path) -> tuple[dict | None, str | None]:
    """Return (session_meta payload, first user message preview) for a session file."""
    meta: dict | None = None
    preview: str | None = None
    try:
        with path.open() as f:
            for i, line in enumerate(f):
                if i > 40:  # bound the scan
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if meta is None and obj.get("type") == "session_meta":
                    meta = obj.get("payload") or {}
                if preview is None:
                    payload = obj.get("payload") or {}
                    if (
                        obj.get("type") == "response_item"
                        and payload.get("type") == "message"
                        and payload.get("role") == "user"
                    ):
                        content = payload.get("content") or []
                        for block in content:
                            text = (
                                block.get("text")
                                if isinstance(block, dict) else None
                            )
                            if text:
                                preview = text.strip().replace("\n", " ")[:120]
                                break
                if meta is not None and preview is not None:
                    break
    except OSError:
        return None, None
    return meta, preview


@mcp.tool()
def codex_list_sessions() -> list[dict]:
    """List all active Codex chat sessions held by this MCP server."""
    return [
        {
            "session_name": name,
            "thread_id": chat.thread_id,
            "model": chat.model,
        }
        for name, chat in _sessions.items()
    ]


@mcp.tool()
def codex_reset(session_name: str = "default") -> dict:
    """Discard a named Codex conversation. Next codex_send starts fresh."""
    existed = _sessions.pop(session_name, None) is not None
    return {"session_name": session_name, "removed": existed}


if __name__ == "__main__":
    mcp.run()
