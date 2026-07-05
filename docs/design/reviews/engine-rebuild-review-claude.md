I now have a thorough understanding of all the files. Here's my review:

---

## Code Review: Rebuilt Review Engine (Agentic Foundation)

### Summary

This is a solid, well-structured implementation that cleanly separates concerns across engine, models, config, and schema. The agentic/bundled mode distinction works, the race condition protection via UNIQUE constraint is correct, and the test suite covers the public API thoroughly. However, there are several issues worth addressing — one critical (command injection in synthesis fallback), one important (non-zero exit code treated as success), and several minor items around robustness and missing test coverage for the `_run_single_review` and `_synthesize_reviews` paths.

### Findings

- **[CRITICAL] Command injection in synthesis fallback path**
  - File: `src/claude_hub/review_engine.py:1141`
  - Description: When the synthesis model isn't in the registry, the fallback truncates the prompt and passes it directly as a CLI argument: `cmd = ["claude", "-p", synthesis_prompt[:100000]]`. This bypasses the ARG_MAX protection that the rest of the code carefully implements via temp files. More importantly, if `synthesis_prompt` contains shell metacharacters from model output (which it will — it includes raw model findings), this is a vector for injection via `subprocess.run` argument parsing. Even without shell=True, the prompt content becomes a direct CLI argument which some tools may re-parse.
  - Suggestion: The fallback should also write to a temp file and use `{prompt_file}` substitution, or read from stdin. The `$(cat {prompt_path})` line on 1139 (commented-out intent) confirms the original plan was file-based. Simplest fix: `cmd = ["claude", "-p", "--input-file", prompt_path]` or just raise an error if the synthesis model isn't configured — the YAML already guarantees it.

- **[IMPORTANT] Non-zero exit code treated as successful review**
  - File: `src/claude_hub/review_engine.py:752-781`
  - Description: When a model subprocess returns a non-zero exit code, the code logs a warning but still marks the review as `status='complete'` and stores whatever partial output was captured. A non-zero exit code typically indicates the model failed (rate limit, crash, OOM). Treating this as "complete" means broken/partial output enters the synthesis and degrades results.
  - Suggestion: Either mark as `'failed'` on non-zero exit (consistent with how timeout/FileNotFoundError are handled), or add a distinct status like `'partial'` so synthesis can weight it appropriately.

- **[IMPORTANT] TOCTOU race in `_check_and_synthesize`**
  - File: `src/claude_hub/review_engine.py:960-993`
  - Description: Three separate `pool.acquire()` calls check pending count, check existing synthesis, then fetch completed rows — each in its own connection. Between the pending check (line 961) and the completed rows fetch (line 983), another review could complete or a concurrent task could start synthesis. The UNIQUE constraint catches the INSERT race, but the gap means synthesis could run with stale data (missing a just-completed review). 
  - Suggestion: Combine these into a single connection with a transaction, or at minimum fetch pending count and completed rows in one query. The UNIQUE constraint is the real safety net (correctly implemented), so this is more a data-freshness issue than a correctness bug.

- **[IMPORTANT] `review_modes` missing from `get_review_results` synthesis response**
  - File: `src/claude_hub/review_engine.py:591-597`
  - Description: The `ReviewSynthesis` Pydantic model (`review_models.py:30`) includes `review_modes: dict[str, str]`, but `get_review_results` doesn't populate it — the synthesis dict returned at line 591-597 lacks a `review_modes` key. This means callers using the `ReviewGetResponse` model will always get the default empty dict, losing the agentic/bundled attribution.
  - Suggestion: Either query `review_modes` from the individual review rows when building the synthesis response, or store `review_modes` in the `review_syntheses` table (it's already in the artifact content at line 1236 but not in the DDL).

- **[MINOR] `get_review_results` missing `invocation_mode` and `files_accessed` from test review rows**
  - File: `tests/test_review_engine.py:599-618`
  - Description: Several test fixtures for review rows in `TestGetReviewResults` omit the `invocation_mode` and `files_accessed` keys that `get_review_results` reads via `row.get("invocation_mode")` and `row.get("files_accessed")`. The tests pass because `.get()` returns None/defaults, but they don't exercise the real data shape. This is also why the `review_modes` bug above wasn't caught.
  - Suggestion: Add these fields to test fixtures to match the actual SELECT column list at line 537.

- **[MINOR] `_extract_files_accessed` is brittle and over-matches**
  - File: `src/claude_hub/review_engine.py:933-944`
  - Description: The heuristic matches any markdown bullet containing `/` and `.`, which will match findings like `- src/foo.py:42 has a SQL injection risk` as a "file accessed". It also won't match file paths that use backtick formatting like `` - `src/foo.py` `` correctly in all cases (the strip works for simple cases but not nested formatting). Given this is "best-effort" it's acceptable, but the false positive rate may be high.
  - Suggestion: Consider a more targeted pattern — look for a "Files read:" or "Files accessed:" header and only extract from the subsequent list, rather than scanning the entire output.

- **[MINOR] `shutil` imported inside `finally` block**
  - File: `src/claude_hub/review_engine.py:854`
  - Description: `import shutil` is done lazily inside the `finally` block of `_run_single_review`. This works but is unconventional — if the import fails (extremely unlikely but possible in constrained environments), the temp directory leaks. Same pattern at line 1185.
  - Suggestion: Move `import shutil` to the top of the file with other imports.

- **[MINOR] `check_review_status` returns `not_found` which isn't in Pydantic model**
  - File: `src/claude_hub/review_engine.py:458-462` / `review_models.py:81`
  - Description: `ReviewStatusResponse.status` describes valid values as `'pending', 'running', 'complete', or 'failed'` but `check_review_status` can return `'not_found'`. Same issue in `get_review_results` at line 551. The Pydantic model won't reject it (it's a `str` field), but the documented contract is inconsistent.
  - Suggestion: Either add `'not_found'` to the Field description, or raise an HTTP 404 in the server endpoint instead of returning a status object.

- **[MINOR] Background tasks created with `asyncio.create_task` are not tracked**
  - File: `src/claude_hub/review_engine.py:398`
  - Description: The tasks are fire-and-forget — if the server shuts down gracefully, these tasks may be cancelled mid-review without cleanup. Also, unhandled exceptions in background tasks produce "Task exception was never retrieved" warnings unless explicitly handled.
  - Suggestion: Store task references and implement graceful shutdown. The exception handling inside `_run_single_review` is thorough enough that in practice this is unlikely to cause issues, but the task references should still be stored per asyncio best practices.

- **[MINOR] `_parse_review_output` embedded JSON extraction is greedy**
  - File: `src/claude_hub/review_engine.py:899-909`
  - Description: Using `find("{")` and `rfind("}")` on the entire output will grab the outermost braces, which could span unrelated JSON objects if the model output contains multiple JSON blocks (e.g., a finding that includes a JSON example). This matches the same strategy in `_parse_synthesis_json` and works in the common case but could produce surprising results.
  - Suggestion: Acceptable for now, but consider trying to parse the largest balanced JSON object rather than first-`{`-to-last-`}`.

### What's Done Well

- **Race condition prevention**: UNIQUE constraint on `review_syntheses.job_id` with proper `UniqueViolationError` catch is the right pattern — simple and reliable.
- **Semaphore-based concurrency limiting**: `asyncio.Semaphore(3)` correctly protects the VPS without complex queue infrastructure.
- **Temp file strategy**: Consistent use of `tempfile.mkdtemp` with cleanup in `finally` blocks prevents ARG_MAX issues and avoids leaving temp files.
- **Sensitive artifact rejection**: Clean gate at dispatch time before any model invocation.
- **Mode-aware invocation**: The agentic/bundled split is cleanly implemented in `_run_single_review` with shared prompt construction.
- **Pydantic models**: Well-structured, properly documented with Field descriptions, and correctly separate request/response for each tool.
- **DDL design**: Partial index on `status IN ('pending', 'running')` is a nice touch for the common query pattern.
- **Test organization**: 60 tests with clear class-based grouping, good edge case coverage on parsing functions, and proper registry reset fixture.
- **Error handling granularity**: Separate handlers for `TimeoutExpired`, `FileNotFoundError`, and general `Exception` with appropriate status values for each.
