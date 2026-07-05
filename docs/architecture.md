# Architecture

## Core Vision

Chat Claudes "just talk" to a persistent Claude Code instance. The protocol is natural language conversation, not structured APIs.

```
Chat Claude A ──┐
Chat Claude B ──┼──► claude-hub (MCP) ──► Main Claude Code ──► sub-agents
Chat Claude C ──┘
```

## Components

### MCP Server (this repo)

Thin relay handling:
- **Routing table**: Maps conversation IDs to target sessions
- **Session lifecycle**: Spawn, resume, restart sessions
- **Message relay**: Pass messages, return responses (blocking)
- **Control command parsing**: Handle routing changes from Claudes

The server has no business logic. Intelligence lives in the Claudes.

### Main Claude

Persistent Claude Code session that:
- Holds infrastructure knowledge, conventions, cross-chat context
- Makes routing decisions (handle directly vs delegate)
- Manages sub-agents for heavy work
- Maintains continuity via window files

### Sub-agents

Disposable Claude processes (separate `claude` invocations) for:
- Implementation work
- Long-running tasks
- Anything that would bloat main Claude's context

Tracked via beads or similar task management.

### Window Files

Context continuity via linked window file chain:
- Context window = working memory (ephemeral)
- Window files = long-term memory (persistent)

Rather than summarizing (lossy), save state to window file and restart fresh. Window files are timestamped markdown with YAML frontmatter, linked via parent pointers into a traversable chain.

## Composition pattern

Claude-hub plays two well-known architectural roles for everything behind it:

1. **API Gateway** — single front door for all MCP traffic. Terminates auth at the public boundary, exposes a unified tool surface, forwards to internal subservices over localhost HTTP via thin `httpx` calls in the `/tools/...` route handlers. Internal services are not publicly addressable; the gateway is the only door.
2. **Backend for Frontend (BFF)** — the tool surface is shaped specifically for MCP clients (claude.ai, codex, gemini). If a different consumer class ever needed a different surface, it'd be a sibling BFF rather than another concern jammed into this one.

Internal services bind to `127.0.0.1:<port>` and rely on **bind address as security boundary** — no nginx, no SSL, no auth between gateway and backend. Each service owns its Postgres schema in the shared `claude_hub` database (**schema-isolated shared DB** — the pragmatic small-team compromise between database-per-service and shared-schema).

The work-graph integration is the canonical example: separate project at `~/projects/work-graph/` with its own `deploy.yaml`, systemd unit on `127.0.0.1:8421`, owns the `work_graph` schema, forwarded by `_forward_to_wg()` in `server.py`, response shapes typed in `claude_hub.work_graph_models`. New internal subservices should follow the same shape.

None of these primitives are exotic — FastAPI subservice, `httpx` forwarder, systemd, Postgres schema, localhost socket. The implementation is small-scale (no Kong, no Envoy, no service mesh) but the architecture is what AWS would draw on a whiteboard.

## Communication Model

**Blocking/conversational for v1:**
- Chat Claude sends message, waits for response
- Main Claude can ask clarifying questions
- Simple state: one message in flight per conversation

Async (email-like) model deferred until needed.

## Conversation IDs

Chat Claudes don't have unique identifiers. The MCP server generates one on `hub_init` and the chat Claude includes it in subsequent calls.

## Dynamic Routing

Main Claude can modify routing via control commands:
- Route conversation to sub-agent (full delegation)
- Route for N messages then return
- Sub-agents can escalate or release

Commands embedded in response, parsed by MCP server.

## Wake-up Trigger

MCP server spawns main Claude session when messages arrive and no session is active. The server is "always on"; Claude sessions are spawned on demand.

## Session Continuity

Using patterns from Continuous-Claude-v2:
1. Session approaches context limit
2. Fork narrative agent to capture state in window file
3. Finalize current window, create new child window
4. Resume fresh, loading window file chain

This avoids "summary of summary" degradation.

## Open Questions

- **Window file format**: What's the minimal viable structure for wake-up?
- **Control command syntax**: Embedded in response or separate channel?
- **Sub-agent tracking**: Integrate beads or build custom?
- **Context limit detection**: How does session know it's full?
