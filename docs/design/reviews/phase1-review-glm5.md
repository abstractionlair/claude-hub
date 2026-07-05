
> build · glm-5


→ Read migrations/001_initial_schema.sql
→ Read src/claude_hub/database.py→ Read src/claude_hub/artifact_models.py
→ Read src/claude_hub/embedding.py
→ Read src/claude_hub/artifact_store.py
→ Read src/claude_hub/server.py [offset=95, limit=11]
→ Read src/claude_hub/server.py [offset=2370, limit=181]
→ Read thoughts/shared/spec-personal-ai-infrastructure.md
→ Read tests/test_artifact_store.py
→ Read tests/test_embedding.py
→ Read tests/test_database.py
I'll read all the files in parallel to conduct the review.
## Phase 1 Artifact Store Review

### Critical (blocks production use)

1. **pg_dump missing database connection** — `artifact_store.py:739-756`
   - The `pg_dump` subprocess call has no `-d` or connection string argument
   - Will fail or use wrong database depending on environment
   - Fix: Pass DSN via `--dbname=` or environment variable

### Important (should fix before relying on it)

1. **Missing empty content validation in update_artifact** — `artifact_store.py:535-659`
   - Spec requires "Empty content → 400" but no validation exists
   - Add check: `if not content: raise ValueError("Artifact content must not be empty")`

2. **Missing validation in update_metadata** — `artifact_store.py:662-710`
   - Spec requires "Empty metadata and no tags/archived → 400"
   - Currently performs a no-op UPDATE if all params are empty/default

3. **Import trusts content_hash without verification** — `artifact_store.py:908-909`
   - Reads `content_hash` from import file but never verifies it matches actual content
   - Corrupted/malicious files could have mismatched hashes
   - Fix: Compute hash from content and compare, or recompute on import

4. **derives_from references not validated** — `artifact_store.py:101-104`
   - UUID format is validated, but existence of referenced artifacts is not checked
   - Could create orphan lineage references
   - Spec doesn't explicitly require this, but it's a data integrity concern

5. **Sensitive artifacts have no "note" in embedding row** — `artifact_store.py:152-158`
   - Spec says embedding row should have "a note" when sensitive
   - Implementation just leaves `status='pending'` with no indication it's intentional
   - Retry loop correctly skips, but row looks like a failed embedding

### Minor (nice to have)

1. **Test embedding dimension mismatch** — `test_artifact_store.py:334,350`
   - Fake embeddings are 1536-dim but model outputs 768-dim
   - Doesn't affect correctness, just inconsistent

2. **Hardcoded backup directory** — `artifact_store.py:29`
   - `_BACKUP_DIR` should be configurable via environment or config

3. **Missing type annotation** — `artifact_store.py:52-58`
   - `_validate_uuid` return type not annotated

### Confirmed Correct

1. **Dedup via unique partial index** — Eliminates race condition per spec
2. **Content hash** — SHA-256 of UTF-8 bytes, 64-char hex
3. **Embedding pipeline** — Retry loop (60s poll, max 5 retries), startup sweep, batch embedding (20/batch, 100ms delay)
4. **Version immutability** — Updates create new versions, preserve history
5. **Outcome boosting** — Search scoring matches spec (±0.2/0.1)
6. **Sensitive handling** — Skipped from embedding generation and retry sweep
7. **Parameterized queries** — No SQL injection risk
8. **Transaction boundaries** — Multi-table inserts atomic
9. **Graceful degradation** — Gemini unavailable → embedding disabled, search returns 500
10. **All 9 MCP tools implemented** — Endpoints match spec signatures
