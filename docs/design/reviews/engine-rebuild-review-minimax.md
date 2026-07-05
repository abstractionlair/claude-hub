### Summary

The review engine is well-implemented with a solid agentic foundation. The code correctly implements R2.1 (agentic reviews), R2.2 (intent pairing), R2.6 (opinion isolation), and the spec's security requirements (sensitive artifact rejection, ARG_MAX protection via temp files, concurrency limiting). The synthesis logic properly identifies consensus, unique findings, and contradictions. There's one critical bug in the SQL column order that would cause data corruption.

---

### Findings

#### [CRITICAL] review_engine.py:390-391 — SQL column order mismatch causes data corruption
- **File**: `src/claude_hub/review_engine.py:390-391`
- **Description**: The INSERT query has columns in order `(job_id, artifact_id, model, prompt, clean_room, status, invocation_mode)` but the VALUES bind `prompt` at position 4 and `clean_room` at position 5 — they're reversed. This stores the prompt text in the `clean_room` column and the boolean in the `prompt` column.
- **Suggestion**: Swap the order: `prompt, clean_room,` should be `clean_room, prompt,`

#### [CRITICAL] review_engine.py:398-410 — Fire-and-forget tasks lose errors
- **File**: `src/claude_hub/review_engine.py:398-410`
- **Description**: `asyncio.create_task()` runs reviews in the background with no way for the caller to know if they failed. The task catches exceptions internally and logs them, but the original `dispatch_review()` caller has no error indicator.
- **Suggestion**: Either return a list of task handles so callers can await them, or use a callback/result notification mechanism.

#### [IMPORTANT] review_engine.py:688-689 — Temp directory too permissive
- **File**: `src/claude_hub/review_engine.py:688-689`
- **Description**: `tempfile.mkdtemp(prefix="review_")` creates directories with default permissions (typically 0o755). Review prompts containing sensitive context are written there.
- **Suggestion**: Use `tempfile.mkdtemp(prefix="review_", mode=0o700)` to restrict access.

#### [IMPORTANT] review_engine.py:1138-1141 — Synthesis fallback truncates
- **File**: `src/claude_hub/review_engine.py:1138-1141`
- **Description**: When synthesis model isn't in registry, falls back to `"claude", "-p", synthesis_prompt[:100000]` — truncating to 100k chars. Could lose data in large reviews.
- **Suggestion**: Use temp file for fallback too: `["claude", "-f", prompt_path]`

#### [IMPORTANT] review_engine.py:920-944 — Weak files_accessed extraction
- **File**: `src/claude_hub/review_engine.py:920-944`
- **Description**: The regex `line.startswith("- ") and ("/" in line or "." in line)` could match non-file lines. Path validation is minimal (just length < 200 and no "http").
- **Suggestion**: Use stricter validation (e.g., require known extensions or path patterns).

#### [IMPORTANT] No review cancellation mechanism
- **Description**: Once a review is dispatched, there's no API to cancel running reviews. Long-running or unwanted reviews waste resources.
- **Suggestion**: Add a `review_cancel` endpoint that updates status to 'cancelled' and prevents synthesis.

#### [MINOR] Test coverage gaps
- **File**: `tests/test_review_engine.py`
- **Description**: No tests for actual subprocess execution, synthesis fallback path, or concurrent synthesis race conditions beyond the basic UniqueViolationError catch.
- **Suggestion**: Add integration-style tests for CLI invocation paths.

#### [MINOR] review_engine.py:631-632 — Unsafe dict access
- **File**: `src/claude_hub/review_engine.py:631-632`
- **Description**: `row.get("files_accessed")` is used but if the column doesn't exist in older data, could cause issues. Safe but inconsistent with other field accesses.
- **Suggestion**: This is fine given the code handles None appropriately.

---

### What's Done Well

1. **Agentic mode implemented correctly** — models receive file paths and read the codebase
2. **Intent resolution solid** — both `intent` (inline) and `intent_ref` (file path or artifact) work
3. **Opinion isolation** — boundary section excludes process docs per R2.6
4. **Bundled fallback** — content-only reviews work for documents
5. **Synthesis logic** — properly identifies consensus, unique findings, contradictions
6. **Race condition handling** — UNIQUE constraint on job_id plus UniqueViolationError catch
7. **Sensitive artifact check** — rejected before dispatch per spec
8. **ARG_MAX protection** — prompts written to temp files (except Claude's inline template)
9. **Concurrency limited** — semaphore at 3 for VPS protection
10. **Good test coverage** — 60 tests covering critical paths
11. **Clean separation** — engine, models, config, and server layers are well-organized
12. **Error handling** — timeouts, missing binaries, and generic failures all handled
