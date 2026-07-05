# Claude-Hub

Personal AI infrastructure backbone — MCP server, artifact store, multi-model review engine, and session continuity system.

## Codebase

```
src/claude_hub/
├── server.py            # FastAPI app, MCP endpoint (:8420)
├── session.py           # Session management, Claude subprocess spawning
├── chat_process.py      # Chat participant subprocess management
├── artifact_store.py    # Semantic artifact CRUD (pgvector)
├── review_engine.py     # Multi-model review dispatch
├── review_cli.py        # CLI: python3 -m claude_hub.review_cli
├── continuity.py        # Window file management
├── embedding.py         # Gemini embedding pipeline
├── database.py          # Postgres connection pool, migrations
├── message_router.py    # Conversation routing
├── conversation_store.py # Multi-participant message history
├── observations.py      # Topic-triggered retrieval
├── notifications.py     # Dashboard notifications
├── scheduler.py         # Cron-like scheduling (wake_at, wake_every)
└── workspace.py         # Delegated agent workspaces
```

## Services

- **MCP server**: FastAPI on port 8420, relayed via nginx. OAuth 2.1 + TOTP auth.
- **Nightly check**: Automated health check via systemd timer (5am UTC).

## Running locally

```bash
cd ~/projects/claude-hub
source venv/bin/activate
uvicorn claude_hub.server:app --host 127.0.0.1 --port 8420
```

## Database

PostgreSQL `claude_hub` on localhost:5432. Key tables: artifacts, artifact_embeddings, reviews, review_syntheses, patterns, connector_index.

## Key References

- `CONTEXT.md` — Full project context, architecture, changelog
- `docs/shared-context.md` — Shared state model, infrastructure conventions
- `docs/architecture.md` — Architecture design
- `docs/design/ontology.md` — System ontology (role, project, service, agent, task, resource, session)
- `docs/design/vision-personal-ai-infrastructure.md` — Vision document
- `config/review_models.yaml` — Model registry for multi-model reviews
