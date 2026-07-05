[0m
> build · gpt-5.3-codex
[0m
[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1307, limit=2000][0m

[0m✱ [0mGlob "**/.claude/settings.json"[90m in . · 0 matches[0m[0m✱ [0mGrep "PostToolUse|PreCompact|SessionStart|Stop"[90m in . · 80 matches[0m

[0m→ [0mSkill "hook-developer"
[0m→ [0mRead src/claude_hub/server.py[90m [offset=1, limit=260][0m[0m✱ [0mGrep "FastApiMCP|mcp =|mount"[90m in src/claude_hub/server.py · 6 matches[0m
[0m✱ [0mGrep "@app.post\("/"[90m in src/claude_hub/server.py · 36 matches[0m
[0m✱ [0mGlob ".claude/settings.json"[90m in . · 0 matches[0m
[0m✱ [0mGlob ".claude/hooks/**/*.sh"[90m in . · 0 matches[0m
[0m✱ [0mGlob ".claude/hooks/**/*.mjs"[90m in . · 0 matches[0m
[0m✱ [0mGlob ".claude/hooks/**/*.ts"[90m in . · 0 matches[0m
It’s much stronger than Draft 1, but I’d do another revision before implementation. The biggest remaining issues are around raw-content reviews, sensitive-data handling, and hook/runtime correctness.

**Critical**
- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:204`, `thoughts/shared/spec-personal-ai-infrastructure.md:221`, `thoughts/shared/spec-personal-ai-infrastructure.md:750`, `thoughts/shared/spec-personal-ai-infrastructure.md:775`  
  **Issue:** Raw-content review flow is internally inconsistent. `reviews.artifact_id` is nullable, but `review_syntheses.artifact_id` is `NOT NULL REFERENCES artifacts(id)`, while `review_dispatch` says raw content can use generated `job_id` not tied to an artifact. This cannot be persisted as described.  
  **Suggestion:** Add a real `job_id UUID` on both `reviews` and `review_syntheses` (or force creation of a synthetic artifact for raw content first), then make `review_status/review_get` query by `job_id`.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:536`, `thoughts/shared/spec-personal-ai-infrastructure.md:425`, `thoughts/shared/spec-personal-ai-infrastructure.md:392`  
  **Issue:** `sensitive=true` promises “never sent to third-party APIs,” but embedding-on-write always sends content to Gemini.  
  **Suggestion:** Define explicit enforcement: if `sensitive`, skip remote embedding/review or route to local embedding model only; enforce this in `artifact_store`, retry loop, and review dispatch.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1489`, `thoughts/shared/spec-personal-ai-infrastructure.md:1520`  
  **Issue:** PreCompact hook output schema is wrong for Claude Code (`result/message`), so compaction injection likely won’t work.  
  **Suggestion:** Return valid hook JSON (`continue`, `systemMessage`, optionally `hookSpecificOutput`) per actual PreCompact contract.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1429`, `thoughts/shared/spec-personal-ai-infrastructure.md:1545`, `thoughts/shared/spec-personal-ai-infrastructure.md:1560`  
  **Issue:** Hook scripts call `/log_operation`, `/context_load`, `/artifact_unrated` directly, but server tools are exposed as `/tools/<name>` in current codebase pattern. As written, calls likely 404.  
  **Suggestion:** Standardize hook calls to real mounted endpoints (likely `/tools/...`), and document exact request/response payloads for each hook-facing internal endpoint.

**Important**
- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:28`, `thoughts/shared/spec-personal-ai-infrastructure.md:525`, `thoughts/shared/spec-personal-ai-infrastructure.md:1873`  
  **Issue:** Tool count mismatch. Listed MCP tools sum to 30 (9+3+4+2+3+6+3), but spec repeatedly says 31.  
  **Suggestion:** Reconcile count and explicitly name the missing/extra tool (or correct all references to 30).

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1369`, `thoughts/shared/spec-personal-ai-infrastructure.md:1400`  
  **Issue:** Placeholder contract is inconsistent (`{prompt_file}` in YAML templates vs text saying `{prompt}` placeholder).  
  **Suggestion:** Pick one placeholder vocabulary (`{prompt_file}` / `{content_file}`) and enforce via schema validation at startup.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:737`, `thoughts/shared/spec-personal-ai-infrastructure.md:543`  
  **Issue:** Dedup semantics conflict: `artifact_store` dedups by `content_hash + source_ref`, but `artifact_import` says dedup by `content_hash` only.  
  **Suggestion:** Define one canonical dedup strategy and apply it across store/import/ingest; if import intentionally differs, document why.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1508`, `thoughts/shared/spec-personal-ai-infrastructure.md:1742`  
  **Issue:** PreCompact hook depends on `workflow_active_items`, but workflow features land in Phase 7; Phase 3 hook behavior is therefore partially broken/noisy early.  
  **Suggestion:** Gate this call behind feature detection or move active-work-item injection to post-Phase-7 milestone.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1442`  
  **Issue:** PostToolUse registration example omits matcher; in Claude Code hooks, matcher is typically required for PostToolUse blocks.  
  **Suggestion:** Register with explicit matcher (`"*"` or tool subset) and provide tested minimal valid JSON example.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1465`, `thoughts/shared/spec-personal-ai-infrastructure.md:1471`  
  **Issue:** Stop hook expects numeric `COUNT`, but response shape for `/log_unsummarized_count` is unspecified; if JSON object is returned, numeric compare fails.  
  **Suggestion:** Specify response as `{count:int}` and parse with `jq -r '.count // 0'`.

**Minor**
- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1538`  
  **Issue:** SessionStart script reads `.type`; current hook payload uses `source`.  
  **Suggestion:** Use `.source` (startup/resume/clear/compact) consistently.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:855`  
  **Issue:** “sub-10ms” target for HTTP hook -> FastAPI -> DB is likely unrealistic on a small VPS under load.  
  **Suggestion:** Relax to percentile-based SLO (e.g., p95 < 50ms) and batch/async if needed.

- **Location:** `thoughts/shared/spec-personal-ai-infrastructure.md:1531`, `thoughts/shared/spec-personal-ai-infrastructure.md:1571`  
  **Issue:** SessionStart integration says “depends on existing structure,” leaving key integration details vague.  
  **Suggestion:** Add one concrete integration path (exact hook file + merge behavior + fallback behavior).

**Internal contradictions / non-working components**
- Raw review job identity and synthesis persistence are contradictory (would fail as specified).
- Sensitive-artifact promise conflicts with mandatory Gemini embedding.
- Hook endpoint paths and hook output schemas don’t match likely runtime behavior.
- Tool-count/accounting is inconsistent.

**API surface consistency (31 MCP tools)**
- Naming is mostly coherent and requirement mapping is clear.
- Not internally consistent yet on count, raw-review job model, and dedup policy.
- I’d call API design “near-ready but needs normalization pass.”

**Build order / dependency graph**
- Overall phase decomposition is good and mostly sound.
- One dependency leak exists (Phase 3 PreCompact expecting workflow endpoint from Phase 7).
- Fix with feature flags or staged hook capability expansion.

**Hook integration vs Claude Code hook system**
- Concept is good, but several examples are not schema-accurate enough to trust copy/paste execution.
- Needs one “hook contract compliance” pass (input fields, output schema, matcher usage, endpoint paths, parse robustness).

Overall: not implementation-ready yet. I’d do a short Draft 3 focused only on these correctness issues; after that, it should be ready to build.
