# Review: 2026-03-22 12:10 UTC

**Prompt:** Review this design document covering both architecture decisions and an open ontology question for a personal AI infrastructure system. Focus on: (1) whether the ontology (role, project, service, agent, job) covers the space, (2) which option (A-D) for project structure works best, (3) whether 'facet' is the right term, (4) any concerns about the Part 1 decisions, (5) manifest structure recommendations. Be specific and critical — identify gaps, redundancies, and likely failure modes.
**Files:** docs/design/reviews/review-ontology-and-architecture.md
**Job ID:** 161fe9c6-0168-4613-ac69-9b8e704e0b33

## Synthesis

## Synthesis: Ontology and Architecture Review

Three reviewers produced substantive feedback (Kimi K2.5 returned no output). The convergence across Gemini, GPT-5.4, and Sonnet is unusually strong — they independently arrived at the same core conclusions on nearly every major point, which gives high confidence in those findings.

### High-Confidence Consensus (All Three Agree)

**The ontology is missing a concept for durable things that aren't agents/services/jobs.** All three reviewers independently identified that infrastructure primitives — databases, storage mounts, data feeds, repos — don't fit any of the five proposed concepts. Gemini calls it "Resource/Asset," GPT-5.4 calls it "component/asset," Sonnet calls it "Environment." The naming differs but the gap is identical: the system has durable infrastructure that no agent owns, no project defines, and no role constitutes. These things need a name so they can participate in tagging and cross-referencing. **Severity: high** — without this, the manifest becomes an untyped dumping ground for everything that doesn't fit elsewhere.

**Option B is the right filesystem layout.** All three converge on this with nearly identical reasoning: AI models rely on spatial proximity, and scattering a project across `~/services/`, `~/agents/`, `~/projects/` (Option C) forces expensive cross-filesystem traversal to build context. All three also agree that Option D (dot-notation metadata) is complementary, not an alternative — use it for tagging on top of B's physical structure. Option A gets less consensus: Gemini doesn't address it directly, GPT-5.4 dismisses it as "too lossy," Sonnet says it works but makes the manifest load-bearing. **Severity: medium-high.**

**"Facet" conflates two orthogonal classification axes.** All three identify that the proposed facet values mix activity types (`development`, `research`, `operations`) with entity/execution types (`services`, `agents`). A session developing an agent is simultaneously both. GPT-5.4 and Sonnet both explicitly recommend splitting into two fields — GPT-5.4 suggests `workstream` + `component_kind`, Sonnet suggests `domain` + `runtime`. Gemini reaches the same conclusion but recommends `workstream` as a single replacement term if you insist on one field. **Severity: high** — this is the finding with the strongest cross-reviewer agreement and the most detailed reasoning from each.

**The agent/service/job boundary is mechanism-driven and fragile.** All three note that distinguishing these by "does it use an LLM?" creates classification drift. A cron job that adds anomaly detection becomes an agent; a service that adds a model call becomes... what? Gemini proposes definitions based on operational nature (always-on vs. scheduled vs. autonomous loop). Sonnet proposes the same framing in different words. GPT-5.4 identifies the same problem but focuses on the missing `execution`/`session` concept as the fix. **Severity: medium.**

**The instruction precedence rule ("most specific wins") is dangerous without guardrails.** Both GPT-5.4 and Sonnet flag this, and Gemini raises a related concern. GPT-5.4 says to split role instructions into non-overridable invariants and overridable defaults. Sonnet raises the multi-project boundary problem (editing claude-hub code while under prediction-markets conventions). Gemini notes that LLMs don't actually override like compilers — they blend conflicting instructions. **Severity: medium** (GPT-5.4 rates it medium, Sonnet and Gemini flag it without explicit severity).

**The manifest should be an index, not documentation.** All three converge on this. Skill names without descriptions, stable capabilities separated from volatile infrastructure facts, and pointers to authoritative sources rather than inline details. Sonnet's specific proposal (two sections: stable capabilities vs. "should verify" environment) is the most actionable. **Severity: medium.**

### Unique Findings (Single Reviewer)

**GPT-5.4 alone** caught that the ontology needs a first-class `execution`/`session` concept. The window files describe concrete work in a specific run, but the ontology only defines durable concepts (agent, service, job). You can't distinguish "market-scout the agent" from "the 2026-03-22 market-scout run." This is a genuinely important gap that the other two missed entirely. GPT-5.4 also uniquely caught the "Job" naming collision — Part 1 says roles are "job descriptions," then Part 2 introduces `Job` as a separate ontological concept. **Severity: high.**

**GPT-5.4 alone** identified that the document claims to record "decisions already made" but adjacent design docs still encode the older architecture (spec and requirements still reference `thoughts/windows/{harness}/`, vision doc still uses different role framing). If this doc is meant to settle architecture, it should say what it supersedes. **Severity: medium.**

**Sonnet alone** caught the missing zeroth tier in the instruction hierarchy — harness-global config (`~/.claude/CLAUDE.md` or settings.json) loads before any role or project context and should be documented as the most general tier. **Severity: low** but a real gap.

**Sonnet alone** raised the git boundary complexity in Option B — if `~/projects/prediction-markets/` has a `dev/` subdirectory that's a full git repo, nesting repos requires submodule mechanics. The practical resolution (code repo *is* the project root, non-code subdirectories live within it) should be documented. **Severity: medium.**

**Sonnet alone** noted that the window file commit policy (committed vs. not) is inferred from convention rather than explicitly stated, which will confuse future agents about edge cases like low-quality window files. **Severity: low.**

**Gemini alone** flagged the hook injection overhead — prepending role context, infrastructure manifest, and situating instructions creates a large static token block at session start that will grow over time and eat into context budget. **Severity: medium** — this is an operational concern the design-focused reviewers didn't address.

**Gemini alone** noted the missing "Skill/Capability" concept — skills are mentioned in Part 1.4 but absent from the formal ontology. If a role is a job description, a skill is a tool authorized for that role. **Severity: low-medium.**

### Contradictions

There are no hard contradictions between reviewers. The closest is a **framing disagreement** on what to do about the facet problem:

- **GPT-5.4** insists on splitting into two fields (`workstream` + `component_kind`) and says a single field is fundamentally the wrong shape.
- **Gemini** recommends `workstream` as a single replacement term, treating it as adequate if you commit to one axis.
- **Sonnet** offers three options including both approaches and leans toward splitting but doesn't insist.

This is a disagreement about how far to go, not about the diagnosis. All three agree the current design is broken; they differ on whether one well-scoped field or two fields is the right fix.

There's also a minor **emphasis disagreement** on the "project doing too much work" finding. GPT-5.4 treats it as high severity and says the ontology needs a `component` concept between project and its contents. Sonnet agrees the tension exists but says the ontology "shouldn't ask project to resolve" it — that's what facets are for. Gemini doesn't address this specific framing. The practical difference is small: both are saying project is an umbrella, not a primitive.

### Reviewer Quality Assessment

**GPT-5.4** produced the sharpest review — it found the most unique high-severity issues (session/execution gap, naming collision, document supersession problem) and gave the most precise line-number references. Its recommendations are the most architecturally grounded.

**Sonnet** produced the most thorough and well-organized review, with the best practical recommendations (manifest structure, git boundary resolution, array-valued project field). It covered more surface area than the others but found fewer unique high-severity issues.

**Gemini** was solid on the consensus findings and uniquely caught the token budget concern, but was less architecturally deep than GPT-5.4 and less thorough than Sonnet.

**Kimi K2.5** produced no output. **Grade: fail.**

### Core Recommendation

The ontology needs two additions: a runtime concept (`execution`/`session`) and a durable-thing concept (`component`/`asset`/`resource`). The facet field should be split into activity-type and execution-mode dimensions. Option B is the right filesystem layout with D-style metadata on top. The manifest should be a stable index with explicit staleness signals, not inline documentation. And the document should state what it supersedes in the existing design docs.

**Models responded:** gemini-3.1-pro (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic), claude-sonnet-4.6 (agentic)

## Individual Reviews

### gemini-3.1-pro (complete)

Here is my review of the `review-ontology-and-architecture.md` document, based on the provided text and context gathered from reading `docs/architecture.md` and `docs/design/vision-personal-ai-infrastructure.md`.

### Files Read Beyond Review Targets
- `docs/architecture.md` (Full read)
- `docs/design/vision-personal-ai-infrastructure.md` (Read lines 1-150 for broader context on role vs. project separation)

---

### 1. The Ontology (Role, Project, Service, Agent, Job)
The proposed ontology is close, but there are a few blurry boundaries and missing primitives.

**Gaps & Overlaps:**
- **Agent vs. Service vs. Job:** The boundary here is driven by mechanism (does it use an LLM?) rather than system architecture, which can cause confusion. A Python script running on a cron schedule is a "Job," but if it makes an LLM call, does it become an "Agent"? 
  - *Recommendation:* Define these by their operational nature. A **Service** is an always-on, event-driven listener (API server, MCP endpoint). A **Job** is a deterministic, schedule-driven, bounded execution. An **Agent** is an autonomous, non-deterministic loop that relies on a model for control flow and decision making. 
- **Missing concept: Resource / Asset:** The infrastructure manifest lists databases, FUSE mounts, and active ports. These don't fit into the current ontology. You need a formal concept for "Infrastructure Resources" or "Assets" so models know how to categorize and query environmental dependencies.
- **Missing concept: Skill / Capability:** You mention skills in Part 1.4, but they are absent from the formal ontology. If a role is a "job description," a skill is a "tool authorized for that role."

### 2. Project Structure (Options A-D)
**Option B (Namespaced sub-structure within projects)** is the most robust and AI-friendly choice, but it can be combined with **Option D (Dot-notation/metadata)**.

*Why Option B works best:* AI models rely heavily on spatial proximity and localized context. If an AI is launched in `~/projects/prediction-markets/`, it can use `glob` or `grep` to quickly survey the code, the service configurations, and the research docs without accidentally bleeding into unrelated system directories. 
*Why Option C fails:* Separating by concern (`~/projects/`, `~/services/`, `~/agents/`) maps well to Linux hierarchies (`/opt`, `/etc/systemd`, `/var/lib`), but it forces the AI to traverse the filesystem to build a mental model of a single project. This fragments context and increases the number of tool calls required just to "look around."

*Recommendation:* Use **Option B** for physical filesystem layout (keep all related code, services, and agent definitions under the single project umbrella) and use **Option D** for logical metadata tagging in the window files.

### 3. Terminology: Is "Facet" the right term?
"Facet" implies viewing the exact same object from different angles (like facets of a diamond). However, `dev`, `services`, `research`, and `data` are entirely distinct types of work or distinct structural pieces of the project.

*Alternative recommendations:*
- **Workstream:** Best for categorized activities (e.g., tagging a window file: "This session belongs to the research workstream").
- **Component / Domain:** Best for structural code/system boundaries (e.g., "The data collector component").
- "Workstream" is likely the most natural fit for window file frontmatter because window files represent time and narrative activity.

### 4. Concerns Regarding Part 1 Decisions
- **1.3 Three-tier instruction delivery (Most specific wins):** LLMs are not compilers; they do not strictly "override" conflicting instructions based on file hierarchy. If a subdirectory instruction contradicts a project-level instruction, the model is highly likely to blend them or become confused. *Failure mode:* Silent degradation of rules. You must ensure that specific instructions explicitly state what they are overriding (e.g., "Ignore the project-level rule about X in this folder").
- **1.5 Window files stored per-role:** Storing window files in `~/roles/{name}/windows/` is great for role continuity, but it fragments project history. If the `workbench` role and the `sysadmin` role both do work on `claude-hub`, the project's historical narrative is now split across two different role directories. *Failure mode:* When an agent asks "What happened recently on claude-hub?", it will miss half the context unless it explicitly queries all other roles' directories. You will need a mechanism to aggregate or symlink window files by project.
- **1.2 Hook Injection Overhead:** Prepending the situating context, role instructions, and infrastructure manifest via a hook creates a massive, static block of tokens at the very start of every session. Over time, as instructions grow, this will eat a significant percentage of your context budget before the user even says "hello."

### 5. Infrastructure Manifest Recommendations
Given the ~200 token limit, the manifest must be strictly an **index**, not a manual. It should rely entirely on the model using `read_file` to fetch the details it needs.

**Recommended Structure (Highly constrained Markdown/YAML):**
1. **Identity:** 1 sentence defining the role's core directive.
2. **Environment Assets:** Key-value map of system facts (e.g., `DB: postgres@localhost:5432`, `Storage: /storage/`).
3. **Capabilities (The Index):** A terse list of available skills/tools paired strictly with the file paths to read for instructions. (e.g., `- [MCP Server Ops] -> /docs/skills/mcp-ops.md`).
4. **Current State:** A pointer to a dynamic state file (if needed) rather than injecting dynamic state directly into the manifest, ensuring the manifest remains cacheable.


### gpt-5.4 (complete)

I read the target plus these adjacent design docs for context: `docs/design/plan-infrastructure-redesign.md`, `docs/design/spec-personal-ai-infrastructure.md`, `docs/design/requirements-personal-ai-infrastructure.md`, `docs/design/vision-personal-ai-infrastructure.md`, and `docs/design/reviews/review-architecture-question.md`. I did not read code/tests because this review target is a standalone design doc and the relevant context lives in adjacent design documents.

High severity: the ontology does not yet cover the thing your window files actually need to describe: a specific execution or session. In `docs/design/reviews/review-ontology-and-architecture.md:71`-`docs/design/reviews/review-ontology-and-architecture.md:80`, `service`, `agent`, and `job` are defined as durable concepts, but the window-tagging section at `docs/design/reviews/review-ontology-and-architecture.md:127`-`docs/design/reviews/review-ontology-and-architecture.md:142` is about concrete work that happened in a particular session or run. Without a first-class `session` or `execution` concept, you cannot cleanly distinguish “market-scout the agent” from “the 2026-03-22 market-scout run that produced this output,” or “workbench the role” from one specific interactive invocation. I would add `execution`/`session` as a top-level concept and make `service`, `agent`, and `job` definitions that can each have many executions. Related naming problem: Part 1 says roles are “job descriptions” at `docs/design/reviews/review-ontology-and-architecture.md:13`-`docs/design/reviews/review-ontology-and-architecture.md:19`, then Part 2 introduces `Job` as a separate noun at `docs/design/reviews/review-ontology-and-architecture.md:79`; that collision will confuse both humans and models.

High severity: the proposed `facet` axis is internally inconsistent and loses information. At `docs/design/reviews/review-ontology-and-architecture.md:92` and `docs/design/reviews/review-ontology-and-architecture.md:139`, values like `development`, `research`, and `operations` are activities, while `services` and `agents` are entity types. Those are different dimensions. A session spent “developing the market-scout agent” is simultaneously development work and agent-related work; a single `facet` field forces you to drop one of those truths. So no, `facet` is not the right term here, and more importantly a single field is not the right shape. I would split it into at least two fields: `workstream` (`development`, `research`, `operations`) and `component_kind` (`service`, `agent`, `job`, `dataset`, `repo`, etc.). If you insist on one word, `workstream` is much better than `facet`, because it describes what the session was doing rather than pretending this is a clean orthogonal taxonomy.

High severity: `project` is doing too much work because the ontology is missing a first-class concept for durable project-owned things. The tension section at `docs/design/reviews/review-ontology-and-architecture.md:81`-`docs/design/reviews/review-ontology-and-architecture.md:90` shows this clearly: a project contains code, services, agents, research, and data. Right now `service`/`agent`/`job` cover only some operational entities, and everything else gets shoved under the project umbrella. That leaves research corpora, datasets, repos, and document collections as second-class citizens. I would add `component`, `asset`, or `resource` as the durable thing a project contains, then treat `service` and `agent` as specialized component kinds. Without that, the ontology will keep sprouting special-case metadata fields.

Medium-high severity: of the A-D structure options, `Option B` is the only one that really satisfies the stated requirement to map concepts onto directory structure. `Option A` at `docs/design/reviews/review-ontology-and-architecture.md:94`-`docs/design/reviews/review-ontology-and-architecture.md:100` is too lossy; it turns real structure into tags. `Option C` at `docs/design/reviews/review-ontology-and-architecture.md:111`-`docs/design/reviews/review-ontology-and-architecture.md:118` creates clean nouns but scatters tightly coupled project material across the filesystem. `Option D` at `docs/design/reviews/review-ontology-and-architecture.md:119`-`docs/design/reviews/review-ontology-and-architecture.md:125` is useful as metadata, but it dodges the physical-layout question rather than answering it. My recommendation is: choose B as the default physical layout, but make it optional and lightweight, not mandatory boilerplate for every project. Then use D-style qualified identifiers in metadata and search, on top of B, not instead of it.

Medium severity: Part 1’s instruction precedence rule is too coarse. `docs/design/reviews/review-ontology-and-architecture.md:30`-`docs/design/reviews/review-ontology-and-architecture.md:38` says “most specific wins,” which is fine for local coding conventions, but dangerous if it also applies to role-level operating constraints, boundary rules, or continuity behavior. A project should be able to override formatting or test workflow; it should not be able to accidentally nullify the role’s infrastructure contract. I would explicitly split role instructions into non-overridable invariants and overridable defaults. Otherwise “project wins” becomes a subtle boundary bug factory.

Medium-high severity: the role-scoped window decision is directionally right, but the metadata model is too thin to make it safe. `docs/design/reviews/review-ontology-and-architecture.md:44`-`docs/design/reviews/review-ontology-and-architecture.md:52` says windows live per role to enable cross-project continuity, which matches the redesign plan, but that only works if each window carries enough metadata to prevent cross-project and concurrent-thread contamination. The proposed frontmatter at `docs/design/reviews/review-ontology-and-architecture.md:134`-`docs/design/reviews/review-ontology-and-architecture.md:141` is not enough. It needs, at minimum, a session/execution identifier, room for multiple related components, and separation between activity and component type. Otherwise role memory becomes a pile of prose with weak joins.

Medium severity: the document says these are “decisions already made,” but adjacent docs still encode the older architecture, so the design is not yet complete as a system of record. `docs/design/reviews/review-ontology-and-architecture.md:44`-`docs/design/reviews/review-ontology-and-architecture.md:52` moves windows to role scope, but `docs/design/spec-personal-ai-infrastructure.md:283` and `docs/design/requirements-personal-ai-infrastructure.md:215` still specify `thoughts/windows/{harness}/`. Likewise the role framing differs from `docs/design/vision-personal-ai-infrastructure.md:91`, which still says a role is a “persona with a job description.” If this doc is meant to settle architecture, it should explicitly say which earlier docs it supersedes and what must be updated next, or the ontology will fork on paper before it even exists in code.

Medium severity: the manifest proposal is too compressed and too blended. `docs/design/reviews/review-ontology-and-architecture.md:57`-`docs/design/reviews/review-ontology-and-architecture.md:60` and `docs/design/reviews/review-ontology-and-architecture.md:144`-`docs/design/reviews/review-ontology-and-architecture.md:152` ask one ~200-token document to describe capabilities, storage layout, services, data sources, and infrastructure facts. That will either become vague or stale. I would make the injected manifest a stable index with three sections only: `identity and rules` (role, harness tier, precedence, when to look things up), `capabilities` (verbs and their canonical tools/skills), and `stable resources` (authoritative paths/endpoints/names, not live status). Anything dynamic—service health, timers, mounted volumes currently available, last-run state—should live in a discoverable registry or status command, not in the always-injected manifest.

If I reduce this to the core recommendation: the ontology wants one more runtime concept (`execution`/`session`) and one more durable-thing concept (`component`/`asset`); `Option B` is the best filesystem default; `facet` should be replaced by split fields, not just renamed; and the manifest should be an index to authoritative sources, not a miniature encyclopedia.


### kimi-k2.5 (complete)

*No output (status: complete)*

### claude-sonnet-4.6 (complete)

I now have sufficient context to write a thorough review. I've read:
- `docs/design/reviews/review-ontology-and-architecture.md` (the primary target)
- `docs/design/vision-personal-ai-infrastructure.md` (Draft 13)
- `docs/design/plan-infrastructure-redesign.md`
- `docs/design/requirements-personal-ai-infrastructure.md` (Draft 12, partial)
- `docs/design/reviews/review-architecture-question.md` (prior review context)

---

## Review: Infrastructure Ontology and Architecture

### Preliminary Note

This is a well-thought-out document that's doing real design work, not just organizing vocabulary. The ontology decisions will determine what's searchable and navigable for years. My concerns below are proportional to that stakes level.

---

### Part 1: Ontology Coverage — Role, Project, Service, Agent, Job

The five concepts cover the described space reasonably well, but there are two gaps worth examining and one redundancy risk.

**The missing concept: Environment**

The "other infrastructure facts" section at the bottom of Part 2 lists things that don't map to any of the five concepts: storage mounts, email, database, web services, data collectors. These are operating environment — persistent infrastructure that everything else depends on but that no agent owns, no project defines, and no role constitutes. The PostgreSQL instance is not a "service" in the proposed sense (it doesn't need an LLM to respond to requests). The FUSE mounts at `/storage/` are not a "project." The GitHub mirror at `~/repos/` is not a "job."

This isn't a trivial labeling problem. As the system grows, queries like "which agents depend on the CBOE data feed?" or "what uses the PostgreSQL instance?" require a named concept that can be tagged and cross-referenced. Right now, the manifest is an ad hoc container for these facts, but it's not an ontological concept. Calling these "infrastructure primitives" or "environment facts" and giving them a named concept would let them participate in the tagging system rather than floating unclassified.

**The agent/job distinction is fragile under evolution**

The current distinction is useful and real: an agent has a model, ongoing responsibility, and reads its continuity; a job is discrete and may not involve a model. But the classification is based on current capability, not identity. A nightly pipeline that does simple file operations today might incorporate anomaly detection with a model next month. Is it now an agent? The document should acknowledge this classification will drift — calling it out explicitly prevents future confusion about whether migration between the two categories is a philosophical change or just a label update.

**Service vs. Agent overlap**

The market scout is cited as an agent. But the polymarket collector is cited as a service. Both are long-running processes that do work on a schedule. The distinguishing criterion appears to be model-use, but the document doesn't say this explicitly. A one-sentence definition of what separates service from agent would prevent misclassification. Proposed framing: a service responds to requests or runs continuously without deliberative AI reasoning; an agent invokes a model to exercise judgment at runtime.

**The "project" concept is doing too much work**

The document correctly identifies the tension: prediction-markets is simultaneously development work, running services, research, and data. This tension is evidence that "project" is an umbrella concept, not a primitive. It's the right umbrella — "these things belong together" — but the ontology shouldn't ask "project" to resolve "what kind of thing is this?" That's what facets are for. The document is already halfway to this conclusion; making it explicit would clean up the definition.

---

### Part 2: Project Structure — Which Option

**Option B is the right answer, with one clarification on git boundaries.**

The "over-engineered for small projects" objection in the document is weak. Adding a top-level directory structure costs almost nothing and pays off immediately as a project grows. The real question is how git repo boundaries work in Option B.

If `~/projects/prediction-markets/` contains a `dev/` subdirectory that is itself a full git repo, the parent directory can't also be a git repo without submodule mechanics. This creates friction: commits to service configs and research docs don't naturally belong in the `dev/` repo, but having an outer repo with a nested repo is awkward.

The practical resolution is: the existing code repo *is* the project root (`~/projects/prediction-markets/` is the git repo), and subdirectories for `services/`, `research/`, and other facets live within it and are tracked there. The `data/` subdirectory is the exception — it's either a symlink/bind mount to the data volume, or it's git-ignored entirely. This is functionally Option B without the git nesting problem.

**Option C** scatters things across the filesystem in a way that makes "show me everything about prediction-markets" require knowing the taxonomy in advance. For a personal system where discovery is a key goal, this is actively harmful. Cross-facet operations — "which services depend on this collector?" — require querying across `~/services/` and `~/projects/` simultaneously. The manifest becomes load-bearing in a way that breaks when it's stale.

**Option D** is not an alternative to the others. It's a tagging convention that should be used *alongside* one of the structural options. Dot-notation metadata is useful for queries; it doesn't help with navigation. Use it in frontmatter; don't mistake it for a filesystem organization strategy.

**Option A** works but forces the manifest/search layer to compensate for structural ambiguity. When the manifest is stale or a search returns unexpected results, there's no filesystem fallback for understanding where things are. For a personal system where a human also navigates the filesystem directly, this is a maintenance burden.

---

### Part 3: Is "Facet" the Right Term

"Facet" is defensible but imprecise in a specific way that matters here: it conflates two different classification axes that are actually orthogonal.

The first axis is **activity type**: development (writing code), research (analysis, literature), operations (running, monitoring). The second axis is **execution mode**: persistent services, scheduled agents, discrete jobs, interactive sessions. These are different questions. A market scout is research *and* an agent. Collector code development is development *and* scheduled-job-to-run-it. Calling both dimensions "facets" and using the same field for both means the frontmatter's `facet:` field has to pick one axis, losing the other.

The proposed values in the frontmatter (`development`, `services`, `agents`, `research`, `operations`) mix the two axes. `development` and `research` are activity types; `services` and `agents` are execution modes; `operations` is somewhere in between.

This matters for the query use case. "What has the workbench role been doing in the *research* facet?" is an activity query. "What services does prediction-markets run?" is an execution-mode query. Using a single `facet` field answers one or the other, not both.

**Options:**
1. Keep `facet` as a single field but commit to one axis (activity type seems more query-useful for humans). Add a separate `mode` or `kind` field for execution mode.
2. Keep `facet` as free-form tags (multiple values), accepting some noise in queries.
3. Rename and split: use `domain: development|research|analysis` and `runtime: service|agent|job|interactive`.

The term itself — "facet" vs. "aspect" vs. "domain" — matters less than resolving which axis it captures. "Facet" is fine once that decision is made. "Domain" is slightly more intuitive in conversation ("what domain of the project is this?"), but "facet" is already in use and not worth changing.

---

### Part 4: Concerns About Part 1 Decisions

**1.2 Launch from project directory — what happens at the boundary**

The three-tier delivery model is sound. The underdocumented edge case is what happens when work crosses project boundaries within a session. A workbench session that starts in `~/projects/prediction-markets/` then reads files in `~/projects/claude-hub/` will get JIT-loaded instructions from the first project's subdirectories but not the second. The model could be operating under prediction-markets conventions while editing claude-hub code. The document doesn't acknowledge this, and it's a real footgun for multi-project sessions.

**1.3 Three-tier hierarchy is actually four-tier**

The document lists three tiers: role, project, subdirectory. But there's also a zeroth tier: harness-global config (`~/.claude/CLAUDE.md` or settings.json). In Claude Code, user-level CLAUDE.md loads before any project context and before hooks fire. It's the most general tier and it belongs in the hierarchy table. Not documenting it makes the model's context precedence subtly wrong — agents may not know to expect harness-level instructions to exist above their role instructions.

**1.5 Window files and multi-project sessions**

The frontmatter schema has `project:` as a single string. Sessions that touch multiple projects (common in this infrastructure) produce a window file tagged to one project while containing context about both. "What happened with prediction-markets last week?" might miss window files from sessions that started in claude-hub but discussed prediction-markets. This isn't a fundamental flaw — you can use free-text search — but the structured `project:` field loses precision. Consider `projects: [prediction-markets, claude-hub]` (array), or accept the limitation explicitly.

**1.7 Window files: committed or not**

The document says mechanical logs and session transcripts are not committed. Window files are, implicitly, committed (they're described as version-controlled). But window files are also generated by hooks, similar to mechanical logs. The policy is correct — window files are curated summaries, not raw transcripts — but it should be stated explicitly. Otherwise future agents will have to infer the distinction from convention, which breaks under edge cases (what about a very low-quality window file that's basically a mechanical log? What about a mid-session snapshot?).

---

### Part 5: Manifest Structure

The key design tension is that **capabilities** (skills, tools) and **facts** (services, data, storage) have different decay rates. Skills change rarely; infrastructure facts change whenever a service is added, a mount point moves, or a database is renamed. Mixing them in a single manifest means the manifest either ages out fast or requires frequent maintenance.

A structural recommendation:

```
## Capabilities (stable)
/launch-model, /session-search, /artifact-store, /query-database, /review, /system-admin, /write-design-doc

## Environment (should verify)
DB: postgres/localhost:5432 (claude_hub) | API: :8420 | Storage: /storage/ | Data: thoughts/ (50GB bind mount)
Collectors: polymarket (persistent), cboe/fred/coingecko (daily timers)
```

Two sections, not one. The "should verify" label on the environment section signals to models that these facts might be stale and worth checking before acting on them. Skills can be trusted until explicitly removed; infrastructure facts can't be.

At ~200 tokens total, this leaves ~120 for capabilities and ~80 for environment. That's achievable if capabilities are listed as skill names without descriptions (descriptions live in the skill files themselves). The manifest is an index, not documentation — one word per skill is enough to trigger recognition and prompt skill loading.

**The manifest should not describe what skills do.** The current example in the plan (`- Fork agents or launch other models (Skill: /launch-model)`) uses ~10 tokens per skill for explanation. At 8 skills, that's already 80 tokens. Dropping descriptions and just listing skill names saves ~60 tokens for environment facts: `/launch-model, /session-search, /artifact-store, /query-database, /review, /system-admin, /write-design-doc` fits in ~25 tokens.

---

### Summary of Key Issues

| Issue | Severity | Location |
|---|---|---|
| Missing "environment" concept for infrastructure primitives | Medium | Part 2 ontology |
| Agent/job distinction fragile under evolution; should be acknowledged | Low | Part 2 ontology |
| Service vs. agent distinction undefined | Medium | Part 2 ontology |
| `facet` conflates two orthogonal axes (activity type vs. execution mode) | High | Window file tagging |
| Option B has unacknowledged git boundary complexity | Medium | Part 2 project structure |
| Part 1.3 hierarchy missing zeroth tier (harness-global) | Low | Part 1 decisions |
| Multi-project sessions: `project:` single-value loses precision | Medium | Window file frontmatter |
| Window file commit policy needs to be explicit, not inferred | Low | Part 1 decisions |
| Manifest mixes stable capabilities with volatile infrastructure facts | Medium | Infrastructure manifest |

The ontology is coherent and well-motivated. The main gap is that "facet" is trying to be two things at once. Splitting the classification axes would clean up both the tagging model and the query semantics downstream.

