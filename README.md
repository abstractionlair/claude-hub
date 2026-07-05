# claude-hub

Personal AI infrastructure hub — a single gateway that connects MCP-capable AI
sessions (claude.ai, Codex, Gemini) to a persistent Claude Code backend with
work tracking, semantic artifact storage, multi-model reviews, scheduling, and
group chat across frontier models.

Designed for a single operator. Published as a working reference — not a
supported product.

---

## Capabilities

### Session orchestration (`hub_*`)

Three-tool MCP surface for delegating work to a persistent Claude Code backend:

- **`hub_init`** — Start a conversation; returns a `conversation_id`.
  Pre-warms a Claude process so the first `hub_send` is fast.
- **`hub_send`** — Send a message (returns `request_id` immediately, processes
  asynchronously).
- **`hub_poll`** — Retrieve the response for a `request_id`.
- **`hub_status`** — Active sessions, routing table, token usage, observations.

The backend Claude process runs with full tooling, stored context, and system
access — it understands natural language requests without a structured API.

### Work Graph (`wg_*`)

A persistent, navigable graph of work-in-progress shared across all sessions.
Runs as a separate service on `localhost:8421`; claude-hub forwards to it.

- **`wg_session_start`** — Get a session token (cursor + breadcrumb trail).
- **`wg_brief`** — Token-free, read-only prose brief of current work state.
- **`wg_capture`** — Capture a work item (creates a node in the graph).
- **`wg_goto`** — Navigate to a node (returns provenance path, children, edges).
- **`wg_status`** — Current session state (cursorless: all roots; cursor: full
  context).
- **`wg_query`** — Structured queries: overview, ready, recent, deferred, blocked.
- **`wg_search`** — Case-insensitive substring search across all nodes.
- **`wg_add_dependency`** — Create `blocks` or `related` edges between nodes.
- **`wg_update`** — Update a node's text/status (lifecycle: captured →
  in-progress → done / won't-do).

Provenance edges (parent-child) are automatic on capture. Cross-cutting edges
are explicit via `wg_add_dependency`. Read-only web UI at `/work-graph`.

### Artifact Store (`artifact_*`)

Durable knowledge storage with semantic search (pgvector + Gemini embeddings),
versioning, confidence scoring, and Bayesian utility tracking.

- **`artifact_store`** — Store with content, type, tags, source ref, derives_from.
- **`artifact_get`** — Retrieve by ID with optional version history and feedback.
- **`artifact_search`** — Semantic search with filters (type, tags, date, confidence).
- **`artifact_list`** — Paginated browsing.
- **`artifact_archive`** / **`artifact_update`** / **`artifact_update_metadata`**
  — Lifecycle management.
- **`artifact_export`** / **`artifact_import`** — Backup/restore.
- **`artifact_feedback`** — Record usefulness feedback (updates Bayesian score).
- **`artifact_set_confidence`** — Mark confidence level (HIGH/MEDIUM/LOW/SUPERSEDED).
- **`artifact_retirement_candidates`** — Find low-utility artifacts for cleanup.

### Multi-Model Review

Dispatch code, documents, or artifacts to multiple AI models for review and
synthesize their findings into a consensus report. The review engine is
CLI-based — `python3 -m claude_hub.review_cli` — not exposed as MCP/HTTP
tools (the request/response models in `src/claude_hub/review_models.py` are
retained for documentation).

Model registry: `config/review_models.yaml`.

### Scheduling (`schedule_*`)

Cron-like wake-up system — schedule one-time or recurring prompts to any
session. Background thread checks every 30 seconds.

- **`schedule_wake_at`** — One-time wake-up at a specific time.
- **`schedule_wake_every`** — Recurring (e.g., every 4 hours).
- **`list_schedules`** / **`cancel_schedule`** — Manage active schedules.

### Group Chat (multi-model)

Real-time group conversations between humans, Claude instances, Codex CLI, and
Gemini CLI — all in one room.

- **Web UI** — `/group` — browser-based group chat with participant management.
- **`group_join`** / **`group_send`** / **`group_poll`** / **`group_leave`** —
  MCP tools for programmatic participation.
- **REST API** — Create/manage conversations, add Claude/Codex/Gemini participants.
- **WebSocket** — `/ws/group/{conversation_id}` — streaming multi-agent protocol
  with participant join/leave, stream chunks, catch-up history, keepalive.

Messages persist to PostgreSQL; crash recovery marks interrupted conversations.

### OAuth 2.1 + MCP Surface

The server exposes all tools via two MCP transports:
- **Streamable HTTP** (`/mcp`) — modern default (claude.ai, Excel, Codex).
- **SSE** (`/mcp-sse`) — legacy compatibility.

OAuth 2.1 with PKCE (S256), dynamic client registration (RFC 7591), and TOTP
for web UI sessions. All tool endpoints require Bearer token auth when enabled.

### Notifications (`notify`)

Fire-and-forget notifications to the human operator:
- **`notify`** — Send a notification (message, priority, project context).
- **Web UI** — `/notifications/view` — TOTP-protected notification viewer.
- **API** — List, read, mark-read with TOTP session auth.

### Chat surfaces

- **Web Chat** — `/chat` — browser chat UI with WebSocket streaming
  (`/ws/chat`). Token-level streaming, observation recording, chat history logs.
- **MCP** — `hub_send`/`hub_poll` — for claude.ai and MCP clients.
- **REST** — `/chat/send` — simple POST interface (nginx basic auth).

### File Storage (`files_*`)

Read/write/list/append/search files under `/storage/` with path traversal
protection.

- **`files_read`**, **`files_write`**, **`files_list`**, **`files_append`**,
  **`files_search`**

### GitHub Integration

- **`github_read_file`** — Fetch file content from GitHub repos via API.
- **Webhook** — `/webhooks/github` — auto-pull local clones on push events
  (HMAC-SHA256 verification).

### Connectors (`connector_*`)

Federated search across registered data sources:
- **`connector_register`** — Register an artifact_store or filesystem connector.
- **`connector_index`** — Trigger indexing.
- **`query_federated`** — Search across all connectors with merged, ranked results.

---

## Architecture

```
Chat claude.ai ──┐
Codex ───────────┼──► claude-hub (MCP gateway) ──┬── Main Claude (persistent)
Gemini ──────────┘    :8420                       │
                     ├── work-graph service ───── 127.0.0.1:8421
                     ├── PostgreSQL (claude_hub) ─ 127.0.0.1:5432
                     ├── GitHub API
                     └── /storage/ (file I/O)
```

**API Gateway + BFF pattern**: claude-hub terminates auth at the public
boundary, forwards to internal subservices over localhost HTTP. Internal
services bind to `127.0.0.1` only — no nginx, no SSL between services.
Schema-isolated shared database (`claude_hub`).

**MCP surface**: All tool endpoints become MCP tools automatically via
[fastapi-mcp](https://github.com/daohoangson/fastapi-mcp). Two transports:
Streamable HTTP (`/mcp`) and SSE (`/mcp-sse`).

**Session model**: One persistent Claude Code backend per conversation,
communicating via stream-json stdin/stdout. Background reader task prevents
pipe buffer overflow. Idle processes reaped after 30 minutes.

---

## Running

### Configuration (environment)

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_HUB_CLAUDE_BINARY` | `claude` | Path to the `claude` CLI binary |
| `CLAUDE_HUB_PROJECT_DIR` | `~/claude-hub` | Project root for sessions, workspaces |
| `CLAUDE_HUB_SOURCE_DIR` | `~/projects/claude-hub` | Source tree for docs served by the hub |
| `CLAUDE_HUB_PG_DSN` | _(none)_ | PostgreSQL DSN (required for artifacts, connectors, scheduler, notifications, conversations) |
| `CLAUDE_HUB_JWT_SECRET` | _(none)_ | Enables OAuth 2.1 when set |
| `HUB_BASE_URL` | `http://localhost:8420` | Public base URL for OAuth metadata |
| `HUB_TERMINAL_USER` | `admin` | TOTP user for terminal/notifications |
| `GITHUB_WEBHOOK_SECRET` | _(none)_ | HMAC secret for GitHub webhooks |
| `WORK_GRAPH_URL` | `http://127.0.0.1:8421` | Work-graph service URL |

### Install

```bash
cd ~/projects/claude-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Start

```bash
source .venv/bin/activate
uvicorn claude_hub.server:app --host 127.0.0.1 --port 8420
```

### Test

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

The suite runs keyless — tests use mocks and SQLite where possible. Observed
pass count: **638 tests passed**.

---

## Caveats

- **Single-user design.** No multi-tenancy, no per-user isolation, no rate
  limiting between clients.
- **Single-operator security model.** OAuth 2.1 and TOTP protect the public
  surface, but internal trust is assumed once authenticated.
- **PostgreSQL required for most features.** Without `CLAUDE_HUB_PG_DSN`, only
  hub_*, files_*, and GitHub tools function.
- **Work-graph is a separate service.** Must be deployed independently (not in
  this repo). claude-hub forwards calls to it but does not ship its code.
- **Deployment specifics reduced, not eliminated.** Host-specific
  configuration (nginx, secrets, machine identifiers, ops runbooks) lives in
  the private deployment and is not in this tree. Reference systemd units
  ship in `scripts/services/`; storage paths and URLs are environment-driven
  (`HUB_BASE_URL`, `ARTIFACT_BACKUP_DIR`, `CLAUDE_HUB_PG_DSN`, ...). The
  private process archive (design reviews, session transcripts) is excluded.
- **No horizontal scaling.** Single-process FastAPI with in-memory state
  (routing table, pending responses). Restart drops pending messages.
