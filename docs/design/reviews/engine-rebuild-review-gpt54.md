### Summary
The rebuild has a solid shape: the registry-driven invocation model, prompt boundaries, synthesis race protection, temp-file handling, and concurrency cap all move the system much closer to the spec. But there are a few high-impact gaps in the current implementation: content/artifact reviews do not actually reach the configured reviewers, `intent_ref` can exfiltrate arbitrary local or sensitive artifact content, and subprocess failures are still treated as successful reviews. I also ran `pytest tests/test_review_engine.py`; all 60 tests pass, but the suite emits unawaited-coroutine warnings and misses several of the failure paths above.

### Findings
- **[CRITICAL] Content and artifact reviews silently dispatch reviewers with nothing to inspect**
  - File: `src/claude_hub/review_engine.py:341`, `src/claude_hub/review_engine.py:692`, `config/review_models.yaml:15`
  - Description: The constructed review prompt only includes file paths, intent, and instructions; it never includes the raw review subject. `_run_single_review()` only passes `content` through in `bundled` mode, but every configured model is `agentic`. That means `review_dispatch(content=...)` and `review_dispatch(artifact_id=...)` currently succeed while sending reviewers no actual document/artifact content to review, which breaks the bundled fallback requirement and can produce meaningless results.
  - Suggestion: For `content`/`artifact_id` reviews, either route only to bundled-capable models, or materialize the subject into a file that agentic reviewers are explicitly told to read. If no selected model can access the subject, reject the request instead of silently dispatching.

- **[CRITICAL] `intent_ref` can leak arbitrary filesystem data and sensitive artifacts**
  - File: `src/claude_hub/review_engine.py:306`
  - Description: `intent_ref` reads any existing local path directly into the model prompt, with no workspace-root validation. The artifact branch also loads an intent artifact without checking its `sensitive` flag. This bypasses the explicit sensitive-artifact protection on `artifact_id` and allows a caller to exfiltrate local files or marked-sensitive artifact content to third-party models.
  - Suggestion: Restrict file-based `intent_ref` values to an allowlisted project root, reject absolute/out-of-tree paths, and apply the same `sensitive` check to artifact-backed intent references before including them in prompts.

- **[IMPORTANT] Non-zero model exits are recorded as successful reviews**
  - File: `src/claude_hub/review_engine.py:752`
  - Description: When a model subprocess exits non-zero, the code logs a warning but still marks the review `complete` and feeds stdout into parsing/synthesis. That makes `review_status` over-report success, lets broken invocations contribute bogus findings, and weakens synthesis quality.
  - Suggestion: Treat non-zero exits as `failed` by default, and only mark `complete` on a successful exit with parseable output. If needed, preserve stdout/stderr separately for diagnostics.

- **[IMPORTANT] Stored review audit data does not reflect what was actually reviewed**
  - File: `src/claude_hub/review_engine.py:389`, `src/claude_hub/review_engine.py:769`, `src/claude_hub/review_engine.py:591`
  - Description: The `reviews.prompt` column stores only the caller-supplied prompt, not the fully constructed task prompt with files/intent/boundaries. Later, `raw_content` is overwritten with model stdout, even though the schema/spec uses that field for the reviewed raw content. `review_get` also omits `review_modes` from the synthesis payload despite the response model/spec expecting it. Together, this weakens replayability and auditability of the rebuilt engine.
  - Suggestion: Persist the full `task_prompt`, store reviewed raw content separately from model output, and include `review_modes` in `review_get` responses (either persisted in `review_syntheses` or derived from the review rows).

- **[MINOR] Invalid `job_id` values become 500s instead of client errors**
  - File: `src/claude_hub/review_engine.py:448`, `src/claude_hub/review_engine.py:518`, `src/claude_hub/server.py:2602`
  - Description: `check_review_status()` and `get_review_results()` call `uuid.UUID(job_id)` directly, and the corresponding endpoints do not catch `ValueError`. A malformed `job_id` therefore bubbles up as an internal server error instead of a 400-style validation failure.
  - Suggestion: Validate UUID format in the request models or catch `ValueError` in the server handlers and return `HTTPException(status_code=400, ...)`.

- **[MINOR] The test suite misses core execution paths and currently masks lifecycle issues**
  - File: `tests/test_review_engine.py:312`
  - Description: The suite heavily patches `asyncio.create_task` and never meaningfully exercises `_run_single_review()` subprocess behavior. That leaves the non-zero-exit bug, content/artifact-review gap, and invalid-input handling uncovered. The current pytest run also emits `RuntimeWarning: coroutine '_run_single_review' was never awaited`, which suggests the test doubles are leaking coroutines.
  - Suggestion: Add focused async tests around `_run_single_review()` with patched `subprocess.run`, cover `content`/`artifact_id` reviews against the real registry shape, and replace the `create_task` stub with one that consumes/closes the coroutine or asserts the scheduled call cleanly.

### What's Done Well
- The registry/config split is clean and matches the spec’s “add models without code changes” intent.
- Array-style `subprocess.run()` invocation and temp-file prompt handling avoid shell injection and ARG_MAX problems in the main path.
- `UNIQUE(job_id)` plus `UniqueViolationError` handling is a good, concrete synthesis race guard.
- The default boundary prompt and `include_paths` override reflect the spec’s soft clean-room model well.
- The semaphore-based concurrency limit and per-model timeouts are sensible protections for the VPS.
