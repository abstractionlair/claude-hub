[0m
> build · gpt-5.4
[0m

[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1307, limit=1200][0m[0m→ [0mSkill "hook-developer"
[0m✗ [0mread failed
[91m[1mError: [0mFile not found: /home/claude/claude-hub/.claude/settings.json
[0m✗ [0mglob failed
[91m[1mError: [0mNo such file or directory: '/home/claude/claude-hub/.claude/hooks'
[0m✗ [0mglob failed
[91m[1mError: [0mNo such file or directory: '/home/claude/claude-hub/.claude/hooks/src'
It needs another revision before implementation. The core direction is good, but there are a few real correctness gaps and the hook section is not compatible with Claude Code as written.

**Critical**
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:202`, `thoughts/shared/spec-personal-ai-infrastructure.md:219`, `thoughts/shared/spec-personal-ai-infrastructure.md:750`; **Issue** raw-content reviews are allowed by `review_dispatch`, and `reviews.artifact_id` is nullable, but `review_syntheses.artifact_id` is `NOT NULL REFERENCES artifacts(id)`. A synthesis row cannot be stored for a non-artifact review job. **Suggestion** add an explicit `review_jobs` table keyed by `job_id`, or make `review_syntheses.artifact_id` nullable and add a separate non-artifact `job_id` column used consistently by `reviews`, `review_syntheses`, `review_status`, and `review_get`.

**Important**
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:1410`, `thoughts/shared/spec-personal-ai-infrastructure.md:1437`, `thoughts/shared/spec-personal-ai-infrastructure.md:1489`, `thoughts/shared/spec-personal-ai-infrastructure.md:1537`; **Issue** the hook integration does not match Claude Code’s actual hook contract. `PostToolUse` registration is missing a required matcher, `PreCompact` returns `result/message` instead of `continue/systemMessage`, and `SessionStart` reads `.type` instead of `.source`. **Suggestion** rewrite hook examples to the real schemas and registration shapes used by Claude Code.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:1465`, `thoughts/shared/spec-personal-ai-infrastructure.md:1502`, `thoughts/shared/spec-personal-ai-infrastructure.md:1508`, `thoughts/shared/spec-personal-ai-infrastructure.md:1873`; **Issue** hooks depend on `log_unsummarized_count`, `log_recent`, and `workflow_active_items`, but those endpoints are not defined in the API surface or module architecture. **Suggestion** either add these endpoints explicitly, or rework hooks to call already-specified tools/endpoints.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:28`, `thoughts/shared/spec-personal-ai-infrastructure.md:525`, `thoughts/shared/spec-personal-ai-infrastructure.md:748`, `thoughts/shared/spec-personal-ai-infrastructure.md:1873`; **Issue** the spec claims 31 MCP tools, but the enumerated tools add up to 30. The extra hook-only HTTP endpoints are not MCP tools. **Suggestion** correct the count or add the missing MCP tool explicitly.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:1369`, `thoughts/shared/spec-personal-ai-infrastructure.md:1400`; **Issue** the review model registry contradicts itself: the YAML uses `{prompt_file}`, but the prose says the supported placeholders are `{file}` and `{prompt}`. **Suggestion** define one placeholder contract, show one canonical example, and validate templates at startup.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:295`, `thoughts/shared/spec-personal-ai-infrastructure.md:478`, `thoughts/shared/spec-personal-ai-infrastructure.md:1352`, `thoughts/shared/spec-personal-ai-infrastructure.md:1595`; **Issue** connector embeddings are specified but not actually supported by the embedding pipeline. `connector_index` has embedding state, `FilesystemConnector` says it queues embeddings, but `embedding.py` only handles artifact IDs / `artifact_embeddings`. **Suggestion** add a generic embedding job system or a parallel connector-embedding worker path with retry/error handling.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:891`, `thoughts/shared/spec-personal-ai-infrastructure.md:570`; **Issue** `artifact_rate` says reasoning becomes searchable by appending it to metadata, but semantic search only embeds artifact content. That reasoning will not affect vector retrieval. **Suggestion** either include outcome reasoning in embedded searchable text, or add full-text search over reasoning and merge it with semantic ranking.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:542`, `thoughts/shared/spec-personal-ai-infrastructure.md:737`, `thoughts/shared/spec-personal-ai-infrastructure.md:146`; **Issue** dedup semantics are inconsistent and non-atomic. `artifact_store` dedups by `content_hash + source_ref`; `artifact_import` dedups by `content_hash` only; and there is no DB uniqueness constraint, so concurrent writes can still duplicate. **Suggestion** choose one provenance rule and enforce it with a unique index such as `(content_hash, coalesce(source_ref, ''))`.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:1689`, `thoughts/shared/spec-personal-ai-infrastructure.md:1755`, `thoughts/shared/spec-personal-ai-infrastructure.md:1760`, `thoughts/shared/spec-personal-ai-infrastructure.md:1768`; **Issue** build order is mostly sound, but Phase 3 and Phase 8 both claim ledger ingestion, and Phase 7’s “state loads on session start” acceptance criterion implicitly depends on continuity work from Phase 3. **Suggestion** make ledger ingestion happen in one phase only, and either relax that Phase 7 acceptance test or declare the Phase 3 dependency.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:94`, `thoughts/shared/spec-personal-ai-infrastructure.md:1855`; **Issue** there is an internal contradiction about hook DB access. Earlier, hooks use HTTP and do not need direct DB credentials; later, the spec says hooks need the Postgres DSN. **Suggestion** remove the hook-DSN requirement unless hooks will actually connect to Postgres directly.

**Minor**
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:914`; **Issue** `INTERVAL '$1 days'` is not valid parameterized SQL. **Suggestion** use `NOW() - make_interval(days => $1)` or `NOW() - (($1 || ' days')::interval)`.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:1021`, `thoughts/shared/spec-personal-ai-infrastructure.md:1027`; **Issue** `workflow_advance` says to validate legal stage transitions, then says non-sequential transitions are allowed. **Suggestion** decide whether this is hard validation or advisory warning-only.
- **Location** `thoughts/shared/spec-personal-ai-infrastructure.md:817`, `thoughts/shared/spec-personal-ai-infrastructure.md:1482`; **Issue** `context_summarize` treats `content` and `auto` as separate modes, but the Stop-hook flow calls it with both. **Suggestion** define precedence or split this into two explicit operations.

**Direct answers**
- **Internal contradictions:** yes; the biggest are raw-review storage, hook DB access, workflow transition rules, placeholder naming, and duplicated ledger-ingestion phase ownership.
- **Specified-but-won’t-work components:** yes; raw-content review synthesis, hook injection as written, and connector semantic indexing are the main ones.
- **API surface consistency:** not yet; tool count is off, raw-review job identity is inconsistent, and hook-required helper endpoints are missing.
- **Build order / dependency graph:** mostly good structurally after Phase 1, but it needs dependency cleanup around continuity/workflow and duplicate ingestion.
- **Claude Code hook compatibility:** no, not as written.

Overall: close, but not ready yet. I’d do one more revision focused on the review job model, hook schema correctness, connector embedding plumbing, and API/tool-count cleanup.
