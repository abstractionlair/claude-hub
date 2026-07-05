

[0m> build · kimi-k2.5
[0m[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1152][0m
## Review: Agentic Review Design Changes

### Document 1: Vision (Draft 8) — Lines 65-67

**Findings:**

- **Minor:** The paragraph split at line 65-67 is confusing. The bold heading line 65 stands alone, then lines 66-67 continue the thought. This appears to be a formatting issue where the paragraph break is mid-sentence.

- **Important:** The integration with "The Quality Problem" section is solid. The progression from "Multiple models" → "Diminishing returns" → "Best model changes" → "How models review matters" is logical.

- **Observation:** The opinion/fact distinction is clear in the text (line 67: "The boundary is intent (share it) versus editorial opinion (withhold it)"), but the paragraph is information-dense. Consider breaking it into two paragraphs: one on intent/semantic errors, one on clean-room boundaries.

**Cross-reference:** Consistent with Requirements R2.1 and R2.6 revisions.

---

### Document 2: Requirements (Draft 7) — R2.1 and R2.6

**Findings:**

- **Critical:** R2.1 acceptance criteria says "Reviewers demonstrate codebase exploration (reading files beyond those explicitly listed) in their output" — but the spec doesn't define *how* this is verified. Is this a human-judged criterion? Automated detection? The spec says "demonstrates" but doesn't show the mechanism.

- **Important:** The bundled fallback (line 146: "Models that lack agentic capability... may fall back to receiving bundled content") creates a two-tier system. This is acknowledged, but R2.1's acceptance criteria don't distinguish between agentic and bundled reviewers. If bundled can't demonstrate codebase exploration, they can't meet the acceptance criteria. The constraint says bundled is "fallback" but the requirement doesn't calibrate expectations for this degraded mode.

- **Minor:** R2.6 acceptance says "The reviewer's output demonstrates it read the spec and explored the codebase, but did not reference process documents" — this requires the reviewer to prove a negative (what they *didn't* read). In practice, reviewers might simply not mention process docs without explicitly demonstrating non-access. Consider: "output shows no evidence of process document influence" rather than "demonstrates it did not read."

- **Important:** R2.6's clean-room boundary lists default `exclude_paths: ["thoughts/", ".claude/", "CLAUDE.md"]` in spec — but the requirements don't mention this default. If the vision says "thoughts/ directory (except the spec)" is excluded, the requirements should explicitly state the default exclusion list or defer to the spec's authority.

**Cross-reference check:**
- ✅ Vision's "intent vs editorial opinion" maps cleanly to R2.1's "pair with intent" and R2.6's "opinion isolation"
- ⚠️ R2.1 acceptance criteria don't account for bundled-mode limitations
- ⚠️ R2.6's default exclude_paths isn't in requirements

---

### Document 3: Spec (Draft 4) — Section 6 (Review Model Registry)

**Findings:**

- **Important:** Prompt construction (lines 1504-1510) lists 5 components but doesn't provide an example prompt. Without seeing the actual constructed prompt, it's hard to verify the boundaries work correctly. Suggest adding an example showing how the 5 components combine.

- **Minor:** Clean-room implementation says "The review prompt's boundary instructions provide the soft isolation layer across all models" (line 1521) — but doesn't show what those instructions actually say. What's the exact text of the soft boundary?

- **Minor:** `exclude_paths` parameter in `review_dispatch` accepts a list, but the prompt construction logic says "Default: 'Please do NOT read files under thoughts/ (other than the spec)...'" — how does "other than the spec" work when `exclude_paths` is a simple list? Is there an `include_paths` override mechanism?

- **Observation:** The `mode: agentic | bundled` distinction is clean and implementable. The invoke templates using array-style subprocess (line 1525) correctly prevents shell injection.

- **Minor:** `UNIQUE(job_id)` on `review_syntheses` (line 240) prevents duplicate synthesis — but what happens if synthesis fails and needs retry? The constraint blocks re-synthesis for the same job_id, which could be intentional (idempotency) or problematic (no recovery path). The spec notes "guarded by UNIQUE constraint" in `_check_and_synthesize` (line 1730) but doesn't specify the retry behavior on unique violation.

- **Minor:** Sensitive artifact check on `review_dispatch` (line 822) rejects with 400 — should this be 403 (Forbidden) or 409 (Conflict) instead? 400 implies client error, but the artifact *is* sensitive; that's not a malformed request.

**Cross-reference check:**
- ✅ Spec's agentic/bundled modes implement R2.1's "agentic codebase access" requirement
- ✅ Spec's clean-room implementation matches R2.6's "opinion isolation via soft boundaries"
- ⚠️ Spec's prompt construction lacks concrete examples of the boundary instructions
- ⚠️ `exclude_paths` doesn't explain how to handle "exclude thoughts/ except the spec"

---

### Overall Cross-Reference Assessment

**Story consistency: PASS** — The three documents tell a coherent story: reviewers are agents, reviews pair with intent, clean-room isolates opinions not facts.

**Spec-to-requirements fidelity: MOSTLY PASS** — Minor gaps in how bundled mode meets R2.1 acceptance criteria, and missing example prompts.

**Requirements-to-vision fidelity: PASS** — Both requirements directly trace to vision paragraphs.

---

### Overall Assessment: **NEEDS MINOR REVISION**

**Must fix before ready:**
1. Vision line formatting (65-67 paragraph break)
2. Clarify how bundled-mode reviewers meet R2.1 acceptance criteria (or add bundled-specific criteria)
3. Add example constructed prompt to spec showing the 5 components
4. Clarify `exclude_paths` vs "except the spec" mechanism

**Should fix:**
- Change R2.6 acceptance from "demonstrates it did not read" to "shows no evidence of reading"
- Fix sensitive artifact HTTP status (403 vs 400)
- Document `exclude_paths` default in requirements, not just spec

**Ready after these fixes.**
