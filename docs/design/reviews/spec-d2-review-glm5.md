[0m
> build · glm-5
[0m

[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1307][0m# Spec Review: Personal AI Infrastructure (Draft 2)

## Critical Findings

### C1. Hook Input Schema Assumptions
**Location:** Section 7 (all hooks)

**Issue:** All hooks assume input fields that may not match Claude Code's actual hook output schema:
- PostToolUse: reads `.session_id`, `.tool_name`, `.tool_input.file_path`
- Stop: reads `.session_id`
- PreCompact: reads `.session_id`
- SessionStart: reads `.type`

**Suggestion:** Verify against actual hook schemas before implementation. The hook-developer skill has the authoritative schemas. At minimum, add a validation step: "Before Phase 3, verify hook input schemas against Claude Code documentation."

---

### C2. MCP Tool Count Discrepancy
**Location:** Summary (line 1873), Changes header (line 10)

**Issue:** Spec claims "31 MCP tools" but Section 4 lists only 30:
- R1: 9, R2: 3, R3: 4, R5: 2, R4: 3, R6: 6, R7: 3 = **30 tools**

The changes header says "31 total, up from 28" but 28+4=32, not 31.

**Suggestion:** Reconcile the count. Either:
1. There's a missing tool not listed in Section 4
2. The count should be 30
3. Internal HTTP endpoints (`/log_operation`, etc.) were mistakenly counted as MCP tools

---

### C3. PreCompact Hook Output Format
**Location:** Section 7.3, lines 1519-1525

**Issue:** Hook outputs JSON with `result: "continue"` and `message: "..."`. This format may not match Claude Code's expected PreCompact hook output schema.

**Suggestion:** Verify the correct output format for PreCompact hooks. The hook should likely output plain text that gets injected, not a JSON envelope.

---

## Important Findings

### I1. Missing Internal HTTP Endpoints
**Location:** Section 7 references endpoints not defined in Section 4

**Issue:** Hooks call these endpoints that aren't documented in API Surface:
- `/log_unsummarized_count` (line 1465)
- `/log_recent` (line 1502)
- `/workflow_active_items` (line 1508)

**Suggestion:** Add Section 4.8 "Internal HTTP Endpoints" documenting these:
```
POST /log_unsummarized_count — Return count of unsummarized log entries
POST /log_recent — Return recent log entries for a session
GET /workflow_active_items — Return all in-progress work items
```

---

### I2. Embedding Vector Serialization Incorrect
**Location:** Section 3.3, lines 457-462

**Issue:** Code uses `str(embedding)` which won't work with asyncpg + pgvector:
```python
await pool.execute("""
    UPDATE artifact_embeddings
    SET embedding = $1, ...
""", str(embedding), row['id'])
```

**Suggestion:** Use proper vector format. With asyncpg:
```python
from pgvector.asyncpg import register_vector
# Register on pool creation
await register_vector(conn)
# Then pass list directly
await pool.execute(..., embedding, row['id'])
```
Or use the `pgvector.asyncpg` helper. This is noted in Open Decisions but the code example is wrong.

---

### I3. Pattern Auto-Detection State Tracking
**Location:** Section 4.5, lines 950-951

**Issue:** "The `artifact_store` tool tracks the count and fires `pattern_detect` when the threshold is crossed."

Where is this count stored? In-memory (lost on restart)? In database? Needs explicit design.

**Suggestion:** Add a `system_state` table or use a config file:
```sql
CREATE TABLE system_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);
-- Store: {"session_summary_count_since_last_pattern_check": 7}
```

---

### I4. Review Synthesis Model Selection
**Location:** Section 4.2, line 772

**Issue:** "trigger synthesis via Claude (the synthesis model)" — but how is this configured? The model registry has multiple models. Is synthesis model hardcoded?

**Suggestion:** Add to model registry or config:
```yaml
synthesis:
  model: claude
  # or: model: gemini
```

---

### I5. Clean-Room Implementation Vague for Non-Claude Models
**Location:** Section 6, lines 1389-1402

**Issue:** OpenCode models have `clean_room_args: ""` with comment "clean room is achieved by not passing any system prompt beyond the review instructions." This is vague — what does the review engine actually do differently?

**Suggestion:** Document the clean-room invocation flow:
```
For clean_room=true:
1. Write only artifact content + prompt to temp file
2. Invoke model with NO system prompt, NO CLAUDE.md
3. For CLI wrappers: use clean_room_args flags
4. For API wrappers: omit system_prompt parameter
```

---

### I6. Dedup Behavior When source_ref is NULL
**Location:** Section 4.1, lines 542-544

**Issue:** "same content_hash AND same source_ref (if provided)" — ambiguous when source_ref is NULL. Does NULL match NULL? Or does "if provided" mean "if non-NULL"?

**Suggestion:** Clarify:
```
Dedup logic:
- If source_ref IS NOT NULL: dedup on (content_hash, source_ref)
- If source_ref IS NULL: dedup on content_hash alone
- NULL source_ref matches NULL source_ref in SQL
```

---

### I7. PreCompact Fork Race Condition
**Location:** Section 7.3, lines 1496-1499

**Issue:** Forks ledger update agent non-blocking (`&`). If compaction completes before forked agent finishes, ledger won't be updated in time for compaction to use it.

**Suggestion:** Either:
1. Make ledger update blocking (but this delays compaction)
2. Accept that ledger update is for *next* session, not current compaction
3. Write urgent state directly in hook (no fork), then fork for full ledger update

---

### I8. Federated Query SQL Not Shown
**Location:** Section 4.7, lines 1127-1129

**Issue:** "query `connector_index.embedding` directly using vector similarity" — but no SQL shown.

**Suggestion:** Add example:
```sql
SELECT ci.id, ci.title, ci.content_preview, ci.source_path,
       1 - (ci.embedding <=> $1::vector) AS score
FROM connector_index ci
WHERE ci.connector_id = $2
  AND ci.embedding IS NOT NULL
ORDER BY score DESC
LIMIT $3
```

---

## Minor Findings

### M1. HNSW ef_search Setting Ambiguity
**Location:** Section 2.7, line 380

**Issue:** "Set `SET hnsw.ef_search = 64` at session start" — "session" is ambiguous (Postgres connection vs Claude session).

**Suggestion:** "Set per connection after pool acquisition, or per-query via `SET LOCAL hnsw.ef_search = 64`."

---

### M2. Embedding Startup Recovery Not in Code
**Location:** Section 3.3, lines 474-475

**Issue:** Text describes startup recovery sweep, but code example only shows 60-second loop.

**Suggestion:** Add startup sweep code:
```python
async def start_embedding_retry_loop(pool):
    # Immediate sweep on startup
    await process_pending_embeddings(pool)
    # Then enter polling loop
    while True:
        await asyncio.sleep(60)
        await process_pending_embeddings(pool)
```

---

### M3. Rateable Types Hardcoded
**Location:** Section 4.4, line 926

**Issue:** Rateable types list is hardcoded in SQL comment.

**Suggestion:** Make configurable via system_state table or config file.

---

### M4. Pattern Detection Scope "Recent" Undefined
**Location:** Section 4.5, line 936

**Issue:** "last 20 sessions" — how determined? By artifact count? By date?

**Suggestion:** "last 20 session-summary artifacts by created_at DESC".

---

### M5. Export Path Hardcoded
**Location:** Section 4.1, lines 722-723

**Issue:** `/mnt/HC_Volume_104288266/data/backups/artifacts/` is hardcoded.

**Suggestion:** Use environment variable `CLAUDE_HUB_BACKUP_PATH` or config.

---

### M6. Stop Hook Error Handling Missing
**Location:** Section 7.2

**Issue:** PostToolUse hook has `|| true` for silent failure. Stop hook doesn't.

**Suggestion:** Add `2>/dev/null || true` to curl calls in Stop hook.

---

## Internal Contradictions

1. **MCP tool count**: Claims 31, lists 30
2. **Embedding serialization**: Code shows `str(embedding)`, Open Decisions acknowledges this needs resolution

---

## Components That Wouldn't Work As Described

1. **Hook input parsing**: jq commands assume fields that may not exist
2. **PreCompact output format**: JSON envelope may not be valid
3. **Embedding serialization**: `str(embedding)` fails with asyncpg+pgvector

---

## Build Order Assessment

**Sound.** Dependencies are correct:
- Phase 1 standalone ✓
- Phases 2-5 parallelizable ✓
- Phase 6 needs 1+3+4 ✓
- Phase 7 needs 1+2 ✓
- Phase 8 needs all ✓

---

## Overall Assessment

**Not ready for implementation.** 

The spec needs another revision to address:
1. Hook schema verification (Critical)
2. MCP tool count reconciliation (Critical)
3. Missing internal endpoints (Important)
4. Embedding serialization fix (Important)
5. Pattern auto-detection state design (Important)

**Recommendation:** Before Draft 3, run a focused review of hook integration against actual Claude Code hook schemas, and add the missing internal endpoint documentation.
