# Review grading — options for improvement

**Date:** 2026-07-20
**Status:** Options analysis. Nothing implemented; no option is committed to.
**Companion:** `notes-review-grading-consensus-problem.md` (problem statement —
read first for the mechanism and severity assessment).

## Constraint

Assume neither Scott nor any human manually reviews all reviews or all code.
Any option requiring per-finding human adjudication is out of scope.

## The reframe

You do not need to verify every finding. You need enough verified findings to
*rank models*. That is a sampling problem, not a coverage problem — and sampling
is what the `review-diversity` plan already concluded was sufficient for FDR
("estimated from a **sample** of out-of-key pointers per condition (with a CI),
not a full census").

Ground truth does not have to come from a human. It has to come from something
mechanically checkable.

## Options, ranked

### 1. Backtest against your own git history — RECOMMENDED

Take a fix commit from a private repo, check out the parent, hand the panel the
buggy state, score who points at the span the fix touched.

- **The answer key already exists.** Whoever fixed it wrote it, at the time,
  without knowing it would be used this way. Uncontaminated by the panel.
- **Zero human labor.** Fully automated end to end.
- **Scoring is already written.** `_spans_overlap` and `_score_locations` in
  `~/projects/review-diversity/factory/smoke_review.py` are exactly the
  primitive — span overlap with ±3 line tolerance.
- **Training-contamination sidestepped** by using private repos (claude-hub,
  work-graph, prediction-markets, and others) rather than public OSS.
- **Directly measures the thing roster decisions need:** per-model recall on
  real bugs, owing nothing to consensus.

Run monthly over a handful of recent fix commits as roster calibration. Note
this needs a fraction of the research project's rigor — the goal is ranking six
models, not defending a confirmatory claim.

### 2. Turn findings into tests

A correctness finding is a test specification: "this breaks on empty input"
states precisely what to write. Run it; the finding is true or false with no
judgment involved.

- Fits the existing TDD path.
- Verification is not wasted work — the test persists as a regression guard.
- Covers only mechanically checkable claims, but those are the ones that matter
  most for grading.

### 3. Give the grader tools — cheapest fix

`hallucinated_evidence` is currently a judgment call solely because
`--allowedTools ""` prevents the grader from checking whether a cited
`file:line` exists. Removing that restriction converts one failure mode from
opinion into a fact check. Roughly an hour of work.

### 4. Deferred outcome as free instrumentation

Did the flagged location get modified in a later fix commit? Did a test start
failing there? Findings that predicted future changes were probably real;
findings at locations never touched again probably were not.

- Slow (weeks) and noisy.
- Zero marginal cost — accrues as a byproduct of normal work.
- Needs only a join between review findings and subsequent commits.

### 5. Replace consensus with adversarial pressure where no ground truth exists

For non-testable findings, headcount is a weak proxy but not the only available
one. Ask a *different-lineage* model to refute a specific finding with a
counter-citation. A finding that survives targeted refutation is better evidence
than a finding four models happened to mention — it rewards defensibility rather
than popularity.

The concede/defend machinery already implements this, restricted to
contradictions and to seats with session resume. Generalizing it is mostly
plumbing, plus fixing session-id capture for the agy and opencode seats (see the
problem note: 3 of 6 seats currently cannot defend at all).

### 6. Proper scoring rules — layer, not standalone

Have reviewers state confidence, then score with a proper scoring rule against
whatever ground truth arrives from options 1–4. Rewards calibration, punishes
hedging and spraying findings. Only works once a ground-truth source exists.

## Addressing the lineage-monoculture conflict

None of the above fixes the conflict identified in the problem note: a Claude
instance still runs the calibration and reports it, and that instance authored
the code under review.

- **Cheap structural fix:** have a non-Claude seat write the drop
  recommendation, or at least a second opinion on it. The dispatch machinery
  already exists. Smaller change than reworking the grader, and it addresses the
  checkpoint that actually feeds Scott's decision.
- **Option 1 partially self-mitigates:** its output is a recall number against a
  key neither the recommender nor the panel chose, leaving much less room for
  any one instance's read to shape the result.
- **Make the verify step explicit.** When a drop is proposed, the settling
  question should be "which of its findings were right, and did anyone else
  catch them," not "did it seem unhelpful." Checking against reality is immune
  to all upstream bias.

## Suggested minimum

If only one thing: **option 1**. It is the only option that directly measures
"does this model find real bugs," it reuses code already written, and it
produces exactly the number roster decisions need.

**Option 3** is worth doing regardless — it is nearly free.
