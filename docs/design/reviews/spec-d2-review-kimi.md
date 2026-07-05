[0m> build · kimi-k2.5

[0m

[0m→ [0mRead thoughts/ledgersI'll review this spec systematically. Let me first check for any active ledgers or additional context that might be relevant.
[0m
/home/claude/claude-hub/thoughts/shared/requirements-personal-ai-infrastructure.md
/home/claude/claude-hub/thoughts/shared/spec-personal-ai-infrastructure.md
/home/claude/claude-hub/thoughts/shared/vision-personal-ai-infrastructure.md[0m

[0m$ [0mfind /home/claude/claude-hub -name "requirements-personal-ai-infrastructure.md" -o -name "*personal-ai*" 2>/dev/null | head -20
[0m→ [0mRead thoughts/shared/requirements-personal-ai-infrastructure.md
[0m✱ [0mGlob "**/server.py"[90m 1 match[0m
[0m✱ [0mGlob "**/mcp*.py"[90m 0 matches[0m
[0m→ [0mRead src/claude_hub/server.py
Now I have comprehensive context. Let me provide my structured review:

---

## Review: Spec — Personal AI Infrastructure (Draft 2)

### **Critical Issues (Block Implementation)**

| # | Location | Issue | Suggestion |
|---|----------|-------|------------|
| C1 | §2.1:175, §3.2:462 | **Vector serialization format incorrect** — `str(embedding)` on a Python list produces `[0.1, 0.2, ...]` but pgvector expects `'[0.1, 0.2, ...]'::vector` or array literal | Use `asyncpg`'s built-in pgvector support or format as `'[' || array_to_string(embedding, ',') || ']'` |
| C2 | §4.1:590-618 | **Outcome-weighted search SQL has malformed COALESCE** — Line 602-603 shows `COALESCE(CASE ... END, 0)` inside a score formula, but the CASE is incomplete (line 603 has `COALESCE(CASE ... END, 0) AS final_score` which references undefined CASE) | Fix SQL: the CASE should be wrapped or the subquery aliased properly. Simpler: `base_score + COALESCE(outcome_boost, 0) AS final_score` |
| C3 | §4.1:541-542 | **Deduplication logic contradicts schema** — Spec says dedup by "content_hash + source_ref" but line 541 says "same content_hash AND same source_ref (if provided)" — if source_ref is NULL in both, this matches any artifact with same hash regardless of source | Define behavior: if both source_refs are NULL, should it dedup? Probably yes for identical content from "unknown" sources |
| C4 | §4.3:844-855 | **`/log_operation` endpoint missing** — Section 1.3 says PostToolUse hook uses `curl` to `/log_operation`, but this endpoint isn't defined in the API surface | Add the endpoint definition with request/response models, or define what the curl target actually is |
| C5 | §3.1:397-409 | **Gemini embedding client sync/async mismatch** — `genai.embed_content()` is synchronous; the async wrapper uses `asyncio.to_thread()` but error handling and retry logic aren't specified | Define what happens when embedding fails (rate limit, API error, network timeout) — these need specific exception handling |

### **Important Issues (Should Fix Before Implementation)**

| # | Location | Issue | Suggestion |
|---|----------|-------|------------|
| I1 | §2.1:156, §4.1:536 | **`sensitive` flag inconsistent** — Schema defines `sensitive BOOLEAN` on artifacts (line 156), but spec says "sensitive content never sent to third-party APIs" — yet embedding happens automatically on write. How do sensitive artifacts get embedded? | Clarify: sensitive artifacts skip embedding entirely (stored but not searchable via vector), or use local-only embedding |
| I2 | §4.2:750-781 | **Review dispatch content resolution underspecified** — Three content sources (artifact_id, content, file_path) but priority/conflict resolution isn't defined when multiple are provided | Define precedence: exactly one required → 400 if 0 or 2+ provided; artifact_id takes precedence if multiple somehow present |
| I3 | §4.6:1029-1033 | **Stage templates path not validated** — References `config/stage_templates.yaml` but this path isn't in the infrastructure section | Either add to §1 as a config file location or make it an env var/parameter |
| I4 | §5.1:1139-1272 | **Connector ABC missing `index` return type consistency** — `index()` returns `IndexReport` but §5.2 federated_query doesn't show how IndexReport integrates with connector_index table | Clarify relationship: does `index()` populate `connector_index` table directly or return data for caller to store? |
| I5 | §2.5:282-308 | **connector_index.embedding vs artifact_embeddings mismatch** — Schema stores embeddings directly in connector_index (line 302), but search in §4.7:1126-1131 suggests querying both. How are these kept in sync? | Define: connector_index has its own vectors; no sync needed. But then why have both tables? |
| I6 | §4.4:881-927 | **Outcome reasoning searchable but not embedded** — R5.4 says reasoning is searchable, but only appended to metadata (line 894). Metadata is GIN-indexed (line 339) which supports text search, but not semantic search | Clarify: "searchable" means keyword/GIN search, not semantic. If semantic search on reasoning is needed, it should be concatenated to artifact content before embedding |
| I7 | §3.2:165-166 | **Token threshold monitoring not specified** — R3.2 requires "token consumption thresholds (approximately every 20K tokens)" but spec doesn't define how this is measured or triggered | Add mechanism: hook callback, periodic check, or token counter in SessionManager? Needs explicit design |
| I8 | §1.3:100 | **Hook HTTP access pattern inefficient** — Every tool use triggers curl to FastAPI. At high frequency (file edits in a loop), this creates process overhead per operation | Consider batching or direct SQLite fallback for mechanical_log hot path, with async sync to Postgres |
| I9 | §4.1:534 | **UUID validation for derives_from incomplete** — Validates "each UUID string" but doesn't specify behavior on invalid UUID format | Define: 400 error with specific message indicating which index in the list failed validation |

### **Minor Issues (Nice to Have)**

| # | Location | Issue | Suggestion |
|---|----------|-------|------------|
| M1 | §2.1:148 | **content_hash generation not specified** — SHA-256 of what exactly? Raw text? Normalized (stripped whitespace)? | Add: "SHA-256 of UTF-8 encoded content, raw bytes, no normalization" |
| M2 | §2.1:169 | **artifact_versions content_hash not unique** — Should (artifact_id, content_hash) be unique to prevent storing identical versions? | Consider UNIQUE(artifact_id, content_hash) to prevent no-op version creation |
| M3 | §3.3:474 | **Startup recovery sweep race condition** — "immediate sweep" on startup could conflict with embedding_retry_loop starting simultaneously | Document: use asyncio.Lock or sequential initialization |
| M4 | §4.2:772 | **Synthesis model "Claude" is ambiguous** — Which Claude? Sonnet, Opus, Haiku? Via API or local Claude Code? | Specify: "Claude 3.5 Sonnet via Anthropic API" or whichever model |
| M5 | §2.3:237-246 | **mechanical_log has no cleanup policy** — Table grows unbounded; R3.5 says log is truncated after summarization but §3.5 isn't shown | Add migration or retention policy: truncate after 30 days or N rows? |
| M6 | §4.5:950 | **Pattern detection threshold inconsistency** — Spec says "every 10 new session-summary artifacts" trigger automatic detection, but R4.1 says "configurable threshold (e.g., every 10)" | Clarify: is 10 hardcoded or configurable? If configurable, where is config stored? |
| M7 | §1.4:104-122 | **Migration runner not shown** — Schema defined but Python runner code not included | Add reference implementation or link to existing migration pattern in codebase |

### **Internal Contradictions**

1. **Pool singleton removed but referenced**: Section 1.3 line 18 says "Removed pool singleton text (hooks are separate processes)" — yet line 100 says hooks "using the server's connection pool rather than opening their own connections". These contradict: hooks can't use the server's pool if they're separate curl processes. (Hooks use HTTP, not pool — clarify this distinction.)

2. **Review model registry location**: Section 4.2 mentions model registry for dispatch, but §5 doesn't define it. Section 4.6 line 1033 says templates are in `config/stage_templates.yaml` "alongside the review model registry" — but registry location was never specified.

3. **Embedding retry_loop vs startup_recovery**: Section 3.3 shows `embedding_retry_loop` runs every 60 seconds, but §1.3 line 474 mentions "startup recovery sweep" — is this the same loop or separate? Clarify they're the same function with immediate first iteration.

4. **derives_from cardinality**: Schema (§2.1:153) defines `derives_from UUID[]` (array), but lineage description (§6.3:300) says "A requirements doc references its vision doc" (singular). The schema supports multiple parents (DAG), but examples imply single parent (tree). Both are valid but should be explicit: DAG or tree?

### **Components That Wouldn't Work As Described**

1. **Embedding serialization (C1 above)**: The Python list→string conversion won't work with pgvector without proper formatting.

2. **Outcome-weighted search SQL (C2 above)**: The COALESCE/CASE construction has syntax issues and will fail.

3. **Hook HTTP pattern without defined endpoints**: PostToolUse hook calls `/log_operation` but this endpoint isn't defined in §4.3 or elsewhere.

4. **Review synthesis timeout**: Line 772 mentions "timeout after 5 minutes per model" but there's no timeout mechanism shown in the dispatch logic.

5. **Connector index embeddings**: connector_index stores its own embeddings (line 302) but the batch_embed function (§3.4:481-506) only updates artifact_embeddings. The connector_index.embedding_status will never transition to 'complete'.

### **API Surface Assessment (31 Tools)**

The 31 tools are internally consistent and well-organized by requirement. However:

- **Missing**: `/log_operation` endpoint (mentioned in hooks but not defined)
- **Inconsistent naming**: `artifact_store` creates, but `connector_register` also creates — should be `connector_create` for consistency? (Minor style issue)
- **Missing return field**: `review_dispatch` returns `{ job_id, models_dispatched }` but doesn't include the artifact_id of the created review artifact (needed for lineage tracking per R6.3)
- **Parameter inconsistency**: `artifact_search` uses `date_from/date_to` (ISO strings) but SQL would prefer TIMESTAMPTZ — conversion logic not shown

### **Build Order Soundness**

The 8-phase build order isn't explicitly shown in the excerpt I can see (cut off at line 1306), but from the dependencies described:

**Dependency Graph Analysis:**
- R1 (Artifact Store) is correctly foundational
- R3.5 (mechanical_log) can indeed be built independently — validates correctly
- R7 depends on R1 — correct
- R2 depends on R1 — correct
- R6 depends on R2 — correct

**Potential issue**: If the spec was cut off before showing phases, I can't assess the phase ordering. The dependency graph appears sound based on requirements.

### **Hook Integration with Claude Code**

**Major concern**: The spec assumes these hooks exist in Claude Code:
- PostToolUse (for mechanical_log) — **exists in Claude Code**
- Stop (for log_unsummarized_count) — **exists**
- PreCompact (for context injection) — **exists in OpenCode, not Claude Code**
- SessionStart (for outcome prompting) — **exists**

**Critical gap**: Section 1.3 says PreCompact "injects open threads + active work items" but Claude Code's PreCompact doesn't support arbitrary prompt injection — it only affects what gets compacted. The spec describes influencing "what the compaction retains" (R3.6:188) which is correct, but the injection mechanism needs clarification: is this modifying the compaction prompt template, or something else?

**Hook routing**: The curl-to-FastAPI pattern is sound for process isolation, but requires the FastAPI server to be running on localhost:8420. If the server isn't running, hooks fail. Needs fallback or startup ordering guarantee.

---

## Overall Assessment

**Status: Needs Revision Before Implementation**

The spec is comprehensive and well-structured, addressing all 24 findings from the 6-model review of Draft 1. The data model is sound, the API surface is mostly consistent, and the requirement coverage is good.

**However**, there are **5 critical issues** that would block implementation:

1. Vector serialization format won't work with pgvector
2. Outcome-weighted SQL has syntax errors  
3. `/log_operation` endpoint is referenced but undefined
4. `sensitive` flag interaction with embedding pipeline unclear
5. derives_from validation and deduplication logic has edge cases

**Recommendation**: Fix C1-C5, address I1-I9, then proceed to implementation. The architecture is sound; these are implementation-detail gaps, not design flaws.
