Loaded cached credentials.
(node:1026876) MaxListenersExceededWarning: Possible EventTarget memory leak detected. 11 abort listeners added to [AbortSignal]. MaxListeners is 10. Use events.setMaxListeners() to increase limit
(Use `node --trace-warnings ...` to show where the warning was created)
The implementation of the Phase 1 Artifact Store is functionally comprehensive and aligns well with the architectural intent, particularly in its handling of sensitivity and vector search. However, there are critical deployment and API surface gaps that must be addressed for the system to be production-ready.

### 1. Critical Findings

*   **Missing `pgvector` Extension:**
    *   **File:** `migrations/001_initial_schema.sql`
    *   **Issue:** The migration creates tables with the `vector(768)` type but does not execute `CREATE EXTENSION IF NOT EXISTS vector;`.
    *   **Impact:** The migration will fail on any fresh database instance.
*   **Broken `pg_dump` Export:**
    *   **File:** `src/claude_hub/artifact_store.py`, Line 378
    *   **Issue:** `subprocess.run` calls `pg_dump` without passing any connection parameters (host, port, user, password, or database name).
    *   **Impact:** The command will fail unless the environment is perfectly configured with `.pgpass` or env vars; the code comment at line 375 notes this but the implementation is missing.
*   **Missing Outcome Tracking API Surface (R5):**
    *   **Files:** `src/claude_hub/artifact_store.py`, `src/claude_hub/server.py`
    *   **Issue:** While the `artifact_outcomes` table and search-boosting logic are implemented, the `artifact_rate` and `artifact_unrated` tools defined in Spec sections 4.4 and 4.8 are missing.
    *   **Impact:** There is currently no way for the user or agent to record outcomes, rendering the outcome-boosting search logic useless for live data.

### 2. Important Findings

*   **Tablespace Dependency:**
    *   **File:** `migrations/001_initial_schema.sql`, Lines 11-49
    *   **Issue:** Every table and index is pinned to `TABLESPACE artifact_data`.
    *   **Impact:** Migrations will fail unless this specific tablespace is manually created by a superuser beforehand. This should be documented as a prerequisite or made configurable.
*   **Hardcoded Volume Path:**
    *   **File:** `src/claude_hub/artifact_store.py`, Line 23
    *   **Issue:** `_BACKUP_DIR` is hardcoded to a specific Hetzner volume path (`/mnt/HC_Volume_...`).
    *   **Impact:** Prevents portability across environments/operating systems.
*   **`import_artifacts` OOM Risk and Performance:**
    *   **File:** `src/claude_hub/artifact_store.py`, Line 427
    *   **Issue:** Uses `json.loads(import_path.read_text())` to load the entire backup into memory. For large backups (R1.7), this risks OOM. Additionally, it executes one transaction per artifact (Lines 455-502).
    *   **Impact:** Slow and potentially unstable for large data migrations.

### 3. Minor Findings

*   **Search Boost Magic Numbers:**
    *   **File:** `src/claude_hub/artifact_store.py`, Lines 197-202
    *   **Issue:** Boost values (0.2, 0.1, etc.) are hardcoded in the SQL string rather than using the `_OUTCOME_BOOST` dict defined at Line 26.
    *   **Impact:** Maintenance burden; updating the dict won't update the search behavior.
*   **Conservative Retry Sweep:**
    *   **File:** `src/claude_hub/embedding.py`, Line 20
    *   **Issue:** `_SWEEP_BATCH_SIZE` is set to 10 with a 60s poll.
    *   **Impact:** Recovery from a prolonged API outage or large import will be slow (e.g., 1,000 pending embeddings would take ~1.6 hours to clear).

### 4. Confirmed Correct (High Integrity)

*   **Sensitivity Logic:** `sensitive=True` is rigorously respected across `store_artifact`, `embed_artifact`, `batch_embed`, and `_sweep_pending`. This ensures PII/secrets never reach the Gemini API.
*   **Deduplication (R1.1):** The use of a partial unique index `idx_artifacts_dedup` combined with `UniqueViolationError` handling in `store_artifact` (Lines 125-139) is a robust way to handle the race condition between check and insert.
*   **Vector Search Implementation:** The use of `1 - (<=>)` for cosine similarity and the `LATERAL` join for outcome fetching is idiomatic and performant for the target scale.
*   **Async/Sync Boundary:** `asyncio.to_thread` for `genai.embed_content` correctly prevents blocking the event loop for the synchronous Google library.

### 5. Test Coverage Gaps

*   **Integration:** There are no tests for the `import_artifacts` or `export_artifacts` logic, which contain the most complex file/subprocess interactions.
*   **Concurrent Access:** Tests use a mocked `pool`, so they do not verify transaction isolation or the `UniqueViolationError` behavior in a real database context.
*   **Search Ranking:** `test_results_include_expected_fields` verifies fields but not the *order* or the outcome boost logic.
