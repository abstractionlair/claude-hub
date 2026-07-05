# claude-hub

MCP server enabling chat Claude instances to converse with a persistent Claude Code backend.

## Architecture

```
Chat Claude A ──┐
Chat Claude B ──┼──► claude-hub (MCP) ──► Main Claude Code ──► sub-agents
Chat Claude C ──┘
```

**Core idea**: The protocol is natural language conversation, not structured APIs. Chat Claudes "just talk" to a persistent Claude Code instance that has full tooling, stored context, and direct system access.

## Components

- **MCP Server**: Thin relay handling routing, session lifecycle, message passing
- **Main Claude**: Persistent Claude Code session with infrastructure knowledge, manages delegation
- **Sub-agents**: Disposable Claude processes for heavy implementation work
- **Window Files**: Context continuity (context as working memory, window files as long-term memory)

## Status

Early development. See design notes in `docs/`.
