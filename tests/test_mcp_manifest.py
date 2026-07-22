"""Regression tests for the FastApiMCP tool manifest."""

import claude_hub.server as server_module


def test_mcp_manifest_only_exposes_tool_routes():
    """Web API routes must not leak into the MCP operation map."""
    leaked = {
        operation_id: spec["path"]
        for operation_id, spec in server_module.mcp.operation_map.items()
        if not spec["path"].startswith("/tools/")
    }

    assert leaked == {}


def test_cli_participant_web_routes_are_not_mcp_tools():
    assert "add_codex_to_conversation" not in server_module.mcp.operation_map
    assert "add_gemini_to_conversation" not in server_module.mcp.operation_map
