# Review: 2026-03-22 17:14 UTC

**Prompt:** Review these three design documents as a coherent chain (vision → requirements → spec). Check for: (1) internal consistency — do the requirements trace to vision statements, does the spec implement the requirements? (2) stale references — any remaining mentions of SQLite, ledgers, personas, or outdated paths that should have been updated? (3) ontology alignment — do all three documents consistently use the 7-concept ontology (role, project, service, agent, task, resource, session) and the workstream × component tagging? (4) completeness — are there vision concepts not covered by requirements, or requirements not specified? Focus on substantive issues, not formatting.
**Files:** docs/design/vision-personal-ai-infrastructure.md, docs/design/requirements-personal-ai-infrastructure.md, docs/design/spec-personal-ai-infrastructure.md
**Job ID:** c4acb0e4-af54-42a1-abc8-bd2002ac2c4a

## Synthesis

## Review Synthesis: Vision D14 → Requirements D13 → Spec D12

Eight models produced substantive reviews (grok-code-fast-1 and mimo-v2-pro returned nothing). The reviews split into two camps: document-only reviewers (Claude, Claude Sonnet, Gemini, Kimi, GLM-5) and implementation-checking reviewers (GPT-5.4, GPT-5.3 Codex, MiniMax). The second group found more — and more severe — issues, because the design chain's biggest problems are at the spec↔code boundary, not within the documents themselves.

### High-Confidence Consensus (3+ reviewers agree)

**MCP tool count is wrong.** Claude, Claude Sonnet, and GPT-5.3 Codex all independently found that the spec summary claims 23 tools with "2 knowledge-quality," but Section 4.4 defines 3 knowledge-quality tools, making the real total 24. The error is confined to the summary paragraph; the individual sections and build phases are correct. Medium severity — bookkeeping, but the kind that causes implementation confusion.

**R3.5 and R3.7 acceptance criteria point at fallback paths, not primary.** Claude, Claude Sonnet, GPT-5.3 Codex, GPT-5.4, and MiniMax all flagged this. The requirement bodies correctly describe `~/roles/{role}/` as primary with `thoughts/windows/{harness}/` as fallback, but the acceptance criteria still hard-code the old harness-scoped paths. GPT-5.3 Codex put it most sharply: "a team can satisfy acceptance while violating the stated architecture." This is the single most-agreed-upon finding across all reviewers. High severity in aggregate — it's a test-oracle conflict that would let the wrong implementation pass.

**FilesystemConnector default path is stale.** Claude, Claude Sonnet, Kimi, and GPT-5.3 Codex all caught `"/home/claude/claude-hub/thoughts/"` in the spec's connector example. The canonical path is now `/home/claude/projects/claude-hub/thoughts/`. Medium severity — a developer implementing from the spec would use the wrong path.

**Vision cross-references are stale.** Claude and GPT-5.3 Codex noted the vision's implementation status still says "Requirements Draft 12, Spec Draft 11" when they're now Draft 13 and Draft 12. Low-medium severity — bookkeeping that undermines the provenance chain.

**Requirements scope still says "Outcome tracking."** Claude Sonnet, Gemini, and GPT-5.3 Codex found that line 31 of the requirements doc still reads "Outcome tracking — rating approach results to build weighted precedent" even though R5 was rewritten as "Knowledge Quality." Medium-low severity, but it reintroduces the old conceptual model at the top of the document.

**Ontology concept "resource" is undefined downstream.** Claude, Claude Sonnet, and GPT-5.3 Codex noted that the 7-concept ontology includes "resource" but it never appears in requirements, spec, or frontmatter. Claude Sonnet was strongest: "an undefined concept is a gap" in what's described as the organizing principle. Low-medium severity — it's either a gap or a concept that should be removed from the ontology.

### Findings From Multiple Reviewers (2 agree)

**Clean-room exclude paths are inconsistent across documents and code.** Claude Sonnet and GPT-5.4 found that the requirements, spec, and implementation all give different answers to "what are the default clean-room excludes?" Requirements list `thoughts/ledgers/`, `thoughts/history/`, `.claude/`, `CLAUDE.md`. The spec's prompt text omits `thoughts/ledgers/`. The actual code (`review_engine.py:111`) excludes all of `thoughts/`. MiniMax added that this broader exclusion blocks reviewers from reading window files — a functional regression. Medium-high severity collectively.

**The role-scoped continuity architecture is not settled.** GPT-5.4 and MiniMax both checked the implementation and found that `continuity.py` still uses `thoughts/windows/{harness}/` as primary, directly contradicting the spec's `~/roles/{role}/windows/` primary path. GPT-5.4 called this "the biggest problem" — the chain doesn't give one unambiguous answer to where role memory lives. GPT-5.3 Codex confirmed via test inspection. High severity — this is an architecture fork, not a typo.

**Workstream × component tagging exists but isn't operationalized.** GPT-5.4 and MiniMax both found that while the frontmatter schema includes `workstream` and `component`, there are no requirements or acceptance tests for querying by them, and `continuity_ingest.py` drops those fields entirely when persisting to the artifact store. The tags exist syntactically but not behaviorally. Medium-high severity per GPT-5.4; low per MiniMax.

### Unique Findings (single reviewer)

**Gemini: `artifact_search` SQL ignores the `confidence` filter parameter.** The tool signature accepts `confidence` but the SQL WHERE clause never binds it. High severity — the API contract is broken at the SQL layer. No other reviewer caught this. Worth verifying; Gemini is sometimes overconfident on SQL analysis, but the finding is specific enough to be credible.

**Gemini: Write tools lack inline `confidence` parameter.** R5.2 says agents can annotate confidence when storing, but `artifact_store` and `artifact_update` don't accept it — requiring a separate `artifact_set_confidence` call. Medium severity — friction that contradicts the requirement's intent.

**Claude Sonnet: R6.1 creation templates are conflated with review gate prompts.** The requirement asks for creation-time guidance ("what sections to include when starting a new document") but the spec only delivers review-time prompts ("does this doc fully cover the vision?"). The two halves of R6.1 are collapsed into one. High severity — an entire half of a requirement is unspecified.

**Claude Sonnet: R6.3 lineage traversal isn't achievable from the specified API.** The acceptance criterion requires transitive discovery ("artifacts related to [vision doc]" returning descendants), but the GIN index only supports single-hop containment queries, not recursive DAG traversal. High severity — the acceptance criterion is unimplementable from the spec as written.

**Claude Sonnet: R4.2 auto-detection coupling is unexamined.** The spec has `artifact_store` tracking counts and triggering `pattern_detect()`, making the store responsible for compounding logic. This inverts the expected dependency direction. Medium severity — design debt that deserves at least a note.

**GPT-5.3 Codex: R4.2 promotion target "agent update" is missing from spec.** Requirements include escalation to an agent update, but `pattern_promote` only allows `skill|hook|rule`. Medium severity — a required promotion type is unspecified.

**GPT-5.4: Vision's boundary/scoping model doesn't carry into requirements.** The vision distinguishes discoverability from content access and makes data boundaries foundational. Requirements reduce this to MCP auth and `sensitive` artifacts. No requirement for role-scoped or connector-scoped access, no discoverability-vs-access primitive. Medium-high severity — GPT-5.4 called it "a real completeness gap, not just an editorial omission."

**GPT-5.4: Persistent agent infrastructure disappears after the vision.** The vision makes persistent agents architecturally central, but requirements have zero coverage for enabling infrastructure (agent registry, scheduling, inter-agent messaging) — even though `scheduler.py` and `workspace.py` already exist. Medium severity.

**Gemini: Retirement timestamp ambiguity.** `artifact_retirement_candidates` doesn't specify whether `min_age_days` evaluates against `created_at` or `last_retrieved`. Low severity but operationally relevant.

**Claude: Ontology frontmatter example omits `children` field.** The ontology doc's example doesn't include `children: []` that the spec and requirements define. Low severity.

**GLM-5: Spec comment says "analyst" role but ontology only defines three roles.** Line 287 comment mentions `(workbench, analyst, etc.)` but "analyst" isn't a defined role. Low severity — comment-only.

### Contradictions Between Reviewers

**Severity of the path/acceptance-criteria issue.** Claude rated R3.5/R3.7 path issues as "Low severity." Claude Sonnet rated R3.7 as "High severity." GPT-5.3 Codex rated the combined finding as "High." GPT-5.4 rated the broader continuity path fork as "High." The implementation-checking reviewers were right to escalate — the issue extends beyond documents into live code.

**Stale references: clean or problematic?** GLM-5 declared "no stale references found" across all three documents. Every other reviewer found at least one. GLM-5 appears to have checked only for SQLite/ledger/persona references and missed path staleness entirely. Least reliable review of the set.

**Ontology alignment: complete or partial?** Kimi's table shows all 7 concepts as "Aligned" across all documents. GPT-5.3 Codex and Claude both note that "resource" is absent from requirements and spec. MiniMax adds that "agent" and "task" are also absent from window frontmatter. Kimi's assessment is the most optimistic and least accurate on this point.

**Chain coherence overall.** Kimi and GLM-5 describe the chain as ready for implementation with no blocking issues. GPT-5.4 says the newer architecture layer is "only half translated from vision into requirements and spec." The gap is real — the document-only reviewers saw a well-structured chain; the implementation-checking reviewers saw a chain that's coherent on paper but divergent in code.

### Severity Summary

| Severity | Finding | Reviewers |
|----------|---------|-----------|
| High | Continuity path fork: spec says role-scoped, code says project-local | GPT-5.4, MiniMax, GPT-5.3 Codex |
| High | R3.5/R3.7 acceptance criteria test fallback paths, not primary | Claude, Sonnet, GPT-5.4, GPT-5.3 Codex, MiniMax |
| High | `artifact_search` SQL ignores `confidence` filter | Gemini (unique) |
| High | R6.1 creation templates unspecified (only review prompts exist) | Sonnet (unique) |
| High | R6.3 lineage traversal unimplementable from spec API | Sonnet (unique) |
| Medium-High | Clean-room excludes inconsistent across docs and code | Sonnet, GPT-5.4, MiniMax |
| Medium-High | Vision boundary/scoping model not carried to requirements | GPT-5.4 (unique) |
| Medium | MCP tool count 24 not 23 | Claude, Sonnet, GPT-5.3 Codex |
| Medium | FilesystemConnector default path stale | Claude, Sonnet, Kimi, GPT-5.3 Codex |
| Medium | Workstream × component tags not operationalized | GPT-5.4, MiniMax |
| Medium | "Outcome tracking" still in requirements scope line | Sonnet, Gemini, GPT-5.3 Codex |
| Medium | R4.2 "agent update" promotion target missing from spec | GPT-5.3 Codex (unique) |
| Medium | Confidence not accepted on write tools | Gemini (unique) |
| Low-Medium | Vision draft cross-references stale | Claude, GPT-5.3 Codex |
| Low | "Resource" absent from downstream docs | Claude, Sonnet, GPT-5.3 Codex |
| Low | Ontology frontmatter example missing `children` | Claude (unique) |
| Low | "Analyst" in spec comment not a defined role | GLM-5 (unique) |

### Reviewer Quality Notes

**GPT-5.4** produced the strongest review — it checked implementation, found architectural-level issues others missed (boundary model, persistent agent gap, workstream operationalization), and its severity assessments were well-calibrated. **Claude Sonnet** was the sharpest on spec-level logic (R6.1 creation/review conflation, R6.3 transitive traversal, R4.2 coupling). **Gemini** caught the SQL-level `confidence` filter bug that everyone else missed. **Claude (Opus)** was thorough on bookkeeping and traceability. **GPT-5.3 Codex** added the R4.2 promotion target gap. **MiniMax** confirmed implementation-level findings but added less that was new. **Kimi** was solid on structure but too optimistic on alignment. **GLM-5** produced the weakest review — shallow analysis that declared no issues where multiple existed.

**Models responded:** claude (agentic), claude-sonnet-4.6 (agentic), gemini-3.1-pro (agentic), kimi-k2.5 (agentic), gpt-5.4 (agentic), gpt-5.3-codex (agentic), glm-5 (agentic), minimax-m2.7 (agentic), grok-code-fast-1 (agentic), mimo-v2-pro (agentic)

## Individual Reviews

### claude (complete)

---

## Review: Vision (D14) → Requirements (D13) → Spec (D12)

**Files reviewed:** The three design documents, plus `docs/design/ontology.md` as evaluative context.

---

### 1. MCP Tool Count Is Wrong (Spec — Medium Severity)

The spec claims 23 MCP tools throughout (scope section line 60, Section 4.3 line 868, summary line 2004). The summary breakdown says "2 knowledge-quality." But Section 4.4 is headed "R5 — Knowledge Quality (3 tools)" and defines three: `artifact_feedback`, `artifact_set_confidence`, `artifact_retirement_candidates`. The actual count is 9 + 0 + 0 + **3** + 3 + 6 + 3 = **24**. The "2 knowledge-quality" in the summary is a typo, and the 23 figure carries forward in three places. This is the kind of error that could cause confusion during implementation if someone tries to reconcile tool counts.

---

### 2. Vision Implementation Status References Are Stale (Vision line 5 — Low-Medium Severity)

The vision's implementation status note says "Requirements (Draft 12) and spec (Draft 11) cover Phases 1-8." But the requirements are now Draft 13 and the spec is Draft 12. The vision was clearly updated to Draft 14 but didn't increment these cross-references. This is a bookkeeping error, not a conceptual one, but it undermines the chain-of-derivation tracking that the spec-driven workflow depends on.

---

### 3. FilesystemConnector Default Path Is Stale (Spec line 1378 — Medium Severity)

The FilesystemConnector reference implementation specifies:
```json
{ "root_path": "/home/claude/claude-hub/thoughts/", ... }
```

The project now lives at `~/projects/claude-hub/`. The old path `/home/claude/claude-hub/` still resolves (it's a bind mount or symlink situation), but the spec should reference the canonical path. Anyone implementing from the spec would use the stale path.

---

### 4. R3.5 and R3.7 Acceptance Criteria Reference Fallback Paths as Primary (Requirements — Low Severity)

R3.5 acceptance (line 204) says: "a JSONL log exists at `thoughts/mechanical.jsonl`" — but the primary path is now `~/roles/{role}/mechanical.jsonl` (the body of R3.5 itself says so). The acceptance criterion should reference the primary path, with the fallback as the fallback.

Similarly, R3.7 acceptance (line 219) says: "two linked window files exist in `thoughts/windows/{harness}/`" — but the primary path is now `~/roles/{role}/windows/`. The acceptance criterion uses the pre-restructuring fallback path, not the primary.

Both the requirement bodies describe the correct primary paths, so this is a consistency issue between the prose and the acceptance criteria within the same requirement.

---

### 5. Vision Omits Two Ontology Concepts (Vision ↔ Ontology — Low Severity)

The ontology defines 7 concepts: role, project, service, agent, task, resource, session. The vision's Section 4 ("The Architecture Problem") discusses roles, projects, agents, tasks, and multi-harness. But **resource** (durable infrastructure like PostgreSQL, FUSE mounts, the volume) and **session** (a concrete execution instance) are absent as named concepts. "Session" is used informally throughout the vision (e.g., "interactive sessions") but never defined as a first-class organizing concept. "Resource" doesn't appear at all.

This isn't a gap in the requirements or spec — both inherit from the ontology document, which is the authoritative source. But if the vision is supposed to be the governing document from which everything else derives, it would be cleaner for it to at least acknowledge these two concepts, since the requirements and spec use them extensively.

---

### 6. Ledger References Are Correct but Noisy (All Three Documents — Informational)

The documents contain many references to ledgers: in changelogs, in R3.4 (migration complete), in the existing infrastructure table. All references are correctly contextualized as "decommissioned" or "migrated." None treat ledgers as current infrastructure. This is not a stale reference problem — it's historical documentation working as intended. The only question is whether the volume of historical ledger references is worth the reading cost, but that's an editorial choice, not a correctness issue.

---

### 7. Ontology Frontmatter Example Omits `children` (Ontology ↔ Spec — Low Severity)

The ontology document's frontmatter example (ontology.md line 87-101) does not include a `children` field. Both the spec (Section 2.3) and requirements (R3.7) specify `children: []` as part of the window file frontmatter schema. This is a minor inconsistency between the ontology doc (which is the authoritative source for the frontmatter schema per its "What This Document Supersedes" section) and the design chain.

---

### 8. Requirements-to-Vision Traceability Is Strong

Every requirement section includes an explicit "Vision reference" header pointing to the relevant vision section. I spot-checked all seven:

- R1 → "Generated Artifacts Need a Home," "Persistent Context That Compounds" ✓
- R2 → "Multiple models produce better results," "Multi-model review has a diminishing returns curve" ✓
- R3 → "Conserve," "Persistent Context That Compounds," incremental summarization ✓
- R4 → "Persistent Context That Compounds" (capability compounding), "Custom beats generic" ✓
- R5 → "Persistent Context That Compounds" (usage-weighted feedback), "Compounding over features" ✓
- R6 → "Structured workflows beat ad hoc prompting," "Progressive refinement" ✓
- R7 → "The hard part is connectors," "View, don't warehouse" ✓

The tracing is solid and each requirement clearly derives from identifiable vision statements.

---

### 9. Spec-to-Requirements Traceability Is Strong

The spec organizes its API surface and build phases by requirement number. Every requirement is implemented. The acceptance tests in the build phases (Section 9) closely mirror the acceptance criteria in the requirements. The phasing is well-motivated by the dependency structure. I found no requirement that lacked spec coverage or spec content that didn't trace to a requirement.

---

### 10. Vision Concepts Without Explicit Requirements Coverage (Vision ↔ Requirements — Informational)

The vision describes several concepts that are explicitly out of scope in the requirements:
- Proactive context surfacing (vision Section 2, acknowledged as out of scope in requirements)
- Agent autonomy policies (mentioned in both vision open questions and requirements out-of-scope)
- Cost management (same)
- Cross-agent coordination (vision open question, no requirement)
- Packaging for public use (vision open question, no requirement)

This is clean — the requirements scope section explicitly lists what's out of scope and why. These aren't gaps; they're deliberate deferrals with the architecture not precluding them.

---

### 11. "Outcome" Language Remnants (Spec — Informational)

The spec's index name at line 434 is `idx_artifact_feedback_artifact` (correct), but the comment on line 434 says `-- Outcomes`. This is a minor remnant from the "outcome tracking" → "knowledge quality" rename. The changelogs document this rename happened in Draft 9/10, but this comment wasn't caught. Cosmetic only — doesn't affect behavior.

---

### Summary of Actionable Findings

| # | Severity | Document | Finding |
|---|----------|----------|---------|
| 1 | Medium | Spec | MCP tool count is 24, not 23; summary says "2 knowledge-quality" but section defines 3 |
| 2 | Low-Medium | Vision | Implementation status says "Requirements Draft 12, Spec Draft 11" — should be 13 and 12 |
| 3 | Medium | Spec | FilesystemConnector root_path uses old `/home/claude/claude-hub/` path |
| 4 | Low | Requirements | R3.5 and R3.7 acceptance criteria use fallback paths, not primary |
| 5 | Low | Vision | Ontology concepts "resource" and "session" absent from vision |
| 7 | Low | Ontology | Frontmatter example omits `children` field that spec/requirements define |

The chain is well-constructed overall. The traceability from vision through requirements to spec is unusually thorough — every requirement traces to vision statements, every spec section traces to requirements, and the build phases have acceptance tests that mirror requirement criteria. The substantive issues are bookkeeping (tool count, cross-reference versions, path updates) rather than conceptual gaps.


### claude-sonnet-4.6 (complete)

**Files read beyond review targets:** None. The three review targets were sufficient to form complete findings.

---

## Review: Vision → Requirements → Spec Chain

### High Severity

**1. MCP tool count is wrong in the spec summary (Spec, Section 11, line 2004)**

The summary states "23 MCP tools organized by... 2 knowledge-quality." But Section 4.4 defines three knowledge-quality tools — `artifact_feedback`, `artifact_set_confidence`, and `artifact_retirement_candidates` — and Phase 4's build task (line 1831) explicitly says "Add 3 MCP tools." With 3 knowledge-quality tools the correct total is 24, not 23. The error is entirely in the summary paragraph; all three tools are fully specified and the build phase is correct. The "2 knowledge-quality" is a stale count from a previous draft that didn't get updated when the third tool was added.

**2. R3.7 acceptance criterion points to the wrong window file path (Requirements, R3.7)**

The R3.7 acceptance says "two linked window files exist in `thoughts/windows/{harness}/`." The spec's Section 2.3 establishes `~/roles/{role}/windows/` as the primary location, relegating `thoughts/windows/{harness}/` to fallback status when no role is active. Since the role system is operational and the infrastructure restructuring placed window files in the role-scoped directory, the acceptance criterion in requirements is pointing at the fallback rather than the primary path. A test written against this criterion would pass the fallback case and fail to cover the primary case.

**3. R6.1's creation template requirement is not implemented in the spec (Requirements, R6.1; Spec, Section 4.6)**

R6.1 requires "each stage has a template or prompt that guides its creation: what sections to include, what questions to answer, what level of detail is appropriate." The acceptance criterion says "when starting a new requirements document, the system provides a template or structured prompt."

The spec delivers review gate prompts stored in `config/stage_templates.yaml` — prompts like "Does this requirements doc fully cover the vision? Are there gaps?" These are review-time prompts used by `workflow_advance` when transitioning between stages, not creation-time guidance. There's no spec coverage for the creation side: how does a user start writing a new vision doc? What template do they get? The two halves of R6.1 (creation guidance and review gate prompts) are conflated in the spec as though they're the same thing.

---

### Medium Severity

**4. Default clean-room exclude paths are inconsistent between documents (Requirements, R2 constraints; Spec, Section 6)**

Requirements R2 constraints, inherited from the Draft 4 changelog, list the default exclude paths as `["thoughts/ledgers/", "thoughts/history/", ".claude/", "CLAUDE.md"]`. The spec's Clean-Room Implementation section (Section 6) says "Suppress: Project-level instructions (CLAUDE.md), process preferences, style guides, design rationale, thoughts/history/ directory" — omitting `thoughts/ledgers/`. With the ledger system decommissioned in March 2026, `thoughts/ledgers/` likely doesn't exist; including it in the defaults is harmless but misleading. More concretely: the two documents give different answers to "what are the default clean-room exclude paths?" This matters for implementing and testing R2.6's acceptance criterion, which requires that "the constructed review prompt verifiably includes boundary instructions specifying which paths to avoid."

**5. Mechanical log path stale in R3.5 acceptance (Requirements, R3.5)**

R3.5 acceptance says "a JSONL log exists at `thoughts/mechanical.jsonl`." The spec Section 2.3 and R3.5's constraints both establish `~/roles/{role}/mechanical.jsonl` as the primary path, with `thoughts/mechanical.jsonl` as fallback. The acceptance criterion tests the fallback path rather than the primary one. Same pattern as finding 2: the requirements didn't get updated when the role-scoped infrastructure was introduced.

**6. FilesystemConnector default root_path is stale (Spec, Section 5.3)**

The default config for `FilesystemConnector` shows `"root_path": "/home/claude/claude-hub/thoughts/"`. The infrastructure restructuring moved projects to `~/projects/`, making the current path `/home/claude/projects/claude-hub/thoughts/`. The old path is a default value a developer would use without checking, and a connector instantiated with this path would silently index nothing (or whatever lives at that old location).

**7. Auto-detection coupling is unexamined design debt (Spec, Section 4.5, line 957)**

R4.1 requires pattern detection to fire automatically after every 10 new session-summary artifacts. The spec implements this by having `artifact_store` track the count and trigger `pattern_detect()` when the threshold is crossed. This makes the artifact store responsible for capability compounding logic — a coupling that runs opposite to how every other cross-requirement interaction works (the patterns module should react to artifact store events, not the other way around). The spec doesn't acknowledge this coupling as a deliberate choice, doesn't discuss how to avoid circular imports between `artifact_store.py` and `patterns.py`, and doesn't consider whether this should use an event/hook approach instead. At minimum it deserves a design note.

---

### Low Severity

**8. R3.5/Phase 3.5 naming collision (Requirements, Dependencies section)**

The requirements acknowledge this with a parenthetical note. The collision between R3.5 (mechanical log requirement ID) and Phase 3.5 (semantic retrieval build phase) is benign for human readers who notice the footnote, but will cause systematic confusion in any automated cross-referencing, tooling, or future document that references these by ID. The fix is a rename — either R3.5 becomes R3.a or the Phase becomes 3b.

**9. "Resource" is named in the ontology but undefined everywhere (Vision, Section 4)**

The vision establishes a 7-concept ontology: role, project, service, agent, task, resource, session. Six of the seven appear in requirements (R3.7 frontmatter, R6, R4) and the spec schema. "Resource" is named once in the vision, never defined, doesn't appear in the window file frontmatter, and has no corresponding schema element. If the seven-concept ontology is the organizing principle of the system — and it's described as such — an undefined concept is a gap. The connector interface (R7) is the closest thing to resource formalization, but neither the requirements nor spec make that connection.

**10. Persistent agent infrastructure is vision-critical but requirements-absent**

The vision's Architecture Problem section treats persistent agents as a first-class architectural element: agents that read window files and pick up where they left off, that can be combined into multi-agent pipelines, that maintain continuity across invocations without human re-briefing. The requirements scope statement explicitly puts "agent autonomy policies" out of scope, which is reasonable. But there's a distinction between autonomy policy (how much an agent can do unsupervised) and infrastructure (what plumbing would support persistent agents at all — agent registry, scheduling, inter-agent messaging). The scheduler module exists in the codebase and is mentioned in the CLAUDE.md, but it doesn't appear anywhere in these three documents. The vision describes persistent agents as architectural load-bearing structure; the requirements have zero coverage for the enabling infrastructure even at an abstract level. This is either an intentional deferral that should be stated, or a gap.

**11. R6.3 lineage traversal not deliverable from specified API (Requirements, R6.3; Spec, Section 4.1)**

R6.3 acceptance: "Query the artifact store for 'artifacts related to [vision doc].' The requirements doc and any reviews appear in results." This requires discovering descendants transitively — finding everything that derives from a given artifact. The spec provides `idx_artifacts_derives_from` (a GIN index supporting containment queries) and `artifact_search`, but neither supports recursive DAG traversal. A GIN containment query finds artifacts where the given UUID appears in `derives_from`, but not artifacts that derive from those, and so on. The acceptance criterion as written is not achievable from the specified API surface without either a new tool or recursive SQL that isn't defined.

**12. R1 constraints paragraph misleadingly describes the past as present (Requirements, R1 constraints)**

The paragraph reads: "The thoughts/ directory already contains valuable content (ledgers, plans, design docs, research). The store should be able to ingest existing files, not require re-creation. Ledgers are imported into the store (R3.4)." Ledgers were decommissioned in March 2026. The first sentence suggests ledgers are current content awaiting ingestion; R3.4 clarifies they're already done; but the two together read as contradictory. This is cosmetic but would mislead anyone implementing R1's ingestion requirement.


### gemini-3.1-pro (complete)

I have reviewed the three design documents (`vision-personal-ai-infrastructure.md`, `requirements-personal-ai-infrastructure.md`, and `spec-personal-ai-infrastructure.md`) as a cohesive sequence, alongside `docs/design/ontology.md` to establish the 7-concept baseline. I did not read any files in the restricted directories (`thoughts/`, `.claude/`, or `CLAUDE.md`).

Overall, the chain from vision to requirements to specification is exceptionally strong. The recent migration from "Outcome Tracking" to "Knowledge Quality" (agent-driven feedback) is well-reasoned, and the window-file architecture elegantly solves the context-rot problem without over-engineering. Ontology alignment is perfect: the 7 concepts and the orthogonal `workstream` × `component` tagging are explicitly represented in the YAML frontmatter definitions across both the requirements and the spec.

Here are my findings, ordered by severity.

### 1. Search SQL ignores the `confidence` filter (High Severity)
**Location:** `spec-personal-ai-infrastructure.md`, Section 4.1 (`artifact_search`)
The `artifact_search` tool signature defines a `confidence` parameter (intended to filter results by a minimum confidence level, e.g., "HIGH"). However, the provided SQL query entirely omits this filter from its `WHERE` clause. It only checks `(a.confidence != 'SUPERSEDED' OR include_archived)`, but does not bind or evaluate the user-provided `confidence` parameter. As written, the API contract is broken at the SQL layer. 

### 2. Missing `confidence` parameter on write tools (Medium Severity)
**Location:** `requirements-personal-ai-infrastructure.md` (R5.2) vs `spec-personal-ai-infrastructure.md` (Section 4.1)
Requirements R5.2 explicitly states: *"When storing or updating knowledge, agents can annotate their confidence level."* However, the Spec's `artifact_store` and `artifact_update` tools do not accept a `confidence` parameter. To fulfill the requirement today, an agent must make two separate tool calls (`artifact_store` followed immediately by `artifact_set_confidence`), which introduces unnecessary friction to what should be an inline, low-friction metadata annotation. 

### 3. Stale "Outcome Tracking" in Requirements Scope (Medium/Low Severity)
**Location:** `requirements-personal-ai-infrastructure.md`, Line 31
The document correctly notes in its changelog that Requirement 5 was rewritten and renamed from "Outcome Tracking" to "Knowledge Quality". The section body (R5) is perfectly updated. However, the high-level "In scope" list at the top of the document still reads: *"5. Outcome tracking — rating approach results to build weighted precedent"*. This should be updated to reflect the new Knowledge Quality / usage-weighted feedback framing.

### 4. Ambiguous timestamp for retirement evaluation (Low Severity)
**Location:** `spec-personal-ai-infrastructure.md`, Section 4.4 (`artifact_retirement_candidates`)
The behavior definition says: *"Find artifacts with low utility scores, low confidence, or SUPERSEDED status that are older than `min_age_days`."* The spec recently added a `last_retrieved` column to the `artifacts` table. It should explicitly state whether `min_age_days` is evaluated against `created_at` (absolute age) or `last_retrieved` (time since last used), as the latter is a much stronger signal for safe retirement.

### 5. Minor Stale Nomenclature (Low Severity)
**Locations:** `spec-personal-ai-infrastructure.md` (Line 434) and `requirements-personal-ai-infrastructure.md` (Line 160)
- In the Spec's database schema, the comment before creating `idx_artifact_feedback_artifact` still reads `-- Outcomes`. It should be `-- Knowledge Quality`.
- In the Requirements (R2.6 Constraints), the default clean-room exclude paths list *"continuity ledgers"*. Since the ledger system was entirely decommissioned and migrated to window files (per R3.4), this is a stale reference to the old continuity artifact.


### kimi-k2.5 (complete)

I'll review the three design documents as a coherent chain. Let me start by reading them and then explore adjacent context.
Now I have a comprehensive view of the three documents plus the ontology and infrastructure redesign plan. Let me write my review.

---

## Review: Vision → Requirements → Spec Chain

### Files Read
Beyond the three review targets, I also read:
- `docs/design/ontology.md` — defines the 7-concept ontology and frontmatter schema
- `docs/design/plan-infrastructure-redesign.md` — implementation context for role/project separation

### Executive Summary
The documents form a coherent and well-traced chain. Vision concepts generally have corresponding requirements, and requirements have spec implementations. The ontology is consistently applied across all three. I found **no blocking issues** — only minor inconsistencies, stale references, and one completeness gap that appears intentional.

---

### 1. Internal Consistency

**Strengths:**
- Every requirement section opens with a "Vision reference" that accurately points to specific vision sections
- The spec's derives-from pointer is current (Draft 12 → Draft 13)
- Phase implementation status (Phases 1-5 implemented) is consistent across all three docs
- The role/job-description framing is consistently applied (no regressions to "persona" language)

**Minor Issues:**

**R3.4 ledger migration wording inconsistency** (Medium)
- **Location:** requirements-personal-ai-infrastructure.md:198
- **Issue:** States "Ledger migration complete — ledger system decommissioned March 2026" but later mentions "the thoughts/ directory already contains valuable content (ledgers, plans, design docs, research)" at line 109
- **Problem:** If ledgers are decommissioned, why do they still exist in thoughts/? This creates confusion about whether legacy content remains
- **Suggested fix:** Clarify that legacy ledger files exist in thoughts/ for historical reference but are no longer the active continuity mechanism; or if they've been migrated and removed, state that explicitly

**Review model registry format drift** (Low)
- **Location:** spec-personal-ai-infrastructure.md:1386-1418
- **Issue:** The model registry shows `invoke: ["claude", "-p", "{prompt}"]` but the spec describes array-style subprocess invocation with `{prompt}` and `{prompt_file}` substitution
- **Problem:** The example doesn't show the full template syntax (e.g., no `--file` flag example for OpenCode's file-based prompt)
- **Note:** This is minor — the section explains substitution clearly

---

### 2. Stale References

**SQLite references — NONE FOUND** ✓
All SQLite references have been updated to PostgreSQL consistently.

**Ledger references — MOSTLY RESOLVED** ✓
- R3.4 marks ledgers as decommissioned
- Window files are the replacement
- However, see note under R3.4 above about "thoughts/ directory contains...ledgers"

**Persona references — NONE FOUND** ✓
All references to "persona" have been replaced with "job description" framing per the ontology.

**Path references — ONE STALE REFERENCE** (Low)
- **Location:** spec-personal-ai-infrastructure.md:1378
- **Issue:** FilesystemConnector default config shows `{ "root_path": "/home/claude/claude-hub/thoughts/", ...}`
- **Problem:** Per the ontology and vision, window files are now role-scoped at `~/roles/{role}/windows/` not `thoughts/`. The `thoughts/` directory appears to be legacy
- **Suggested fix:** Update the example to show indexing from role-scoped paths or clarify that this is a fallback location

---

### 3. Ontology Alignment

**7-Concept Ontology Consistency** — **MOSTLY ALIGNED** ✓

The ontology (role, project, service, agent, task, resource, session) is consistently referenced:

| Concept | Vision | Requirements | Spec | Status |
|---------|--------|--------------|------|--------|
| Role | ✓ | ✓ (R3.7) | ✓ (window frontmatter) | Aligned |
| Project | ✓ | ✓ (R3.7) | ✓ (window frontmatter) | Aligned |
| Service | ✓ | ✓ | ✓ | Aligned |
| Agent | ✓ | ✓ | ✓ | Aligned |
| Task | ✓ | ✓ | ✓ | Aligned |
| Resource | ✓ | ✓ | ✓ | Aligned |
| Session | ✓ | ✓ | ✓ | Aligned |

**Workstream × Component Tagging** — **ALIGNED** ✓
- Vision line 121: "Sessions... are tagged by *workstream* (what you're doing: development, research, or operations) and *component* (what you're working on: codebase, service, agent, task, dataset, or document)"
- Requirements R3.7 includes both in window file frontmatter
- Spec section 2.3 shows YAML frontmatter with `workstream` and `component` fields
- Ontology section 64-83 confirms the same classification axes

**One Minor Inconsistency:**

**Task vs. "job" terminology** (Low)
- **Location:** ontology.md:43
- **Issue:** "Named 'task' rather than 'job' to avoid collision with roles being described as 'job descriptions'"
- **Problem:** The vision uses "job description" for roles, but requirements/spec don't explicitly discuss this naming collision or why "task" was chosen
- **Note:** This is documented in the ontology but could be a brief footnote in requirements R4 or R6 where tasks are mentioned

---

### 4. Completeness

**Vision concepts adequately covered:**

| Vision Concept | Requirement | Spec Implementation | Status |
|----------------|-------------|---------------------|--------|
| Native artifact store | R1 | Phase 1 | ✓ Complete |
| Multi-model review | R2 | Phase 2 | ✓ Complete |
| Context continuity | R3 | Phase 3/3.5 | ✓ Complete |
| Capability compounding | R4 | Phase 6 | ✓ Specified |
| Knowledge quality | R5 | Phase 4 | ✓ Complete |
| Spec-driven workflow | R6 | Phase 7 | ✓ Specified |
| Connector interface | R7 | Phase 5 | ✓ Complete |

**Explicitly deferred (per vision Open Questions):**
- Proactive context surfacing — vision line 246: "The architecture must not preclude it, but we don't yet have enough clarity to write acceptance criteria" — this is correctly listed as out-of-scope in requirements
- Agent autonomy policies — vision line 249: "This is a trust question that evolves over time, not a design question with a fixed answer" — correctly deferred
- Cost management — vision line 254: "choosing the cheapest model that meets the need" — partially addressed via review model registry cost_tier field

**One Completeness Gap:**

**Skill/hook promotion details in R4** (Medium)
- **Location:** requirements-personal-ai-infrastructure.md:232-269 (R4 Capability Compounding)
- **Issue:** R4.1-R4.3 define pattern detection and promotion, but the requirements don't fully address *how* patterns are detected (what LLM prompt/approach)
- **Problem:** The spec section 4.5 describes `pattern_detect` calling "an LLM to analyze summaries" but doesn't specify the prompt or methodology. This is a research-level decision that affects whether detection actually works
- **Status:** This appears to be an intentional research gap — the vision acknowledges pattern detection is hard ("ambitious end is research") and the spec says "The system should start simple and grow toward proactive retrieval as the knowledge base and the tooling mature"
- **Recommendation:** Add a note in R4 constraints that pattern detection methodology is experimental and will be refined based on observed session data

---

### Summary Table: Findings by Severity

| Severity | Count | Items |
|----------|-------|-------|
| High | 0 | None |
| Medium | 3 | R3.4 ledger wording, skill/hook promotion methodology, path reference in filesystem connector |
| Low | 3 | Task vs job note, model registry example completeness, review quality grading integration |

### Files Referenced Beyond Review Targets
- `docs/design/ontology.md`
- `docs/design/plan-infrastructure-redesign.md`

### Overall Assessment
The three documents form a **highly coherent chain** with excellent traceability. The ontology is consistently applied. Stale references have been largely cleaned up (only minor residual mentions of legacy paths). The completeness gap in R4 (pattern detection methodology) appears to be an intentional research boundary rather than an oversight. The system is ready for the remaining implementation phases (6-8) pending Phase 6 kickoff.


### gpt-5.4 (complete)

I read the three target docs, then checked `docs/design/ontology.md`, `src/claude_hub/continuity.py`, `src/claude_hub/continuity_ingest.py`, `src/claude_hub/review_engine.py`, `src/claude_hub/chat_process.py`, `src/claude_hub/artifact_store.py`, `src/claude_hub/connectors/artifact_connector.py`, `src/claude_hub/connectors/filesystem_connector.py`, `src/claude_hub/server.py`, `src/claude_hub/scheduler.py`, `src/claude_hub/workspace.py`, `migrations/004_knowledge_quality.sql`, `migrations/005_connectors.sql`, `tests/test_continuity.py`, `tests/test_continuity_ingest.py`, `tests/test_review_engine.py`, and `tests/test_connectors.py` for adjacent context.

Overall, the chain is solid on the artifact-store/review/connector story, but it is still not a clean system of record on the newer architecture and ontology pieces. The biggest problems are continuity ownership/pathing and the fact that the ontology/tagging update stops at “fields exist” instead of becoming queryable behavior.

High severity: the continuity architecture still forks between role-scoped memory and project-local storage. The vision makes role memory load-bearing (`docs/design/vision-personal-ai-infrastructure.md:95`, `docs/design/vision-personal-ai-infrastructure.md:101`, `docs/design/vision-personal-ai-infrastructure.md:117`), and the requirements/spec say window files and mechanical logs are role-scoped (`docs/design/requirements-personal-ai-infrastructure.md:202`, `docs/design/requirements-personal-ai-infrastructure.md:212`, `docs/design/spec-personal-ai-infrastructure.md:277`, `docs/design/spec-personal-ai-infrastructure.md:313`). But the same downstream docs still require `thoughts/mechanical.jsonl`, `thoughts/windows/{harness}/`, and `thoughts/windows/NARRATIVE_PROMPT.md` in acceptance criteria and hook examples (`docs/design/requirements-personal-ai-infrastructure.md:204`, `docs/design/requirements-personal-ai-infrastructure.md:219`, `docs/design/spec-personal-ai-infrastructure.md:1566`, `docs/design/spec-personal-ai-infrastructure.md:1596`, `docs/design/spec-personal-ai-infrastructure.md:1636`, `docs/design/spec-personal-ai-infrastructure.md:1795`). The adjacent code shows the same split rather than resolving it: `src/claude_hub/continuity.py:26` and `tests/test_continuity.py:78` are still project-local, while `src/claude_hub/chat_process.py:448` already expects role-scoped windows. Right now the chain does not give one unambiguous answer to “where does role memory live?”

High severity: the workstream x component / ontology update is only partially operationalized. The vision says these tags exist to support cross-cutting queries across sessions (`docs/design/vision-personal-ai-infrastructure.md:121`), and `docs/design/ontology.md:68`, `docs/design/ontology.md:74`, and `docs/design/ontology.md:83` define the actual taxonomy. But the requirements and spec mostly stop at putting `role`, `projects`, `workstream`, `component`, and `service` into window frontmatter (`docs/design/requirements-personal-ai-infrastructure.md:214`, `docs/design/spec-personal-ai-infrastructure.md:291`, `docs/design/spec-personal-ai-infrastructure.md:293`, `docs/design/spec-personal-ai-infrastructure.md:294`, `docs/design/spec-personal-ai-infrastructure.md:295`). There is no downstream requirement or acceptance test for ingesting those fields into searchable metadata or querying by them, which is the main reason the tags matter. The implementation context makes the gap concrete: `src/claude_hub/continuity_ingest.py:71` persists only `session_id`, `harness`, timestamps, `finalized`, and `parent`, dropping the ontology-bearing fields entirely. So the chain claims ontology alignment, but not the behavior that would make the ontology useful.

Medium-high severity: the vision’s boundary/scoping model is not really carried into requirements or spec. The vision distinguishes discoverability from content access and says data boundaries must be designed in from the start (`docs/design/vision-personal-ai-infrastructure.md:109`, `docs/design/vision-personal-ai-infrastructure.md:226`, `docs/design/vision-personal-ai-infrastructure.md:250`). Downstream, the requirements mostly reduce security to MCP auth and “sensitive/local-processing-only” artifacts (`docs/design/requirements-personal-ai-infrastructure.md:395`), and the spec does the same with `sensitive` artifacts and connector credential handling (`docs/design/spec-personal-ai-infrastructure.md:649`, `docs/design/spec-personal-ai-infrastructure.md:1255`). There is no concrete requirement for role- or connector-scoped access, no discoverability-vs-access primitive, and no real translation of the personal/professional boundary. That feels like a real completeness gap, not just an editorial omission, because the vision treats it as foundational.

Medium severity: the architecture problem around persistent agents, services, and tasks mostly disappears after the vision. The vision makes the agent/task/service distinction central (`docs/design/vision-personal-ai-infrastructure.md:99`, `docs/design/vision-personal-ai-infrastructure.md:103`, `docs/design/vision-personal-ai-infrastructure.md:105`), but the requirements scope does not turn that into a dedicated requirement family (`docs/design/requirements-personal-ai-infrastructure.md:27`, `docs/design/requirements-personal-ai-infrastructure.md:33`). The spec likewise has no agent/task/service phase beyond review agents and continuity forks. Given that the repo already contains adjacent machinery like `src/claude_hub/scheduler.py:1` and `src/claude_hub/workspace.py:1`, this reads as a genuine gap in the vision -> requirements -> spec chain rather than an intentional omission.

Medium severity: the clean-room review boundary still has stale and conflicting path assumptions. The requirements say the default excludes should be specific opinion-carrying paths, not the whole `thoughts/` tree (`docs/design/requirements-personal-ai-infrastructure.md:160`). The spec changelog agrees (`docs/design/spec-personal-ai-infrastructure.md:18`), but the live prompt text only excludes `thoughts/history/`, `.claude/`, and `CLAUDE.md` (`docs/design/spec-personal-ai-infrastructure.md:1435`), omitting `thoughts/ledgers/`, and it still points at old locations like `thoughts/shared/` and `.claude/skills/review/SKILL.md` (`docs/design/spec-personal-ai-infrastructure.md:18`, `docs/design/spec-personal-ai-infrastructure.md:854`). The adjacent implementation is broader still: `src/claude_hub/review_engine.py:111` excludes all of `thoughts/`, and `tests/test_review_engine.py:789` encodes that. So this part of the chain is not actually settled.

Medium-low severity: there is still a stale conceptual summary in the requirements doc. The scope section says item 5 is “Outcome tracking — rating approach results to build weighted precedent” at `docs/design/requirements-personal-ai-infrastructure.md:31`, even though R5 and the spec have already moved to agent usage feedback plus confidence. That one-line summary reintroduces the old model at the top of the document.

If I had to reduce this to one sentence: the chain is coherent on storage/review/search, but the newer architecture layer — role-scoped continuity, ontology-backed tagging, and scoped shared infrastructure — is still only half translated from vision into requirements and spec.


### gpt-5.3-codex (complete)

I reviewed the three design docs as a chain, then checked adjacent implementation/tests for context. Overall, the chain is strong conceptually (vision themes generally map to R1–R7, and the spec has clear sections per requirement), but there are a few substantive drift points that break traceability.

- High — Requirement 3 has conflicting acceptance criteria versus its own ontology/path model. In `docs/design/requirements-personal-ai-infrastructure.md:212` and `docs/design/requirements-personal-ai-infrastructure.md:227`, R3.7/R3.5 describe role-scoped paths (`~/roles/{role}/...`) with fallback, but acceptance still hard-codes old harness-scoped paths at `docs/design/requirements-personal-ai-infrastructure.md:204` and `docs/design/requirements-personal-ai-infrastructure.md:219`. This creates a test-oracle conflict: a team can satisfy acceptance while violating the stated architecture and ontology alignment.
- Medium — R4.2 is not fully carried into spec. Requirements include escalation to an **agent update** (`docs/design/requirements-personal-ai-infrastructure.md:254`), but spec `pattern_promote` only allows `skill|hook|rule` (`docs/design/spec-personal-ai-infrastructure.md:966`). That leaves one required promotion target unspecified.
- Medium — Requirements scope still contains stale “outcome tracking” language that conflicts with the current R5 framing. `docs/design/requirements-personal-ai-infrastructure.md:31` says “Outcome tracking — rating approach results,” while the active requirement is “Knowledge Quality” and usage-feedback driven (`docs/design/requirements-personal-ai-infrastructure.md:272`). This is not just wording; it changes who emits signal and when.
- Medium — Spec has internal counting inconsistencies that affect planning confidence. It states “23 MCP tools” (`docs/design/spec-personal-ai-infrastructure.md:60`), and summary claims “2 knowledge-quality” tools (`docs/design/spec-personal-ai-infrastructure.md:2004`), but section 4.4 defines 3 R5 tools (`docs/design/spec-personal-ai-infrastructure.md:872`) and section totals add to 24.
- Medium — Implementation-status metadata is stale at the top of the vision doc. `docs/design/vision-personal-ai-infrastructure.md:5` still references requirements/spec Draft 12/11 while the linked docs are now Draft 13/12. Small on its own, but this is the top-level provenance anchor for the chain.
- Low/Medium — Ontology alignment is partial, not complete. Vision explicitly formalizes 7 concepts including `resource` (`docs/design/vision-personal-ai-infrastructure.md:5`), but requirements/spec operationalize frontmatter around `role/projects/workstream/component/service/session_id` (`docs/design/requirements-personal-ai-infrastructure.md:214`, `docs/design/spec-personal-ai-infrastructure.md:289`) with no explicit representation strategy for `resource` in session tagging. Also, workstream/component are present but unconstrained in spec, so cross-session query quality may drift over time.
- Low — One active outdated absolute path remains in spec defaults: `"/home/claude/claude-hub/thoughts/"` (`docs/design/spec-personal-ai-infrastructure.md:1378`), which is inconsistent with the current project location convention and the broader move to role-scoped context.

On your stale-reference checklist specifically:
- SQLite mentions are mostly historical/migration context, not active design direction.
- Ledger mentions are mostly decommission/migration context; the problematic part is acceptance criteria still testing old paths.
- Persona references appear only as explicit correction (“roles are job descriptions, not personas”), which is aligned.
- Outdated paths are still present in a few active places (not only changelog text).

Context check against adjacent code supports that some “implemented” claims are optimistic: `src/claude_hub/continuity.py:26` and `tests/test_continuity.py:27` still center `thoughts/windows/{harness}`, and `src/claude_hub/review_engine.py:112` still defaults clean-room excludes to `thoughts/` broadly rather than the narrower path policy described in requirements/spec.

Files read beyond the three targets:
- `docs/design/ontology.md`
- `docs/architecture.md`
- `docs/shared-context.md`
- `src/claude_hub/continuity.py`
- `src/claude_hub/continuity_ingest.py`
- `src/claude_hub/review_engine.py`
- `src/claude_hub/connectors/filesystem_connector.py`
- `tests/test_continuity.py`
- `tests/test_continuity_ingest.py`
- `tests/test_review_engine.py`
- `src/claude_hub/server.py` (targeted endpoint/tool grep only)


### glm-5 (complete)

Now I have a complete picture of all three documents. Let me writemy review.
## Review: Vision → Requirements → Spec Coherence

### Files Read
- `docs/design/vision-personal-ai-infrastructure.md` (Draft 14)
- `docs/design/requirements-personal-ai-infrastructure.md` (Draft 13)
- `docs/design/spec-personal-ai-infrastructure.md` (Draft 12)
- `docs/design/ontology.md` (for ontology reference)

### Overall Assessment

The chain is coherent. All vision concepts trace to requirements, and all requirements have corresponding spec coverage. The documents have been updated to reflect PostgreSQL migration, ledger decommissioning, and role-as-job-description framing. No stale SQLite/ledger/persona references remain in the core three documents.

---

### Ontology Alignment

**Minor inconsistency (Line 287 in spec):** The comment says `# ontology role (workbench, analyst, etc.)` but ontology.md defines only three roles: workbench, sysadmin, mcp-server. "Analyst" is not defined. The frontmatter schema itself is correct; only the comment is misleading. Severity: **Low**.

---

### Traceability Verification

**Vision → Requirements**: All four problem domains map cleanly:
- Data/connectors (Vision §1) → R7
- Context preservation (Vision §2) → R3
- Multi-model quality (Vision §3) → R2
- Architecture (Vision §4) role/project separation → reflected in window file frontmatter, though not a discrete requirement

**Requirements → Spec**: Complete coverage. Each R1-R7 has corresponding schema, tools, and acceptance tests. Implementation status accurately reflects Phases 1-5 complete, Phase 6-8 pending.

**Cross-version references**: Draft numbers align correctly (Spec Draft 12 → Requirements Draft 13 → Vision Draft 14).

---

### Stale References Check

**None found.** The documents correctly describe:
- Line 49 (requirements): "all stores migrated from SQLite"
- Line 158 (spec): "No SQLite databases remain"
- Line 198-199 (spec): Ledger migration marked complete
- Line 91 (vision): "Roles are job descriptions, not personas"

---

### Completeness

**One gap worth noting:** Vision §"Version Control as Audit Trail" (lines 177-181) states "almost every file the system produces... should be managed in version control." Window files are git-tracked, but artifacts stored in Postgres use an `artifact_versions` table rather than git. This is arguably consistent in spirit (immutability + version tracking) but technically different. The spec should acknowledge this distinction. Severity: **Low** — the design choice is sound, but the vision statement is slightly misleading for artifacts.

---

### Draft Changelogs

The changelogs are thorough and correctly distinguish between updates. No contradictions between changelog claims and actual content.

---

### Conclusion

The three documents form a coherent chain with clear traceability. The only substantive issue is the minor ontology mismatch in a comment. The documents appear ready for implementation of Phases 6-8.


### minimax-m2.7 (complete)

Let me read key implementation files to verify alignment.
Let me check a few more files for completeness.
Now I have a thorough picture. Let me check one more thing — the actual window file paths in use.
## Review

### Files read beyond the review targets

- `src/claude_hub/continuity.py`
- `src/claude_hub/artifact_store.py`
- `src/claude_hub/review_engine.py`
- `src/claude_hub/continuity_ingest.py`
- `src/claude_hub/connectors/filesystem_connector.py`
- `tests/test_continuity_ingest.py`

---

### Internal Consistency

**The vision→requirements→spec chain holds generally.** Every capability traces to a vision statement, and the spec implements the requirements. However, there are three places where this chain frays:

**1. Path hierarchy is inverted in the implementation.** The spec (Section 2.3) specifies role-scoped `~/roles/{role}/windows/` as primary with `thoughts/windows/{harness}/` as fallback. The actual `continuity.py` (`_windows_dir`, line 29) does the opposite — it uses `thoughts/windows/{harness}/` as the primary path, with no mention of `~/roles/`. The code should be the spec's primary path; it currently is the spec's fallback path. This is a material deviation, not a naming difference.

**2. `patterns.py` (Phase 6) doesn't exist.** The spec (Section 8.8) specifies a `patterns.py` module with `detect_patterns`, `promote_pattern`, and `dismiss_pattern`. These don't exist in the codebase. Phase 6 is marked "NOT STARTED" in the spec's build order, so this is acknowledged — but it means R4 (Capability Compounding) is unimplemented.

**3. `workflow.py` (Phase 7) doesn't exist.** The spec (Section 8.6) specifies a `workflow.py` module with six workflow tools. These don't exist. Phase 7 is marked "PARTIALLY IMPLEMENTED" in the spec, but the actual MCP tool implementations (`workflow_create`, `workflow_advance`, etc.) are not in the codebase.

---

### Stale References

**1. `continuity.py` still documents `thoughts/windows/` as primary.** The comment at line 29 says "directory under `thoughts/windows/`" — this is the fallback path per spec, not the primary. The `thoughts/` directory was the legacy location before the role extraction. The primary path per spec is `~/roles/{role}/windows/`. This is stale.

**2. The review engine's default exclude paths are stale.** `review_engine.py` line 111: `DEFAULT_EXCLUDE_PATHS = ["thoughts/", ".claude/", "CLAUDE.md"]`. The spec (Draft 12, Section 6.2) updated these to `["thoughts/ledgers/", "thoughts/history/", ".claude/", "CLAUDE.md"]` — the change was made because "design docs subsequently moved to `docs/design/`." The code still excludes all of `thoughts/`, which means reviewers cannot read window files (which live in `thoughts/windows/` or `~/roles/{role}/windows/`). This is a functional regression — window files are precisely the kind of file a reviewer might productively read.

**3. R3.5 mechanical log path references are inconsistent.** The requirements constraint (R3.5) says the mechanical log is at `~/roles/{role}/mechanical.jsonl` with fallback to `thoughts/mechanical.jsonl`. The spec (Section 2.3) says the same. The implementation comment in `continuity.py` line 27 shows `thoughts/windows/{harness}` which is the window path, not the mechanical log path. The `continuity_ingest.py` module doesn't reference the mechanical log at all (it handles ingestion, not the mechanical log). The mechanical log itself is implemented via a PostToolUse hook that appends JSONL — I didn't find the hook script, but the spec says it's at `mechanical-log.sh`.

---

### Ontology Alignment

**The 7-concept ontology is partially implemented in frontmatter.** The vision (Architecture Problem, Section 4) defines: **role, project, service, agent, task, resource, session**. The spec's window file frontmatter (Section 2.3) includes: `role`, `projects` (array), `service`, `harness`, `session_id`, `finalized`. This covers role, projects, service, and session_id — but **agent**, **task**, and **resource** are absent from the frontmatter schema. The vision's own Section 4 says agents and tasks are first-class concepts ("Agents own ongoing work," "Tasks complement agents"), yet they're not fields in the window file that tracks session continuity. This means the ontology is partially declared but not fully materialized in the continuity system.

**Workstream × component classification exists but isn't enforced.** The vision (Section 4, "Work is classified on two orthogonal axes") says workstream is "development, research, or operations" and component is "codebase, service, agent, task, dataset, or document." The spec's frontmatter has both fields but treats them as free-form strings with no enumeration. `continuity.py` (line 179-180) sets them as empty strings on window creation. There's no validation that workstream is one of the three valid values. The classification system is present in the schema but not in the code that uses it.

**"Role" vs. harness confusion.** The vision says roles are job descriptions (workbench, sysadmin, mcp-server) and should be distinct from the harness (Claude Code, Gemini CLI, OpenCode). The window file frontmatter has both `role` and `harness` fields, which is correct. But `continuity.py` line 177 populates `role` from `CURRENT_ROLE` env var, while the harness is a separate field. The system appears to have both concepts, but in `chat_process.py` line 152, `CURRENT_ROLE` is hardcoded to `"mcp-server"`. This means the role is being set by the harness process rather than being a persistent role identity. This isn't wrong, but it's worth noting — the role concept is being used, though the mechanism (env var set by the harness process) may not match the vision of roles as persistent job descriptions outliving any single harness invocation.

---

### Completeness

**Two requirements have no implementation: R4 and R6.** R4 (Capability Compounding, Phase 6) has no code — no `patterns.py`, no pattern detection. R6 (Spec-Driven Workflow, Phase 7) has no code — no `workflow.py`, no workflow tools. Both are explicitly acknowledged as unimplemented in the spec's build order, so this is a documentation accuracy issue rather than a missing requirement. But it means the requirements doc's "Phases 1-5 are implemented" is accurate; the vision's feature list in "What This Enables" includes patterns and capabilities that don't exist yet.

**The `artifact_store.py` has a deprecated parameter.** `get_artifact` has an `include_outcomes` parameter (line 225) documented as "Deprecated alias for `include_feedback`." The requirements and spec use "feedback" terminology throughout. The deprecated alias suggests this was renamed mid-evolution, which is fine, but the parameter should be marked deprecated in a way that generates warnings rather than silently redirecting.

**`continuity_ingest.py` stores `window_file` in artifact metadata where the spec says `service` should go.** The spec's frontmatter has a `service` field ("service name if applicable"). `continuity_ingest.py` (line 78) stores `window_file: source_ref` in the artifact metadata. This is not wrong — `window_file` is a reasonable metadata field — but it's not aligned with the spec's declared frontmatter schema. The spec doesn't actually specify what should populate the `service` field, which suggests the frontmatter schema was extended post-spec and the implementation wasn't updated to match.

---

### Summary of Severity

| Finding | Severity | Location |
|---|---|---|
| Primary window path is `thoughts/windows/` in code, not `~/roles/{role}/windows/` as spec requires | High | `continuity.py:29` |
| Default exclude paths in review engine exclude all of `thoughts/`, blocking window file access by reviewers | High | `review_engine.py:111` |
| `patterns.py` doesn't exist (Phase 6 unimplemented) | Medium | spec build order |
| `workflow.py` doesn't exist (Phase 7 unimplemented) | Medium | spec build order |
| `workstream` field not validated against the 3-value enumeration | Low | `continuity.py:179`, spec frontmatter |
| `agent` and `task` not in window file frontmatter schema despite being in the 7-concept ontology | Low | spec Section 2.3 |
| `include_outcomes` deprecated parameter still present in artifact_store | Low | `artifact_store.py:225` |
| `window_file` stored in artifact metadata instead of `service` field | Low | `continuity_ingest.py:78` |


### grok-code-fast-1 (complete)

*No output (status: complete)*

### mimo-v2-pro (complete)

Now let me explore adjacent code for context.

