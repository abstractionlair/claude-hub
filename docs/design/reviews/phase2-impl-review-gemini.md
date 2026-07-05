Loaded cached credentials.
### Findings

**Finding 1**
- **Severity**: critical
- **Location**: `src/claude_hub/review_engine.py` in `dispatch_review`
- **Finding**: Security/Specification violation. The review dispatch mechanism does not respect the artifact's `sensitive` flag. The spec strictly mandates that sensitive artifacts must be excluded from third-party review dispatch (returning a 400 error) to prevent local-only data from being exfiltrated to external model APIs.
- **Fix**: After fetching the artifact from the store, explicitly check the flag: `if artifact.get("sensitive"): raise ValueError("Cannot dispatch review for sensitive artifacts")`.

**Finding 2**
- **Severity**: important
- **Location**: `src/claude_hub/review_engine.py` in `_check_and_synthesize`, and `migrations/002_reviews.sql`
- **Finding**: Race condition in the synthesis trigger. When multiple model review tasks finish concurrently, they will execute `pending_count` and `already_synthesized` database checks without locking. This allows multiple threads to bypass the check simultaneously, launching multiple synthesis operations and resulting in duplicate rows in `review_syntheses`.
- **Fix**: Add a `UNIQUE(job_id)` constraint to the `review_syntheses` table in the migration to match the spec's intent ("Unique per review run"). Then, in `_check_and_synthesize`, handle `asyncpg.UniqueViolationError` to safely ignore the race losers, or use Postgres advisory locks (`pg_try_advisory_xact_lock`) to serialize the final check.

**Finding 3**
- **Severity**: important
- **Location**: `src/claude_hub/review_engine.py` in `_synthesize_reviews`
- **Finding**: Subprocess invocation safety vulnerability regarding OS constraints. The `synthesis_prompt` concatenates findings from all model reviews and is passed directly as a command-line argument (`["claude", "-p", synthesis_prompt]`). For larger artifacts or verbose findings, this can exceed the system's `ARG_MAX` limit and crash the process with an `OSError: [Errno 7] Argument list too long`. 
- **Fix**: Write the `synthesis_prompt` to a temporary file and pass it as a file argument (e.g., `["claude", "-p", prompt_tmp.name]`), making sure to clean up the temporary file in a `finally` block, identical to the pattern used in `_run_single_review`.

**Finding 4**
- **Severity**: minor
- **Location**: `src/claude_hub/review_engine.py` in `_run_single_review`
- **Finding**: Temporary files for artifact content and prompts are created in text write mode (`mode="w"`) without explicitly defining the encoding. This falls back to the platform's default encoding, which can raise `UnicodeEncodeError` or corrupt text if the artifact contains non-ASCII characters. 
- **Fix**: Explicitly set the encoding parameter: `tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")`.

### Overall Assessment

The Phase 2 implementation establishes a solid architectural foundation that largely matches the spec, but it **needs revision** before being ready for production. The failure to enforce the `sensitive` artifact flag is a critical data-leakage flaw that must be fixed immediately. Resolving the synthesis trigger race condition and preventing prompt length limits from causing subprocess crashes are also highly necessary for system stability. Applying the listed fixes and extending test coverage for these edge cases will bring it in line with production standards.
