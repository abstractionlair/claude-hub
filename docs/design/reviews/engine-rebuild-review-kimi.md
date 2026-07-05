I'll read all the listed files to review the rebuilt review engine. Let me start by reading them in parallel.
Now I have all the context needed. Let me provide a comprehensive code review.

---

## Summary

The rebuilt review engine is well-architected with a clean separation between agentic and bundled modes. The implementation correctly handles most spec requirements including opinion isolation (R2.6), sensitive artifact rejection, ARG_MAX protection via temp files, and race condition prevention via UNIQUE constraints. The code is generally readable with good type hints and docstrings. However, there are several correctness issues around error handling, edge cases, and potential resource leaks that need attention.

---

## Findings

### [CRITICAL] Intent Resolution Exception Handling Bug
- **File:** `src/claude_hub/review_engine.py:306-328`
- **Description:** The intent_ref resolution catches `ValueError` but the logic has a bug. When `uuid.UUID(intent_ref)` succeeds but the artifact isn't found, a `ValueError` is raised with message "Intent reference not found". This is then re-raised in line 323-324. However, if the UUID parsing fails, it raises a different `ValueError` which gets wrapped with a confusing message. The bug is that if `uuid.UUID()` succeeds but artifact fetch returns `None`, the exception message check in line 323 won't match because the exception was just created, not caught.
- **Suggestion:** Restructure the exception handling to be clearer:

```python
try:
    uuid.UUID(intent_ref)  # Validate format first
    intent_artifact = await artifact_store_module.get_artifact(pool, intent_ref)
    if intent_artifact is not None:
        resolved_intent = intent_artifact["content"]
    else:
        raise ValueError(f"Intent reference not found: {intent_ref}")
except ValueError:
    # Not a valid UUID format
    raise ValueError(f"Intent ref '{intent_ref}' is neither a valid file path nor a valid artifact UUID")
```

### [CRITICAL] Synthesis Fallback Command Injection Risk
- **File:** `src/claude_hub/review_engine.py:1138-1145`
- **Description:** When the synthesis model isn't in the registry, the code falls back to `claude -p` with prompt content directly interpolated. If `synthesis_prompt` contains shell metacharacters, this could lead to command injection. While the prompt is trusted (constructed internally), this is still risky and the truncation logic (`[:100000]`) could cut mid-unicode sequence.
- **Suggestion:** Always use the prompt file approach instead of inline content. Remove lines 1138-1145 and require synthesis model to be in registry, or always use `--file` flag.

### [IMPORTANT] Async Task Exception Handling Gap
- **File:** `src/claude_hub/review_engine.py:397-410`
- **Description:** `asyncio.create_task()` is used to spawn background reviews, but no `task.add_done_callback()` is attached to check for exceptions. If `_run_single_review` raises an unhandled exception, Python will log a "Task exception was never retrieved" warning but the review will appear stuck in "running" status forever.
- **Suggestion:** Add exception handling callbacks:

```python
task = asyncio.create_task(...)
task.add_done_callback(_on_review_task_done)

def _on_review_task_done(task):
    try:
        task.result()
    except Exception as e:
        logger.exception("Review task failed with unhandled exception")
```

### [IMPORTANT] Temp File Race Condition in Synthesis
- **File:** `src/claude_hub/review_engine.py:1121-1135`
- **Description:** The synthesis prompt is written to a temp file, but the `finally` block that cleans it up runs concurrently with the subprocess. If the subprocess is slow and the temp file is removed while the process is still reading it, the synthesis will fail.
- **Suggestion:** Ensure temp directory cleanup happens only after subprocess completes, or use a context manager pattern.

### [IMPORTANT] Missing Error Handling for Artifact Store Failures
- **File:** `src/claude_hub/review_engine.py:1191-1225` (review artifact storage)
- **Description:** When storing review artifacts, exceptions are caught and logged, but the review row is left without a `review_artifact_id`. This is fine, but there's no test coverage for this path. More critically, if `store_artifact` fails for the synthesis artifact (lines 1227-1253), the `synthesis_artifact_id` remains `None` but synthesis is still marked complete.
- **Suggestion:** Consider whether synthesis should be considered failed if artifact storage fails, or at least document this behavior.

### [IMPORTANT] Inconsistent Import Pattern for shutil
- **File:** `src/claude_hub/review_engine.py:854, 1185`
- **Description:** `shutil` is imported inside `finally` blocks rather than at module level. While this works, it's inconsistent with the module's style (other imports are at the top) and adds minor overhead on every cleanup.
- **Suggestion:** Move `import shutil` to the top of the file.

### [IMPORTANT] Test Coverage Gap for Bundled Mode
- **File:** `tests/test_review_engine.py`
- **Description:** There are no tests that actually exercise the bundled mode path through `_run_single_review`. The bundled mode writes content to temp files and substitutes `{file}` placeholder, but this isn't tested.
- **Suggestion:** Add tests for bundled mode invocation with mocked subprocess.

### [IMPORTANT] Test Coverage Gap for Semaphore Limiting
- **File:** `src/claude_hub/review_engine.py:737`
- **Description:** The `_review_semaphore` limits concurrent reviews to 3, but there's no test verifying this behavior.
- **Suggestion:** Add a test that verifies only 3 reviews run concurrently.

### [MINOR] Unclear Exception Handling in Intent Ref
- **File:** `src/claude_hub/review_engine.py:322-328`
- **Description:** The exception handling for intent_ref tries to distinguish between "not found" and "invalid UUID" by checking the exception message string. This is fragile.
- **Suggestion:** Use separate exception types or restructure the validation logic to check file existence first, then UUID format, then artifact lookup.

### [MINOR] Unused Variable in get_review_results
- **File:** `src/claude_hub/review_engine.py:599-603`
- **Description:** Lines 599-603 try to get artifact_id from review rows when synthesis doesn't exist, but this logic is unreachable because line 545-552 already handles the "not_found" case.
- **Suggestion:** Remove dead code or document why it's needed.

### [MINOR] Review ID Type Inconsistency in INSERT
- **File:** `src/claude_hub/review_engine.py:1014-1019`
- **Description:** When creating empty synthesis for all-failed reviews, `review_ids` is set to `[]` (empty list). But the column type is `UUID[]` and in the normal path it's populated with actual UUID objects. This type mismatch could cause issues with some PostgreSQL drivers.
- **Suggestion:** Pass empty list consistently typed, or use `None` and handle in query.

### [MINOR] Missing Files Accessed Extraction Tests
- **File:** `tests/test_review_engine.py:1105-1138`
- **Description:** The `_extract_files_accessed` function has limited test coverage. The regex-like extraction could miss valid paths or include invalid ones.
- **Suggestion:** Add tests for edge cases: paths with spaces, backtick-wrapped paths, paths that look like URLs but aren't (e.g., `/path/http/foo`).

---

## What's Done Well

1. **Clean architecture** — Clear separation between agentic and bundled modes with mode-aware invocation in `_run_single_review`.

2. **Security-conscious design** — Sensitive artifact check prevents data leaks (R2), opinion isolation via exclude paths (R2.6), temp files prevent ARG_MAX overflow.

3. **Race condition handling** — The UNIQUE constraint on `review_syntheses.job_id` correctly prevents duplicate synthesis when multiple reviews complete simultaneously.

4. **Comprehensive status tracking** — Individual model statuses with timestamps, completion percentages, and terminal state detection.

5. **Good test coverage** — 60 tests covering registry loading, prompt construction, dispatch, status, results, synthesis parsing, and edge cases.

6. **Flexible model configuration** — YAML-based registry with per-model timeouts, character limits, and clean-room flags.

7. **Idempotent synthesis** — The `_check_and_synthesize` function checks for existing synthesis before attempting insertion, gracefully handling `UniqueViolationError`.

8. **Proper resource cleanup** — Temp directories are cleaned up in `finally` blocks even when exceptions occur.

9. **Type safety** — Good use of Pydantic models for request/response validation.

10. **VPS protection** — The semaphore limits concurrent model invocations to 3, protecting resource-constrained servers.
