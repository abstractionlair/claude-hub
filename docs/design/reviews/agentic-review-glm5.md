[0m
> build · glm-5
[0m
[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1152][0m
# Review: Agentic Review Design Changes

## Document 1: Vision (Draft 8)

### Findings

**Minor** — Paragraph density. Lines 65-67 pack three distinct points into one paragraph: (a) agentic vs bundled review, (b) intent pairing, (c) clean-room redefinition. Each deserves its own sentence or small paragraph for clarity.

**Minor** — Opinion/fact boundary. The examples help (process docs = opinion, spec = fact), but the underlying principle isn't fully articulated. What makes something "opinion" vs "fact"? Is it about authorship (human vs system), about normativity (should vs is), or about provenance (project-specific vs external)?

**Observation** — The colleague analogy ("look at this diff" vs "look at this branch") is excellent and memorable. Consider highlighting it more prominently.

**Observation** — The paragraph integrates naturally with the existing Quality Problem section. It extends the multi-model discussion logically.

---

## Document 2: Requirements (Draft 7)

### Findings

**Important** — R2.1 acceptance criteria: "Reviewers demonstrate codebase exploration (reading files beyond those explicitly listed) in their output." This is a behavioral requirement with no verification mechanism. How do we test this automatically? Options: (a) require reviewers to list files read as structured output, (b) make this a manual verification step, (c) define a proxy metric (e.g., review mentions files not in the input list).

**Important** — R2.6 acceptance criteria: "The review prompt includes explicit boundaries on which directories or files to avoid." This tests prompt construction, not reviewer behavior. The criteria should also verify the reviewer didn't reference excluded content. But this is hard to test — the reviewer might reference something it inferred rather than read. Consider: (a) accept this as untestable and document as manual verification, or (b) add a softer criterion like "reviewer output does not quote or paraphrase content from excluded paths."

**Important** — Bundled fallback creates a two-tier system. The vision explicitly says bundled reviewers are inferior ("will find things that the one reading a bundled excerpt won't"). The requirements acknowledge bundled as fallback but don't address: (a) whether bundled reviews should be flagged as degraded quality, (b) whether synthesis should note which reviews were agentic vs bundled, (c) whether quality claims in the vision apply to bundled reviews. The spec's `mode` field tracks this, but the requirements should address the quality implications.

**Minor** — R2.1 says "dispatch the review to 2-3 models" but the spec's `models` parameter defaults to "all configured models." Should this be "at least 2 models" or exactly "2-3"? The diminishing returns curve in the vision suggests 2-3 is the sweet spot, but the requirement is imprecise.

**Minor** — R2.6 says reviewers should not read "process preferences, style guides, or design rationale." The spec's default `exclude_paths` is `["thoughts/", ".claude/", "CLAUDE.md"]`. This doesn't cover style guides or design rationale unless they live in those paths. Gap between requirement and spec implementation.

**Observation** — The revised R2.1 and R2.6 are internally consistent. The opinion-vs-fact boundary is clear in principle, though the spec's implementation is narrower (see cross-reference check).

---

## Document 3: Spec (Draft 4)

### Findings

**Critical** — Section 6.2 "Prompt Construction" lists what the prompt contains but doesn't provide the actual template. The `review_dispatch` behavior says "Construct the task prompt for each model" but delegates to Section 6. Implementation needs an explicit prompt template. Example:

```
You are reviewing code changes. Your task: {prompt}

**What to review:**
{files}

**Intent (what this code should do):**
{intent}

**Context files to read for conventions:**
{context_files}

**Boundaries (do NOT read these):**
{exclude_paths}

**Output format:**
List findings as JSON: [{ severity, location, finding, fix }]
```

**Important** — Agentic review of non-file content. `review_dispatch` accepts `files`, `artifact_id`, or `content`. For agentic models with `files`, the model reads them. But for `artifact_id` or `content`, what does the agentic model read? The spec says "For agentic models: pass the constructed prompt. The model reads the files itself." But if there are no files, this doesn't make sense. Options: (a) agentic mode requires `files` parameter, (b) agentic models fall back to bundled for non-file content, (c) artifact content is written to a temp file for agentic review. The spec should clarify.

**Important** — Verification of codebase exploration. Phase 2 acceptance says "Reviewers demonstrate codebase exploration (reading files beyond those explicitly listed)." This is identical to R2.1 acceptance — circular. The spec needs a concrete verification mechanism. Suggestion: require reviewers to output a `files_read` list, then verify it contains files not in the input list.

**Important** — Clean-room boundary implementation gap. R2.6 says suppress "process preferences, style guides, or design rationale." Spec's default `exclude_paths` is `["thoughts/", ".claude/", "CLAUDE.md"]`. Style guides and design rationale aren't covered unless they live in those paths. Options: (a) document where these live and add to defaults, (b) make `exclude_paths` more comprehensive, (c) acknowledge the boundary relies on prompt instructions and the path list is a best-effort supplement.

**Minor** — Synthesis model hardcoded as Claude. Should this be configurable? What if Claude isn't available? Consider adding `synthesis_model` to the model registry or `review_dispatch` parameters.

**Minor** — `clean_room_flags` for Claude is `["--profile", "review"]`. The spec mentions what this does in Section 6.3, but should also document it in the model registry section for completeness.

**Minor** — Section 6.2 mentions "Context files — pre-existing code the reviewer should read for conventions and patterns." But `review_dispatch` doesn't have a `context_files` parameter. How does the engine know which files to suggest? This should be a parameter or derived from the files being reviewed (e.g., same directory, related modules).

**Observation** — `UNIQUE(job_id)` on `review_syntheses` correctly prevents duplicate synthesis.

**Observation** — Sensitive artifact check is correctly implemented.

**Observation** — The `mode: agentic | bundled` distinction is clear and implementable.

---

## Cross-Reference Check

| Vision Claim | Requirements | Spec | Consistent? |
|--------------|--------------|------|-------------|
| Reviewers that explore find things bundled reviewers miss | R2.1: agentic invocation, bundled fallback | `mode: agentic | bundled` | **Yes**, but quality implications of bundled not addressed |
| Reviews need intent (spec/requirements) | R2.1: reviews paired with intent | `review_dispatch` has `intent` parameter | **Yes** |
| Clean-room = opinion isolation | R2.6: opinion isolation via soft boundaries | `exclude_paths` + prompt instructions | **Partial** — spec's path list narrower than requirement's scope |
| Don't read process docs, style guides, design rationale | R2.6: suppress these | Default exclude: thoughts/, .claude/, CLAUDE.md | **Gap** — style guides and design rationale not in default exclude |
| Do read spec, code, tests | R2.6: allow these | Prompt construction includes intent, files | **Yes** |
| Bundled is fallback | R2 constraints: bundled for models lacking agentic capability | `mode: bundled` in model config | **Yes**, but no quality flag |

**Key inconsistency**: The vision and requirements define clean-room as suppressing "process preferences, style guides, or design rationale." The spec's implementation only excludes specific paths. Style guides and design rationale might live elsewhere. The spec should either expand defaults or acknowledge the gap.

---

## Overall Assessment

**Not ready.** The changes need revision before implementation.

**Critical issues to resolve:**

1. **Prompt template missing** — Section 6.2 describes prompt contents but doesn't provide the template. Implementation cannot proceed without it.

2. **Verification of codebase exploration** — R2.1 acceptance and Phase 2 acceptance both say "demonstrate codebase exploration" but neither provides a verification mechanism. This is untestable as written.

3. **Agentic review of non-file content** — Spec doesn't explain how agentic models review `artifact_id` or `content` (no files to read).

**Important issues to address:**

4. **Clean-room boundary implementation** — Spec's `exclude_paths` doesn't cover style guides and design rationale mentioned in requirements.

5. **Bundled fallback quality implications** — Vision says bundled is inferior, requirements acknowledge it as fallback, but neither addresses whether bundled reviews should be flagged or whether quality claims apply.

6. **Context files parameter** — Spec mentions suggesting context files but `review_dispatch` lacks this parameter.

**Recommendation**: Revise spec to address items 1-3 (critical) and 4-6 (important), then re-review. The vision and requirements are internally consistent; the spec needs work to faithfully implement them.
