# Standard vs. homebrew tooling — open thread

**Status:** Deferred (raised 2026-05-02, not acted on)

## The question

The recurring source of friction on this VPS is patterns we built ourselves
for problems other people have already solved with widely-deployed tools:

- **Deploy procedure** — `~/bin/deploy <project>` stages from `origin/<branch>`,
  installs into per-project venvs, manages systemd units. Well-defined for us,
  invisible to LLMs in training. Would map naturally to GitHub Actions /
  GitLab CI / a self-hosted runner.
- **Homebrew vault** — our own secret storage, accessed by convention.
  HashiCorp Vault, age-encrypted SOPS, AWS Secrets Manager, even GitHub
  Actions secrets are all on every fresh agent's mental model already.
- **Review dispatch** — `python -m claude_hub.review_cli`, model registry in
  YAML, custom result-aggregation. The unique work-product (multi-model
  consensus + grading) is genuinely ours, but the dispatching/orchestration
  is shaped like a job-queue every CI/CD tool already implements.
- **Ledgers / window files** — the persistence-and-rotation discipline is
  ours; the storage mechanism could be anything.

The hypothesis: for each homebrew piece, a standard tool with strong
training-data coverage might pay back its migration cost in fewer
"Claude doesn't know how this works" incidents — and in less time spent
explaining mechanics to fresh-context agents.

## Counter-pull

Standard tools are heavier than what we need. Kong, Envoy, full HashiCorp
Vault, Kubernetes — none of these fit a 4GB single-VPS personal infrastructure
project. The pull is toward small, well-known *primitives* (FastAPI, httpx,
systemd, Postgres, localhost-bound subservices, schema isolation), not toward
large managed platforms.

## What we did do (2026-05-02)

We named the architectural pattern instead. The work-graph integration is
**API Gateway + BFF**, with **bind address as security boundary** and a
**schema-isolated shared DB**. Each primitive in the implementation
(FastAPI subservice, httpx forwarder, systemd unit, Postgres schema,
127.0.0.1 socket) IS standard and IS in training data; the composition is
custom-to-this-server but built from recognizable parts. Naming this
explicitly in `docs/architecture.md` (claude-hub) and `INTEGRATION-BRIEF.md`
(work-graph) means fresh-context agents pick up the shape on arrival.

That helped for *architecture*. It does not help for *deploy* or *secrets*,
where the homebrew layer is the actual mechanism, not just its shape.

## Per-piece worth-investigating list

In rough order of expected payoff:

1. **Vault** — easy win? `age` + a checked-in encrypted file, or `pass`,
   would already be more legible than what we have, with low migration cost.
   Worth a small experiment.
2. **Deploy** — bigger lift. The current script encodes real per-project
   config (manifest, origin-staging, pre-flight). Replacing it with GitHub
   Actions means moving that config into workflow files. Possible, but the
   gain is "agents recognize the shape" rather than fewer bugs.
3. **Review dispatch** — probably stays. The unique value (multi-model
   consensus grading) outweighs the orchestration layer's weirdness, and
   moving to a generic job runner buys little.
4. **Ledgers / window files** — the rotation/curation policy is the
   substance. Storage is incidental. Not an obvious migration target.

## How to decide on a piece

The test for each: **would a fresh agent with no prior context understand
what's happening, and can it operate the thing without me explaining?**

- If yes for both → leave alone.
- If no on understanding but yes on operation → document the shape (what
  we did for the architecture).
- If no on operation → consider the migration.

## Not yet done

- No experiment with `age`/`pass`/Vault for secrets.
- No prototype of GitHub-Actions deploy.
- No decision rubric beyond the test above.
