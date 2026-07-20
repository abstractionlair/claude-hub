"""Per-tool usage telemetry via the MCP auth middleware.

MCPAuthMiddleware emits one INFO ``mcp_tool_call <name>`` line per
``/tools/<name>`` dispatch, giving a per-tool usage histogram in journald.
FastApiMCP re-dispatches connector calls (``POST /mcp``) as internal ASGI
requests to ``/tools/<name>``, so this line captures connector traffic that
uvicorn's access log -- which only ever records the outer ``POST /mcp`` --
cannot attribute to a specific tool.
"""

import logging

import pytest

from claude_hub.server import MCPAuthMiddleware


async def _drive(path):
    """Run one HTTP request through the middleware with a trivial downstream app."""

    async def dummy_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_msg):
        pass

    scope = {"type": "http", "path": path, "headers": []}
    await MCPAuthMiddleware(dummy_app)(scope, receive, send)


@pytest.mark.asyncio
async def test_tool_call_is_logged(caplog):
    with caplog.at_level(logging.INFO, logger="claude_hub.server"):
        await _drive("/tools/wg_capture")
    assert "mcp_tool_call wg_capture" in caplog.text


@pytest.mark.asyncio
async def test_non_tool_path_not_logged(caplog):
    with caplog.at_level(logging.INFO, logger="claude_hub.server"):
        await _drive("/health")
    assert "mcp_tool_call" not in caplog.text
