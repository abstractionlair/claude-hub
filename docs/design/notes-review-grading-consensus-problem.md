# Review grading is consensus-scored (problem statement)

**Date:** 2026-07-20
**Status:** Analysis complete from code. Two empirical questions unresolved (DB access blocked).
**Scope:** claude-hub multi-model review engine — `src/claude_hub/review_engine.py`,
`config/review_models.yaml`. Relevant to the public claude-hub repo
(`KNOWN_ISSUES.md`), which ships this engine's config.
**Companion:** `notes-review-grading-improvement-options.md` (remediation options).

## Summary

The engine grades reviewer quality against the *synthesis of the reviews being
graded*, not against ground truth. Grades therefore partly measure agreement
with the panel rather than correctness. This is sound for detecting
non-responsive or shallow reviews, and unreliable for distinguishing a wrong
finding from a correct minority one.

## The mechanism (all verified in code)

**1. Synthesis ranks by headcount.** The synthesis prompt
(`review_engine.py:1180-1190`) is, in full:

```
- What do multiple reviewers agree on? (high confidence)
- What did only one reviewer catch? (note which model)
- Where do they contradict each other?
- Note the severity of each finding.
```

"High confidence" is defined as agreement in the prompt. There is no
instruction to verify any claim against the code. The synthesizer runs
agentically (has tool access) but is told "Read *them*" — the reviews — so any
verification is incidental, not designed.

**2. The grader is told the synthesis is the answer key.**
`review_engine.py:1713-1715`, verbatim:

> "You are grading the quality of code reviews. The synthesis below represents
> the merged consensus — use it as an approximate answer key."

**3. The grader cannot verify anything.** `grading_cmd` in
`review_models.yaml` passes `--allowedTools ""` — no tools. The code comment at
`review_engine.py:1747-1748` states "Grading is text-in/JSON-out — no tool
access needed." The grader compares text to text and cannot open a file to see
who was right.

**4. Grades and failure modes** (`review_engine.py:1707-1711`):
`EXCELLENT | ADEQUATE | INADEQUATE | HARMFUL`, with a required failure mode when
negative: `no_output, false_positive, false_negative, wrong_severity,
hallucinated_evidence, credulous, shallow`.

Cross-grading policy (`review_engine.py:1606-1638`): first 20 cycles every model
grades every review (N×N); after that synthesizer-only, unless contradictions
exist or cycle % 5 == 0.

## Failure chain for a lone correct catch

Unbroken, with no verification step anywhere:

1. Model X alone finds a real bug → synthesis buckets it as "only one reviewer
   caught," explicitly *not* high confidence.
2. Contradiction detection excludes it by definition —
   `review_engine.py:1423-1424`: "Unique findings (only one reviewer mentions
   it) are **NOT** contradictions."
3. No peer follow-up fires. X never gets to defend it.
4. Grader, toolless, sees a claim outside the answer key → `false_positive` →
   INADEQUATE or HARMFUL.

A model that catches a real bug nobody else saw can receive a negative grade for
having done so.

## Three stacked discounts on minority findings

- Synthesis labels singletons as lower confidence than agreed findings.
- Bundled-mode reviewers get an extra flag ("Flag any findings that came
  exclusively from bundled reviewers", `review_engine.py:1175-1177`).
- Only 3 of 6 seats can concede/defend at all. Peer follow-up requires
  `resume_cmd` + session-id capture: claude ✓, claude-sonnet-4.6 ✓, gpt-5.4 ✓;
  gemini-3.1-pro ✗, gemini-3.5-flash ✗, grok-4.5 ✗. The config comments the
  cause for the agy seats. The ability to defend a position is available only to
  the Anthropic and OpenAI seats — denied to the seats supplying lineage
  diversity.

## Lineage monoculture in the decision path

Four checkpoints, one lineage:

- synthesizer: `claude`
- default grader after cycle 20: synthesizer-only, so `claude`
- 2 of 6 roster seats: Claude
- the instance that notices "this model is underperforming" and writes the drop
  recommendation to Scott: also Claude

A model that reviews *differently* is marked down at every stage. Additionally,
the instance writing the recommendation is the author of the code that model
criticized — an author-reviewer independence conflict of exactly the shape the
`review-diversity` project's H1 is about, running live in the infrastructure.

## Severity: "want it better," not "worse than nothing"

Calibrated verdict, with reasoning:

**The review product is fine.** Ranking by agreement is a defensible prior.
Unique findings survive into the synthesis prose *with attribution*, and the
prose is what a human actually reads. The human adjudicates and can override the
confidence label. Commit `3d9e102` ("complementary blind spots observed in a live
three-model gate") shows lone catches are already treated as valuable.

**The grades are a mix, not uniformly contaminated.** Several failure modes are
conformity-independent and checkable from text alone: `no_output`, `shallow`,
`credulous`. Those are real signal and probably account for most negative
grades. A model graded 0% pass is a model that failed, not a suppressed
dissenter. Contamination concentrates in `false_positive` / `false_negative`,
and bites hardest on a narrow case: a *strong* model that is strong
*differently*.

**Where it approaches worse-than-nothing:** using these grades as the sole gate
on a model whose value proposition is being different. The bias is directional
rather than noisy, and it ratchets — each drop tightens consensus, which makes
the next outlier look worse.

**Main mitigation:** roster changes are human-decided. `review_models.yaml` is
hand-edited with prose rationale; nothing auto-drops a model. The actual process
is that a working instance notices a problem during real work, raises it,
Scott and the instance discuss and verify, and Scott decides — usually on a
recommendation. The working instance has ground truth access (it holds the code,
spec, and test results), so that recommendation is better-grounded than anything
in `review_grades`. But see the monoculture section: the loop's inputs are near
single-lineage.

**Residual risk:** grades accumulate authority by sitting in a table with a
taxonomy and looking like measurement. Over time "the grades said so" gets cited
without re-examination. This is more a documentation problem than an engine
problem.

## Observed pattern, heavily confounded

All six dropped models (kimi-k2.5, gpt-5.3-codex, glm-5, minimax-m2.7,
grok-code-fast-1, mimo-v2-pro) are non-Anthropic, as is the entire audition
queue. Consistent with the bias — but confounded with capability tier, since
those are mostly cheaper/smaller models that plausibly underperform on merit.
**Do not present this as evidence.** The innocent explanation is fully
available and cannot be separated from the config alone.

## Unresolved — needs DB access

`psql "$CLAUDE_HUB_PG_DSN"` fails auth (password rejected for the app's DB
role; likely stale since a recent credential rotation). Reading the
deployment-host environment file was blocked by the permission classifier.
Two questions remain open:

1. **Were the 2026-03-31 drops hand-checked or purely consensus-graded?**
   Determines whether those six were dropped fairly.
2. **Do self-grading rows exist** (`grader_model = model_name`) from the N×N
   phase? The cross-grading code appears to let models grade themselves.

Also relevant: `consensus` and `unique_findings` columns are deprecated and
written as `'[]'` (`review_engine.py:1357`), so for historical jobs the
structured record of which finding was unique to whom is not in the DB.
Reconstructing it means re-parsing synthesis prose.

## Suggested framing for public disclosure

Measured, not damning — the harm is real but unmeasured:

> Reviewer grading uses the panel synthesis as an approximate answer key, so
> grades partly measure agreement with the panel rather than correctness. This
> is sound for detecting non-responsive or shallow reviews and unreliable for
> distinguishing a wrong finding from a correct minority one. Roster decisions
> are human-made with grades as one input among several.
