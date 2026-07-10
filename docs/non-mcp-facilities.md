# Non-MCP Facility Reference

Last audited: 2026-07-09. Written by GPT-5.5 (Codex) from the source;
verified against the source by Claude the same day (file existence,
commands, flags, and sampled behavioral claims).

This document describes callable or operational facilities in this repo that
are not part of the claude-hub network MCP tool manifest documented in
`docs/mcp-tools.md`.

Some entries below still use the MCP protocol locally. Those are separate
stdio MCP servers intended to be launched by a local harness. They are not
tools exposed by the `claude-hub` service at `/mcp`.

## Quick Inventory

| Facility | Entry Point | Purpose | Status |
| --- | --- | --- | --- |
| Multi-model review CLI | `python3 -m claude_hub.review_cli` | Dispatch model reviews, synthesize results, write review files. | Active, intentionally not HTTP/MCP. |
| Window continuity CLI | `python3 -m claude_hub.continuity` | Manage, load, finalize, ingest, and search window files. | Active, hook/CLI based. |
| Local Codex stdio MCP | `python3 -m claude_hub.codex_mcp` | Expose Codex chat to a local harness. | Local MCP server, not claude-hub network MCP. |
| Local Gemini stdio MCP | `python3 -m claude_hub.gemini_mcp` | Expose Gemini chat to a local harness. | Local MCP server, not claude-hub network MCP. |
| Web chat | `/chat`, `/chat/send`, `/ws/chat` | Browser chat against persistent Claude Code processes. | HTTP/WebSocket surface. |
| Group chat UI and API | `/group`, `/api/conversations/*`, `/ws/group/{id}` | Browser multi-participant conversation UI. | HTTP/WebSocket surface. |
| Notifications UI | `/notifications/*` | View and mark notifications. | TOTP-protected web surface. |
| Terminal UI | `/terminal/*` | Browser terminal page/session gate. | TOTP-protected web surface. |
| OAuth 2.1 endpoints | `/.well-known/*`, `/register`, `/authorize`, `/token` | Client registration and authorization flow for MCP clients. | Infrastructure HTTP surface. |
| Work-graph web UI | `/work-graph`, `/work-graph/{node_id}` | Read-only browser view of work graph state. | HTTP facade over local work-graph service. |
| GitHub webhook | `/webhooks/github` | Pull mirrored repos on GitHub push events. | HMAC-protected HTTP endpoint. |
| Health/debug endpoints | `/health`, `/debug/*`, OpenAPI docs | Operational introspection. | HTTP-only, excluded from MCP. |
| Maintenance scripts | `scripts/*` | Credentials, local tokens, repo mirroring, migrations. | Operational scripts. |
| Background tasks | server lifespan tasks | Embedding retry loop, scheduler, cleanup, migrations. | Internal service behavior. |
| Library-only helpers | `process_launcher.py`, `knowledge_log.py`, `permissions.py` | Reusable or experimental support code. | Not exposed through service routes. |

## Multi-Model Review CLI

Source: `src/claude_hub/review_cli.py`, `src/claude_hub/review_engine.py`,
`src/claude_hub/review_models.py`, `config/review_models.yaml`.

The review system dispatches review jobs to configured model CLIs, stores raw
outputs in Postgres, synthesizes them, stores review artifacts, and writes a
Markdown report. It deliberately bypasses HTTP and MCP to avoid long-running
tool-call timeouts and to keep the flow local and blocking.

Common commands:

```bash
python3 -m claude_hub.review_cli --prompt "Review for correctness"
python3 -m claude_hub.review_cli --files src/foo.py --prompt "Security review"
python3 -m claude_hub.review_cli --intent-ref docs/design/spec.md --models claude gemini
python3 -m claude_hub.review_cli --output docs/design/reviews/my-review.md --prompt "Review"
python3 -m claude_hub.review_cli get <job-id>
```

Main inputs:

- `--files`: file paths to review. If omitted and no content/artifact is given,
  the CLI auto-detects changed files with `git diff`.
- `--content`: raw content to review instead of files.
- `--artifact-id`: review an existing artifact by UUID.
- `--prompt`: review instructions. Required for new reviews.
- `--intent` or `--intent-ref`: what the reviewed work is supposed to do.
- `--context-files`: extra files reviewers should read.
- `--models`: restrict the model set.
- `--no-clean-room`, `--exclude-paths`, `--include-paths`: opinion-isolation
  controls.
- `--review-type`: category used for reviewer quality grading.
- `--output`: target Markdown file.

Operational dependencies:

- `CLAUDE_HUB_PG_DSN` must be set.
- The model registry must exist at `config/review_models.yaml`.
- Configured model CLIs must be installed and authenticated.

## Window Continuity CLI

Source: `src/claude_hub/continuity.py`,
`src/claude_hub/continuity_ingest.py`, `src/claude_hub/continuity_cli.py`.

The continuity system manages Markdown window files linked by YAML frontmatter.
It is designed for hooks and local scripts, not service MCP tools.

Window directory resolution:

- Preferred: `~/roles/{CURRENT_ROLE}/windows/` when `CURRENT_ROLE` is set and
  the directory exists.
- Fallback: `{project}/thoughts/windows/{harness}/`, where project is
  `CLAUDE_PROJECT_DIR` or the current working directory.

Commands:

| Command | Purpose | Key Options |
| --- | --- | --- |
| `load-chain <path>` | Print a parent chain of window files. | `--depth`, `--selective`, `--full-depth`. |
| `find-latest` | Find the latest window file. | `--session-id`, `--harness`. |
| `finalize <path>` | Set `finalized: true` in a window file. | None. |
| `ingest --file <path>` | Ingest one window into the artifact store. | Requires Postgres and Gemini embedding config if embeddings are enabled. |
| `ingest-all` | Bulk ingest all windows for a harness. | `--harness`. |
| `search --topic <text>` | Semantic search across ingested window artifacts. | `--limit`, `--format json|brief`. |

The ingest/search commands require `CLAUDE_HUB_PG_DSN`; they use the artifact
store and embedding configuration. Basic window-chain commands are file-only.

## Local Stdio MCP Adapters

These modules expose Codex and Gemini as local stdio MCP servers. They are
registered with a local harness such as Claude Code, not with the claude-hub
network MCP service.

### Codex Adapter

Source: `src/claude_hub/codex_mcp.py`, `src/claude_hub/codex_chat.py`.

Registration example:

```bash
claude mcp add codex -s user -- \
  /home/claude/projects/claude-hub/venv/bin/python \
  -m claude_hub.codex_mcp
```

Local tools:

| Tool | Purpose | Key Inputs |
| --- | --- | --- |
| `codex_send` | Send a prompt to a named persistent Codex conversation. | `prompt`, optional `session_name`, `model`, `reset`, `thread_id`. |
| `codex_list_recent` | List recent Codex sessions from `~/.codex/sessions`. | Optional `cwd`, `limit`. |
| `codex_list_sessions` | List active sessions held by the stdio MCP process. | None. |
| `codex_reset` | Drop one named in-memory Codex conversation. | Optional `session_name`. |

The adapter keeps in-memory `CodexChat` objects for the lifetime of the local
MCP subprocess. Codex thread IDs can be attached explicitly for resume.

### Gemini Adapter

Source: `src/claude_hub/gemini_mcp.py`, `src/claude_hub/gemini_chat.py`.

Registration example:

```bash
claude mcp add gemini -s user -- \
  /home/claude/projects/claude-hub/venv/bin/python \
  -m claude_hub.gemini_mcp
```

Local tools:

| Tool | Purpose | Key Inputs |
| --- | --- | --- |
| `gemini_send` | Send a prompt to a named persistent Gemini conversation. | `prompt`, optional `session_name`, `model`, `reset`, `session_id`. |
| `gemini_list_recent` | List recent Gemini sessions from `~/.gemini/tmp`. | Optional `cwd`, `limit`. |
| `gemini_list_sessions` | List active sessions held by the stdio MCP process. | None. |
| `gemini_reset` | Drop one named in-memory Gemini conversation. | Optional `session_name`. |

The adapter maps `cwd` through `~/.gemini/projects.json` when filtering recent
sessions. Gemini session IDs can be attached explicitly for resume.

## HTTP and WebSocket Surfaces

These routes are mounted on the same FastAPI service as the MCP endpoint, but
they are not intended as MCP tools.

### OAuth and MCP Auth Support

| Route | Purpose |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | Protected resource metadata for OAuth-aware MCP clients. |
| `GET /.well-known/oauth-authorization-server` | Authorization-server metadata. |
| `POST /register` | Dynamic client registration. |
| `GET /authorize` | Consent page for OAuth authorization-code flow. |
| `POST /authorize/consent` | Consent submission and authorization-code issuance. |
| `POST /token` | PKCE verification and bearer-token issuance. |

These routes support MCP authentication but are not themselves MCP tools.

### Dashboard, Notifications, and Terminal

| Route | Purpose | Protection |
| --- | --- | --- |
| `GET /` | Serve dashboard/PWA landing page. | Proxy/web access controls. |
| `GET /notifications/view` | Notification viewer page. | TOTP session. |
| `GET/POST /notifications/verify` | TOTP verification for notifications. | Attempt-limited TOTP. |
| `POST /notifications/logout` | Clear notification session. | TOTP session cookie. |
| `GET /notifications/api/list` | List notifications for the web UI. | TOTP session. |
| `POST /notifications/api/mark-read` | Mark a notification read. | TOTP session. |
| `GET /terminal` | Terminal entry page. | TOTP session. |
| `GET/POST /terminal/verify` | TOTP verification for terminal. | Attempt-limited TOTP. |
| `GET/POST /terminal/setup` | TOTP enrollment. | First-time setup flow. |
| `POST /terminal/logout` | Clear terminal session. | TOTP session cookie. |
| `HEAD /terminal/ping` | Check whether the terminal session is still valid. | TOTP session. |

The `notify` write path is an MCP tool; the web routes above are the human
view and management surface.

### Web Chat

| Route | Purpose |
| --- | --- |
| `GET /chat` | Serve browser chat UI. |
| `POST /chat/verify` | Lightweight verification endpoint for the browser UI. |
| `POST /chat/send` | Send a non-streaming message to Main Claude. Requires bearer auth. |
| `WS /ws/chat` | Streaming browser chat against a persistent Claude Code process. |

`/ws/chat` accepts JSON messages such as
`{"type":"message","text":"...","chat_id":"..."}` and streams text/status/result
events back. On disconnect, chat history is appended under
`thoughts/chat-history/`.

### Group Chat Web UI

| Route | Purpose |
| --- | --- |
| `GET /group` | Serve multi-participant group chat UI. |
| `GET /api/conversations` | List conversations. |
| `POST /api/conversations` | Create a conversation. |
| `DELETE /api/conversations/{conversation_id}` | Stop and clean up a conversation. |
| `GET /api/conversations/{conversation_id}/messages` | Read persisted messages. |
| `POST /api/conversations/{conversation_id}/add_claude` | Add a Claude process participant. |
| `POST /api/conversations/{conversation_id}/add_codex` | Add a Codex CLI participant. Currently leaks into MCP manifest. |
| `POST /api/conversations/{conversation_id}/add_gemini` | Add a Gemini CLI participant. Currently leaks into MCP manifest. |
| `WS /ws/group/{conversation_id}` | Browser group chat stream. |

The group-chat web API uses `MessageRouter` and `ChatProcessManager` for Claude
participants, and `CodexChat`/`GeminiChat` for CLI participants.

### Work-Graph Web UI

| Route | Purpose |
| --- | --- |
| `GET /work-graph` | Read-only roots overview. |
| `GET /work-graph/{node_id}` | Read-only node view with provenance path, children, and edges. |

These routes forward to the local work-graph service through the same
`_forward_to_wg()` helper used by the `wg_*` MCP tools, but they render HTML
templates for browser use.

### GitHub Webhook

| Route | Purpose |
| --- | --- |
| `POST /webhooks/github` | Verify GitHub HMAC signature and handle push events. |

On push events, the handler looks for `/home/claude/repos/{repo}` and runs
`git pull --ff-only` if the local clone exists. The shared secret comes from
`GITHUB_WEBHOOK_SECRET`.

### Health, Debug, and OpenAPI

| Route | Purpose |
| --- | --- |
| `GET /health` | Basic health and OAuth-enabled status. |
| `GET /debug/headers` | Header inspection. |
| `GET /debug/routes` | Route inspection. |
| `GET /debug/sessions` | Session manager state. |
| `GET /debug/pending` | Pending hub responses. |
| `GET /debug/memory` | Memory/process/task diagnostics. |
| `GET /openapi.json`, `/docs`, `/redoc` | FastAPI-generated API documentation. |

These are excluded from MCP.

## Maintenance Scripts

| Script | Purpose | Inputs and Notes |
| --- | --- | --- |
| `scripts/mint_local_token.py` | Mint a long-lived bearer token for headless local clients. | Reads `CLAUDE_HUB_JWT_SECRET` from env or `/etc/claude-hub/claude-hub.env`; options: `--client-id`, `--hours`, `--scope`. |
| `scripts/generate_credentials.py` | Generate random OAuth/JWT secrets. | Prints `CLAUDE_HUB_CLIENT_ID`, `CLAUDE_HUB_CLIENT_SECRET`, and `CLAUDE_HUB_JWT_SECRET`. |
| `scripts/github-mirror-sync.sh` | Mirror GitHub repos to `/home/claude/repos` and add webhooks. | Requires authenticated `gh`; uses `GITHUB_WEBHOOK_SECRET`; designed for systemd timer use. |
| `scripts/migrate_sqlite_to_postgres.py` | One-time migration from older SQLite stores to Postgres. | Migrates notifications, OAuth, TOTP, conversations, scheduler, and observations. |

## Systemd Units and Timers

| Unit | Purpose |
| --- | --- |
| `scripts/services/claude-hub.service` | Runs uvicorn for `claude_hub.server:app` on `127.0.0.1:8420` with `/etc/claude-hub/claude-hub.env`. |
| `scripts/services/github-mirror.service` | Runs `scripts/github-mirror-sync.sh` as a one-shot service. |
| `scripts/services/github-mirror.timer` | Runs the GitHub mirror service hourly with a randomized delay. |

The main service starts the FastAPI app, runs migrations, initializes stores,
loads active connectors, configures embeddings when possible, and starts
background tasks.

## Background Internal Facilities

These facilities run inside the service process or are initialized by server
startup. They are not direct user-facing routes.

| Facility | Source | Purpose |
| --- | --- | --- |
| Postgres migrations | `database.run_migrations()` from server lifespan | Applies unapplied SQL files from `migrations/` at startup. |
| Embedding retry loop | `embedding.embedding_retry_loop()` | Retries pending/failed artifact embeddings every 60 seconds when Gemini embedding API is configured. |
| Scheduler thread | `scheduler.Scheduler` | Executes scheduled wake-ups and sends prompts to sessions. |
| Periodic cleanup task | `_periodic_cleanup()` in `server.py` | Evicts stale pending responses, reaps idle chat processes, and trims stale route counters. |
| Startup conversation recovery | `MessageRouter.startup_recovery()` | Marks stale active conversations as interrupted after crashes. |
| Connector loading | server lifespan | Loads active connectors from Postgres into an in-memory registry. |

## Library-Only or Experimental Facilities

These modules have tests or useful behavior, but they are not currently exposed
as service MCP tools.

| Module | Purpose | Notes |
| --- | --- | --- |
| `process_launcher.py` | Generalized launcher for Claude, Codex, and Gemini CLIs. | Supports model profiles, command construction, output parsing, and optional `sudo -u` wrapping. Described as a foundation for future process spawning. |
| `knowledge_log.py` | Append-only JSONL log for observations, decisions, discoveries, errors, and checkpoints. | Provides validation, file-locked appends, filtered reads, tail, rotation, and count. No current service route. |
| `permissions.py` | Workspace permission checker. | Docstring states it is not wired into server file writes; currently a convention for cooperating agents. |
| `migrations/006_finance.sql` | Finance/SnapTrade schema. | Creates finance account, holdings, balances, transaction, email event, and sync-run tables. No Python service surface found in this repo. |

