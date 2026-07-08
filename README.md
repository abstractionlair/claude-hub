# claude-hub

Personal AI infrastructure backbone — a persistent Claude Code backend plus the memory, continuity, review, and orchestration layers around it.

Chat sessions on claude.ai are stateless, single-model, and forget on restart. Claude-hub, via MCP, gives them access to a persistent, tool-equipped backend with durable memory, continuity, and multi-model review. The initial, simple idea was to allow Chat Claudes to trade messages with a Claude
in a Claude Code session running on the server. No specialize tools would be needed; they could just talk. My thinking was that rather than a claude.ai conversation producing a runnable artifact within the chat app, it could spin up a full web app hosted on a permanent server. It grew from
there.

---

## Headline features

### Persistent Claude Code backend (`hub_*`)

MCP tools `hub_init`, `hub_send`, `hub_poll`, and `hub_status` transport messages between Chat Claudes and a long-running Claude Code process that 
has the facilities of a well-equipped VPS. The session manager resumes existing sessions first, tracks token usage, and triggers a graceful restart when context is critical. 

*Why:* Your chat agent gets a stateful, permanent backend.

### Work Graph (`wg_*`)

A provenance-by-construction graph of work-in-progress. `wg_capture` creates a node; parent-child edges are automatic, and cross-cutting `blocks`/`related` edges are explicit via `wg_add_dependency`. `wg_brief` returns a token-free, read-only prose brief so a fresh agent can orient itself in seconds. `wg_query`, `wg_search`, `wg_goto`, and `wg_update` provide structured navigation and lifecycle updates.

*Why:* Context is bounded; a fresh agent can pick up exactly what is ready, blocked, deferred, or recent without reading the entire project history.

### Multi-model review engine

A review engine that dispatches a target to Claude, GPT-5/Codex, and Gemini, synthesizes their findings into a consensus report, surfaces contradictions, runs peer-reconciliation rounds, and grades each reviewer on a failure-mode taxonomy (`EXCELLENT`, `ADEQUATE`, `INADEQUATE`, `HARMFUL`; failure modes include `false_positive`, `false_negative`, `wrong_severity`, `hallucinated_evidence`, `credulous`, `shallow`). The model registry is configured in `config/review_models.yaml`.

*Why:* Different models catch different things; a portfolio review plus explicit grading produces higher-confidence feedback than a single pass.

### Artifact store (`artifact_*`)

Semantic knowledge storage with `pgvector` embeddings, confidence levels (`HIGH`, `MEDIUM`, `LOW`, `SUPERSEDED`), Bayesian utility tracking from feedback, and age-based decay. `artifact_search` reranks by embedding similarity plus confidence, usage-utility, and recency; `artifact_retirement_candidates` finds low-utility artifacts for cleanup.

*Why:* Knowledge rots if left alone; confidence, utility, and age decay keep the working memory relevant without manual curation.

### Window-file continuity

Survives context-window exhaustion by narrating state, not summarizing it. When a session approaches its limit, a forked narrator writes a timestamped window file with YAML frontmatter, links it to a parent window, and resumes a fresh session that loads the chain. `continuity_ingest` feeds window content into the artifact store.

*Why:* A long project becomes a chain of fresh sessions instead of one compressed summary; the narrator captures the delta, not a lossy recap.

### Multi-model group chat (`group_*`)

A shared room for humans, Claude, Codex, and Gemini. REST endpoints and WebSocket `/ws/group/{conversation_id}` add participants, stream messages, and persist history to Postgres. MCP tools `group_join`, `group_send`, `group_poll`, and `group_leave` let programmatic participants join the same room.

*Why:* Models with different strengths can collaborate in one conversation instead of the operator copying context between separate chat windows.

### Supporting infrastructure

Fractal delegation (isolated workspaces, handoff documents, cron-like wake-ups via `schedule_*`), OAuth 2.1 + MCP gateway, connectors for federated search across artifact and filesystem sources, and `files_*`, GitHub, and notification tools.

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

## Role system

A role is a harness-neutral job description, not an identity or persona. `docs/design/ontology.md` defines current roles such as `workbench`, `sysadmin`, and `mcp-server`. The model is a parameter of each conversation, so a role can swap between Claude Code, Codex, or Gemini while keeping the same responsibilities, scope, and accumulated context. Runtime code sets `CURRENT_ROLE` and routes window files to `~/roles/$ROLE/windows/` or the project-local `thoughts/windows/` fallback.

---

## Window-file continuity

Continuity is implemented in `src/claude_hub/continuity.py` and `continuity_ingest.py`:

- **Forked narrator.** A `claude --fork-session --print` invocation writes a window-file delta without consuming the main session's budget.
- **Linked window chain.** Each window file has YAML frontmatter with `parent` and `children` references; `load_window_chain` follows the chain chronologically.
- **Artifact ingest.** Window content is parsed and stored as artifacts so the semantic memory can answer "what did we decide about X?" across sessions.

The system is designed around the principle that window files are curated, persistent memory and session JSONL is the raw ground truth.

---

## Honest state

This is a production-deployed personal system (see `deploy.yaml` and `scripts/services/`). The Python source is roughly 18k lines, and the test suite collects 638 tests. The project is spec-driven and uses a multi-model review engine; the engine is currently invoked as a CLI (`python -m claude_hub.review_cli`) rather than an automated CI gate.

Known rough edges, tracked openly:

- **Continuity fork.** The session-ID remap after `claude --fork-session` can leave the `.current-<id>` pointer stale, so a fork may write to the wrong window or create a stray one. Every fork also reloads the full session context via `claude --resume --print`, which is heavy on long sessions. See `KNOWN_ISSUES.md` for the full diagnosis.
- **Gemini integration.** Group chat and review drive Gemini by shelling out to the standalone `gemini` CLI, which Google has since retired in favor of Antigravity. The Gemini seat therefore fails to spawn until the launcher is ported to Antigravity's binary and session model; Claude and GPT-5/Codex are unaffected.
- **Docs lag.** Some design docs still reference untracked `~/.claude` shell hooks and older ledger/append-log patterns that predate the artifact store and observation store.
- **Single-operator model.** Auth protects the public surface, but there is no multi-tenancy or per-user isolation.

---

## Where things live

| Area | Entry points |
|---|---|
| MCP gateway + tool routes | `src/claude_hub/server.py` |
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

---

*Acknowledgments: the "context is the scarce resource" framing is Tyler Cowen's.*
