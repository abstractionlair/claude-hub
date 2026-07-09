# claude-hub

Claude Hub started as an MCP service running on a VPS which would allow a Claude at claude.ai to chat with a Claude in Claude Code running on the VPS with permissions to do things like stand up web apps. It was inspired, in part, by an experience in a claude.ai chat where Claude did a great job creating a simple web app as an artifact which then failed to allow full functionality because of CORS errors. The initial idea was that this could be very simple --- just allowing the two Claudes to chat in natural language. Both the VPS and the MCP service grew more functionality over time. This repo covers the service.

---

## Things that really belong here

### MCP tools

#### Persistent Claude Code backend (`hub_*`)

MCP tools `hub_init`, `hub_send`, `hub_poll`, and `hub_status` transport messages between Chat Claudes and a long-running Claude Code process that
has the facilities of a well-equipped VPS. The session manager resumes existing sessions first, tracks token usage (self-reported context markers, not metered), and triggers a graceful restart when context is critical. This was the initial purpose of claude-hub but it ended up less used than I'd expected. Once I had the VPS running, Claude Code, Codex, Gemini (at the time) installed and authorized, along with all the tools, libraries, ... that I could want, just logging in there and
using Claude Code supplanted a lot of my use of the web chat interface.

*Why:* Your chat agent gets a stateful, permanent backend.

#### Artifact store (`artifact_*`)

Semantic knowledge storage with `pgvector` embeddings, confidence levels (`HIGH`, `MEDIUM`, `LOW`, `SUPERSEDED`), Bayesian utility tracking from feedback, and age-based decay. `artifact_search` reranks by embedding similarity plus confidence, usage-utility, and recency; `artifact_retirement_candidates` finds low-utility artifacts for cleanup.

*Why:* Knowledge rots if left alone; confidence, utility, and age decay keep the working memory relevant without manual curation.

#### Work Graph (`wg_*`)

A DAG of the work on my plate: things I have committed to deliver, things I might do, and things instrumentally required by the others --- not just work in progress. Its first job is keeping me oriented across many concurrent AI-assisted threads; models help maintain it and often execute from it. `wg_capture` creates a node; provenance parent-child edges are automatic, and cross-cutting `blocks`/`related` edges are explicit via `wg_add_dependency`. `wg_brief` returns a curated read-only prose brief so a fresh agent --- or I, coming back after a weekend --- can orient in seconds. `wg_query` (`overview`, `ready`, `recent`, `deferred`, `blocked`), `wg_search`, `wg_goto`, and `wg_update` cover navigation and lifecycle.

The graph itself lives in a separate internal service (see Architecture); the hub is its MCP gateway.

*Why:* AI-speed delegation multiplies open threads faster than human memory holds them; work that leaves my attention should not leave my awareness.

#### Multi-model group chat (`group_*`)

A shared room for humans, Claude, Codex, and Gemini. REST endpoints and WebSocket `/ws/group/{conversation_id}` add participants, stream messages, and persist history to Postgres. MCP tools `group_join`, `group_send`, `group_poll`, and `group_leave` let programmatic participants join the same room.

*Why:* Models with different strengths can collaborate in one conversation instead of the operator copying context between separate chat windows.

#### Supporting tools

Fractal delegation (isolated workspaces, handoff documents, cron-like wake-ups via `schedule_*`), `files_*` persistent storage, `github_read_file`, `notify`, and connectors for federated search across artifact and filesystem sources.

### Not exposed over MCP

- **OAuth 2.1 boundary.** Dynamic client registration, PKCE, consent, and Bearer-token issuance gate the MCP endpoint; TOTP gates the human web surfaces.
- **Web surfaces.** Browser chat (WebSocket streaming against the same persistent backend), the group-chat UI, a notifications viewer, a terminal page, and read-only work-graph views.
- **Background internals.** Startup migrations, an embedding retry loop, the wake-up scheduler, and periodic cleanup run inside the service process.

---

## Things that should have gone in a different project

These live in this repo because the VPS is where the work happened, but they serve the local development process rather than the network service. None of them are in the hub's MCP manifest.

### MCP, but local

#### Codex and Gemini stdio adapters

`python3 -m claude_hub.codex_mcp` and `gemini_mcp` expose persistent Codex and Gemini conversations (`codex_send`, `gemini_send`, session listing and reset) as stdio MCP servers. They speak the MCP protocol, but they register with a local harness such as Claude Code --- they are not tools of the claude-hub service.

### Not MCP

#### Multi-model review engine

A registry-driven review engine that dispatches a target to the configured reviewer models --- the registry is `config/review_models.yaml`, currently holding two Claude, two Gemini, and one GPT seat --- synthesizes their findings into a consensus report, surfaces contradictions, runs peer-reconciliation rounds, and grades each reviewer on a failure-mode taxonomy (`EXCELLENT`, `ADEQUATE`, `INADEQUATE`, `HARMFUL`; failure modes include `false_positive`, `false_negative`, `wrong_severity`, `hallucinated_evidence`, `credulous`, `shallow`). The roster is curated by those grades: open-weight models (GLM, DeepSeek) held seats early on and lost them after poor review grades. A separate OpenCode/OpenRouter dispatch layer keeps other models (Qwen, Kimi, MiniMax, GLM) callable when wanted. Reviews run as a local CLI (`python3 -m claude_hub.review_cli`), deliberately not an HTTP/MCP tool, to avoid tool-call timeouts on long jobs.

*Why:* Different models catch different things; a graded portfolio review produces higher-confidence feedback than a single pass --- and the grades decide who keeps a seat.

#### Window-file continuity

One Markdown file per context-window era, written as contemporaneous commentary rather than a retrospective summary. When a session approaches its context limit, a forked narrator (`claude --fork-session --print`) writes the window file without consuming the main session's budget; YAML frontmatter links each window to its parent and children (the chain is DAG-shaped to accommodate forks), and the next session loads the chain. Unlike built-in compaction, which carries only the latest summary forward, the whole chain is retained and --- via `continuity_ingest` into the artifact store --- semantically searchable, so "what did we decide about X?" is answerable across sessions. The design is a deliberate compromise between raw-log completeness and searchability: window files are curated, persistent memory; session JSONL remains the raw ground truth.

*Why:* A long project becomes a searchable chain of fresh sessions instead of one compressed summary.

#### Role system

A role is a harness-neutral job description, not an identity or persona. `docs/design/ontology.md` defines current roles such as `workbench`, `sysadmin`, and `mcp-server`. The model is a parameter of each conversation, so a role can swap between Claude Code, Codex, or Gemini while keeping the same responsibilities, scope, and accumulated context. Runtime code sets `CURRENT_ROLE` and routes window files to `~/roles/$ROLE/windows/` or the project-local `thoughts/windows/` fallback.

---

## Tool surface

The service exposes 50 MCP tools. [`docs/mcp-tools.md`](docs/mcp-tools.md) is the per-tool reference; [`docs/non-mcp-facilities.md`](docs/non-mcp-facilities.md) covers everything callable that is not in the MCP manifest --- the review and continuity CLIs, local stdio MCP adapters for Codex and Gemini, the web surfaces, maintenance scripts, and background tasks. Both documents were written by GPT-5.5 from the source and then verified claim-by-claim by Claude, including a set-diff of the documented tools against the live manifest.

---

## Architecture

```
Chat claude.ai ──┐
Codex ───────────┼──► claude-hub (MCP gateway) ──┬── Main Claude Code (persistent)
Gemini ──────────┘    :8420                      │
                     ├── work-graph service ───── 127.0.0.1:8421
                     ├── PostgreSQL (claude_hub) ─ 127.0.0.1:5432
                     ├── GitHub API
                     └── /storage/ (file I/O)
```

**API Gateway + BFF.** Claude-hub terminates auth at the public boundary and forwards to internal subservices over localhost HTTP. Internal services bind to `127.0.0.1` only; the gateway is the only public door. The database is a schema-isolated shared Postgres (`claude_hub`). The work-graph service at `127.0.0.1:8421` is the canonical reference internal subservice: it owns its own schema and is reached through a thin forwarder in `server.py`.

The MCP surface is exposed via Streamable HTTP (`/mcp`) and SSE (`/mcp-sse`), with Bearer-token auth when `CLAUDE_HUB_JWT_SECRET` is set.

---

## Status

This is a production-deployed personal system (see `deploy.yaml` and `scripts/services/`). The Python source is roughly 18k lines, and the test suite collects 679 tests. The project is spec-driven; the review engine described above gates its own development, invoked as a CLI rather than an automated CI gate.

Known rough edges are tracked in [`ISSUES.md`](ISSUES.md); the continuity/window system additionally keeps a detailed running log in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

---

## Where things live

| Area | Entry points |
|---|---|
| MCP gateway + tool routes | `src/claude_hub/server.py` |
| MCP tool reference | `docs/mcp-tools.md` |
| Non-MCP facilities reference | `docs/non-mcp-facilities.md` |
| Known issues | `ISSUES.md`, `KNOWN_ISSUES.md` |
| Persistent Claude backend | `src/claude_hub/session.py`, `chat_process.py`, `routing.py` |
| Work graph integration | `src/claude_hub/work_graph_models.py`, forwarders in `server.py`; service runs separately at `127.0.0.1:8421` |
| Multi-model review | `src/claude_hub/review_engine.py`, `review_cli.py`, `review_models.py`, `config/review_models.yaml` |
| Artifact store | `src/claude_hub/artifact_store.py`, `artifact_models.py`, `tests/test_artifact_store.py` |
| Continuity | `src/claude_hub/continuity.py`, `continuity_cli.py`, `continuity_ingest.py`, `KNOWN_ISSUES.md` |
| Group chat | `src/claude_hub/conversation.py`, `conversation_store.py`, `message_router.py`, `codex_chat.py`, `gemini_chat.py` |
| Delegation / scheduling | `src/claude_hub/workspace.py`, `handoff.py`, `scheduler.py` |
| Auth | `src/claude_hub/auth.py`, `oauth_store.py`, `pkce.py`, `totp.py` |
| Connectors | `src/claude_hub/connectors/` |
| Files / GitHub / notifications | `src/claude_hub/storage.py`, `github_tools.py`, `notifications.py` |
| Database migrations | `migrations/` |
| Deployment references | `deploy.yaml`, `scripts/services/` |
| Design docs | `docs/` |

## Running locally

```bash
cd claude-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# PostgreSQL is required to run the server (not to run the tests).
# The server connects at startup and will not start without a reachable
# database; it applies migrations/*.sql itself on first start.
# Requires the pgvector extension to be installed.
createdb claude_hub
export CLAUDE_HUB_PG_DSN="postgresql:///claude_hub"
export CLAUDE_HUB_PROJECT_DIR="$PWD"   # where migrations/ and runtime state live

# Start the server on localhost
uvicorn claude_hub.server:app --host 127.0.0.1 --port 8420

# Run tests (no Postgres needed)
pytest tests/ -v
```
