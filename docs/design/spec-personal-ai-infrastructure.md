# Spec: Personal AI Infrastructure

*Draft 12 — March 22, 2026*
*Derives from: requirements-personal-ai-infrastructure.md (Draft 13)*

**Changes from Draft 11:** Updated for PostgreSQL migration (removed SQLite coexistence section), expanded window file frontmatter to match ontology, marked Phases 1-5 as implemented, updated paths from thoughts/ to role-scoped ~/roles/.

**Changes from Draft 10:** Addressed high and medium severity findings from 7-model R5 Knowledge Quality review. High: (1) Specified utility score aggregation formula — Bayesian average `(count_useful + 1) / (count_total + 2)`. (2) Enriched `review_grades` table — added `review_type TEXT`, `job_id UUID` FK; changed `useful BOOLEAN` to `grade TEXT` with 4-level scale (EXCELLENT/ADEQUATE/INADEQUATE/HARMFUL); updated grading prompt and `get_review_quality` helper. (3) Added `last_retrieved TIMESTAMPTZ` column to artifacts table; `artifact_search` updates it on returned results. (4) Fixed SQL alias reuse in scoring query — wrapped in CTE. (5) Added `content_version INT` to `artifact_feedback` for feedback versioning; `artifact_update` increments artifact version counter. Medium: (6) Fixed Draft 8 changelog — R5.5 uses `review_grades` table, not `artifact_feedback`. (7) Added age decay term to scoring formula: `age_boost = GREATEST(-0.1 * age_days / 365, -0.2)`. (8) Fixed R5.3 acceptance test vocabulary — replaced SUCCEEDED/FAILED with utility_score terminology.

**Changes from Draft 9:** Aligned "outcome" language to "usage-weighted" framing per vision Draft 11 reframing. Changed "outcomes" references in artifact_archive, artifact_export/import, and artifact_store module to "feedback." Updated Phase 6 dependency label from "outcomes" to "knowledge quality." Updated tool category label in summary. Updated derives-from pointer to requirements Draft 12. Changelog entries preserved as-is (historical records).

**Changes from Draft 8:** Rewrote R5 ("Knowledge Quality", was "Outcome Tracking"). Replaced human-initiated `artifact_rate`/`artifact_unrated` with agent-driven `artifact_feedback`, `artifact_set_confidence`, `artifact_retirement_candidates`. Schema: `artifact_feedback` table replaces `artifact_outcomes`; `confidence` and `utility_score` columns on artifacts. Search scoring uses utility + confidence instead of outcome ratings. Phase 4 renamed and tasks rewritten. R5.5 (review quality grading) now uses `review_grades` table. Added "Review Quality Grading" subsection.

**Changes from Draft 7:** Removed `mechanical_log` Postgres table. Replaced 4 MCP tools (`context_summarize`, `context_load`, `log_operation`, `ingest_ledgers`) with window-file architecture. Revised all 4 hook integrations to be file-based (no HTTP calls to FastAPI). Added window file specification (Section 2.3). Added Phase 3.5 (Context Load — Semantic Retrieval). Updated `continuity.py` module. Corrected MCP tool count to 23 (Draft 7 said 30 but had already removed 3 review tools; this draft removes 4 more continuity tools).

**Changes from Draft 6:** Removed MCP tool endpoints (`review_dispatch`, `review_status`, `review_get`) — reviews now use direct CLI (`python3 -m claude_hub.review_cli`). Removed `files_accessed` column (model-forward: audit trail lives in review prose). Updated default exclude paths to reflect `docs/design/` migration.

**Changes from Draft 4:** Addressed 6-model review of agentic review changes (Gemini, GPT-5.4, GPT-5.3 Codex, GLM-5, Kimi K2.5, MiniMax M2.5). Schema: added `invocation_mode TEXT NOT NULL DEFAULT 'agentic'` to reviews table; added `files_accessed TEXT[]` to reviews table for audit trail. API: `review_dispatch` now accepts `intent_ref` (file path or artifact ID) in addition to `intent` (text); added `context_files` parameter; `max_input_chars` exceeded = reject with error (not truncate). Narrowed default `exclude_paths` from `["thoughts/", ".claude/", "CLAUDE.md"]` to `["thoughts/ledgers/", "thoughts/history/", ".claude/", "CLAUDE.md"]` so reviewers can access specs/requirements under `thoughts/shared/` (note: design docs subsequently moved to `docs/design/`). Added `include_paths` override for explicit allowlisting. Added prompt template to Section 6.2. Synthesis output now includes per-review invocation mode. Fixed SessionStart/artifact_unrated inconsistency (outcome prompting is manual only). Synthesis model configurable via `synthesis_model` in review_models.yaml.

**Changes from Draft 3:** Agentic review model. Reviewers are agents with codebase access, not text processors receiving content bundles. Review model registry redesigned: `invoke` templates now launch models as agents with a task prompt (intent + file list + boundaries), not with bundled content files. Added `mode: agentic | bundled` to model configs. `review_dispatch` tool now accepts `intent` and `exclude_paths` parameters. Clean-room redefined as opinion isolation (soft boundary via prompt instructions), not information deprivation. Added `UNIQUE(job_id)` to `review_syntheses`. Added sensitive artifact check to `review_dispatch`. Synthesis prompt written to temp file (not CLI arg). Added `encoding="utf-8"` to temp file creation. `max_input_chars` enforced per model.

**Changes from Draft 2:** Addressed review findings from 6-model review of Draft 2 (Claude, Gemini, GPT-5.4, DeepSeek R1, GLM-5, Kimi K2.5).

*Schema:* Added `job_id UUID NOT NULL` to `reviews` and `review_syntheses` (groups reviews per dispatch run). Made `review_syntheses.artifact_id` nullable for raw content reviews. Added `implementation_artifact_id` to `workflow_projects`. Added `embedding vector(768)` to `patterns` for similarity detection. Added unique partial index `idx_artifacts_dedup` on `(content_hash, COALESCE(source_ref, ''))` for dedup enforcement. Added indexes on `job_id` columns.

*API:* Fixed tool count to 30 (was 31 — miscounted). Dedup now enforced by unique partial index (no application-level race). Increased outcome boost values (0.2/0.1, was 0.1/0.05). Added sensitive artifact behavior (skip embedding, exclude from review dispatch). Fixed `review_dispatch` job_id semantics (new UUID per run, not artifact_id). Fixed `log_operation` latency claim (p95 < 50ms, was sub-10ms). Fixed `artifact_unrated` INTERVAL syntax (`make_interval`). Added outcome reasoning search note. Fixed `workflow_advance` non-sequential transition description. Added Section 4.8 Internal HTTP Endpoints.

*Review Model Registry:* Fixed shell injection — invoke templates now use array-style `subprocess.run()` invocation (no shell). Both artifact content and prompt written to temp files. Fixed Claude clean-room flag (`--profile review`, was `--no-profile`).

*Hooks:* Fixed PostToolUse registration to include `matcher: {}`. Fixed PreCompact output schema (`systemMessage`, was `message`). Gated `/workflow_active_items` call for pre-Phase-7 compatibility. Fixed SessionStart input field (`source`, was `type`). Removed automatic outcome rating prompting from SessionStart (use `artifact_unrated` tool manually).

*Embedding:* Fixed vector serialization — removed `str(embedding)` wrapping (pgvector handles it via `register_vector()`). Added `connector_index` embedding sweep to retry loop. Startup recovery now also sweeps connector_index.

*Connectors:* Added startup reload paragraph (connector registry reloads from DB on FastAPI startup). Fixed filesystem connector root_path to absolute path.

*Open Decisions:* Updated asyncpg vs psycopg3 (pgvector now supports asyncpg natively). Resolved Postgres connection string management. Added content hash format specification.

**Changes from Draft 1→2:** Addressed 24 review findings from 6-model review (Gemini, GPT-5.4, GPT-5.3 Codex, GLM-5, Kimi K2.5, MiniMax M2.5).

*Schema:* Fixed pgcrypto extension (was uuid-ossp). connector_index stores embeddings directly (not FK to artifact_embeddings). reviews.artifact_id now nullable for raw content reviews. Added `sensitive BOOLEAN` to artifacts. Added TABLESPACE to artifact_embeddings, artifact_outcomes, reviews, review_syntheses. Added UNIQUE(artifact_id) on artifact_embeddings. Added `ae.embedding IS NOT NULL` guard to search queries.

*API:* Added artifact_update, artifact_update_metadata, artifact_import, workflow_item_create tools (31 total, up from 28). Fixed outcome JOIN with LATERAL subquery for multiple ratings. Added derives_from UUID validation. Scoped dedup to content_hash + source_ref (not hash alone).

*Hooks:* All hooks now route through FastAPI HTTP (no direct psql). PostToolUse uses curl to /log_operation. Stop hook uses curl to /log_unsummarized_count. PreCompact injects open threads + active work items (not just recent ops). SessionStart prompts for outcome ratings on unrated artifacts.

*Review:* Invoke templates write prompt to temp file (not inline). Synthesis model specified as Claude. Added stage templates for workflow gates.

*Connectors:* Added ConnectorError class with retriable flag. Added validate() method to BaseConnector for credential checking on registration.

*Infrastructure:* Embedding startup recovery sweep on FastAPI boot. HNSW ef_search = 64 documented. Removed pool singleton text (hooks are separate processes).

## Scope

This spec translates seven requirements into buildable components: data model, API surface, embedding pipeline, connector interface, hook integration, module architecture, and build order. It covers the full system from database schema through MCP tool signatures to phased implementation plan.

**What this spec covers:**
- Postgres + pgvector infrastructure on nexus
- Complete DDL for all tables
- Google Gemini embedding pipeline
- 24 MCP tools (organized by requirement)
- Connector abstract base class and registration
- Review model registry
- Hook integration points
- 9-phase build order with dependency graph (8 phases plus Phase 3.5 for semantic retrieval)
- Testing strategy

**What this spec defers:**
- Specific external connectors (email, spreadsheet, calendar) — each gets its own spec per R7
- Proactive context surfacing — architecture supports it, but no tooling in this phase
- Agent autonomy policies
- Cost management infrastructure beyond subscription awareness

---

## 1. Infrastructure

### 1.1 Postgres Setup

Install Postgres 16 and pgvector on nexus:

```bash
sudo apt install postgresql-16 postgresql-16-pgvector
sudo systemctl enable postgresql
```

Create the database and enable extensions:

```sql
CREATE DATABASE claude_hub;
\c claude_hub
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Create a dedicated database user:

```bash
sudo -u postgres createuser claude_hub_app
sudo -u postgres psql -c "ALTER USER claude_hub_app WITH PASSWORD '<generated>';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE claude_hub TO claude_hub_app;"
```

### 1.2 Data Location

Postgres data directory stays at the default location (`/var/lib/postgresql/16/main/`). A tablespace on the attached volume provides durable storage for artifact content:

```sql
CREATE TABLESPACE artifact_data LOCATION '/mnt/HC_Volume_104288266/data/postgres';
```

All artifact tables use this tablespace. System tables (pg_catalog, etc.) stay on the boot disk.

### 1.3 Connection Pooling

asyncpg connection pool within the FastAPI process. The 4GB RAM constraint limits pool size:

```python
pool = await asyncpg.create_pool(
    dsn=os.environ["CLAUDE_HUB_PG_DSN"],
    min_size=2,
    max_size=10,
    command_timeout=30,
)
```

The DSN is stored in an environment variable, not in code or config files. The systemd unit file sets it:

```ini
Environment=CLAUDE_HUB_PG_DSN=postgresql://claude_hub_app:<password>@localhost/claude_hub
```

Context continuity hooks (PostToolUse, Stop, PreCompact, SessionStart) operate on local files — no HTTP calls. Other hooks that need database access (e.g., workflow items after Phase 7) route through the FastAPI server (`curl http://localhost:8420/...`), using the server's connection pool rather than opening their own connections.

### 1.4 Migration Approach

Raw SQL migration files in `migrations/`, numbered sequentially:

```
migrations/
  001_initial_schema.sql
  002_add_patterns.sql
  ...
```

A lightweight migration runner in `database.py` tracks applied migrations in a `schema_migrations` table:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
```

On startup, the runner applies any unapplied migrations in order. This is simpler than Alembic for a single-developer system with straightforward schema evolution.

### 1.5 PostgreSQL Migration (Complete)

All stores (oauth, totp, conversation, scheduler, observations, notifications) have been migrated from SQLite to PostgreSQL via the claude_hub database. No SQLite databases remain in the system.

---

## 2. Data Model

### 2.1 Core Tables

```sql
-- Core artifact storage (R1.1)
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,  -- SHA-256 for dedup
    artifact_type TEXT NOT NULL, -- vision-doc, review, decision, session-summary, skill, hook, rule, etc.
    tags TEXT[],                 -- Postgres array
    source_ref TEXT,             -- Session ID or source identifier
    derives_from UUID[],        -- Parent artifact IDs — enables lineage DAG (R6.3)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sensitive BOOLEAN NOT NULL DEFAULT FALSE,  -- R GPT-5.4: local-processing-only
    archived BOOLEAN NOT NULL DEFAULT FALSE,  -- R1.6
    metadata JSONB NOT NULL DEFAULT '{}',     -- Mutable, extensible
    last_retrieved TIMESTAMPTZ               -- Updated by artifact_search on returned results (R5.4)
) TABLESPACE artifact_data;

-- Immutable version chain (R1.1 — updates create new versions)
CREATE TABLE artifact_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(artifact_id, version)
) TABLESPACE artifact_data;

-- Vector storage (R1.2)
CREATE TABLE artifact_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    embedding vector(768),  -- pgvector column, Gemini text-embedding-004 output
    model TEXT NOT NULL DEFAULT 'text-embedding-004',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'complete', 'failed')),
    error_message TEXT,     -- Last error for failed embeddings
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(artifact_id)    -- One embedding row per artifact
) TABLESPACE artifact_data;

-- Knowledge quality (R5)
CREATE TABLE artifact_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    useful BOOLEAN NOT NULL,             -- R5.1 — was this retrieval helpful?
    note TEXT,                           -- Brief context for the feedback
    agent_id TEXT NOT NULL DEFAULT 'main', -- Which agent provided this feedback
    content_version INT,                 -- Which artifact version this feedback applies to (R5.1)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Review quality grading (R5.5) — per-model signal, not per-artifact
CREATE TABLE review_grades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,                -- Which review run (matches reviews.job_id for traceability)
    model_name TEXT NOT NULL,            -- Which model was graded
    review_type TEXT NOT NULL,           -- e.g. 'code-review', 'design-review', 'security-review'
    grade TEXT NOT NULL                  -- EXCELLENT, ADEQUATE, INADEQUATE, HARMFUL
        CHECK (grade IN ('EXCELLENT', 'ADEQUATE', 'INADEQUATE', 'HARMFUL')),
    note TEXT,                           -- What made it good/bad
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Confidence is stored in artifact metadata (R5.2)
-- ALTER TABLE artifacts ADD COLUMN confidence TEXT DEFAULT 'MEDIUM'
--     CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW', 'SUPERSEDED'));
-- ALTER TABLE artifacts ADD COLUMN utility_score REAL DEFAULT 0.5;
-- (Applied via migration, shown here for reference)
```

### 2.2 Review Tables

```sql
-- Individual model reviews (R2.1)
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,                -- Groups reviews in a single dispatch
    artifact_id UUID REFERENCES artifacts(id) ON DELETE CASCADE,  -- What was reviewed (NULL for raw content reviews)
    review_artifact_id UUID REFERENCES artifacts(id),  -- The review stored as artifact (R2.3)
    raw_content TEXT,              -- Content when reviewing without an artifact
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    clean_room BOOLEAN NOT NULL DEFAULT TRUE,  -- R2.6
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'complete', 'failed', 'timeout')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invocation_mode TEXT NOT NULL DEFAULT 'agentic'  -- 'agentic' or 'bundled'
) TABLESPACE artifact_data;

-- Synthesized review results (R2.2)
CREATE TABLE review_syntheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL UNIQUE,         -- Unique per review run (prevents duplicate synthesis)
    artifact_id UUID REFERENCES artifacts(id) ON DELETE CASCADE,  -- NULL for raw content reviews
    synthesis_artifact_id UUID REFERENCES artifacts(id),  -- Synthesis stored as artifact
    review_ids UUID[] NOT NULL,         -- Individual reviews included
    consensus JSONB NOT NULL DEFAULT '[]',       -- Findings 2+ models agree on (deprecated — synthesis stored as prose artifact via synthesis_artifact_id)
    contradictions JSONB NOT NULL DEFAULT '[]',  -- Conflicting findings (deprecated — synthesis stored as prose artifact via synthesis_artifact_id)
    models_requested TEXT[] NOT NULL,
    models_responded TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;
```

### 2.3 Window Files (R3.7)

Window files are markdown files stored in `~/roles/{role}/windows/`, one per context window. They provide continuity across compaction, `/clear`, and forking events, forming a tree (not a linear chain) that supports parallel workstreams and forked agents.

**Directory:** `~/roles/{role}/windows/` — namespaced by ontology role (e.g., `~/roles/workbench/windows/`). Falls back to `{project}/thoughts/windows/{harness}/` when no role is active. This supports multiple roles and harnesses writing to the same graph. A shared narrative-update prompt lives at `thoughts/windows/NARRATIVE_PROMPT.md` (harness-agnostic).

**Naming:** `{timestamp}.md` where timestamp is ISO 8601 with colons replaced by hyphens for filesystem safety (e.g., `2026-03-07T14-30-00Z.md`).

**YAML frontmatter:**

```yaml
---
parent: "2026-03-07T13-00-00Z.md"  # filename of parent (same dir), or relative path for cross-harness (e.g., ../opencode/...), or null for roots
children: []                         # populated when child windows are created
session_id: "abc-123"               # session ID (format is harness-specific)
harness: "claude-code"              # which coding harness created this window
role: "workbench"                   # ontology role (workbench, sysadmin, mcp-server)
projects: ["claude-hub"]            # active projects during this window
workstream: "development"           # workstream classification
component: "codebase"               # component within project
service: ""                         # service name if applicable
finalized: false                    # true once window is closed
created: "2026-03-07T14:30:00Z"     # ISO 8601
updated: "2026-03-07T15:45:00Z"     # ISO 8601
---
```

**Content:** Free-form markdown. No required sections. The narrative-update prompt (see Section 7.2) explains why context is captured and what good entries look like, but does not mandate structure.

**Lifecycle:**
- **Stop hook (~20K tokens):** Appends to current window file (does not create a new one).
- **Compaction/clear:** Creates a new child window file. Old window is "closed."
- **New session:** Creates a new root (no prior context) or child (resuming prior work).
- **Forked agent:** A forked agent (e.g., summarization fork) may create a child window linked to the forking session's current window. Multiple children from one parent is normal — this is how the tree branches.
- **Current window tracking:** The active window file path for a session is stored in `~/roles/{role}/windows/.current-{session_id}` (symlink or text file). Falls back to `thoughts/windows/{harness}/.current-{session_id}` when no role is active.

**Graph structure:** Window files form a tree within a session (compaction/clear/forking create children) and a forest across sessions, roles, and harnesses. Parent references can cross role and harness boundaries via relative paths. `load_window_chain` follows links regardless of which role or harness directory they traverse.

**Mechanical log:** The mechanical log (R3.5) remains a separate local JSONL file at `~/roles/{role}/mechanical.jsonl` (falls back to `thoughts/mechanical.jsonl` when no role is active), appended by the existing PostToolUse hook. It is read by the narrative-update agent as factual substrate. No Postgres table, no server component.

### 2.4 Workflow Tables

```sql
-- Spec-driven development tracking (R6)
CREATE TABLE workflow_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    current_stage TEXT NOT NULL DEFAULT 'vision'
        CHECK (current_stage IN ('vision', 'requirements', 'spec', 'implementation', 'complete')),
    vision_artifact_id UUID REFERENCES artifacts(id),
    requirements_artifact_id UUID REFERENCES artifacts(id),
    spec_artifact_id UUID REFERENCES artifacts(id),
    implementation_artifact_id UUID REFERENCES artifacts(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Implementation work items (R6.4)
CREATE TABLE workflow_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES workflow_projects(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in-progress', 'complete')),
    spec_ref TEXT,              -- Reference to spec section
    artifact_id UUID REFERENCES artifacts(id),  -- Resulting artifact
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.5 Connector Tables

```sql
-- Registered data source connectors (R7)
CREATE TABLE connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    connector_type TEXT NOT NULL,  -- artifact_store, filesystem, email, spreadsheet, etc.
    config JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'indexing', 'error', 'disabled')),
    last_indexed TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Content indexed by connectors (R7.3, R7.4)
CREATE TABLE connector_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT,
    content_preview TEXT,
    embedding vector(768),                    -- Direct vector storage, not FK
    embedding_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending', 'complete', 'failed')),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(connector_id, source_path)
);
```

### 2.6 Pattern Tables

```sql
-- Detected recurring patterns (R4)
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT NOT NULL,
    pattern_type TEXT NOT NULL
        CHECK (pattern_type IN ('sequence', 'event', 'heuristic', 'workflow')),
    recurrence_count INTEGER NOT NULL DEFAULT 1,
    embedding vector(768),          -- For similarity detection against existing patterns
    session_refs UUID[],            -- Artifact IDs of sessions where observed
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'confirmed', 'promoted', 'dismissed')),
    promoted_to UUID REFERENCES artifacts(id),  -- The skill/hook/rule artifact
    dismissed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.7 Indexes

```sql
-- Artifact queries
CREATE INDEX idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX idx_artifacts_created_at ON artifacts(created_at);
CREATE INDEX idx_artifacts_archived ON artifacts(archived);
CREATE INDEX idx_artifacts_content_hash ON artifacts(content_hash);
CREATE INDEX idx_artifacts_tags ON artifacts USING GIN(tags);
CREATE INDEX idx_artifacts_metadata ON artifacts USING GIN(metadata);
CREATE INDEX idx_artifacts_derives_from ON artifacts USING GIN(derives_from);
-- Note: GIN index supports single-hop containment queries (e.g., "what derives from X").
-- Transitive lineage queries (R6.3 "everything related to [vision doc]") require a
-- recursive CTE over derives_from, which Postgres supports natively.
CREATE UNIQUE INDEX idx_artifacts_dedup ON artifacts(content_hash, COALESCE(source_ref, ''))
    WHERE archived = FALSE;

-- Embedding queries
-- HNSW for approximate nearest neighbor search (better recall than IVFFlat at this scale)
CREATE INDEX idx_artifact_embeddings_vector ON artifact_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- Retry queue: find pending/failed embeddings efficiently
CREATE INDEX idx_artifact_embeddings_pending ON artifact_embeddings(status)
    WHERE status IN ('pending', 'failed');

-- Connector index
CREATE INDEX idx_connector_index_connector ON connector_index(connector_id);
CREATE INDEX idx_connector_index_embedding ON connector_index
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Reviews
CREATE INDEX idx_reviews_artifact ON reviews(artifact_id);
CREATE INDEX idx_reviews_job_id ON reviews(job_id);
CREATE INDEX idx_reviews_status ON reviews(status) WHERE status IN ('pending', 'running');
CREATE INDEX idx_review_syntheses_job_id ON review_syntheses(job_id);

-- Outcomes
CREATE INDEX idx_artifact_feedback_artifact ON artifact_feedback(artifact_id);
CREATE INDEX idx_review_grades_model ON review_grades(model_name, review_type);

-- Workflow
CREATE INDEX idx_workflow_items_project ON workflow_items(project_id);
CREATE INDEX idx_workflow_items_status ON workflow_items(project_id, status);

-- Patterns
CREATE INDEX idx_patterns_status ON patterns(status);
```

Design notes:

- **HNSW over IVFFlat**: At the expected scale (up to 10,000 artifacts), HNSW provides better recall without needing periodic re-training. IVFFlat requires `CREATE INDEX ... WITH (lists = N)` and periodic re-indexing as data grows; HNSW is maintenance-free. The memory cost of HNSW is acceptable — 10,000 vectors at 768 dimensions is ~30MB.
- **HNSW ef_search**: Set `SET hnsw.ef_search = 64` at session start (or per-query) for recall quality. The default (40) is acceptable but 64 gives better accuracy at this scale with negligible latency cost.
- **GIN on tags and metadata**: Supports `@>` containment queries (e.g., `tags @> ARRAY['infrastructure']`) and JSONB path queries.
- **Partial indexes on status columns**: For the embedding retry queue and review status, partial indexes keep the index small by only covering rows that need processing.

---

## 3. Embedding Pipeline

### 3.1 Google Gemini API Integration

**Model**: `text-embedding-004` (768 dimensions)
**Endpoint**: `https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent`
**Auth**: API key from Google AI Studio, stored in environment variable `GEMINI_API_KEY`
**Rate limits**: Free tier allows 1,500 requests/minute, 1M tokens/day. For a personal system doing single-artifact embedding on write plus occasional batch ingestion, this is sufficient.

Python client using the `google-generativeai` package:

```python
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

async def generate_embedding(text: str) -> list[float]:
    """Generate a 768-dim embedding for the given text."""
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document",
    )
    return result['embedding']  # list of 768 floats

async def generate_query_embedding(text: str) -> list[float]:
    """Generate an embedding optimized for query matching."""
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_query",
    )
    return result['embedding']
```

Note: `google-generativeai` is a synchronous library. The async wrapper runs it in a thread pool executor via `asyncio.to_thread()`. If this causes issues, fall back to direct REST API calls with `httpx`.

### 3.2 Embedding on Write

When an artifact is stored via `artifact_store()`:

1. Insert the artifact row into `artifacts`.
2. Insert version 1 into `artifact_versions`.
3. Insert a row into `artifact_embeddings` with `status = 'pending'`.
4. Schedule an async task to generate the embedding.
5. Return the artifact ID immediately — the caller does not wait for embedding.

The async task:
1. Call `generate_embedding(content)`.
2. On success: update the embedding row with the vector and `status = 'complete'`.
3. On failure: update with `status = 'failed'`, `error_message`, increment `retry_count`.

### 3.3 Retry Queue

A background task runs every 60 seconds:

```python
# Note: pgvector.asyncpg.register_vector(pool) must be called at pool creation
# so that asyncpg knows how to serialize/deserialize vector types.

async def embedding_retry_loop(pool: asyncpg.Pool):
    while True:
        await asyncio.sleep(60)
        # Sweep artifact_embeddings for pending/failed
        rows = await pool.fetch("""
            SELECT ae.id, a.content
            FROM artifact_embeddings ae
            JOIN artifacts a ON a.id = ae.artifact_id
            WHERE ae.status IN ('pending', 'failed')
              AND ae.retry_count < 5
            ORDER BY ae.created_at ASC
            LIMIT 10
        """)
        for row in rows:
            try:
                embedding = await generate_embedding(row['content'])
                await pool.execute("""
                    UPDATE artifact_embeddings
                    SET embedding = $1, status = 'complete', updated_at = NOW()
                    WHERE id = $2
                """, embedding, row['id'])
            except Exception as e:
                await pool.execute("""
                    UPDATE artifact_embeddings
                    SET status = 'failed', error_message = $1,
                        retry_count = retry_count + 1, updated_at = NOW()
                    WHERE id = $2
                """, str(e), row['id'])

        # Also sweep connector_index for pending embeddings
        ci_rows = await pool.fetch("""
            SELECT id, content_preview AS content
            FROM connector_index
            WHERE embedding_status IN ('pending', 'failed')
            LIMIT 10
        """)
        for row in ci_rows:
            try:
                embedding = await generate_embedding(row['content'])
                await pool.execute("""
                    UPDATE connector_index
                    SET embedding = $1, embedding_status = 'complete'
                    WHERE id = $2
                """, embedding, row['id'])
            except Exception as e:
                await pool.execute("""
                    UPDATE connector_index
                    SET embedding_status = 'failed'
                    WHERE id = $2
                """, row['id'])
```

Max retries: 5. After 5 failures, the embedding stays in `failed` status and requires manual intervention (re-trigger via API or fix the underlying issue).

**Startup recovery:** On FastAPI startup, the embedding retry loop runs an immediate sweep of all pending/failed artifact_embeddings and connector_index entries (with retry_count < 5 for artifact_embeddings, any pending/failed for connector_index) before entering its 60-second polling loop. This recovers from server restarts that may have left embeddings in pending state.

### 3.4 Batch Embedding

For bulk ingestion (window file import, directory scan), embeddings are generated in batches of 20 with 100ms delays between batches to stay well within rate limits:

```python
async def batch_embed(artifact_ids: list[UUID], pool: asyncpg.Pool):
    """Embed multiple artifacts in batches."""
    for i in range(0, len(artifact_ids), 20):
        batch = artifact_ids[i:i+20]
        for aid in batch:
            row = await pool.fetchrow(
                "SELECT content FROM artifacts WHERE id = $1", aid
            )
            if row:
                try:
                    embedding = await generate_embedding(row['content'])
                    await pool.execute("""
                        UPDATE artifact_embeddings
                        SET embedding = $1, status = 'complete', updated_at = NOW()
                        WHERE artifact_id = $2
                    """, embedding, aid)
                except Exception as e:
                    await pool.execute("""
                        UPDATE artifact_embeddings
                        SET status = 'failed', error_message = $1,
                            retry_count = retry_count + 1, updated_at = NOW()
                        WHERE artifact_id = $2
                    """, str(e), aid)
        if i + 20 < len(artifact_ids):
            await asyncio.sleep(0.1)
```

### 3.5 Embedding Update on New Version

When an artifact's content changes (new version created):

1. Insert the new version into `artifact_versions`.
2. Update the `artifacts` row with new content and content_hash.
3. Set the existing embedding row's `status` to `'pending'` and clear the vector.
4. The retry loop picks it up and generates a fresh embedding.

This ensures the embedding always reflects the latest version of the artifact.

---

## 4. API Surface

All tools are added to the existing FastAPI MCP server (`src/claude_hub/server.py`) and exposed via FastApiMCP. Each tool is a POST endpoint with typed request/response models, following the existing patterns in the codebase.

### 4.1 R1 — Artifact Store (9 tools)

**`artifact_store`** — Store a new artifact.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| content | str | yes | Artifact text content |
| artifact_type | str | yes | Type identifier (vision-doc, review, decision, session-summary, skill, hook, rule, etc.) |
| tags | list[str] | no | Classification tags |
| source_ref | str | no | Session ID or source identifier |
| derives_from | list[str] | no | Parent artifact UUIDs (lineage DAG) |
| sensitive | bool | no | Mark as sensitive — local processing only, never sent to third-party APIs (default false) |
| metadata | dict | no | Additional key-value metadata |

Returns: `{ artifact_id: str, version: 1, embedding_status: "pending" }`

Behavior:
1. Compute SHA-256 of content.
2. Dedup is enforced by the unique partial index `idx_artifacts_dedup` on `(content_hash, COALESCE(source_ref, ''))` where `archived = FALSE`. A concurrent duplicate insert will raise a unique violation, which the handler catches and returns the existing artifact ID. This eliminates the check-then-insert race condition. Content-hash alone doesn't dedup across different sources: the same text from different contexts represents different provenance.
3. Insert into `artifacts`, `artifact_versions` (version 1), and `artifact_embeddings` (pending).
4. If `sensitive = true`, skip embedding generation (step 3 still creates the `artifact_embeddings` row but leaves it in `pending` status with a note; the retry loop skips sensitive artifacts).
5. Schedule async embedding generation (unless sensitive).
6. Return immediately.

Error cases:
- Empty content → 400
- Invalid artifact_type → 400 (if type validation is enabled; initially permissive)
- Invalid derives_from UUID format → 400 (validate each UUID string before insert)

When `sensitive = true`, the artifact is stored but embedding generation is SKIPPED. Sensitive artifacts are findable by type, tags, date, and metadata search, but NOT by semantic (vector) search. They are also excluded from third-party review dispatch — `dispatch_review()` will reject artifacts marked sensitive with an error explaining why.

---

**`artifact_get`** — Retrieve an artifact by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | str | yes | Artifact UUID |
| include_versions | bool | no | Include version history (default false) |
| include_feedback | bool | no | Include usage feedback summary (default true) |

Returns: Full artifact object including content, metadata, type, tags, source_ref, derives_from, created_at, archived status, confidence, utility_score, optional versions list, optional feedback summary.

Error cases:
- Not found → 404

---

**`artifact_search`** — Semantic search across artifacts (R1.2, R1.3, R5.3).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | yes | Natural-language search query |
| artifact_type | str | no | Filter by type |
| tags | list[str] | no | Filter by tags (AND — all must match) |
| date_from | str | no | ISO date, lower bound |
| date_to | str | no | ISO date, upper bound |
| include_archived | bool | no | Include archived artifacts (default false) |
| confidence | str | no | Minimum confidence level (HIGH, MEDIUM, LOW) |
| limit | int | no | Max results (default 10, max 50) |

Returns: `{ results: [{ artifact_id, content_preview, artifact_type, tags, score, utility_score, confidence, created_at }] }`

Behavior:
1. Generate query embedding using `generate_query_embedding(query)`.
2. Build SQL with pgvector cosine distance (`<=>` operator) plus optional WHERE clauses for filters.
3. For quality-weighted retrieval (R5.3): boost score based on utility (agent feedback), confidence, and age. No-signal artifacts get neutral treatment.
4. After computing results, update `last_retrieved = NOW()` on all returned artifacts. This is lightweight telemetry that requires no explicit agent action — the search path handles it.

Score formula:

```sql
WITH scored AS (
    SELECT a.id, a.content, a.artifact_type, a.tags, a.created_at,
           a.utility_score, a.confidence,
           1 - (ae.embedding <=> $1::vector) AS base_score,
           CASE
               WHEN a.confidence = 'HIGH' THEN 0.1
               WHEN a.confidence = 'MEDIUM' THEN 0.0
               WHEN a.confidence = 'LOW' THEN -0.1
               WHEN a.confidence = 'SUPERSEDED' THEN -0.2
           END AS confidence_boost,
           (a.utility_score - 0.5) * 0.4 AS utility_boost,  -- centers at 0, range -0.2 to +0.2
           GREATEST(
               -0.1 * EXTRACT(EPOCH FROM (NOW() - a.created_at)) / (365 * 86400),
               -0.2
           ) AS age_boost  -- slight recency preference, capped at -0.2
    FROM artifacts a
    JOIN artifact_embeddings ae ON ae.artifact_id = a.id
        AND ae.status = 'complete' AND ae.embedding IS NOT NULL
    WHERE a.archived = FALSE  -- unless include_archived
      AND (a.confidence != 'SUPERSEDED' OR include_archived)
      AND (a.artifact_type = $2 OR $2 IS NULL)
      AND (a.tags @> $3 OR $3 IS NULL)
      AND (a.created_at >= $4 OR $4 IS NULL)
      AND (a.created_at <= $5 OR $5 IS NULL)
)
SELECT *, base_score + confidence_boost + utility_boost + age_boost AS final_score
FROM scored
ORDER BY final_score DESC
LIMIT $6
```

The CTE avoids referencing SELECT aliases within the same SELECT expression (which PostgreSQL disallows). The `utility_score` and `confidence` columns live directly on the artifacts table, so no joins are needed for quality-weighted scoring. The `ae.embedding IS NOT NULL` guard prevents null vector distance calculations. The `age_boost` provides a conservative recency signal: artifacts lose up to 0.2 points over 2+ years, but never more — old artifacts with strong utility/confidence still rank well.

Error cases:
- Embedding generation fails for query → 500 with message
- No results → empty list (not an error)

---

**`artifact_list`** — List artifacts with filtering (no semantic search).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| artifact_type | str | no | Filter by type |
| tags | list[str] | no | Filter by tags |
| include_archived | bool | no | Include archived (default false) |
| limit | int | no | Max results (default 20, max 100) |
| offset | int | no | Pagination offset (default 0) |

Returns: `{ results: [...], total_count: int }`

Behavior: Straight SQL query with filters, ordered by `created_at DESC`.

---

**`artifact_archive`** — Archive an artifact (R1.6).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | str | yes | Artifact UUID |

Returns: `{ success: true }`

Behavior: Sets `archived = TRUE` on the artifact. Does not delete content, versions, embeddings, or feedback.

Error cases:
- Not found → 404
- Already archived → success (idempotent)

---

**`artifact_update`** — Create a new version of an artifact (R1.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | str | yes | Artifact UUID |
| content | str | yes | New content for the artifact |
| metadata | dict | no | Metadata to merge into existing |

Returns: `{ artifact_id: str, version: int, embedding_status: "pending" }`

Behavior:
1. Validate artifact exists.
2. Insert new version into `artifact_versions` (next sequential version number).
3. Update `artifacts` row with new content and content_hash.
4. Reset existing embedding row's status to `pending` and clear the vector.
5. If metadata provided, JSONB merge into `artifacts.metadata`.
6. Return the artifact ID, new version number, and embedding status.

Note: The new version number is recorded in `artifact_versions`. Subsequent `artifact_feedback` records include the current `content_version` at time of feedback, so utility scores can be correlated with specific content versions. This prevents stale feedback from an old version silently biasing a materially different new version.

Error cases:
- Not found → 404
- Empty content → 400

---

**`artifact_update_metadata`** — Update artifact metadata independently (R1.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | str | yes | Artifact UUID |
| metadata | dict | yes | Metadata to merge into existing (JSONB merge) |
| tags | list[str] | no | Replace tags if provided |
| archived | bool | no | Set archived status |

Returns: `{ success: true }`

Behavior:
1. JSONB merge on `artifacts.metadata` (`metadata || $1`).
2. Tags replace if provided (not merged — full replacement).
3. Archived flag updated if provided.
4. If searchable fields change, note that re-indexing may be needed for metadata-based search (metadata is already GIN-indexed).

Error cases:
- Not found → 404
- Empty metadata and no tags/archived → 400

---

**`artifact_export`** — Export artifacts for backup (R1.7).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| format | str | no | Export format: "json" or "pg_dump" (default "json") |
| artifact_type | str | no | Filter export to specific type |

Returns:
- For "json": `{ export_path: str, artifact_count: int }` — writes a JSON file to a temp directory
- For "pg_dump": `{ export_path: str }` — runs `pg_dump` for the artifact tables

Behavior:
- JSON export includes all artifact data, versions, feedback, and embeddings metadata (not vectors — those are regenerated on restore).
- pg_dump export captures the raw database state including vectors.
- Export file written to `/mnt/HC_Volume_104288266/data/backups/artifacts/`.

---

**`artifact_import`** — Import artifacts from a backup (R1.7).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | yes | Path to JSON export file |
| dry_run | bool | no | Preview import without storing (default false) |

Returns: `{ imported: int, skipped: int, errors: list[str] }`

Behavior:
1. Read JSON export file (produced by `artifact_export`).
2. For each artifact: check content_hash dedup, skip if already exists.
3. Restore artifact, versions, feedback, and metadata.
4. Queue embedding generation for each imported artifact (vectors are regenerated, not imported).
5. Report counts.

Error cases:
- Invalid file format → 400
- File not found → 404

---

### 4.2 R2 — Multi-Model Review

Reviews are dispatched via CLI (`python3 -m claude_hub.review_cli`), not MCP tools. The CLI calls `dispatch_review()` directly, awaits all tasks via `asyncio.gather`, and writes results to a file. See `.claude/skills/review/SKILL.md` for usage.

---

### 4.3 R3 — Context Continuity

Context continuity uses no MCP tools. All functionality is delivered through hooks and CLI:

- **Mechanical log (R3.5):** Local JSONL file (`~/roles/{role}/mechanical.jsonl`, falls back to `thoughts/mechanical.jsonl`), appended by existing PostToolUse hook. Already implemented — no new work for Phase 3.
- **Narrative updates (R3.2):** Forked agent task triggered by Stop and PreCompact hooks. The agent reads conversation context + mechanical log, writes/updates a window file. Not a tool — cognitive work done by an agent.
- **Context loading (R3.3, Phase 3):** SessionStart hook follows window file parent chain to load recent context. File-based, no artifact store queries.
- **Context loading (R3.3, Phase 3.5):** Semantic retrieval from artifact store. Window files ingested as artifacts; SessionStart queries for topic-relevant past windows. CLI: `python3 -m claude_hub.continuity search --topic "..."`
- **Ledger migration (R3.4):** One-time CLI script (`python3 -m claude_hub.continuity migrate`), completed. Converted existing ledgers to window files with YAML frontmatter. The ledger system has been decommissioned.

This eliminates 4 MCP tools from the original design. Combined with the 3 review tools removed in Draft 7 (total tools: 23, down from 30).

---

### 4.4 R5 — Knowledge Quality (3 tools)

**`artifact_feedback`** — Record usage feedback on a retrieved artifact (R5.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| artifact_id | str | yes | Artifact UUID |
| useful | bool | yes | Whether the retrieved content was useful |
| note | str | no | Brief context (e.g., "outdated info" or "solved my problem directly") |
| agent_id | str | no | Identifier of the agent providing feedback (defaults to current session) |

Returns: `{ success: true, feedback_id: str }`

Behavior:
1. Validate artifact exists.
2. Look up current artifact version from `artifact_versions` (latest version number); record it as `content_version` in the feedback row.
3. Insert into `artifact_feedback` table.
4. Recompute the artifact's `utility_score` using a Bayesian average: `(count_useful + 1) / (count_total + 2)`. This handles cold start (prior = 0.5 with zero feedback), is simple, and prevents single-feedback drama. The `+1`/`+2` Laplace smoothing means an artifact with no feedback has score 0.5 (neutral), one positive → 0.67, one negative → 0.33, etc.
5. Update `artifacts.utility_score` with the recomputed value.

Designed to be called inline during work — an agent retrieves knowledge, uses it (or doesn't), and quickly signals the result. Low friction is critical; this should feel like a bookmark, not a review.

Error cases:
- Artifact not found → 404

---

**`artifact_set_confidence`** — Set confidence level on an artifact (R5.2).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| artifact_id | str | yes | Artifact UUID |
| confidence | str | yes | HIGH, MEDIUM, LOW, or SUPERSEDED |
| reason | str | no | Why this confidence level (e.g., "verified against current codebase" or "was true in Feb, may have changed") |

Returns: `{ success: true }`

Behavior:
1. Update artifact metadata with confidence level and optional reason.
2. SUPERSEDED marks the artifact as replaced by newer information — functionally equivalent to low confidence but semantically distinct (not wrong, just outdated).

Confidence is set at write time or updated when an agent discovers the information is stale. Unlike usage feedback (which accumulates from many agents), confidence is a point-in-time assessment that gets overwritten.

Error cases:
- Artifact not found → 404
- Invalid confidence value → 400

---

**`artifact_retirement_candidates`** — List artifacts that may be ready to archive (R5.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| min_age_days | int | no | Minimum age to consider (default 30) |
| max_utility | float | no | Utility score threshold (default 0.3) |
| limit | int | no | Max results (default 20) |

Returns: `{ candidates: [{ id, artifact_type, content_preview, utility_score, confidence, last_retrieved, created_at }] }`

Behavior:
1. Find artifacts with low utility scores, low confidence, or SUPERSEDED status that are older than `min_age_days`.
2. Return as candidates — retirement requires explicit confirmation via `artifact_archive`.

---

### 4.5 R4 — Capability Compounding (3 tools)

**`pattern_detect`** — Scan session history for recurring patterns (R4.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| scope | str | no | Scope: "recent" (last 20 sessions), "all", or a date range |
| threshold | int | no | Min recurrence count to report (default 3) |
| include_dismissed | bool | no | Re-surface dismissed patterns (default false) |

Returns: `{ patterns: [{ id, description, pattern_type, recurrence_count, example_sessions, status }] }`

Behavior:
1. Load session summary artifacts within scope.
2. Use an LLM call (Claude via CLI) to analyze summaries for recurring patterns: repeated command sequences, similar problem-solving approaches, recurring heuristics.
3. For each detected pattern, include the existing patterns table contents in the LLM prompt. The model determines whether a candidate is new or a recurrence of an existing pattern — deduplication is a judgment call, not a similarity threshold.
4. New patterns: insert with `status = 'candidate'`, `recurrence_count = 1`.
5. Existing patterns: increment `recurrence_count`, add session_refs.
6. Return patterns meeting the threshold.

Automatic detection (R4.1): triggered after every 10 new session-summary artifacts are stored. The `artifact_store` tool tracks the count and fires `pattern_detect(scope="recent", threshold=3)` when the threshold is crossed.

---

**`pattern_promote`** — Promote a pattern to a durable artifact (R4.2, R4.3).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| pattern_id | str | yes | Pattern UUID |
| target_type | str | yes | Target artifact type: "skill", "hook", "rule", or "agent" |
| draft | str | no | Draft implementation content (if not provided, system generates one) |

Returns: `{ artifact_id: str, pattern_status: "promoted" }`

Behavior:
1. Load the pattern and its session_refs.
2. If no draft: use an LLM call to generate a draft implementation appropriate to the target_type.
3. Store the draft as an artifact with:
   - `artifact_type = target_type`
   - `derives_from = pattern.session_refs` (lineage to source observations, R4.3)
   - `tags = ['promoted-from-pattern']`
4. Update the pattern: `status = 'promoted'`, `promoted_to = artifact_id`.

---

**`pattern_dismiss`** — Dismiss a candidate pattern (R4.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| pattern_id | str | yes | Pattern UUID |

Returns: `{ success: true }`

Behavior: Sets `status = 'dismissed'`, `dismissed_at = NOW()`. Dismissed patterns are excluded from future automatic detection runs.

---

### 4.6 R6 — Spec-Driven Workflow (6 tools)

**`workflow_create`** — Start a new project workflow (R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Project name |
| description | str | no | Project description |

Returns: `{ project_id: str, current_stage: "vision" }`

---

**`workflow_status`** — Get current workflow state (R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | yes | Project UUID |

Returns: Full project state including current stage, artifact IDs for completed stages, work item summary (counts by status).

---

**`workflow_advance`** — Advance project to next stage (R6.2, R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | yes | Project UUID |
| stage | str | yes | Stage to advance to |
| artifact_id | str | yes | Artifact ID for the completed stage's deliverable |
| skip_review | bool | no | Skip review gate (default false) |

Returns: `{ success: true, review_job_id?: str }`

Behavior:
1. Validate the stage transition is legal (vision→requirements→spec→implementation→complete).
2. Store the artifact_id in the appropriate column (e.g., `vision_artifact_id`).
3. Unless `skip_review = true`: dispatch a multi-model review of the artifact (calls `dispatch_review()`).
4. Update `current_stage`.

The workflow is advisory (per R6 constraints) — `skip_review` is allowed. Stage transitions are validated against the legal sequence (vision→requirements→spec→implementation→complete) and return a warning for out-of-order advances, but do not block them. The warning is included in the response: `{ success: true, warning?: str, review_job_id?: str }`.

**Stage templates (R6.1):** Each stage has two kinds of templates:

*Creation templates* — guide starting a new document at each stage:
- `vision`: "What problem does this solve? What do we want? What principles guide the design? What's out of scope?"
- `requirements`: "What capabilities are needed? What are the acceptance criteria? What constraints apply?"
- `spec`: "What are the interfaces, data models, and algorithms? How does each requirement map to implementation?"
- `implementation`: "What modules, tests, and integration points are needed?"

*Review-gate templates* — structure the review when transitioning between stages:
- `vision → requirements`: "Does this requirements doc fully cover the vision? Are there gaps?"
- `requirements → spec`: "Does this spec implement all requirements? Are there contradictions?"
- `spec → implementation`: "Is this implementation complete per spec? Are there deviations?"

Templates are stored in `config/stage_templates.yaml` alongside the review model registry.

---

**`workflow_items`** — List work items for a project (R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | yes | Project UUID |
| status | str | no | Filter by status (pending, in-progress, complete) |

Returns: `{ items: [{ id, description, status, spec_ref, artifact_id, created_at }] }`

---

**`workflow_item_create`** — Create a work item for a project (R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | yes | Project UUID |
| description | str | yes | Work item description |
| spec_ref | str | no | Reference to spec section |

Returns: `{ item_id: str }`

---

**`workflow_item_update`** — Update a work item (R6.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | str | yes | Work item UUID |
| status | str | no | New status |
| artifact_id | str | no | Resulting artifact ID |
| description | str | no | Updated description |

Returns: `{ success: true }`

---

### 4.7 R7 — Connector Interface (3 tools)

**`connector_register`** — Register a new data source connector (R7.1).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Unique connector name |
| connector_type | str | yes | Type identifier (artifact_store, filesystem, etc.) |
| config | dict | yes | Connector-specific configuration |

Returns: `{ connector_id: str }`

Behavior:
1. Validate the connector_type has a registered implementation.
2. Insert into `connectors` table.
3. Instantiate the connector class and register it with the ConnectorRegistry.

Error cases:
- Unknown connector_type → 400
- Duplicate name → 409

---

**`connector_index`** — Trigger indexing for a connector (R7.3).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| connector_id | str | yes | Connector UUID |
| path | str | no | Specific path/scope to index (default: full scan) |

Returns: `{ items_scanned: int, items_indexed: int, items_skipped: int, errors: list[str] }`

Behavior:
1. Set connector status to `indexing`.
2. Call the connector's `index()` method.
3. For each item: compute content_hash, check for existing index entry (dedup by connector_id + source_path), generate embedding.
4. Update `last_indexed` timestamp.
5. Set connector status back to `active`.

---

**`query_federated`** — Search across all registered connectors (R7.4).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | yes | Natural-language search query |
| connectors | list[str] | no | Connector names to query (default: all active) |
| artifact_type | str | no | Filter by type (where applicable) |
| limit | int | no | Max total results (default 10) |

Returns: `{ results: [{ content_preview, source, score, connector_name, metadata }] }`

Behavior:
1. Generate query embedding.
2. For each active connector (or specified subset):
   - If the connector has indexed content: query `connector_index.embedding` directly using vector similarity (connector_index stores its own embeddings, independent of artifact_embeddings).
   - If the connector supports live query: call its `query()` method.
3. Merge results from all connectors into a single list, ranked by score.
4. Each result includes `connector_name` to indicate its source.

### 4.8 Internal HTTP Endpoints

These endpoints are called by hooks via `curl` to the FastAPI server. They are NOT MCP tools — they are internal HTTP endpoints on the same server.

**`GET /workflow_active_items`** — Get active work items across all projects (called by PreCompact hook, available after Phase 7).

Response: `{ items: [{ project_name, description, status, spec_ref }] }`

All endpoints return JSON. On error, they return `{ error: str }` with appropriate HTTP status codes.

Note: Context continuity hooks (PostToolUse, Stop, PreCompact, SessionStart) no longer call HTTP endpoints. They operate on local files (mechanical log JSONL, window files). See Section 7 for details.

---

## 5. Connector Interface

### 5.1 Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class ConnectorError(Exception):
    """Raised when a connector operation fails."""
    def __init__(self, message: str, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


@dataclass
class ConnectorResult:
    """A search result from a connector."""
    content: str
    source: str             # Path/URI within the connector
    score: float            # Similarity score, 0-1
    metadata: dict = field(default_factory=dict)
    connector_name: str = ""


@dataclass
class ConnectorItem:
    """A single item in a connector's domain."""
    id: str
    title: str
    content: str
    path: str               # Path/URI within the connector
    metadata: dict = field(default_factory=dict)


@dataclass
class IndexReport:
    """Result of an indexing operation."""
    items_scanned: int = 0
    items_indexed: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Interface that all connectors implement."""

    @abstractmethod
    async def query(self, query: str, filters: dict | None = None,
                    limit: int = 10) -> list[ConnectorResult]:
        """Semantic search within this connector's domain.

        Args:
            query: Natural-language search query
            filters: Connector-specific filters (type, date range, etc.)
            limit: Max results to return

        Returns:
            List of results ranked by relevance
        """

    @abstractmethod
    async def list(self, path: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[ConnectorItem]:
        """List items in this connector's domain.

        Args:
            path: Sub-path to list within (None = root)
            limit: Max items to return
            offset: Pagination offset

        Returns:
            List of items
        """

    @abstractmethod
    async def get(self, item_id: str) -> ConnectorItem:
        """Get a specific item by ID.

        Args:
            item_id: Item identifier (format is connector-specific)

        Returns:
            The item

        Raises:
            KeyError: Item not found
        """

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Return the connector type identifier."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the connector instance name."""

    # Auth contract — connectors manage their own credentials
    # Credentials are stored in the connector's `config` JSONB, not in code.
    # Connectors that access external services must:
    # 1. Validate credentials on registration (fail fast if invalid)
    # 2. Handle credential expiry gracefully (return ConnectorError, not crash)
    # 3. Never log or expose credentials in error messages

    async def validate(self) -> bool:
        """Validate connector configuration and credentials.

        Called on registration. Return True if ready, raise
        ConnectorError with details if not.
        """
        return True

    # Optional methods — override if supported

    async def index(self, path: str | None = None) -> IndexReport:
        """Pre-index content for faster retrieval.

        Not all connectors support indexing. Those that don't raise
        NotImplementedError; the registry skips them during index operations.
        """
        raise NotImplementedError(
            f"{self.connector_type} connector does not support indexing"
        )

    async def write(self, item_id: str, content: str) -> bool:
        """Write back to the data source.

        Not all connectors support write-back. Those that don't raise
        NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.connector_type} connector does not support writes"
        )
```

### 5.2 Connector Registry

```python
class ConnectorRegistry:
    """Holds connector instances and routes federated queries."""

    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector instance."""
        if connector.name in self._connectors:
            raise ValueError(f"Connector '{connector.name}' already registered")
        self._connectors[connector.name] = connector

    def unregister(self, name: str) -> None:
        """Remove a connector."""
        self._connectors.pop(name, None)

    def get(self, name: str) -> BaseConnector:
        """Get a connector by name."""
        if name not in self._connectors:
            raise KeyError(f"Connector '{name}' not found")
        return self._connectors[name]

    @property
    def active_connectors(self) -> list[BaseConnector]:
        """All registered connectors."""
        return list(self._connectors.values())

    async def federated_query(
        self,
        query: str,
        connector_names: list[str] | None = None,
        filters: dict | None = None,
        limit: int = 10,
    ) -> list[ConnectorResult]:
        """Query all (or specified) connectors and merge results.

        Queries run in parallel via asyncio.gather. Results are merged
        into a single list ranked by score. Each result's connector_name
        field indicates its source.
        """
        targets = (
            [self._connectors[n] for n in connector_names if n in self._connectors]
            if connector_names
            else self.active_connectors
        )

        async def query_one(connector: BaseConnector) -> list[ConnectorResult]:
            try:
                results = await connector.query(query, filters, limit)
                for r in results:
                    r.connector_name = connector.name
                return results
            except Exception as e:
                # Log error but don't fail the entire federated query
                logger.error(f"Connector {connector.name} query failed: {e}")
                return []

        all_results = await asyncio.gather(*[query_one(c) for c in targets])
        merged = [r for results in all_results for r in results]
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:limit]
```

On FastAPI startup (lifespan handler), the connector registry queries the `connectors` table for all rows with `status = 'active'`, instantiates the corresponding connector classes, and registers them. This ensures connectors survive server restarts without re-registration.

### 5.3 Reference Implementations

**ArtifactConnector** (R7.2) — wraps the artifact store to implement the connector interface:

- `query()`: delegates to `artifact_search` logic (vector similarity on `artifact_embeddings`)
- `list()`: delegates to `artifact_list` logic
- `get()`: delegates to `artifact_get` logic
- `connector_type`: `"artifact_store"`
- Does not implement `index()` — artifacts are embedded on write

**FilesystemConnector** (R7.3) — indexes markdown files from a directory:

- `index()`: walks the directory, reads each `.md` file, computes content_hash, stores in `connector_index` with embedding stored directly in the `connector_index.embedding` column (not via `artifact_embeddings`), queues embedding generation
- `query()`: vector similarity search against `connector_index.embedding` for this connector
- `list()`: directory listing with metadata
- `get()`: read file content
- `connector_type`: `"filesystem"`
- Default config: `{ "root_path": "/home/claude/projects/claude-hub/thoughts/", "extensions": [".md"], "recursive": true }` (root_path should be absolute; resolve against project directory if relative)

---

## 6. Review Model Registry

Models are configured in a YAML file at `config/review_models.yaml` (R2.4):

```yaml
models:
  claude:
    display_name: "Claude (Anthropic)"
    mode: agentic
    invoke: ["claude", "-p", "{prompt}"]
    cost_tier: subscription
    max_input_chars: 400000
    timeout_seconds: 300
    clean_room_flags: ["--profile", "review"]

  gemini:
    display_name: "Gemini (Google)"
    mode: agentic
    invoke: ["gemini", "-p", "{prompt}", "-o", "text"]
    cost_tier: subscription
    max_input_chars: 2000000
    timeout_seconds: 300
    clean_room_flags: []

  kimi-k2.5:
    display_name: "Kimi K2.5 (via OpenCode)"
    mode: agentic
    invoke: ["opencode", "run", "-m", "opencode/kimi-k2.5", "--file", "{prompt_file}", "--", "Review per prompt."]
    cost_tier: pay-per-use
    max_input_chars: 128000
    timeout_seconds: 300
    clean_room_flags: []

synthesis:
  model: claude  # Which model runs synthesis. Must be a key in 'models' above.
  timeout_seconds: 120
```

### Invocation Modes

Each model has a `mode` field indicating how the review engine should invoke it:

**`agentic`** (primary mode): The model is launched as an agent with a task prompt. The prompt describes what to review and why (intent), lists the changed files as starting points, and sets boundaries on what not to read. The model reads the files itself, explores adjacent code for context, and forms its own understanding. No content is bundled — the model has codebase access.

**`bundled`** (fallback): For models that cannot navigate a codebase (no file-reading tools), the review engine writes the content to a temp file and passes it alongside the prompt. This is a degraded mode — the reviewer can only see what's bundled, not explore context. Use this only for models that lack agentic capability.

### Prompt Construction

The review engine constructs a task prompt for each review. The prompt contains:

1. **What to review** — the list of changed files, with a suggestion of where to start.
2. **Intent** — what the code is supposed to do. This comes from the `intent` parameter on `dispatch_review()`, which should reference the relevant spec section, requirements, or acceptance criteria. Without intent, reviewers can only find mechanical bugs; with intent, they can find semantic errors (code works but doesn't do what was asked).
3. **Context files** — pre-existing code the reviewer should read for conventions and patterns (e.g., "read artifact_store.py for the existing style").
4. **Boundaries** — soft instructions on what not to read. Default: "Please do NOT read files under thoughts/history/, .claude/, or CLAUDE.md — these contain process preferences that could anchor your review."
5. **Review approach** — instructions to explore context and write findings as prose. No output format is imposed — the synthesis model reads raw output directly.

For agentic models, the prompt is passed as a single string via the `{prompt}` placeholder. For models where the prompt must be a file (e.g., OpenCode's `--file` flag), the engine writes the prompt to a temp file and uses `{prompt_file}`.

### Prompt Template

```
You are reviewing code for correctness, completeness, and alignment with requirements.

## Files to Review
{files_list}

## Intent
{intent_text}

{context_files_section}

## Boundaries
Please do NOT read the following paths — they contain process preferences and editorial opinions that could anchor your review:
{exclude_paths_list}

Focus on the code and its alignment with the intent above. Form your own opinions.

## Review Approach
Start by reading the files listed above, then explore adjacent code for context (imports, callers, tests). Report which files you read beyond the review targets.

Write your review as prose. For each finding, note where in the code it occurs and how severe you think it is. Organize however makes sense for what you found — there is no required format. The synthesis model will read your output directly.
```

The `{context_files_section}` is omitted if no context files are provided. When present:

```
## Suggested Context
Read these files for conventions and patterns:
{context_files_list}
```

### Clean-Room Implementation

Clean-room review (R2.6) is opinion isolation, not information deprivation:

- **Suppress**: Project-level instructions (CLAUDE.md), process preferences, style guides, design rationale, thoughts/history/ directory.
- **Allow**: The spec/requirements (intent), the codebase itself, docs/design/ (specs, requirements, reviews), API docs, existing code patterns, tests.

For Claude, `--profile review` loads a dedicated review profile configured with empty system prompt and no project context. For Gemini and OpenCode models, clean room is naturally achieved — they have no project context concept. The review prompt's boundary instructions provide the soft isolation layer across all models.

### Model Registry Details

The `invoke` field is an array of arguments passed to `subprocess.run()` (no shell). The engine substitutes `{prompt}` with the prompt text or `{prompt_file}` with the path to a temp file containing the prompt. Using array invocation prevents shell injection.

`clean_room_flags` are appended to the invoke array when `clean_room = true`. These are model-specific flags that suppress project-level context loading (e.g., `--profile review` for Claude).

`max_input_chars` is enforced per model. If the constructed prompt (including intent, file list, etc.) exceeds the model's limit, the engine rejects with an error: "Prompt exceeds model limit ({chars}/{max_input_chars} chars). Reduce scope or use a model with higher capacity."

The stage templates for workflow review gates are stored in `config/stage_templates.yaml` alongside this model registry file.

Adding a new model requires only a new entry in this YAML file — no code changes (R2.4).

### Model-Forward Principle

The review pipeline follows the vision's model-forward principle (Principle 3): models do understanding, code does mechanics.

**What code does:** CLI invocation, temp file management, parallel dispatch, timeout handling, database writes, job tracking, artifact storage.

**What models do:** Reading reviews, identifying consensus, deduplicating patterns, producing synthesis, grading reviewer quality (R5.5) — all comprehension tasks.

**What code does NOT do:** Parse model output into structured fields, extract findings via regex, impose output formats so downstream code can parse the result.

The self-similarity test: the synthesis model reads raw review outputs the same way a human would — no JSON parser sits between the reviewer's prose and the synthesis model's comprehension.

### Review Quality Grading (R5.5)

After producing the synthesis, the synthesis model also grades each reviewer's contribution. The grading prompt asks for a quality rating on a four-level scale — EXCELLENT (found critical issues others missed), ADEQUATE (solid review, no major gaps), INADEQUATE (shallow or missed obvious issues), HARMFUL (false positives, hallucinated findings, or misleading analysis) — and brief reasoning per reviewer. This is a natural extension of what the synthesis model already does — it has already evaluated each review's findings to produce the synthesis, so grading adds minimal overhead.

Quality grades are stored in the `review_grades` table — a dedicated per-model signal, separate from artifact-level usage feedback. Each grade records `model_name`, `review_type` (e.g., "code-review", "design-review", "security-review"), `grade` (EXCELLENT/ADEQUATE/INADEQUATE/HARMFUL), `job_id` (FK to the review run for traceability), and a `note` explaining what made the review effective or not (e.g., "found the critical race condition others missed" or "all 5 findings were false positives"). Over time, `get_review_quality(model_name, review_type?)` is a direct query against this table, optionally filtered by review type — no joins needed.

The grading output is structured (one grade + note per model) — this is an exception to the "no structured output" principle because the downstream consumer is code (database inserts), not another model. The synthesis prose remains unstructured.

---

## 7. Hook Integration

Hooks connect the new infrastructure to the Claude Code lifecycle. Context continuity hooks (PostToolUse, Stop, PreCompact, SessionStart) are file-based — they read from and write to local files (mechanical log JSONL, window files) with no HTTP calls to the FastAPI server. The legacy ledger system has been decommissioned and replaced by window files. Workflow hooks added in Phase 7+ may use HTTP to query the FastAPI server for active items. Each hook follows the existing pattern: shell wrapper → TypeScript handler (or direct shell for simple cases).

### 7.1 PostToolUse → Mechanical Log (R3.5)

The mechanical log is already implemented via `mechanical-log.sh` — a simple JSONL append to `~/roles/{role}/mechanical.jsonl` (falls back to `thoughts/mechanical.jsonl`). No server dependency, no database writes. The hook must be fast since it fires on every tool use.

```bash
#!/bin/bash
# .claude/hooks/mechanical-log.sh (already implemented)
# Appends tool operations to ~/roles/{role}/mechanical.jsonl (or thoughts/mechanical.jsonl)
# Simple JSONL append — no server dependency
```

Register in `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": {},
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mechanical-log.sh"
      }]
    }]
  }
}
```

An empty matcher `{}` matches all tool uses. To restrict to specific tools, use `{"tool_name": "Write"}` etc.

### 7.2 Stop → Window File Update (R3.2)

When a session's agent stops, check if enough work has been done to warrant a window file update. The Stop hook checks a ~20K token threshold before triggering a window file update.

```bash
#!/bin/bash
# hooks/stop-window-update.sh
set -e
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
[ -z "$SESSION_ID" ] && exit 0

# Check token threshold (~20K) using existing approach
# (existing hook logic already determines whether enough work was done)

# Fork a narrative-update agent (non-blocking)
~/.claude/scripts/fork-agent.sh \
    --task "Update window file for session $SESSION_ID. Read the narrative-update prompt at thoughts/windows/NARRATIVE_PROMPT.md, then read the current conversation context and mechanical log. Write or update the session's window file in ~/roles/{role}/windows/ (or thoughts/windows/claude-code/). Do NOT call any MCP tools — write files directly." \
    --session-id "$SESSION_ID" &
```

The forked agent:
1. Reads the narrative-update prompt from `thoughts/windows/NARRATIVE_PROMPT.md`.
2. Reads the current conversation context and mechanical log (`~/roles/{role}/mechanical.jsonl` or `thoughts/mechanical.jsonl`).
3. Writes or updates the current session's window file in `~/roles/{role}/windows/` (or `thoughts/windows/claude-code/`).
4. Writes files directly — does not call any MCP tools.

**Narrative-update prompt philosophy:** The prompt at `thoughts/windows/NARRATIVE_PROMPT.md` follows the "start with why" principle. It explains *why* we capture context (future sessions need orientation after compaction or `/clear`; decisions need retrieval weeks later; patterns emerge from accumulated observations) and *what good entries look like* (examples of useful context captures). It does not mandate sections or impose structure — the model in the moment is better positioned to decide what matters than a template designed in advance. The prompt is stored as a separate file for easy editing without code changes.

### 7.3 PreCompact → Window File Update + Context Injection (R3.6)

Before compaction, fork an urgent window file update and inject critical state into the compaction prompt. All sources are file-based — no HTTP calls.

```bash
#!/bin/bash
# hooks/pre-compact-window.sh
set -e
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Fork urgent window file update (same agent as Stop, but priority — non-blocking)
~/.claude/scripts/fork-agent.sh \
    --task "URGENT pre-compaction window file update for session $SESSION_ID. Read thoughts/windows/NARRATIVE_PROMPT.md, capture current context + mechanical log, write to window file in ~/roles/{role}/windows/ (or thoughts/windows/claude-code/). Write files directly — no MCP tools." \
    --session-id "$SESSION_ID" &

# Read open threads from current window file (if available)
# Resolve window directory: role-scoped or fallback
WINDOW_DIR="${ROLE_WINDOWS_DIR:-thoughts/windows/claude-code}"
CURRENT_WINDOW=""
WINDOW_POINTER="${WINDOW_DIR}/.current-${SESSION_ID}"
if [ -f "$WINDOW_POINTER" ]; then
    CURRENT_WINDOW=$(cat "$WINDOW_POINTER")
fi
OPEN_THREADS=""
if [ -n "$CURRENT_WINDOW" ] && [ -f "${WINDOW_DIR}/$CURRENT_WINDOW" ]; then
    OPEN_THREADS=$(cat "${WINDOW_DIR}/$CURRENT_WINDOW" | head -100)
fi

# Read recent operations from mechanical log JSONL file
MECH_LOG="${ROLE_DIR:+${ROLE_DIR}/mechanical.jsonl}"
MECH_LOG="${MECH_LOG:-thoughts/mechanical.jsonl}"
RECENT_OPS=$(tail -20 "$MECH_LOG" 2>/dev/null || echo "")

# Build the injection message
cat <<EOF
{
    "result": "continue",
    "systemMessage": "ACTIVE WORK STATE (preserve through compaction):\nRecent operations:\n${RECENT_OPS}\n\nCurrent window context:\n${OPEN_THREADS}\n\nAfter compaction, the window file at ${WINDOW_DIR}/ contains full state."
}
EOF
```

The `systemMessage` field in the hook output injects a system message into the compaction prompt. This influences what the compacted context retains.

### 7.4 SessionStart → Window Chain Loading (R3.3)

On session start, load context from the window file chain. This is entirely file-based — no HTTP calls, no artifact store queries (semantic retrieval from artifact store is deferred to Phase 3.5).

```bash
#!/bin/bash
# hooks/session-start-window.sh
set -e
INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.source // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Resolve window directory: role-scoped or fallback
WINDOW_DIR="${ROLE_WINDOWS_DIR:-thoughts/windows/claude-code}"

# Load context from window file chain
CONTEXT=""

case "$SOURCE" in
    "startup"|"resume")
        # On startup/resume: load current window file for this session
        WINDOW_POINTER="${WINDOW_DIR}/.current-${SESSION_ID}"
        if [ -f "$WINDOW_POINTER" ]; then
            CURRENT_WINDOW=$(cat "$WINDOW_POINTER")
            if [ -f "${WINDOW_DIR}/$CURRENT_WINDOW" ]; then
                # Follow parent chain for additional context (depth 3)
                CONTEXT=$(python3 -m claude_hub.continuity load-chain \
                    "${WINDOW_DIR}/$CURRENT_WINDOW" --depth 3 2>/dev/null || echo "")
            fi
        fi
        ;;
    "compact")
        # Post-compaction: orient to the window file updated by PreCompact fork
        WINDOW_POINTER="${WINDOW_DIR}/.current-${SESSION_ID}"
        if [ -f "$WINDOW_POINTER" ]; then
            CURRENT_WINDOW=$(cat "$WINDOW_POINTER")
            if [ -f "${WINDOW_DIR}/$CURRENT_WINDOW" ]; then
                CONTEXT=$(cat "${WINDOW_DIR}/$CURRENT_WINDOW")
            fi
        fi
        ;;
esac

if [ -n "$CONTEXT" ]; then
    jq -n --arg ctx "$CONTEXT" '{result: "continue", systemMessage: $ctx}'
fi
```

Behavior:
- **Startup/resume:** Load the current window file for the session (follow `.current-{session_id}` pointer in the role or harness directory). Follow the parent chain for additional context (configurable depth, default 3). Parent links may cross role and harness directories.
- **Post-compaction:** Orient to the window file that was just updated by the PreCompact fork.
- **New session without prior context:** No window file exists yet — starts fresh.

Note: Semantic retrieval from the artifact store (querying for topic-relevant past windows) is deferred to Phase 3.5. The Phase 3 implementation loads context purely through the window file chain.

---

## 8. Module Architecture

New Python modules under `src/claude_hub/`:

### 8.1 `database.py`
- `create_pool()` → asyncpg connection pool
- `run_migrations()` → apply pending SQL migrations
- Pool lifecycle management tied to FastAPI lifespan
- Context continuity hooks are file-based (no pool access needed). Workflow hooks access Postgres via HTTP to the FastAPI server (hooks are separate shell processes)

### 8.2 `artifact_store.py`
- `store_artifact(content, type, tags, source_ref, derives_from, metadata)` → UUID
- `get_artifact(id, include_versions, include_feedback)` → Artifact
- `search_artifacts(query_embedding, filters, limit)` → list[ArtifactResult]
- `list_artifacts(filters, limit, offset)` → list[Artifact], total_count
- `archive_artifact(id)` → bool
- `create_version(artifact_id, content)` → version_number
- `export_artifacts(format, type_filter)` → export_path
- `import_artifacts(path)` → import_report

### 8.3 `embedding.py`
- `generate_embedding(text)` → list[float]
- `generate_query_embedding(text)` → list[float]
- `schedule_embedding(artifact_id)` → None (fires and forgets)
- `embedding_retry_loop(pool)` → background coroutine
- `batch_embed(artifact_ids)` → BatchResult

### 8.4 `review_engine.py`
- `load_model_registry(config_path)` → dict[str, ModelConfig]
- `build_review_prompt(files, intent, prompt, exclude_paths, output_format)` → str — Constructs the task prompt from components. No output format is imposed on the reviewer.
- `dispatch_review(pool, files, prompt, intent, models, clean_room, exclude_paths, artifact_id, content)` → job_id
- `check_review_status(pool, job_id)` → ReviewStatus
- `get_review_results(pool, job_id, include_individual)` → ReviewResults (includes synthesis as prose)
- Internal: `_run_single_review(pool, review_id, job_id, model_name, model_config, prompt, clean_room)` → None (background task; stores raw output, no parsing)
- Internal: `_check_and_synthesize(pool, job_id)` → None (idempotent, guarded by UNIQUE constraint)
- Internal: `_synthesize_reviews(pool, job_id, reviews)` → None (passes raw review outputs to synthesis model; stores prose synthesis; inserts per-model quality grades into `review_grades` — R5.5)
- `get_review_quality(pool, model_name, review_type?)` → list[QualityRecord] (historical quality grades for a model from `review_grades` table — R5.5)

### 8.5 `continuity.py`
- `create_window(session_id, harness="claude-code", role=None, parent?)` → path (create new window file with YAML frontmatter in `~/roles/{role}/windows/` or `thoughts/windows/{harness}/`)
- `link_child(parent_path, child_path)` → None (update parent's `children` list in frontmatter; handles cross-harness relative paths)
- `find_current_window(session_id, harness="claude-code")` → path | None (follow `.current-{session_id}` pointer in harness directory)
- `find_latest_window(session_id?)` → path | None (find most recent window file, optionally for a session)
- `load_window_chain(path, depth=3)` → str (follow parent links, return assembled context)
- `migrate_ledgers(directory, dry_run=False)` → MigrateReport (convert existing `CONTINUITY_CLAUDE-*.md` ledgers to window files with YAML frontmatter — completed, ledger system decommissioned)

### 8.6 `workflow.py`
- `create_project(name, description)` → project_id
- `get_project_status(project_id)` → ProjectStatus
- `advance_stage(project_id, stage, artifact_id)` → AdvanceResult
- `list_items(project_id, status_filter)` → list[WorkItem]
- `create_item(project_id, description, spec_ref)` → item_id
- `update_item(item_id, status?, artifact_id?, description?)` → None

### 8.7 `connectors/` package
- `base.py` — `BaseConnector` ABC, `ConnectorResult`, `ConnectorItem`, `IndexReport`
- `registry.py` — `ConnectorRegistry`
- `artifact_connector.py` — `ArtifactConnector(BaseConnector)` — wraps artifact_store
- `filesystem_connector.py` — `FilesystemConnector(BaseConnector)` — indexes directory trees

### 8.8 `patterns.py`
- `detect_patterns(scope, threshold, include_dismissed)` → list[Pattern]
- `promote_pattern(pattern_id, target_type, draft?)` → artifact_id
- `dismiss_pattern(pattern_id)` → None
- Internal: `analyze_sessions_for_patterns(session_artifacts)` → list[CandidatePattern]

---

## 9. Build Order

### Phase 1: Foundation + Artifact Store (R1) — IMPLEMENTED

**This is the MVP. It produces a usable system.** Implemented as of March 2026.

Tasks:
1. Install Postgres 16 + pgvector on nexus.
2. Create database, user, tablespace.
3. Write `migrations/001_initial_schema.sql` with artifacts, artifact_versions, artifact_embeddings tables and indexes.
4. Implement `database.py` — pool creation, migration runner.
5. Implement `embedding.py` — Gemini API client, retry loop.
6. Implement `artifact_store.py` — full CRUD.
7. Add 9 MCP tools to `server.py`: `artifact_store`, `artifact_get`, `artifact_search`, `artifact_list`, `artifact_archive`, `artifact_update`, `artifact_update_metadata`, `artifact_export`, `artifact_import`.
8. Wire up pool lifecycle in FastAPI lifespan.
9. Write unit and integration tests.

**Acceptance tests:**
- Store a 10K-char artifact with metadata, retrieve by ID.
- Semantic search: 5 artifacts, 3 queries with different words, relevant artifact in top 2.
- Filter by type, date, tags, and combination with semantic search.
- Archive an artifact, verify search exclusion and ID retrieval.
- Export/restore cycle: export, delete, restore, verify all searchable.

**Deliverable:** A working artifact store with semantic search, accessible as MCP tools.

### Phase 2: Multi-Model Review (R2) — IMPLEMENTED

Tasks:
1. Write `config/review_models.yaml` with Claude, Gemini, and one OpenCode model.
2. Implement `review_engine.py`.
3. Write `migrations/002_reviews.sql` with reviews and review_syntheses tables.
4. CLI entrypoint: `python3 -m claude_hub.review_cli` (direct Python, no HTTP/MCP).

**Acceptance tests:**
- Dispatch review to 2 models with intent (spec reference), collect structured results.
- Reviewers demonstrate codebase exploration (reading files beyond those explicitly listed).
- Synthesis identifies consensus, unique findings, contradictions.
- Review stored as artifact in the artifact store.
- Add a model to YAML, run review including it — no code changes.
- Clean-room review: reviewer reads spec and codebase but does not reference process docs or CLAUDE.md.
- Sensitive artifact rejected with 400.

### Phase 3: Context Continuity (R3) — IMPLEMENTED

Tasks:
1. Create `~/roles/{role}/windows/` directory structure and define window file format (with role namespace, falling back to `thoughts/windows/{harness}/`).
2. Write narrative-update prompt (`thoughts/windows/NARRATIVE_PROMPT.md` — shared across harnesses and roles).
3. Implement `continuity.py` with window file management functions.
4. Adapt Stop hook to create/update window files.
5. Adapt PreCompact hook to write window files + inject context from file-based sources.
6. Adapt SessionStart hook to load from window file chain instead of HTTP artifact store.
7. Migrate existing `CONTINUITY_CLAUDE-*.md` ledgers: add YAML frontmatter, link as roots. (Completed; ledger system decommissioned.)
8. Write tests for window file creation, linking, chain traversal, migration.

**Acceptance tests:**
- Window file created during a session with ~20K+ tokens of work.
- After compaction, new window file links to pre-compaction window via parent.
- SessionStart loads context from window chain.
- Existing ledgers migrated with frontmatter, findable by chain traversal. (Completed.)
- Fork failure logged, does not interrupt main session.
- Parent links that cross harness boundaries (relative paths) are traversable by load_window_chain.
- Mechanical log continues working (no regression — already implemented).

### Phase 3.5: Context Load — Semantic Retrieval — IMPLEMENTED

**Depends on:** Phase 1 (artifact store) + Phase 3 (window files). Implemented as of March 2026.

Tasks:
1. Ingest window files into artifact store as they're created (index at creation time, per PostToolUse Write hook pattern).
2. Implement `context_search(topic, limit)` in `continuity.py` — semantic search across window file artifacts.
3. Extend SessionStart hook to optionally query artifact store for topic-relevant past windows.
4. CLI: `python3 -m claude_hub.continuity search --topic "..."`

**Acceptance tests:**
- Window files automatically ingested as artifacts on creation.
- Semantic search for a topic discussed in a past window returns relevant results.
- SessionStart with semantic retrieval loads context from both window chain and topically relevant past windows.

### Phase 4: Knowledge Quality (R5) — IMPLEMENTED

Tasks:
1. Write `migrations/003_knowledge_quality.sql`: `artifact_feedback` table (with `content_version`), `review_grades` table (with `review_type`, `grade`, `job_id`), add `confidence`, `utility_score`, and `last_retrieved` columns to artifacts.
2. Add 3 MCP tools: `artifact_feedback`, `artifact_set_confidence`, `artifact_retirement_candidates`.
3. Implement quality-weighted scoring in `artifact_search` (utility + confidence boosts).
4. Extend review synthesis to emit per-model quality grades into `review_grades` table (R5.5).
5. Add `get_review_quality` query helper: direct query on `review_grades` by model name.

**Acceptance tests:**
- Agent records positive feedback on a retrieved artifact; utility score increases.
- Artifact with high utility ranks above same-topic artifact with no feedback.
- Confidence set to SUPERSEDED excludes artifact from default search.
- Retirement candidates listed for old, low-utility artifacts.
- After a multi-model review, each reviewer's artifact has a quality grade.
- Quality grades are queryable by model name and accumulate across reviews.

### Phase 5: Connector Interface (R7) — IMPLEMENTED

Tasks:
1. Write `migrations/004_connectors.sql` with connectors and connector_index tables.
2. Implement `connectors/` package: base, registry, artifact_connector, filesystem_connector.
3. Add 3 MCP tools: `connector_register`, `connector_index`, `query_federated`.

**Acceptance tests:**
- Artifact store queryable through connector interface (same results as direct query).
- Filesystem connector indexes thoughts/ directory.
- Semantic search across filesystem connector works.
- Federated query merges results from artifact store + filesystem connectors.

### Phase 6: Capability Compounding (R4) — NOT STARTED

**Depends on:** Phase 1 (artifact store) + Phase 3 (window files) + Phase 4 (knowledge quality). All dependencies are now implemented.

Tasks:
1. Write `migrations/005_patterns.sql` with patterns table.
2. Implement `patterns.py`.
3. Add 3 MCP tools: `pattern_detect`, `pattern_promote`, `pattern_dismiss`.
4. Add auto-detection trigger in `artifact_store` (fires after every 10 session-summary artifacts).

**Acceptance tests:**
- Given 10 session summaries with recurring pattern, system detects it.
- Auto-detection fires after threshold new summaries.
- Pattern promotion creates artifact with lineage to source sessions.
- Dismissed patterns not resurfaced.

### Phase 7: Spec-Driven Workflow (R6) — PARTIALLY IMPLEMENTED

**Depends on:** Phase 1 (artifact store) + Phase 2 (multi-model review). The spec-driven development workflow exists in practice (vision -> requirements -> spec -> implementation with multi-model review gates) but is not yet formalized in tooling. The workflow tables and MCP tools are not yet implemented.

Tasks:
1. Write `migrations/006_workflow.sql` with workflow_projects and workflow_items tables.
2. Implement `workflow.py`.
3. Add 6 MCP tools: `workflow_create`, `workflow_status`, `workflow_advance`, `workflow_items`, `workflow_item_create`, `workflow_item_update`.

**Acceptance tests:**
- Create project, advance through stages with artifacts.
- Stage advance triggers review (unless skipped).
- Work items trackable through implementation.
- State loads on session start without manual reconstruction.

### Phase 8: Migration + Polish — NOT STARTED

Tasks:
1. Ingest all existing window files into artifact store.
2. Index thoughts/ directory via filesystem connector.
3. End-to-end test across all requirements.
4. Performance testing: semantic search under 2 seconds with 10,000 artifacts.
5. Documentation: update CLAUDE.md, shared-context.md, CONTEXT.md with new infrastructure.

### Dependency Graph

```
Phase 1 (Artifact Store) ✓ ───┬── Phase 2 (Review) ✓ ───────┐
                               ├── Phase 3 (Continuity) ✓ ┐  │
                               │   └── Phase 3.5 (Load) ✓ ┤  │
                               ├── Phase 4 (Quality) ✓ ─┐  │  │
                               └── Phase 5 (Connectors) ✓│  │  │
                                                          │  │  │
                                   Phase 6 (Patterns) ←──┘──┘  │
                                   Phase 7 (Workflow) ←─────────┘
                                   Phase 8 (Migration) ← all
```

**Implementation status (March 2026):** Phases 1-5 are implemented. Phase 6 (Capability Compounding) has all dependencies met but has not been started. Phase 7 (Spec-Driven Workflow) is partially implemented — the workflow pattern is in active use but the formal tooling (tables, MCP tools) is not yet built. Phase 8 (Migration + Polish) awaits completion of Phases 6-7.

Phase 3 itself has NO dependency on Phase 1 — it is entirely file-based (window files, mechanical log JSONL). Phase 3.5 depends on both Phase 1 (artifact store for semantic retrieval) and Phase 3 (window files to ingest). After Phase 1, Phases 2-5 have no mutual dependencies and can be built in any order or in parallel. Phase 3 can even begin before Phase 1. Phase 6 requires 1+3+4. Phase 7 requires 1+2. Phase 8 requires all.

---

## 10. Testing Strategy

### Unit Tests (pytest)

Each module gets a test file:
- `test_artifact_store.py` — CRUD operations, dedup, versioning, archival
- `test_embedding.py` — embedding generation (mocked API), retry logic
- `test_review_engine.py` — model dispatch (mocked), synthesis logic
- `test_continuity.py` — window file creation, linking, chain traversal, migration
- `test_workflow.py` — state transitions, work items
- `test_connectors.py` — registry, federation, individual connector behavior
- `test_patterns.py` — detection, promotion, dismissal

Unit tests mock the Postgres connection pool and external APIs (Gemini, model CLIs).

### Integration Tests

Run against a test Postgres instance (separate database `claude_hub_test`):
- Schema migration applies cleanly.
- Artifact store → embed → search round-trip.
- Review dispatch → collect → synthesize (with at least one real model if available, otherwise mocked).
- Window file create → link → chain load cycle.
- Connector registration → index → query.

### Acceptance Tests

One test per acceptance criterion in the requirements doc. These are the definitive pass/fail criteria. Examples:

- **R1.2**: Store 5 artifacts on different topics. Run the fixed evaluation set (3 queries with different words). Relevant artifact in top 2 for each.
- **R2.2**: Given 3 model reviews, synthesis identifies consensus, unique, contradictions. Synthesis shorter than combined reviews.
- **R5.3**: Two artifacts same topic, one with positive usage feedback (high utility_score) and one with no feedback (neutral utility_score). Semantic query returns the high-utility artifact first.

### Embedding Evaluation Set

Per R1.2, maintain a fixed evaluation set for regression testing:

```python
EVAL_SET = [
    {
        "artifact": "Considering consulting work next year, freelance projects",
        "query": "career planning decisions",
        "expected_rank": 1,  # Should be in top 2
    },
    {
        "artifact": "Switched from SQLite to Postgres for concurrent write support",
        "query": "database migration choices",
        "expected_rank": 1,
    },
    {
        "artifact": "The OAuth 2.1 flow uses PKCE with SHA-256 code challenge",
        "query": "authentication security implementation",
        "expected_rank": 1,
    },
]
```

Run this set after any embedding or indexing changes.

---

## 11. Open Decisions

These are genuine unknowns to resolve during implementation:

**asyncpg vs psycopg3.** asyncpg is faster and has native prepared statement support. psycopg3 has a more familiar interface. The pgvector library now supports asyncpg natively via `pgvector.asyncpg.register_vector(pool)`, which handles vector serialization automatically — this eliminates the main advantage psycopg3 had (native pgvector integration). With this parity, asyncpg's performance advantage makes it the stronger default. Decision deferred to Phase 1 for hands-on confirmation.

**Review dispatch: subprocess vs API.** The model registry uses CLI invocation templates (subprocess). This is simple and works for all models (Claude CLI, Gemini CLI, OpenCode CLI). The alternative — direct API calls — would be faster and more reliable but requires per-model API client code, defeating the configuration-only model registry goal (R2.4). Start with subprocess; revisit if reliability becomes a problem.

**Embedding retry interval and max retries.** Spec says 60 seconds and 5 retries. These may need tuning based on observed Gemini API error patterns. Make them configurable via environment variables:
- `CLAUDE_HUB_EMBEDDING_RETRY_INTERVAL=60`
- `CLAUDE_HUB_EMBEDDING_MAX_RETRIES=5`

**Postgres connection string management.** RESOLVED — env var `CLAUDE_HUB_PG_DSN` in both the systemd unit file and shell profile (`~/.bashrc`). Simple, standard, no new config mechanism. Context continuity hooks are file-based (no Postgres access needed). Workflow hooks access Postgres via HTTP to the FastAPI server. The DSN is only needed for standalone scripts.

**HNSW index parameters.** The spec uses `m = 16, ef_construction = 64`, which are reasonable defaults for up to ~100K vectors. At the expected scale (10K artifacts), these provide good recall without excessive memory. May need tuning if search quality is insufficient.

**Content hash algorithm.** SHA-256 is specified. Alternatives (xxhash for speed, BLAKE3 for modern performance) are faster but SHA-256 is universally available and speed is not critical for this write path.

**Content hash format.** SHA-256 of the raw UTF-8 encoded bytes of the content string, hex-encoded. No normalization (whitespace, encoding) is applied before hashing. This means the same text with different trailing whitespace produces different hashes — by design, since whitespace may be semantically significant in code artifacts.

---

## Summary

This spec defines a Postgres-backed personal AI infrastructure extending the existing claude-hub MCP server with:

- **11 tables** across 5 functional areas (artifacts, reviews, workflow, connectors, patterns) plus file-based window architecture for context continuity
- **24 MCP tools** organized by 7 requirements (9 artifact, 0 review (CLI-based), 0 continuity (file/hook-based), 3 knowledge-quality, 3 pattern, 6 workflow, 3 connector) plus internal HTTP endpoints for workflow hooks
- **Window file architecture** for context continuity — one markdown file per context window, linked via YAML frontmatter, content guided by narrative prompts rather than fixed sections
- **Google Gemini embedding pipeline** with async-on-write and retry queue
- **Connector interface** with abstract base class, registry, and 2 reference implementations
- **Configuration-based review model registry** (YAML, no code changes to add models)
- **4 hook integration points** for mechanical logging, window file updates, compaction injection, and context loading (context continuity hooks are file-based; workflow hooks added in Phase 7 may use HTTP)
- **9-phase build order** (including Phase 3.5 for semantic retrieval) with Phase 1 as standalone MVP, Phase 3 buildable independently of Phase 1, and explicit parallelism after Phase 1
- **5 open decisions** to resolve during implementation (1 resolved: Postgres connection string)

The system runs within nexus's 4GB RAM constraint by using API-based embeddings, moderate connection pooling (2-10 connections), and HNSW indexes that scale to the expected 10,000-artifact range with ~30MB memory overhead.
