# Review: 2026-03-07 14:52 UTC

**Prompt:** Review these two design documents (spec Draft 8 and requirements Draft 10) for the Phase 3 window-file architecture redesign. Focus on: internal consistency between the two documents, stale references to removed concepts (mechanical_log table, context_summarize/context_load/log_operation/ingest_ledgers tools), correctness of the tree/fork/parallel session model, adequacy of the harness namespace design, achievable acceptance criteria, and any gaps or contradictions.
**Files:** docs/design/spec-personal-ai-infrastructure.md, docs/design/requirements-personal-ai-infrastructure.md
**Job ID:** 34a460ab-19b1-4fd5-99b8-ce2e9b18f3f3

## Synthesis

## Synthesis: Phase 3 Window-File Architecture Reviews

### High-Confidence Consensus

All three reviewers agree on the fundamentals: the window-file architecture is a strong design, the tree/fork/parallel session model is the standout feature, and the Phase 3 vs 3.5 separation is correct and implementable. The harness namespace design (`thoughts/windows/{harness}/`) gets universal praise for extensibility. All three confirm that decommissioned tools (`context_summarize`, `context_load`, `log_operation`, `ingest_ledgers`) and the `mechanical_log` table have been properly removed from the document body, with references surviving only in changelogs where they belong. The "start-with-why" narrative prompt principle is validated across all reviews. Overall verdict from all three: approve, ready for implementation with fixes.

Two of three reviewers (Gemini and GPT-5.3-Codex) independently flagged the **hook transport contradiction** as a real problem — the spec declares hooks are fully file-based with no HTTP calls, but other sections show `curl` calls to internal endpoints like `workflow_active_items`. This is the highest-confidence finding since two models caught it independently. **Severity: High.**

### Unique Findings

**GPT-5.3-Codex** was the most aggressive reviewer and caught several issues nobody else found:

- `files_accessed TEXT[]` still present in the `reviews` table DDL despite the Draft 8 changelog saying it was removed. A direct stale-reference bug. **Severity: High.** This is notable because Kimi explicitly checked for stale schema elements and reported the schema clean — a false negative.

- R5.2 (outcome prompting) has a requirements/spec mismatch: requirements say SessionStart prompts for unrated artifacts, but the spec changed this to manual prompting without updating R5.2. **Severity: High.**

- The `findings JSONB` field (marked deprecated) and "collect structured results" language in Phase 2 acceptance criteria conflict with the model-forward philosophy of raw prose being canonical. **Severity: Medium.**

- Backup/restore acceptance criteria say artifacts and embeddings should be "present and searchable" after restore, but the spec regenerates vectors asynchronously. Should explicitly allow eventual consistency or require blocking. **Severity: Medium.**

**Kimi K2.5** found a numbering confusion: R3.5 (a requirement ID for mechanical log) vs Phase 3.5 (semantic retrieval) — similar numbers for different things. **Severity: Low**, but worth a clarifying note. Kimi also noted missing explicit R3 sub-dependencies in the requirements doc and that cross-harness session loading isn't covered in acceptance tests. Both **very low severity**.

**Gemini** uniquely observed a potential overlap between the `FilesystemConnector` (which indexes `thoughts/` in place) and Phase 3.5 ingestion (which imports window files into the `artifacts` table). Noted as redundant but consistent with the "own it" principle — more of an architectural observation than a bug.

### Contradictions Between Reviewers

The sharpest disagreement is on stale references. Kimi K2.5 gave the schema a clean bill of health ("No references to `mechanical_log` table in schema — correctly absent") and found "no gaps or contradictions in core architecture." GPT-5.3-Codex found two concrete stale references (`files_accessed` in DDL, `findings JSONB` still active). Kimi appears to have validated the *intent* of the cleanup without cross-checking every DDL line. On this point, GPT-5.3-Codex is more credible — it cited specific line numbers.

Similarly on hooks: Kimi validated "hooks are file-based, no HTTP calls" as a checkmark item, while Gemini and GPT-5.3-Codex both found contradictory `curl` references elsewhere in the same document. Kimi took the declaration at face value rather than searching for inconsistencies. Two-against-one favors the contradiction being real.

### Recommended Actions

1. **Fix the hook transport model** — pick one canonical rule (file-based or HTTP-allowed) and reconcile all sections. (High, consensus)
2. **Remove `files_accessed TEXT[]`** from the `reviews` DDL. (High, GPT-5.3-Codex only but clearly correct)
3. **Reconcile R5.2** — either update the requirement to match the spec's manual prompting or restore the SessionStart behavior. (High, GPT-5.3-Codex only)
4. **Clean up `findings JSONB`** and "structured results" language to match model-forward philosophy. (Medium, GPT-5.3-Codex only)
5. **Clarify backup/restore** eventual consistency for embeddings. (Medium, GPT-5.3-Codex only)
6. **Add clarifying note** distinguishing R3.5 (requirement) from Phase 3.5 (build order). (Low, Kimi only)

**Models responded:** gemini (agentic), gpt-5.3-codex (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### gemini (complete)

I will begin by reading the requirements and specification documents to understand the Phase 3 redesign, specifically focusing on the transition to a window-file architecture and the removal of legacy tools and tables.

I will now read the specification document to examine the technical design for Phase 3, paying close attention to the window-file architecture, the removal of the mechanical log table, and the transition to file-based hooks.

I have reviewed the requirements and specification documents for the Phase 3 redesign. I will now perform a targeted search for any lingering references to removed tools or tables and examine the `continuity.py` and hook scripts to verify that the design aligns with the current implementation.

I will now check the body of the `docs/design/spec-personal-ai-infrastructure.md` file to ensure that the `mechanical_log` table and the four removed tools are no longer present, confirming that the document's content aligns with the change log.

I will now check for "mechanical log" and `log_unsummarized_count` in the specification document. I will also list the MCP tools mentioned to confirm the count and ensure no decommissioned tools remain.

The MCP tool count is confirmed at 23, and internal HTTP endpoints are correctly excluded. I will now examine the requirements document for any references to "mechanical_log" and verify that it has been appropriately replaced by the file-based mechanical log in the redesign.

The requirements document is clean of the old identifiers. I will now perform a final check for "mechanical log" in both the requirements and specification documents.

The mentions of "mechanical log" now consistently refer to the local JSONL file. The harness namespace design and `load_window_chain` appear sound, with Phase 3.5 correctly adding semantic retrieval. The "sensitive" flag provides necessary security, and the "start-with-why" narrative prompt aligns with the requirements. I will now verify the existence and functionality of the `claude` and `gemini` CLIs on nexus to ensure they can be used as agentic reviewers as specified.

`run_shell_command` is not in my available toolset despite the system prompt's instructions. I will use `grep_search` to find references to the `claude`, `gemini`, and `opencode` CLIs in the codebase, which will help me confirm their presence and intended usage for agentic reviews.

`CONTEXT.md` confirms `Claude Code` is installed, supporting the spec's `claude` command. I've noted the `gemini` and `opencode` commands in the review model registry and will now search the codebase for `gemini` to verify its presence and usage.

The infrastructure for multi-model reviews is confirmed, although `claude -p` may have output issues in certain environments. The window-file tree structure and harness namespacing are consistent, though parallel updates to a parent's `children` list could pose a minor concurrency risk. Phase 3.5's requirement for window file ingestion into the artifact store is clear. I will now check `src/claude_hub/` for the `continuity.py` module to determine its current status.

`continuity.py` is currently a spec, and Phase 3 is not yet implemented, while Phases 1 and 2 are partially complete. The window-file architecture design, featuring harness namespacing and parallel branching, is consistent across the requirements and spec. However, I need to clarify how window files will be ingested into the artifact store for Phase 3.5, given the "no MCP tools" instruction for forked agents. I will also examine the current `mechanical-log.sh` implementation in `.claude/hooks/` to see if it already handles log truncation as specified.

`CONTEXT.md` suggests `hooks/` and `skills/` are in `~/.claude/`, while the session context shows a `.claude/` directory in the project root. I'll re-examine the project's `.claude/` directory to clarify its contents.

`~/.claude/` refers to `/home/claude/.claude/`, while the session context shows a `.claude/` directory within `claude-hub/`. I'll now check the contents of `/home/claude/.claude/` to see if the hooks and skills are located there.

I'm restricted to `/home/claude/claude-hub/`, and the `hooks/` directory in `CONTEXT.md` likely refers to a location I can't access. I'll focus on `thoughts/mechanical.jsonl`, which `grep` previously identified, to see its contents.

The `mechanical.jsonl` log confirms recent work consistent with the Draft 10/8 updates, and the log's small size suggests truncation is functioning correctly. The PreCompact hook successfully implements context injection, although I've identified a minor inconsistency between Sections 1.3/4.8 and the shell script in 7.3 regarding the `workflow_active_items` call. The vision-requirements-spec chain is robust, with Phase 3's independence and the tree-structured window architecture standing out as particularly strong design choices. The "sensitive" flag and Claude's clean-room profile also represent well-thought-out features. I will now proceed to write the final review, incorporating these observations.

---

### Review: Personal AI Infrastructure Redesign (Phase 3 Window-File Architecture)

The transition to a window-file architecture in Phase 3 represents a significant architectural improvement over the previous tool-centric design. By moving context continuity from a structured database (`mechanical_log` table and MCP tools) to a file-based tree structure, the system gains robustness, supports parallel workstreams natively, and eliminates the "cold start" dependency on the Postgres/FastAPI infrastructure.

#### 1. Architectural Consistency and Vision Alignment
The "vision-requirements-spec" chain is coherent and well-maintained. The redesign directly addresses the "model-forward" principle by shifting cognitive tasks (summarization, narrative interpretation) from tools to forked agents, while keeping the "mechanics" (file I/O, hook triggers) in the code layer. 

**Finding:** The tree/fork/parallel session model in Section 2.3 is a major highlight. It correctly identifies that agentic workflows are not linear and provides a first-class data structure (window files with parent/children linking) to handle branching.

#### 2. Context Continuity Redesign (Phase 3)
The decision to make Phase 3 entirely file-based is strategically sound. It allows for immediate implementation and use without waiting for the more complex artifact store (Phase 1).

**Gap:** There is a minor inconsistency regarding the `PreCompact` hook. 
- **Section 1.3** and **Section 4.8** state that the `PreCompact` hook calls the internal HTTP endpoint `GET /workflow_active_items` to inject active work items.
- However, the reference implementation in **Section 7.3** does not show this `curl` call, only reading local window and log files. 
- *Recommendation:* Update the Section 7.3 script to include the `curl` call (likely as an optional block that fails gracefully if the server is down or Phase 7 isn't reached) to ensure "active work state" from Requirement 3.6 is fully satisfied.

**Observation:** The harness namespace design (`thoughts/windows/{harness}/`) effectively manages multi-tool support. Using a shared `NARRATIVE_PROMPT.md` ensures consistency in summary quality across different harnesses while allowing harness-specific window tracking via `.current-{session_id}` pointers.

#### 3. Stale References and Decommissioned Tools
The review confirms that Draft 8 of the spec and Draft 10 of the requirements have been rigorously cleaned of decommissioned tools (`context_summarize`, `context_load`, `log_operation`, `ingest_ledgers`) and the `mechanical_log` table. 

**Finding:** All body text and tool lists correctly reflect the new 23-tool count. Lingering references only exist in historical change logs and previous review documents, which is appropriate for audit purposes.

#### 4. Phase 3.5 (Semantic Retrieval) and Ingestion
The addition of Phase 3.5 bridges the gap between the file-based continuity layer and the semantic artifact store.

**Finding:** The ingestion of window files as artifacts is a key requirement (R3.3 Phase 3.5). The spec handles this by noting that window files are AI-generated artifacts and belong in the native store.
- *Potential Conflict:* There's a slight overlap between the `FilesystemConnector` (which indexes `thoughts/` in place) and Phase 3.5 ingestion (which imports window files into the `artifacts` table). While redundant, this follows the "own it" principle for AI-generated content.

#### 5. Review Engine and Security
The agentic review model is well-specified. The use of `--profile review` for Claude clean-room isolation is an elegant solution to the anchoring bias problem.

**Finding:** The `sensitive` flag implementation (Section 4.1) is robust. By skipping embedding and excluding sensitive artifacts from third-party review dispatch, it provides a verifiable privacy boundary.

#### 6. Acceptance Criteria and Testability
The acceptance criteria are generally achievable and empirical.
- **R1.2 (Semantic Search):** The fixed evaluation set (Section 10) is a professional standard for regression testing embedding quality.
- **R3.2 (Automatic Summarization):** The 20K token threshold and the use of `fork-agent.sh` are practical and align with the existing infrastructure.

**Finding:** The "mechanical log" truncation logic (R3.5) is critical for VPS performance. The current log (`thoughts/mechanical.jsonl`) shows active use, and the spec correctly identifies the need for truncation after successful summarization to prevent unbounded growth.

### Summary
The redesign is ready for implementation. The shift to a file-based, tree-structured context layer is a significant maturation of the system. The few inconsistencies found (specifically the `PreCompact` hook's use of workflow items) are minor and easily corrected during the implementation of the relevant phases. The dependency graph correctly identifies that Phase 3 can proceed immediately, providing high value for session continuity regardless of the Postgres rollout.


### gpt-5.3-codex (complete)

I reviewed only the two target files (`docs/design/spec-personal-ai-infrastructure.md` and `docs/design/requirements-personal-ai-infrastructure.md`); I did not read additional files.

Main finding: the redesign is directionally solid (window-file tree, harness namespace, Phase 3.5 split, mechanical log as JSONL), but there are a few high-impact consistency breaks that should be fixed before implementation.

- **High — Hook transport model is internally contradictory and misses your stated intent (“all hooks file-based, no HTTP”).**  
  In the spec, hooks are declared fully file-based with no HTTP calls (`docs/design/spec-personal-ai-infrastructure.md:1471`), but the same doc also says hooks call internal endpoints via `curl` (`docs/design/spec-personal-ai-infrastructure.md:1103`) and that some hooks route through FastAPI (`docs/design/spec-personal-ai-infrastructure.md:124`, `docs/design/spec-personal-ai-infrastructure.md:1645`, `docs/design/spec-personal-ai-infrastructure.md:1938`). This needs one canonical rule.

- **High — Stale schema element: `files_accessed` is “removed” in changelog but still present in DDL.**  
  The spec says Draft 8 removed `files_accessed` (`docs/design/spec-personal-ai-infrastructure.md:8`), but the `reviews` table still defines `files_accessed TEXT[]` (`docs/design/spec-personal-ai-infrastructure.md:242`). That is a direct stale-reference inconsistency.

- **High — Requirements/spec chain mismatch on outcome prompting (R5.2).**  
  Requirements require SessionStart prompting for unrated artifacts (`docs/design/requirements-personal-ai-infrastructure.md:287`), but the spec explicitly says this was changed to manual prompting (`docs/design/spec-personal-ai-infrastructure.md:10`) and the SessionStart flow reflects loading context only (`docs/design/spec-personal-ai-infrastructure.md:1580`). Either R5.2 must be revised or the spec must restore prompt behavior.

- **Medium — Model-forward review philosophy conflicts with residual “structured findings/results” language.**  
  The spec says raw prose is canonical and no parsing should occur (`docs/design/spec-personal-ai-infrastructure.md:1463`), yet still includes a `findings JSONB` field (marked deprecated) (`docs/design/spec-personal-ai-infrastructure.md:234`) and Phase 2 acceptance says “collect structured results” (`docs/design/spec-personal-ai-infrastructure.md:1739`). Not fatal, but this blurs implementation direction.

- **Medium — Backup/restore acceptance is underspecified vs async embedding behavior.**  
  Requirements expect restored artifacts and embeddings “present and searchable” (`docs/design/requirements-personal-ai-infrastructure.md:97`), while spec JSON restore regenerates vectors asynchronously (`docs/design/spec-personal-ai-infrastructure.md:797`, `docs/design/spec-personal-ai-infrastructure.md:816`). Acceptance should explicitly allow eventual searchability (or require blocking until re-embed complete).

What is coherent and strong:
- Tree/forest window model and forking semantics are consistently described across both docs (`docs/design/spec-personal-ai-infrastructure.md:261`, `docs/design/requirements-personal-ai-infrastructure.md:217`).
- Harness namespace design is clear and extensible (`docs/design/spec-personal-ai-infrastructure.md:265`, `docs/design/requirements-personal-ai-infrastructure.md:212`).
- Phase 3 vs 3.5 separation is consistent and implementable in principle (`docs/design/spec-personal-ai-infrastructure.md:1767`, `docs/design/requirements-personal-ai-infrastructure.md:180`).
- Narrative “start-with-why” principle is explicitly captured (`docs/design/spec-personal-ai-infrastructure.md:1529`).


### kimi-k2.5 (complete)

I'll review the Phase 3 window-file architecture design documents. Let me start by reading the files mentioned in the prompt.
Let me continue reading the spec to see the rest of the content:
After reviewing both documents, here's my assessment:

## Overall Assessment

The documents are **internally consistent and well-aligned** with the stated intent. The Phase 3 redesign is coherent and represents a thoughtful simplification from the earlier architecture.

## Findings

### Minor Issues

**1. Requirements Doc: Dependency Comment on R3.5 (Low severity)**
- Line 419 in requirements: "R3.5 (mechanical log) is already implemented, no new work"
- **Issue:** The parenthetical "mechanical log" is confusing—R3.5 is semantic retrieval; the mechanical log is R3.5 in the requirements list (line 202). This appears to be a copy/paste error where "mechanical log" should be "semantic retrieval" or the reference is to R3.5 being mechanical log (which is wrong).
- **Clarification needed:** The mechanical log is requirement R3.5 in Draft 10 (line 202), but Phase 3.5 in the spec is "Context Load — Semantic Retrieval". These are different things with similar numbering—one is a requirement ID, one is a phase number. Not a bug, but potentially confusing.

**2. Requirements Doc: R2 Dependency Statement (Low severity)**
- Line 418: "R2 (Multi-Model Review) depends on R1 for storing results."
- This is technically true but circular—every requirement "depends on R1 for storing results." The more precise dependency is that R2 uses the artifact store to persist reviews and syntheses, which is correctly elaborated in R2.3.

**3. Requirements Doc: Missing Explicit Dependencies for R3.2 and R3.6 (Low severity)**
- The dependencies section (lines 414-424) doesn't explicitly list the internal R3 sub-dependencies.
- The spec Section 9 (Build Order) correctly states that R3.2 and R3.6 depend on R3.7 (window files) and R3.5 (mechanical log).
- **Recommendation:** Add these sub-dependencies to the requirements doc for completeness: "R3.2 and R3.6 depend on R3.7 and R3.5."

**4. Spec: Tool Count Math Check (Low severity)**
- Line 6: "Corrected MCP tool count to 23 (Draft 7 said 30 but had already removed 3 review tools; this draft removes 4 more continuity tools)."
- Original: 30 tools
- Draft 7 removed: 3 review tools → 27
- Draft 8 removes: 4 continuity tools → 23
- **Math checks out:** 30 - 3 - 4 = 23 ✓

### Validation of Key Changes

✅ **Mechanical log removed from Postgres:** Spec 2.3 clearly states it's a local JSONL file only.

✅ **4 MCP tools replaced:** Spec 4.3 confirms no MCP tools for continuity; hooks and CLI instead.

✅ **Window files form a tree:** Spec 2.3: "Window files form a tree (not a linear chain)" and "multiple children from one parent is normal."

✅ **Harness namespace:** Spec 2.3: `thoughts/windows/{harness}/` — correctly supports multi-tool.

✅ **Phase 3.5 for semantic retrieval:** Clearly separated in both documents (Requirements R3.3 Phase 3.5, Spec Build Order Phase 3.5).

✅ **Hooks are file-based:** Spec 7: "All hooks are file-based... No hooks make HTTP calls."

✅ **Narrative prompt start-with-why:** Spec 7.2 explicitly describes this principle.

### Stale References Checked

- ❌ **No references to `mechanical_log` table** in schema (correctly absent)
- ❌ **No references to `context_summarize`, `context_load`, `log_operation`, `ingest_ledgers`** as tools (correctly removed)
- ✅ All references to these concepts now point to the file-based equivalents

### Gaps or Contradictions

**None found** in core architecture. The tree/fork/parallel model is coherent. The acceptance criteria are achievable. The vision-requirements-spec chain is intact.

### Cross-Harness Clarification Needed (Very low severity)

Spec 2.3 mentions parent references "can cross harness boundaries via relative paths," but the acceptance test in R3.7 only tests within a single harness. The SessionStart hook (Spec 7.4) reads from `thoughts/windows/claude-code/` specifically. Consider documenting how a forked agent from one harness creating a child in another harness would work in practice—though this may be intentionally deferred as an edge case.

## Summary

**Verdict: Approve with minor clarifications.**

The documents are ready for implementation. The only recommended changes are:
1. Fix the confusing parenthetical in requirements line 419 (clarify R3.5 vs Phase 3.5 distinction)
2. Add explicit R3 sub-dependencies in requirements
3. Optionally clarify cross-harness session loading behavior in spec Section 7.4

