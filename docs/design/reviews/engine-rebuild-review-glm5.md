I'll read all the files listed in the review prompt to conduct a thorough code review.
### Summary

The review engine implementation is well-architected with strong spec alignment, proper race condition handling via database constraints, and good defensive error handling. The agentic foundation is solid—models receive task prompts and explore the codebase themselves. However, there's one critical spec violation (inline prompt passing risks ARG_MAX overflow), and several important code paths lack test coverage. The synthesis race condition prevention via UNIQUE constraint is correctly implemented.

### Findings

**[CRITICAL] ARG_MAX Violation for Individual Reviews**
- File: `config/review_models.yaml:16`
- Description: Claude's invoke template uses `["claude", "-p", "{prompt}"]` which passes the prompt inline as a CLI argument. For long prompts (e.g., reviewing multiple files with extensive context), this can exceed the system's ARG_MAX limit (~2MB on Linux), causing the subprocess to fail with "Argument list too long". The spec explicitly states "prompts written to temp files, not passed as CLI args" (Draft 3 changes).
- Suggestion: Change Claude's invoke to `["claude", "-p", "$(cat {prompt_file})"]` or use stdin/file input. Alternatively, require all models to use `{prompt_file}` instead of `{prompt}`. The code at `review_engine.py:715-720` supports both placeholders, so the fix is config-only.

**[IMPORTANT] Missing Test Coverage for Subprocess Execution**
- File: `tests/test_review_engine.py`
- Description: The `_run_single_review` function (lines 649-866) and `_synthesize_reviews` function (lines 1028-1290) contain critical subprocess execution logic, timeout handling, and temp file management, but have no direct test coverage. Tests mock `asyncio.create_task` at line 312, 341, etc., preventing actual execution. This leaves timeout handling, FileNotFoundError recovery, and temp file cleanup untested.
- Suggestion: Add integration tests that actually spawn subprocesses (with short timeouts and mock CLIs), or add unit tests that mock `subprocess.run` and verify the error handling branches.

**[IMPORTANT] Concurrency Limit Not Tested**
- File: `tests/test_review_engine.py`
- Description: The semaphore at `review_engine.py:231` limits concurrent reviews to 3, but no test verifies this constraint. A bug in the semaphore logic could allow unlimited concurrent model invocations, overwhelming the 4GB VPS.
- Suggestion: Add a test that dispatches 5+ models and verifies only 3 run concurrently (using timing assertions or a mock that tracks concurrent invocations).

**[IMPORTANT] Bundled Mode Execution Path Untested**
- File: `tests/test_review_engine.py`
- Description: The bundled mode code path at `review_engine.py:692-708` writes content to a temp file and substitutes `{file}` in the invoke template. No test exercises this path. The backward compatibility test at line 1147 dispatches with `content` but doesn't verify bundled mode was actually used.
- Suggestion: Add a test that dispatches with `content` to a model configured with `mode: bundled`, and verify the temp file is created and `{file}` substitution occurs.

**[MINOR] Synthesis Fallback Truncation**
- File: `src/claude_hub/review_engine.py:1141`
- Description: When the synthesis model isn't in the registry, the fallback passes `synthesis_prompt[:100000]` inline. This silent truncation could lose critical review data, producing incomplete synthesis. The spec requires prompts be written to temp files for synthesis.
- Suggestion: Either remove the fallback (require synthesis model in registry) or write to a temp file like the normal path. Don't silently truncate.

**[MINOR] No Validation of Model Config Consistency**
- File: `src/claude_hub/review_engine.py:75-81`
- Description: `load_model_registry` validates required fields (`invoke`, `timeout_seconds`, `mode`) but doesn't validate that `invoke` templates contain valid placeholders (`{prompt}`, `{prompt_file}`, `{file}`). A typo like `{promt_file}` would fail silently at runtime.
- Suggestion: Add validation that invoke templates contain at least one of the expected placeholders, and warn if a model uses `{prompt}` inline (ARG_MAX risk).

**[MINOR] Files Accessed Extraction is Fragile**
- File: `src/claude_hub/review_engine.py:921-944`
- Description: `_extract_files_accessed` uses simple pattern matching (`line.startswith("- ")` and `"/" in line`). This works for markdown lists but fails for other formats (e.g., "I read src/foo.py" or numbered lists). The function is best-effort per the docstring, but the pattern is brittle.
- Suggestion: Expand patterns to match common formats: numbered lists, "I read:", "Files:", and inline mentions. Or document that models should output markdown lists for reliable extraction.

### What's Done Well

- **Race condition prevention**: The UNIQUE(job_id) constraint on review_syntheses (migration line 37) with UniqueViolationError handling (lines 1021, 1277) correctly prevents duplicate synthesis without application-level locks.

- **Sensitive artifact protection**: Lines 296-301 reject sensitive artifacts before dispatch, preventing data leaks to third-party models.

- **Opinion isolation**: The exclude/include path logic (lines 176-204) correctly implements soft boundaries, allowing specs under `thoughts/shared/` while excluding process docs.

- **Concurrency protection**: The semaphore (line 231) limits concurrent model invocations to 3, protecting the VPS from resource exhaustion.

- **Defensive error handling**: Lines 829-848 catch all exceptions, update review status, and have nested try/except for database failures. Lines 860-865 wrap synthesis check to prevent cascading failures.

- **Temp file security**: `tempfile.mkdtemp()` creates directories with 0700 permissions. Cleanup is in finally blocks.

- **JSONB handling**: Lines 576-590 correctly handle both string and dict JSONB values from asyncpg.

- **Spec alignment**: All R2 requirements (agentic reviews, intent pairing, opinion isolation, synthesis, race prevention, sensitive rejection, ARG_MAX protection for synthesis) are implemented.

- **Test coverage for public API**: dispatch, status, get, and prompt construction are well-tested with edge cases.
