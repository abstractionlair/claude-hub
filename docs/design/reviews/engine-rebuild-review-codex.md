### Summary
The rebuild is directionally strong and mostly aligned with the agentic-review goals: model registry loading, async fanout, race-safe synthesis insertion, and clean-room boundaries are all in place. The largest gaps are around data-leak safety (`intent_ref`), incomplete ARG_MAX protection (prompts still passed inline for some models), and a spec drift where synthesis review modes are computed but not persisted/returned. I also found a couple of correctness edge cases that should be fixed for reliability.

### Findings
- **[CRITICAL] `intent_ref` allows arbitrary local file exfiltration**
  - File: `src/claude_hub/review_engine.py:306`
  - Description: `intent_ref` is treated as a raw filesystem path (`Path(intent_ref).exists()` + `read_text()`), with no path allowlist/sandbox. A caller can pass paths like `/etc/...` and have local sensitive content included in prompts sent to external models.
  - Suggestion: Restrict `intent_ref` file reads to a safe project root allowlist (e.g., repo-relative paths only), reject absolute paths/path traversal, and explicitly deny known sensitive locations.

- **[IMPORTANT] Sensitive artifact protection is bypassed for `intent_ref` artifacts**
  - File: `src/claude_hub/review_engine.py:315`
  - Description: The main `artifact_id` path correctly blocks `sensitive` artifacts, but `intent_ref` artifact resolution does not check `intent_artifact.get("sensitive")`. Sensitive data can still be sent to third-party models via intent context.
  - Suggestion: Apply the same sensitive-artifact guard used for `artifact_id` when resolving `intent_ref` UUIDs.

- **[IMPORTANT] ARG_MAX protection is incomplete; prompts still passed as CLI args**
  - File: `src/claude_hub/review_engine.py:716`
  - Description: Even though prompt files are created, `{prompt}` substitution is still used where configured, so large prompts are passed inline as argv. This conflicts with the stated ARG_MAX protection goal.
  - Suggestion: Standardize on `{prompt_file}` for all models and remove `{prompt}` substitution in runtime paths. Update model config entries that currently use inline prompt args.
  - File: `config/review_models.yaml:16`
  - Description: `claude` and `gemini` are configured with `{prompt}` inline invocation.
  - Suggestion: Switch these to file-based input variants to keep prompt transport off argv.
  - File: `src/claude_hub/review_engine.py:1130`
  - Description: Synthesis invocation also substitutes `{prompt}`; fallback path explicitly truncates and passes inline text.
  - Suggestion: Use only file-based synthesis invocation and remove inline fallback behavior.

- **[IMPORTANT] `review_modes` are computed but not persisted/returned in synthesis**
  - File: `src/claude_hub/review_engine.py:1058`
  - Description: Per-review modes are collected and included in artifact content, but not stored in `review_syntheses` and not returned by `review_get` synthesis payload.
  - Suggestion: Add a `review_modes JSONB` column to `review_syntheses`, persist it on insert, and include it in `get_review_results` synthesis output.
  - File: `migrations/002_reviews.sql:25`
  - Description: Schema has no `review_modes` column.
  - Suggestion: Add migration for this field (and backfill default `{}` where needed).
  - File: `src/claude_hub/review_engine.py:591`
  - Description: Returned synthesis object omits `review_modes`.
  - Suggestion: Return persisted `review_modes` to align with spec and response model intent.

- **[MINOR] `artifact_id` fallback in `review_get` cannot work as written**
  - File: `src/claude_hub/review_engine.py:535`
  - Description: The review query does not select `artifact_id`, but fallback logic later attempts `review_rows[0].get("artifact_id")`, so it will always be `None`.
  - Suggestion: Include `artifact_id` in the `SELECT` for reviews, or remove fallback branch.

- **[MINOR] Bundled model edge case can produce malformed invocation**
  - File: `src/claude_hub/review_engine.py:692`
  - Description: Bundled behavior only triggers when `mode == "bundled"` and `content is not None`; otherwise it falls into agentic path where `{file}` may remain unresolved for bundled templates.
  - Suggestion: If `mode == bundled` and no `content`, fail fast with a clear validation error (or explicitly synthesize bundle content from files if that is intended).

### What's Done Well
- Good race-condition handling via `UNIQUE(job_id)` and graceful `UniqueViolationError` handling (`review_syntheses`).
- Concurrency protection is implemented with a semaphore (`3` parallel review invocations), matching VPS safety intent.
- Prompt construction cleanly includes intent/context/boundaries/output format and supports include-over-exclude overrides.
- Subprocess invocation uses argument arrays (no shell), reducing command-injection risk.
- Test suite is substantial and covers many key happy/edge paths (status transitions, parsing, dispatch validation, synthesis race).
