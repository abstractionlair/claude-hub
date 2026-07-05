# Review: 2026-03-08 00:30 UTC

**Prompt:** Review the R5 Knowledge Quality sections in both the requirements and spec documents. This was recently rewritten from 'Outcome Tracking' (human-initiated rating) to 'Knowledge Quality' (agent-driven feedback). Focus areas: 1) Are R5.1-R5.5 well-specified and internally consistent? 2) Does the artifact_feedback table + review_grades table schema support the requirements? 3) Is the quality-weighted search scoring formula reasonable? 4) Is the retirement mechanism well-defined? 5) Any missing edge cases or gaps between requirements and spec?
**Files:** docs/design/requirements-personal-ai-infrastructure.md, docs/design/spec-personal-ai-infrastructure.md
**Job ID:** 67353ab7-53ff-4e1a-825d-a4b7a7795749

## Synthesis

## Synthesis: R5 Knowledge Quality Rewrite Reviews

Four models reviewed the R5 rewrite across the requirements and spec documents. Here's what emerged.

### Strong Consensus (all or most reviewers)

**The `review_grades` schema doesn't match its own usage.** All four reviewers flagged this. The table defines `useful BOOLEAN`, but Section 6 of the spec asks the synthesis model to emit a 4-level grade (SUCCEEDED, PARTIAL_SUCCESS, PARTIAL_FAILURE, FAILED). GPT-5.4 escalated this to HIGH severity, noting the table also lacks `review_type` and `review_id`/`review_artifact_id` columns that the requirements demand for querying by model and review type. Gemini and Claude raised the same core issue at moderate severity. The schema simply cannot express what the grading system needs it to express — this is a blocking gap.

**Utility score aggregation is undefined.** Every reviewer called out the spec's "(rolling average or similar)" language as insufficient. The aggregation formula determines how quickly feedback changes ranking, whether early feedback has outsized influence, and whether recovery from negative signal is possible. Claude noted that a simple average means one early negative review permanently drags the score; Gemini suggested a Bayesian average regressing toward 0.5; Kimi asked whether an EMA should be used. All agree this needs a concrete specification, not a hand-wave. Medium severity across reviewers.

**Confidence storage is ambiguous.** Claude, GPT-5.4, and Kimi all caught the contradiction between "confidence is stored in artifact metadata" (line 232/896) and the search formula reading `a.confidence` as a direct column (line 686). The spec says both things. GPT-5.4 raised the sharpest version of this finding, noting it also clashes with versioning — confidence stored on the mutable artifact row bleeds across content versions. This versioning dimension was unique to GPT-5.4 and elevates the severity.

**The SQL scoring formula isn't executable.** Claude and GPT-5.4 both identified that the formula references column aliases (`confidence_boost`, `utility_boost`) from the same SELECT clause, which Postgres doesn't allow. GPT-5.4 additionally flagged `include_archived` being used as if it were a SQL variable. The formula needs restructuring as a CTE or with inlined expressions. Medium severity — it's a spec bug, not a design flaw.

**`last_retrieved` has no backing data.** Claude, GPT-5.4, and Kimi all noted that `artifact_retirement_candidates` returns `last_retrieved`, but no column tracks retrieval events. The `artifact_feedback` table records optional feedback, not retrievals — and the artifacts most likely to be retirement candidates are precisely those with zero feedback and thus no retrievable timestamp. Either add a `last_retrieved_at` column or remove it from the return type.

**Stale terminology persists.** Claude and GPT-5.4 found lingering "Outcome Tracking" references: the scope section still says "Outcome tracking," Phase 6 depends on "Phase 4 (outcomes)," and the summary counts "2 outcome tools" when Section 4.4 defines 3. GPT-5.4 also caught that Phase 4's task list forgets to create the `review_grades` table despite later tasks depending on it. Low severity individually, but collectively they signal the rewrite needs one more editorial pass.

### Unique Findings

**GPT-5.4** caught the most architecturally significant unique issue: confidence and utility stored on the mutable artifact row clash with content versioning. Feedback on an older version bleeds into newer content. This is high severity and none of the other reviewers identified it. GPT-5.4 also uniquely noted that auto-excluding SUPERSEDED artifacts from default search (via WHERE clause) effectively retires them without the confirmation step that R5.4 requires — a semantic violation of the requirements, not just a technical one.

**Claude** uniquely identified the feedback bootstrapping problem: nothing in the hook system or session flow prompts agents to call `artifact_feedback` after retrieving artifacts. The old system had a SessionStart ceremony; the new one removed it but didn't replace the nudge. This means feedback accumulation depends entirely on voluntary agent behavior, which may produce very sparse signal. Claude also noted a missing index on `review_grades.job_id` and that the SUPERSEDED penalty applies even when a user explicitly requests archived content (double punishment).

**Gemini** brought a recommender-systems perspective: the quality-weighted system creates an exploration-vs-exploitation problem where popular artifacts accumulate feedback and perpetually outrank potentially excellent but unseen content. This is a long-term scaling concern rather than a spec bug, but it's a thoughtful observation no other reviewer made.

**Kimi** was the only reviewer to read the actual implementation code (`artifact_store.py`, `review_engine.py`, migrations, tests). This revealed that the current codebase still implements the old outcome-based model — `artifact_outcomes` with a 4-level rating enum and `rated_by TEXT DEFAULT 'human'`. The gap between spec and implementation is total, not incremental. Kimi also raised an edge case no one else mentioned: what happens when a SUPERSEDED artifact receives positive feedback? Should the status be automatically cleared?

### Contradictions

There are no hard contradictions between reviewers — they agree on the core issues. The differences are in scope and severity calibration:

- **Severity of `review_grades` mismatch**: GPT-5.4 calls it HIGH (blocking), Gemini says MODERATE, Claude frames a related but different concern (requirements vs spec table choice) as MEDIUM. The underlying issue is the same; GPT-5.4's assessment is most accurate since the schema literally cannot store what the system needs.

- **Scope of review**: Kimi read the implementation code and treats the spec-to-implementation gap as a primary finding. The other three reviewed the spec documents on their own terms. Neither approach is wrong — they're answering different questions. Kimi's implementation analysis confirms that Phase 4 is a ground-up build, not a modification.

- **Retirement specificity**: GPT-5.4 calls the retirement mechanism underspecified at medium-high severity, noting the acceptance criterion requires "negative feedback from multiple agents over several weeks" but the spec has no minimum feedback count, no multi-agent requirement, and no audit trail. Claude rates the same area as low severity. GPT-5.4's reading of the acceptance criteria is more precise here.

### Summary by Severity

**High** (consensus or strongly argued): `review_grades` schema mismatch with grading system; confidence/utility versioning clash (GPT-5.4 unique but compelling); SUPERSEDED auto-exclusion violating R5.4 confirmation requirement (GPT-5.4 unique).

**Medium** (broad agreement): utility score aggregation undefined; confidence column-vs-metadata ambiguity; SQL formula not executable as written; retirement mechanism underspecified relative to acceptance criteria; no `last_retrieved` backing column.

**Low** (worth noting): stale terminology and tool counts; no feedback deduplication; agent_id semantics unspecified; no feedback bootstrapping mechanism; exploration-vs-exploitation risk; missing `review_grades.job_id` index.

The reviewers converge on a clear verdict: the conceptual rewrite from human ceremonies to agent-driven signal is right, but the spec needs one more pass to resolve three things — what entity gets graded, how feedback aggregates into utility score, and how SUPERSEDED differs operationally from archived. GPT-5.4's framing of these as the three load-bearing ambiguities is the most actionable summary across all four reviews.

**Models responded:** claude (agentic), gemini (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### claude (complete)

Now I have everything I need. Let me write my review.

---

## Review: R5 Knowledge Quality Rewrite

**Files reviewed:**
- `docs/design/requirements-personal-ai-infrastructure.md` (full document, focus on lines 274-317, 427-445)
- `docs/design/spec-personal-ai-infrastructure.md` (full document, focus on Section 4.4 lines 858-919, Phase 4 lines 1815-1831, schema lines 212-237, indexes lines 429-430, review quality grading lines 1490-1497, score formula lines 684-709, module 8.4 lines 1696-1704)

No files read beyond the two review targets — the documents are self-contained for this review scope.

---

### 1. R5.1–R5.5 Internal Consistency

**R5.1 (Usage feedback)** is well-specified. The acceptance criterion tests the right things: positive/negative feedback changes utility, no-feedback artifacts unaffected. The spec's `artifact_feedback` tool (Section 4.4) matches — boolean useful signal, optional note, agent_id attribution.

**R5.2 (Confidence annotation)** is clear and the distinction from usage feedback (write-time property vs retrieval-time signal) is explicitly stated. However, the spec stores confidence in two different places and the relationship is ambiguous:

- **Medium severity.** The schema comment at line 233-236 shows `confidence` and `utility_score` as columns on the `artifacts` table (applied via migration), but the `artifact_set_confidence` tool description says "Update artifact metadata with confidence level" (line 896). Is confidence stored in the `confidence` column or in the `metadata` JSONB? The score formula (line 689) references `a.confidence` as a column, so presumably it's a dedicated column. But the tool description saying "metadata" is misleading. The spec should be consistent — if it's a column, the tool description should say "Update artifact's confidence column," not "metadata."

**R5.3 (Quality-weighted retrieval)** is the most complex piece. The requirements say "no penalty for being new" and the spec implements this via utility_score defaulting to 0.5 (which maps to a 0.0 boost in the formula `(utility_score - 0.5) * 0.4`). This is correct and well-thought-out. The confidence default of MEDIUM also maps to 0.0 boost. Good alignment.

- **Low severity, but worth noting.** The acceptance test in R5.3 (line 299) says "Two artifacts on the same topic with similar semantic match. One has positive usage feedback from 3 agents; the other has none. The high-feedback artifact ranks first." But the spec's utility_boost maxes out at +0.2 (when utility_score = 1.0). If two artifacts have "similar semantic match" within 0.2 cosine distance of each other, the utility boost might not always be enough to reorder them. This is fine in practice — 0.2 is a large margin for semantically similar content — but the acceptance test should be run with awareness that the boost magnitude is the tuning knob.

- **Medium severity.** The score formula at line 697 references `COALESCE(confidence_boost, 0)` using a column alias defined in the same SELECT clause (line 689-693). Standard SQL doesn't allow referencing a column alias from the same SELECT in another expression. Postgres doesn't allow this either. The query would need to be restructured as a CTE or subquery, or the CASE expression needs to be repeated inline. This is a spec bug — the actual implementation will need to expand the CASE expressions inline or use a CTE.

**R5.4 (Retirement)** is well-specified. The two-step flow (suggest candidates, then confirm via `artifact_archive`) is clean. The tool `artifact_retirement_candidates` uses sensible defaults (30 days, 0.3 utility threshold). One observation:

- **Low severity.** The requirements mention "sufficient age" as a retirement criterion alongside low utility and low confidence. The spec's `artifact_retirement_candidates` implements `min_age_days` and `max_utility` as parameters, but there's no explicit `max_confidence` parameter. The behavior description (line 916) says "low confidence, or SUPERSEDED status" are considered, but this filtering isn't exposed as a parameter. This is minor — the hardcoded logic is reasonable — but the tool's parameters don't fully mirror the requirements' three-dimensional criteria (age + utility + confidence). An implementer might miss the confidence filtering since it's described in prose but not parameterized.

**R5.5 (Review quality grading)** is well-specified and the requirements-to-spec mapping is clean. The synthesis model as ready-made grader is a pragmatic design choice. The `review_grades` table is correctly separate from `artifact_feedback` — these are different signal types (per-model reviewer quality vs per-artifact usage quality).

- **Medium severity, potential confusion.** The requirements say grades are stored "as feedback on its review artifact" (line 309 acceptance criterion). But the spec uses a separate `review_grades` table, not the `artifact_feedback` table. These are different mechanisms. The requirements wording is ambiguous — it could mean "feedback about the review artifact" (which `artifact_feedback` would handle) or "quality grades associated with the review" (which `review_grades` handles). The spec chose the latter, which is architecturally better (dedicated table, no overloading of `artifact_feedback`). But the requirements acceptance criterion should be updated to match the spec's design, or the disconnect should be explicitly acknowledged.

### 2. Schema Analysis

The `artifact_feedback` table (lines 213-220) is clean. It correctly allows multiple feedback entries per artifact (no UNIQUE on artifact_id), supports different agents, and timestamps each entry. The boolean `useful` field is appropriately simple.

The `review_grades` table (lines 223-230) is clean. It uses `job_id` to link to review runs and `model_name` to identify the graded model.

**Missing:** There's no foreign key from `review_grades.job_id` to `reviews.job_id`. The `reviews` table doesn't have a UNIQUE constraint on `job_id` either (multiple reviews share the same job_id — one per model). So there's no referential integrity path from `review_grades` back to the actual reviews. This is probably fine for a single-developer system, but worth noting. An `idx_review_grades_job_id` index might also be useful for querying "all grades from a specific review run."

**The `utility_score` update mechanism is underspecified.** The `artifact_feedback` tool says (line 875): "Update the artifact's aggregate utility score (rolling average or similar)." This is important — the aggregation formula determines how quickly feedback changes ranking. Is it:
- Simple average of all feedback (1.0 for useful, 0.0 for not useful)?
- Exponential moving average (recent feedback weighted more)?
- Something else?

The "(rolling average or similar)" phrasing defers this to implementation, which is reasonable for a spec, but the choice has real consequences. A simple average means early feedback has outsized influence (first negative review permanently drags the score down). An EMA allows recovery. This should at least be flagged as an implementation decision.

### 3. Quality-Weighted Search Scoring Formula

The formula (lines 684-709) is reasonable. Breaking it down:

- `base_score` = cosine similarity (0.0 to 1.0 range)
- `confidence_boost` = -0.2 to +0.1 range
- `utility_boost` = -0.2 to +0.2 range

Total adjustment range: -0.4 to +0.3. On a cosine similarity scale of 0-1, this means quality signals can dominate over semantic relevance in some cases. An artifact with 0.5 cosine similarity and maximum quality boost (+0.3) would score 0.8, outranking an artifact with 0.75 cosine similarity and minimum quality (-0.4) scoring 0.35. That's a very large reordering.

**Medium severity.** The asymmetric confidence boost (HIGH=+0.1, LOW=-0.1, SUPERSEDED=-0.2) is reasonable, but the SUPERSEDED penalty of -0.2 combined with a potential utility penalty of -0.2 means superseded low-utility artifacts get a -0.4 adjustment. That's severe enough to effectively bury them even when they're the best semantic match. The requirements say SUPERSEDED items should be excluded from default search unless `include_archived` is set (line 302-303 imply retirement→archive). But the score formula already filters SUPERSEDED out at line 702: `AND (a.confidence != 'SUPERSEDED' OR include_archived)`. So SUPERSEDED items are both excluded by WHERE clause AND penalized in scoring — double punishment that only applies when `include_archived=true`. Is that intended? If someone explicitly asks to include archived/superseded content, they probably want to see it ranked by semantic relevance, not buried by quality penalties.

### 4. Retirement Mechanism

The two-step retirement flow is well-defined: `artifact_retirement_candidates` suggests, `artifact_archive` confirms. This matches the requirements constraint "suggested, not automatic."

**Low severity.** The `artifact_retirement_candidates` return type includes `last_retrieved` (line 913), but there's no `last_retrieved` column in the schema. The `artifact_feedback` table has `created_at` per feedback entry, and you could derive "last retrieved" from the most recent feedback timestamp. But artifacts with zero feedback (the ones most likely to be retirement candidates) would have no `last_retrieved` at all. The tool would need to handle this — perhaps falling back to `created_at` from the artifacts table. This is a minor gap but should be noted for the implementer.

### 5. Gaps Between Requirements and Spec

**The agent_id attribution model is underspecified.** R5.1 says "Multiple agents contribute feedback over time" and the spec has `agent_id TEXT NOT NULL DEFAULT 'main'` on the feedback table. But there's no specification of what agent_id values look like, how they're determined, or whether the system validates them. The `artifact_feedback` tool says the parameter "defaults to current session" (line 867), but session IDs and agent IDs are different concepts. Is a forked sub-agent a different agent_id? Is a different Claude Code session a different agent? This doesn't need rigid specification, but the "which agent provided this feedback" question should have at least a convention.

**No feedback deduplication.** The `artifact_feedback` table has no unique constraint preventing the same agent from recording multiple feedback entries for the same artifact. This could be intentional (an agent might retrieve the same artifact in different contexts and have different assessments), but it means a buggy agent could flood the feedback table. If utility_score is a simple average, repeated negative feedback from one agent could unfairly tank the score. Consider whether feedback should be deduplicated per (artifact_id, agent_id) or rate-limited.

**The summary tool count is stale.** Line 1990 says "2 outcome" tools, but Section 4.4 defines 3 tools (`artifact_feedback`, `artifact_set_confidence`, `artifact_retirement_candidates`). This is a documentation inconsistency, not a design issue.

### 6. The Agent-Driven Feedback Model

The rewrite from human-initiated rating to agent-driven feedback is a significant improvement. The design correctly identifies that:
- Signal should emerge from existing work, not separate ceremonies
- The synthesis model is a natural grader for review quality
- Boolean useful/not-useful is the right granularity for inline feedback

One architectural observation: the system currently has no mechanism to *prompt* agents to provide feedback. The tool exists (`artifact_feedback`), but nothing in the hook system or session flow reminds agents to use it after retrieving artifacts via `artifact_search`. The old system had a SessionStart prompt for rating unrated artifacts; the new system removed that ceremony but didn't replace it with any nudge mechanism. This means feedback accumulation depends entirely on agents voluntarily calling `artifact_feedback` — which may result in very sparse signal, especially early on. The spec might benefit from a note about how feedback habits get bootstrapped (e.g., a system reminder after `artifact_search` returns results, or the search tool itself returning a "feedback pending" prompt).

### Summary of Findings by Severity

**Medium:**
1. Confidence storage location ambiguity (column vs metadata JSONB) — spec lines 233 vs 896
2. SQL column alias reuse in score formula — spec line 697 references aliases from same SELECT
3. Requirements R5.5 acceptance criterion says "feedback on review artifact" but spec uses separate `review_grades` table — requirements line 309 vs spec line 494
4. SUPERSEDED double-filtering (WHERE clause exclusion + score penalty) may over-penalize when explicitly included — spec lines 702 and 692

**Low:**
1. `utility_score` aggregation formula deferred with "(or similar)" — spec line 875
2. `last_retrieved` in retirement candidates return type has no backing column — spec line 913
3. Confidence not exposed as a parameter on `artifact_retirement_candidates` despite being a listed criterion — spec line 916 vs requirements line 302
4. No feedback deduplication or rate-limiting per agent
5. Tool count "2 outcome" should be "3" — spec line 1990
6. No nudge mechanism for agents to provide feedback after retrieval
7. Missing `review_grades.job_id` index (present for `artifact_feedback.artifact_id` but not for `review_grades.job_id`)


### gemini (complete)

Your request was to review the R5 Knowledge Quality rewrite in `docs/design/requirements-personal-ai-infrastructure.md` and `docs/design/spec-personal-ai-infrastructure.md`. My review focused on the consistency and completeness of the agent-driven feedback model, its supporting schema, the search scoring logic, and the artifact retirement mechanism.

I have read the following files as part of this review:
*   `docs/design/requirements-personal-ai-infrastructure.md`
*   `docs/design/spec-personal-ai-infrastructure.md`

No other files were consulted.

### General Assessment

The transition from human-initiated "Outcome Tracking" to agent-driven "Knowledge Quality" is a significant conceptual improvement. The new design is well-aligned with the principle of "signal emerges from work," creating a system that learns organically from agent activity rather than requiring separate, burdensome curation ceremonies. The requirements (R5.1-R5.5) are clear, internally consistent, and well-supported by the technical implementation detailed in the specification document.

The separation of concerns is particularly strong:
1.  **Usage Feedback** (`artifact_feedback`): A lightweight signal from the *consumer* of knowledge about its utility at the point of use.
2.  **Confidence** (`artifacts.confidence`): A signal from the *producer* of knowledge about its expected reliability at the time of creation.
3.  **Review Grading** (`review_grades`): A meta-signal about the *quality of a reviewer*, generated as a byproduct of the existing synthesis process.

This multi-faceted approach provides a robust framework for assessing and managing the health of the knowledge base over time. The search scoring formula and retirement mechanism are logical, reasonable, and directly implement the stated requirements.

Despite the strong overall design, there are a few areas with inconsistencies or gaps that merit attention.

### Findings

#### 1. Inconsistent `review_grades` Schema and Usage

**Severity:** Moderate

**Location:** `docs/design/spec-personal-ai-infrastructure.md`, Sections 2.1 and 6.

There is a direct contradiction in how review quality grades are specified.
*   **Section 2.1 (Data Model)** defines the `review_grades` table with a `useful BOOLEAN NOT NULL` column.
*   **Section 6 (Review Quality Grading)** states that the grading prompt asks the synthesis model for a richer quality rating: `SUCCEEDED, PARTIAL_SUCCESS, PARTIAL_FAILURE, FAILED`.

This is an inconsistency that would block implementation. The richer enumeration described in Section 6 is more expressive and would provide more nuanced signal about reviewer performance than a simple boolean. The schema should be updated to reflect the more descriptive rating system, for instance by using a `TEXT` column with a `CHECK` constraint for the allowed enum values.

#### 2. Undefined `utility_score` Aggregation Logic

**Severity:** Minor

**Location:** `docs/design/spec-personal-ai-infrastructure.md`, Section 4.4.

The specification for the `artifact_feedback` tool states that it updates the artifact's aggregate `utility_score`. However, the logic for this aggregation is not defined. The current score is a critical component of the quality-weighted search ranking, but the spec leaves its calculation ambiguous.

Is it a simple rolling average of all `useful` booleans (e.g., treating true as 1 and false as 0)? Does it use a Bayesian average that regresses toward the neutral default of 0.5? Does feedback decay over time? This is a key implementation detail that will significantly influence the system's learning behavior and should be specified.

#### 3. Long-Term Knowledge Discovery (Exploration vs. Exploitation)

**Severity:** Minor

**Location:** Conceptual gap across R5 and the supporting spec.

The quality-weighted retrieval system is designed to promote useful artifacts, which is its primary purpose. However, this creates a potential long-term risk where popular, "good enough" artifacts are consistently ranked highly, receive all the attention and feedback, and perpetually drown out potentially excellent but newer or lesser-seen artifacts.

The system lacks a defined mechanism for *exploration*—surfacing content that is not currently top-ranked to give it a chance to be evaluated. This is a classic challenge in recommender systems. While not a critical flaw for the initial implementation, which correctly handles new artifacts with a neutral score, it's a predictable scaling issue. The spec could be strengthened by acknowledging this and suggesting a potential future mitigation, such as occasionally injecting a lower-ranked or random result into the search returns to encourage discovery and a richer feedback distribution.

---
Overall, the R5 rewrite is a very successful and well-thought-out design. The findings above are intended to refine an already strong proposal by closing implementation gaps and addressing potential long-term dynamics.


### gpt-5.4 (complete)

The rewrite is directionally right — moving R5 from human rating ceremonies to agent-emitted signal fits the rest of the system much better — but I don’t think it is fully specified yet.

Beyond the two target docs, I read `migrations/001_initial_schema.sql`, `migrations/002_reviews.sql`, `migrations/003_model_forward.sql`, `src/claude_hub/artifact_store.py`, `src/claude_hub/artifact_models.py`, `src/claude_hub/review_engine.py`, `tests/test_artifact_store.py`, and `tests/test_review_engine.py`.

- High: `review_grades` does not actually support R5.5 as written. In `docs/design/spec-personal-ai-infrastructure.md:1492` the synthesis is said to emit a 4-level grade (`SUCCEEDED`, `PARTIAL_SUCCESS`, `PARTIAL_FAILURE`, `FAILED`), but the table at `docs/design/spec-personal-ai-infrastructure.md:223` only stores `useful BOOLEAN`. It also has no `review_type`, even though `docs/design/requirements-personal-ai-infrastructure.md:309` says grades must be queryable by model and review type, and no `review_id`/`review_artifact_id`, even though Phase 4 acceptance says each reviewer’s artifact gets a grade at `docs/design/spec-personal-ai-infrastructure.md:1829`. Right now the schema loses both granularity and provenance.

- High: confidence/utility storage is internally inconsistent, and it clashes with versioning. The spec says “Confidence is stored in artifact metadata” at `docs/design/spec-personal-ai-infrastructure.md:232`, but the search formula reads `a.confidence` and `a.utility_score` as columns at `docs/design/spec-personal-ai-infrastructure.md:686`, and Phase 4 says to add those columns at `docs/design/spec-personal-ai-infrastructure.md:1818`. `artifact_set_confidence` also says it updates metadata at `docs/design/spec-personal-ai-infrastructure.md:894`. More importantly, `docs/design/requirements-personal-ai-infrastructure.md:292` says confidence is a property of the content at write time, but the design stores it at the mutable artifact row, while artifact content itself versions in place; the adjacent implementation model in `src/claude_hub/artifact_store.py:557` makes that concrete. That means feedback/confidence on an older version will bleed into newer content unless you move these signals to a version-aware record.

- High: the quality-weighted search formula is not executable as written, and its semantics overstep the retirement rules. In `docs/design/spec-personal-ai-infrastructure.md:684`, `final_score` references `confidence_boost` and `utility_boost` aliases from the same `SELECT`, which Postgres does not allow, and `include_archived` is used as if it were a SQL variable at `docs/design/spec-personal-ai-infrastructure.md:702`. The documented `confidence` filter parameter at `docs/design/spec-personal-ai-infrastructure.md:672` also never appears in the query. Separately, excluding `SUPERSEDED` from default search at `docs/design/spec-personal-ai-infrastructure.md:702` effectively retires those artifacts without the confirmation required by `docs/design/requirements-personal-ai-infrastructure.md:302` and `docs/design/requirements-personal-ai-infrastructure.md:315`.

- Medium-High: the agent feedback model is still too vague to produce stable utility scores. `artifact_feedback` is just `(artifact_id, useful, note, agent_id, created_at)` in `docs/design/spec-personal-ai-infrastructure.md:213`, and the behavior says “rolling average or similar” at `docs/design/spec-personal-ai-infrastructure.md:874`. But R5 depends on distinctions like “multiple agents contribute over time” in `docs/design/requirements-personal-ai-infrastructure.md:287`, “no signal = neutral” in `docs/design/requirements-personal-ai-infrastructure.md:297`, and “consistently low utility” in `docs/design/requirements-personal-ai-infrastructure.md:302`. Without defining aggregation, priors, duplicate handling, and whether feedback is per artifact or per retrieved version/context, search and retirement behavior will be arbitrary. This also shows up in `artifact_retirement_candidates`: it returns `last_retrieved` at `docs/design/spec-personal-ai-infrastructure.md:913`, but the schema never records retrievals, only optional feedback events.

- Medium: the retirement mechanism is only partially defined. The requirement acceptance case is “negative feedback from multiple agents over several weeks” at `docs/design/requirements-personal-ai-infrastructure.md:304`, but the spec’s candidate selection is just low utility / low confidence / superseded plus age at `docs/design/spec-personal-ai-infrastructure.md:916`. There is no minimum number of feedback events, no multi-agent requirement, no persisted candidate state/reason, and no audit trail for who confirmed retirement. That may be enough for a toy implementation, but it is underspecified for the behavior the requirement describes.

- Low: there is still rewrite drift from the old “Outcome Tracking” model. `docs/design/requirements-personal-ai-infrastructure.md:27` still names “Outcome tracking” in scope. In the spec, Phase 6 still depends on “Phase 4 (outcomes)” at `docs/design/spec-personal-ai-infrastructure.md:1847`, the dependency graph still says “Outcomes” at `docs/design/spec-personal-ai-infrastructure.md:1891`, and the summary still counts “2 outcome” tools at `docs/design/spec-personal-ai-infrastructure.md:1990` even though Section 4.4 defines 3 R5 tools. Phase 4 task 1 at `docs/design/spec-personal-ai-infrastructure.md:1818` also forgets to create `review_grades`, even though later tasks depend on it.

My main takeaway: the conceptual rewrite is good, but the spec still needs one more pass to make R5 canonical around three things: what entity gets graded (`artifact`, `artifact version`, or `review`), how agent feedback aggregates into `utility_score`, and how `SUPERSEDED` differs operationally from `archived`. Once those are nailed down, most of the remaining inconsistencies fall out naturally.


### kimi-k2.5 (complete)

I'll review the R5 Knowledge Quality sections in both documents. Let me start by reading the requirements and spec files.
Now let me explore any adjacent code files for additional context on how these schemas might be implemented.
Based on my thorough review of the requirements and spec documents, here is my assessment of the R5 Knowledge Quality rewrite:

## Executive Summary

The R5 Knowledge Quality rewrite successfully reorients from human-initiated rating ceremonies to agent-driven feedback, but there's a **critical implementation gap**: the current codebase still implements the OLD "Outcome Tracking" model while the spec documents the NEW "Knowledge Quality" model.

---

## Findings

### 1. **Critical: Schema Mismatch Between Spec and Implementation** (Severity: HIGH)

**Location:** `migrations/001_initial_schema.sql:54-63` vs `spec-personal-ai-infrastructure.md:212-236`

The current implementation uses the OLD schema:
```sql
-- Current (outdated)
CREATE TABLE artifact_outcomes (
    rating TEXT CHECK (rating IN ('SUCCEEDED', 'PARTIAL_SUCCESS', 'PARTIAL_FAILURE', 'FAILED')),
    rated_by TEXT DEFAULT 'human'
)
```

The spec requires the NEW schema:
```sql
-- Required per spec Section 2.1
CREATE TABLE artifact_feedback (
    useful BOOLEAN NOT NULL,  -- R5.1: binary agent feedback
    agent_id TEXT DEFAULT 'main'
);

CREATE TABLE review_grades (  -- R5.5: separate per-model table
    job_id UUID NOT NULL,
    model_name TEXT NOT NULL,
    useful BOOLEAN NOT NULL
);
```

**Impact:** The artifact store is currently using human-initiated outcome ratings (SUCCEEDED/FAILURE enum) while the requirements specify agent-driven binary feedback. The migration `003_knowledge_quality.sql` mentioned in Phase 4 tasks doesn't exist yet.

### 2. **Search Scoring Formula Discrepancy** (Severity: MEDIUM)

**Location:** `artifact_store.py:313-443` vs `spec-personal-ai-infrastructure.md:682-710`

Current implementation uses OLD outcome-based scoring:
```python
+ CASE latest_outcome.rating
    WHEN 'SUCCEEDED' THEN 0.2
    WHEN 'PARTIAL_SUCCESS' THEN 0.1
    ...
```

Spec requires NEW quality-weighted scoring using `utility_score` and `confidence` columns:
```sql
-- Per spec Section 4.1
CASE
    WHEN a.confidence = 'HIGH' THEN 0.1
    WHEN a.confidence = 'MEDIUM' THEN 0.0
    WHEN a.confidence = 'LOW' THEN -0.1
    WHEN a.confidence = 'SUPERSEDED' THEN -0.2
END AS confidence_boost,
(a.utility_score - 0.5) * 0.4 AS utility_boost
```

**Gap:** The spec mentions adding `confidence` and `utility_score` columns to artifacts (Section 2.1, lines 232-236), but the search query in the spec uses `a.utility_score` and `a.confidence` directly on the artifacts table, which would require columns that don't exist in the current schema.

### 3. **Missing Utility Score Aggregation Logic** (Severity: MEDIUM)

**Location:** `spec-personal-ai-infrastructure.md:871-875`

The spec states: "Update the artifact's aggregate utility score (rolling average or similar)" but doesn't specify:
- The exact aggregation formula (exponential moving average? simple average?)
- Whether to weight recent feedback more heavily
- How to handle multiple feedback entries from the same agent
- Whether feedback expires after some time

**Recommendation:** Specify a concrete algorithm, e.g., exponential moving average with α=0.3, or document that this is intentionally left to implementation discretion.

### 4. **Retirement Mechanism Gap: No "Last Retrieved" Tracking** (Severity: MEDIUM)

**Location:** `spec-personal-ai-infrastructure.md:905-918` (artifact_retirement_candidates)

The `artifact_retirement_candidates` tool returns `last_retrieved` but there's no schema column to track this. The requirements (R5.4) mention "low utility, low confidence, or sufficient age" but the spec's retirement query references `last_retrieved` which isn't stored anywhere.

**Gap:** No mechanism to track when an artifact was last accessed/retrieved. Either:
- Add a `last_retrieved_at` column to artifacts
- Or remove `last_retrieved` from the retirement candidates response
- Or infer from feedback entries (but this misses retrievals that didn't result in feedback)

### 5. **Confidence vs. SUPERSEDED Semantics** (Severity: LOW)

**Location:** `requirements-personal-ai-infrastructure.md:291-295` vs `spec-personal-ai-infrastructure.md:893-898`

Requirements describe confidence as "set at write time or updated when an agent discovers the information is stale" and SUPERSEDED as "marks the artifact as replaced by newer information — functionally equivalent to low confidence but semantically distinct."

The spec's search scoring treats SUPERSEDED as -0.2 (worse than LOW at -0.1), but the requirements acceptance says: "Search returns the high-confidence artifact first. An agent later discovers the low-confidence item was wrong and marks it as superseded."

**Question:** Can confidence be changed from HIGH/MEDIUM/LOW to SUPERSEDED? Or is SUPERSEDED a separate status? The spec shows it as a confidence level, but the semantics suggest it's more like an archival flag.

### 6. **Review Quality Grading (R5.5) Implementation Gap** (Severity: MEDIUM)

**Location:** `spec-personal-ai-infrastructure.md:1490-1497` vs `review_engine.py`

The spec requires the synthesis model to emit quality grades into `review_grades` table during review synthesis. However, looking at `review_engine.py` and the test files, this functionality is not yet implemented.

**Missing:**
- The grading prompt that asks for per-reviewer quality ratings
- The `review_grades` table insertion logic
- The `get_review_quality()` query helper mentioned in spec Section 8.4

### 7. **Inconsistent Default Utility Score** (Severity: LOW)

**Location:** `spec-personal-ai-infrastructure.md:234` vs scoring formula

The spec shows: `ALTER TABLE artifacts ADD COLUMN utility_score REAL DEFAULT 0.5;`

This centers the utility boost at 0 (since `(0.5 - 0.5) * 0.4 = 0`), which is correct for neutral treatment of new artifacts. However, there's no explicit discussion of why 0.5 was chosen or whether this default should be configurable.

### 8. **Edge Case: Feedback on Superseded Artifacts** (Severity: LOW)

**Location:** `requirements-personal-ai-infrastructure.md:302-305`

The retirement acceptance criteria mentions: "An artifact has received negative feedback from multiple agents over several weeks."

**Gap:** No specification for what happens if an artifact receives positive feedback after being marked SUPERSEDED. Should the superseded status be automatically removed? Should the human be notified? Currently unclear.

### 9. **Agent Identification in Feedback** (Severity: LOW)

**Location:** `spec-personal-ai-infrastructure.md:218` (artifact_feedback.agent_id)

The schema has `agent_id TEXT NOT NULL DEFAULT 'main'` but there's no specification of:
- What constitutes a valid agent ID
- Whether agents self-identify or the system assigns IDs
- How to prevent feedback spam from a single agent
- Whether agent reputation/weighting is considered

### 10. **Internal Consistency of R5.1-R5.5** (Severity: LOW - Documentation)

**Strengths:**
- R5.1 (usage feedback) and R5.5 (review grading) are well-distinguished: one is per-artifact, one is per-model-per-review
- R5.2 (confidence) and R5.3 (quality-weighted retrieval) align well — confidence is write-time, retrieval uses it for ranking
- R5.4 (retirement) correctly builds on the signals from R5.1-R5.3

**Minor Gap:** R5.5 says "The synthesis model — which already evaluates findings for consensus, contradictions, and unique contributions — is a ready-made grader." This is elegant, but the spec doesn't clarify whether grading happens for every review or only when explicitly requested. Given that review synthesis is already complex, adding grading could affect latency.

---

## Recommendations

### Immediate Actions (Before Phase 4 Implementation)

1. **Create migration `003_knowledge_quality.sql`** with:
   - Drop `artifact_outcomes` table (or keep for backward compatibility during transition)
   - Create `artifact_feedback` table
   - Create `review_grades` table
   - Add `confidence` and `utility_score` columns to artifacts

2. **Update `artifact_store.py`**:
   - Replace outcome-based search scoring with utility_score + confidence formula
   - Remove `include_outcomes` parameter from `get_artifact()`
   - Add `include_feedback` parameter per spec

3. **Add `last_retrieved_at` column** to artifacts table, or remove it from retirement candidates spec

4. **Implement feedback aggregation** in `artifact_feedback` tool with documented algorithm

### Clarifications Needed

1. **Can confidence be changed to SUPERSEDED?** Or is SUPERSEDED a separate lifecycle state?
2. **What's the feedback aggregation formula?** Simple average, weighted average, or EMA?
3. **Should retirement be fully automatic or always require confirmation?** Spec says "suggested... requires confirmation" which is correct per R5 constraints.

---

## Summary Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| R5.1-R5.5 Well-Specified | ✅ Good | Clear capabilities with proper distinctions |
| Schema Support | ⚠️ Gap | Spec defines correct schema, but implementation uses old model |
| Search Scoring Formula | ⚠️ Gap | Formula is reasonable (+/- 0.1-0.2 range) but not yet implemented |
| Retirement Mechanism | ⚠️ Partial | Well-defined criteria but missing `last_retrieved` tracking |
| Agent-Driven Model | ✅ Good | Successfully reoriented from human ratings |
| Edge Cases | ⚠️ Needs Work | Several gaps around feedback aggregation, agent ID, superseded handling |

**Overall:** The rewrite is conceptually sound and well-documented, but the implementation hasn't caught up to the spec. The gap between "outcome ratings" (current) and "knowledge quality" (spec) needs to be closed before Phase 4 can be considered complete.

