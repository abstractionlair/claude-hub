# Review Engine Rebuild — 8-Model Review Synthesis

**Date**: 2026-03-06
**Models**: Claude, Gemini, Grok 4.1 Fast, Kimi K2.5, GPT-5.4, GPT-5.3 Codex, GLM-5, MiniMax M2.5
**Subject**: Rebuilt review engine (agentic foundation) — review_engine.py, review_models.py, review_models.yaml, 002_reviews.sql, server.py endpoints, test_review_engine.py

## Overall

All 8 models agree: the rebuild is structurally solid — clean registry-driven invocation, correct agentic/bundled mode split, synthesis race protection via UNIQUE constraint, sensitive artifact rejection, and VPS concurrency limiting. No model said "block deployment." The issues are fixable without architectural changes.

## Consensus Findings (2+ models agree)

### C1. [CRITICAL] Synthesis fallback bypasses ARG_MAX protection (7/8)
- **Models**: Grok, Kimi, GLM-5, Gemini, Claude, MiniMax, Codex
- **File**: `review_engine.py:~1138-1145`
- **Issue**: When synthesis model is not in registry, fallback passes `synthesis_prompt[:100000]` directly as CLI arg. This bypasses the temp-file ARG_MAX protection used everywhere else, and truncation can cut mid-content. Also a command injection vector since the prompt contains raw model output.
- **Fix**: Always use temp file for synthesis prompt. Or remove fallback entirely (YAML guarantees synthesis model is configured).

### C2. [CRITICAL] `intent_ref` allows arbitrary file exfiltration (2/8)
- **Models**: Codex, GPT-5.4
- **File**: `review_engine.py:~306`
- **Issue**: `intent_ref` as file path reads any local path (e.g., `/etc/shadow`) with no sandboxing. Contents get sent to external models. Also skips sensitive artifact check.
- **Fix**: Restrict to repo-relative paths (resolve against repo root, reject `..` traversal and absolute paths).

### C3. [CRITICAL] Claude/Gemini invoke uses `{prompt}` inline (3/8)
- **Models**: GLM-5, Gemini, Codex
- **File**: `config/review_models.yaml:16,25`
- **Issue**: Claude and Gemini configs use `{prompt}` placeholder, passing the full prompt as a CLI argument. Large prompts (up to 400K chars) will exceed Linux ARG_MAX (~2MB). The code already supports `{prompt_file}` — this is a config-only fix.
- **Fix**: Change both to use `{prompt_file}` like the OpenCode models.

### C4. [IMPORTANT] Fire-and-forget asyncio tasks (3/8)
- **Models**: Claude, Kimi, MiniMax
- **File**: `review_engine.py:~398`
- **Issue**: `asyncio.create_task()` spawns reviews with no callback or tracking. Unhandled exceptions leave reviews stuck in "running" forever. No mechanism for graceful shutdown or cancellation.
- **Fix**: Add `add_done_callback()` to log/handle exceptions, or track tasks for cleanup.

### C5. [IMPORTANT] Non-zero exit code treated as successful review (2/8)
- **Models**: Claude, GPT-5.4
- **File**: `review_engine.py:~752`
- **Issue**: Model subprocess returning non-zero exit is logged as warning but still marked `status='complete'`, allowing broken/partial output into synthesis.
- **Fix**: Mark as `status='error'` on non-zero exit. Only `complete` reviews should feed synthesis.

### C6. [IMPORTANT] Fragile `_extract_files_accessed` (4/8)
- **Models**: Grok, GLM-5, Gemini, MiniMax
- **File**: `review_engine.py:~930`
- **Issue**: Regex matches any bulleted line containing `/` or `.`, producing false positives. Misses non-markdown formats.
- **Fix**: Tighten regex (require file extension or known path prefix), cap entries.

### C7. [IMPORTANT] Synthesis race — redundant computation (3/8)
- **Models**: Gemini, Kimi, Claude
- **File**: `review_engine.py:~960-993`
- **Issue**: UNIQUE constraint prevents duplicate rows but doesn't prevent multiple concurrent synthesis attempts. Multiple reviews finishing simultaneously all trigger `_synthesize_reviews`, wasting resources.
- **Fix**: Use `SELECT ... FOR UPDATE SKIP LOCKED` or `pg_try_advisory_lock` before synthesis.

### C8. [IMPORTANT] `review_modes` not persisted/returned (2/8)
- **Models**: Claude, Codex
- **File**: `review_engine.py:~591, ~1058`
- **Issue**: Per-review modes are computed and included in artifact content but never stored in `review_syntheses` table or returned by `review_get`.
- **Fix**: Add `review_modes JSONB` column or accept that it's only in the artifact content.

### C9. [MINOR] Test suite misses core execution paths (4/8)
- **Models**: Kimi, GLM-5, MiniMax, GPT-5.4
- **Issue**: Heavy mocking of `asyncio.create_task` means subprocess behavior, bundled mode, semaphore limits, and synthesis fallback are never meaningfully tested.
- **Fix**: Add integration-style tests for key paths.

## Unique Findings (1 model only, notable)

### U1. [IMPORTANT] Content/artifact reviews send nothing to inspect (GPT-5.4)
- **File**: `review_engine.py:~341, ~692`
- All configured models are agentic, but content-based reviews (not file-based) include file paths in the prompt without the actual content. Agentic models can't read content that was passed via API — they need file paths on disk.
- **Impact**: Content-only reviews produce meaningless results.

### U2. [IMPORTANT] Audit trail incomplete (GPT-5.4)
- `prompt` column stores caller prompt, not the full constructed task prompt. `raw_content` is overwritten with model stdout. Weakens replayability.

### U3. [MINOR] Invalid `job_id` causes 500 instead of 400 (GPT-5.4)
- Missing UUID validation on `check_review_status` and `get_review_results` inputs.

### U4. [MINOR] `shutil` imported inside `finally` blocks (Kimi, Claude)
- Should be at module level.

## Verified False Positive

- **SQL column order mismatch** (MiniMax): Verified — column order in INSERT matches parameter order. Not a bug.

## Prioritized Fix Order

1. **C1 + C3**: Synthesis fallback + claude/gemini invoke — both ARG_MAX/injection issues. Config change + remove/fix fallback.
2. **C2**: `intent_ref` path sandboxing — security fix.
3. **C5**: Non-zero exit → error status — correctness fix.
4. **C4**: Task tracking/callbacks — reliability fix.
5. **C7**: Synthesis advisory lock — efficiency fix.
6. **C6**: Tighten `_extract_files_accessed` regex.
7. **C8**: `review_modes` persistence decision.
8. **U1**: Content review path for agentic models.
9. **C9**: Test coverage for key paths.
10. **U2-U4**: Minor fixes.

## Model Performance Notes

| Model | Findings | Unique Value |
|-------|----------|--------------|
| GPT-5.4 | 6 (2C, 2I, 2m) | Strongest — found content gap (U1) and audit trail gap (U2) no one else caught |
| Codex | 6 (1C, 3I, 2m) | Security focus — intent_ref exfiltration, sensitive bypass |
| Claude | 10 (1C, 3I, 6m) | Broadest coverage, good minor details |
| Kimi | 11 (2C, 5I, 4m) | Most findings total, thorough edge case analysis |
| Gemini | 5 (1C, 2I, 2m) | Concise, focused on ARG_MAX and race conditions |
| GLM-5 | 7 (1C, 3I, 3m) | Clean analysis, config-only fix insight |
| MiniMax | 8 (2C, 4I, 2m) | One false positive (SQL order), but good coverage otherwise |
| Grok 4.1 Fast | 3 (0C, 1I, 2m) | Lightest review — accurate but shallow. First run, may improve with tuning. |
