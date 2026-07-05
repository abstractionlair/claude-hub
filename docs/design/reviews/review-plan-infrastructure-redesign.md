# Review: 2026-03-21 19:07 UTC

**Prompt:** Review this infrastructure redesign plan. It was developed through extensive experimentation — the hook injection mechanisms have been empirically tested and confirmed working. Focus on whether the plan as a whole is sound, not on whether individual mechanisms work (they do). Be critical about gaps, ordering mistakes, or unstated assumptions.
**Files:** docs/design/plan-infrastructure-redesign.md
**Job ID:** 3463f67f-6701-4499-8e8b-b145237270e4

## Synthesis

The Kimi K2.5 review appears to have been truncated before producing any findings — it's just setup narration with no actual analysis. The synthesis below draws from the two substantive reviews: Gemini 3.1 Pro and GPT-5.4.

---

## Synthesis

### High-confidence findings (both reviewers agree)

**`.current-role` as global mutable state is broken by design (Critical).** Both reviewers independently identify the same race condition: a single well-known file for current role identity cannot survive concurrent sessions. Gemini frames it as two terminal windows overwriting each other; GPT-5.4 extends the scenario to review dispatches and scheduled agents, noting the vision *explicitly expects* multiple agents. Both converge on session-scoped identity as the fix — Gemini suggests environment variables inherited by the process tree, GPT-5.4 suggests keying by session ID, PID, or TTY. This is the highest-confidence finding in the review set.

**Role memory is claimed but not implemented (Critical).** Both reviewers flag that the vision's core promise — role continuity that spans projects — has no concrete plan. The vision says window files serve role memory; the plan injects role instructions at launch and stops there. GPT-5.4 is sharper here: it traces the gap through the downstream requirements and spec docs, showing they still assume harness-scoped window files rather than role-scoped ones. Gemini makes the same point but frames it as a storage-redirection problem (window files need to write to `~/roles/{name}/` not the project directory). Neither reviewer considers this optional — both treat it as load-bearing for the architecture.

**Config ownership between role and project is ambiguous (Medium-High).** Both reviewers see the same tension: role directories hold harness-specific config files, but hooks inject role instructions dynamically from a different path, and Phase C conflates role hooks with project hooks during migration. GPT-5.4 frames it as a composition contract problem (which config wins?); Gemini frames it as redundant files that will never be parsed. Same underlying issue, different angles.

### Unique findings (single reviewer)

**Instruction precedence rules are missing (GPT-5.4, Medium).** The three-tier context model (role / project-root / path-scoped) never specifies what wins on conflict. Because each harness injects at different points, you could get three different "correct" behaviors from the same inputs. This is a classic integration boundary bug that Gemini didn't flag.

**Phase A/B ordering creates a ghost-capability window (GPT-5.4, Medium).** The manifest advertises skills (`/launch-model`, `/artifact-store`, `/query-database`) that don't exist until Phase B completes, but the plan says A and B can run in parallel. Agents would be told they have capabilities they can't use. Straightforward fix, but a real plan defect.

**Phase D cuts against "view, don't warehouse" (GPT-5.4, Medium).** Moving durable documents out of `thoughts/` contradicts the vision's principle that data stays where it's most useful. The existing requirements and spec already assume in-place indexing via filesystem connectors. GPT-5.4 wants a sharper rule for what migrates vs. what gets indexed.

**Git as audit trail is asserted but unplanned (GPT-5.4, Medium).** The plan elevates version control to the safety/control model without any implementation work covering repo boundaries, commit conventions for generated artifacts, or secrets exclusion.

**Access scoping is absent (GPT-5.4, Medium).** Broadening access to shared data across all roles and harnesses without even minimal scoping primitives (discoverable metadata vs. session-authorized content) is noted as a gap against the vision's own security-from-the-start principle.

**Gemini context bloat on every prompt (Gemini, Low-Medium).** Gemini CLI's `BeforeAgent` hook fires on every prompt, potentially injecting the full role instructions + manifest repeatedly into the conversation. This is a Gemini-specific implementation concern that GPT-5.4 didn't address.

**Artifact store has no backend (Gemini, Low).** Phase B introduces an `/artifact-store` skill but no phase actually creates the underlying storage structure it would talk to.

**Missing concrete tasks (GPT-5.4, Low).** Role directory creation, thin wrapper templates, migration from current state, and `session-archive` scheduling are described but never appear as actual phase steps.

### Contradictions

There are no direct contradictions between the two reviews. They consistently agree on the critical issues and their framings are complementary rather than conflicting. GPT-5.4 is broader in scope — it reads downstream docs (requirements, spec) to check alignment and catches more medium-severity boundary issues. Gemini is more focused on mechanical correctness of the hook injection system. Both are useful; neither undermines the other.

### Overall assessment

The plan's direction is sound — role/project/harness separation, project-directory launch, and pragmatic harness-parity choices all fit the vision. But it is currently a plan for role *bootstrap*, not for the role *architecture* the vision describes. The two critical gaps (session identity and role memory) must be resolved before implementation, or the system will silently produce wrong behavior under normal concurrent usage. The medium-severity config/precedence/scoping issues are the kind of boundary contracts that get harder to retrofit later and should be pinned in the plan now.

Kimi K2.5 produced no usable output — it spent its budget on file exploration without reaching analysis. This is consistent with prior observations that Kimi is thorough when it completes but can get stuck in setup. For a document review of this scope, two substantive reviews provided strong coverage regardless.

**Models responded:** gemini-3.1-pro (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### gemini-3.1-pro (complete)

Here is the review of the `plan-infrastructure-redesign.md` against the intent and constraints outlined in `vision-personal-ai-infrastructure.md`. 

### Review Findings

**1. Race Condition in Role Injection (Severity: Critical)**
- **Location:** Section 2 (Launch from project directory), Section 8 (Role launcher script), and Phase A
- **Issue:** The plan dictates that the launcher writes a `.current-role` file to a "known location," which the hooks read dynamically upon events like session start, compaction, or every prompt. If a user runs multiple roles concurrently in different terminal windows (e.g., `role researcher` and `role sysadmin`), the global file will be overwritten. Consequently, a hook firing in the first terminal mid-session would read the *new* file and seamlessly (and incorrectly) swap the agent's identity to `sysadmin`.
- **Fix/Risk Mitigation:** The plan should replace the global `.current-role` file mechanism with environment variables (e.g., `CURRENT_ROLE=researcher claude`). Hooks inherit the environment of the harness process, cleanly binding the role to the specific session tree without race conditions.

**2. Loss of Role Memory and Continuity (Severity: Critical)**
- **Location:** Section 2 ("Launch from project directory"), Risks section
- **Issue:** The vision explicitly mandates that "role memory spans projects" and uses the window file system to maintain this continuity ("A role switching from one project to another should not carry stale project-specific details in its continuity chain"). However, the plan states harnesses will be launched directly in the project directory. By default, harnesses like Claude Code will store their session state and window files in the project's local directory (e.g., `~/project-a/.claude/`). This completely severs cross-project continuity for a role.
- **Fix/Risk Mitigation:** The plan must explicitly address how the harness's session storage or continuity hook is redirected to read/write narrative state/window files from `~/roles/{name}/` rather than the active working project directory.

**3. Contradiction in Role Directory Contents vs. Hook Injection (Severity: Medium)**
- **Location:** Section 1 vs Section 2
- **Issue:** Section 1 defines the contents of `~/roles/{name}/` as containing `CLAUDE.md`, `GEMINI.md`, etc., which are described as "thin orientation wrappers". However, Section 2 explains that the harness is launched in the *project directory* (so native JIT loads the *project's* `CLAUDE.md`) and the role instructions are injected entirely via hooks. If the role instructions are injected dynamically by hooks, the `CLAUDE.md` and `GEMINI.md` files sitting in the role directory will never be natively parsed by the harnesses.
- **Fix/Risk Mitigation:** Clarify what the hooks are actually reading. If the hook directly reads `shared.md`, then the harness-specific markdown files in the role directory are redundant and should be removed to prevent confusion.

**4. Global vs. Project Hook Ambiguity (Severity: Medium)**
- **Location:** Phase A and Phase C (Steps 8-9)
- **Issue:** Phase A introduces a new "role-injection hook for each harness." If harnesses are launched in the project directory, does this foundational hook live globally or in every project? Phase C mentions moving project-specific hooks from `~/.claude/hooks/` to "role/project `.claude/hooks/`." The distinction between a *role* and a *project* is the core of the redesign, but this step conflates them.
- **Fix/Risk Mitigation:** Clarify that the new role-injection hook itself must remain a global hook (or be configured globally) so it automatically executes in every project. Separate the migration of project-hooks from role-hooks. 

**5. Token/Context Bloat in Gemini CLI Role Injection (Severity: Low/Medium)**
- **Location:** Section 2 (Three-tier context delivery)
- **Issue:** For Gemini CLI, the hook is `BeforeAgent`, which the plan states "fires on every prompt." While the empirical test confirmed the injection *works*, injecting the full role instructions + infrastructure manifest on *every single prompt* risks severe context bloat or conversational duplication if it constantly appends to the message history. 
- **Fix/Risk Mitigation:** Ensure the injection mechanism for Gemini CLI updates a persistent system instruction layer rather than dynamically appending heavy instruction text to the conversation on every turn.

**6. Missing "Native Store" Instantiation (Severity: Low)**
- **Location:** Phase B, Phase D
- **Issue:** The vision places significant emphasis on an "AI-native data store" that acts as a semantically indexed scratchpad for generated artifacts. The plan introduces an `/artifact-store` skill in Phase B, but the actual instantiation or deployment of this underlying database/directory structure is missing from the build phases.
- **Fix/Risk Mitigation:** Include a specific step in Phase D to initialize the actual backend layout for the artifact store so the skill has something to talk to.

### Files Explored Beyond Review Targets
- `docs/design/vision-personal-ai-infrastructure.md` (Read fully, as requested).
- I used directory listing on `.claude/` and `docs/design/` to understand the current configuration layout and assess the feasibility of the Phase C migration steps.


### gpt-5.4 (complete)

My take: the backbone is right — especially the separation of role/project/harness in `docs/design/plan-infrastructure-redesign.md:16`, the decision to launch from the project directory in `docs/design/plan-infrastructure-redesign.md:28`, and the refusal to chase full harness parity in `docs/design/plan-infrastructure-redesign.md:44`. Those choices fit the vision well. But as a whole, this is still a plan for role bootstrap and config reshaping, not yet a full implementation plan for the Section 4 architecture.

High severity: the plan does not actually implement role memory, which is one of the load-bearing claims in the vision. Section 4 says the role’s continuity should persist across projects and harnesses, and that window files serve role memory in `docs/design/vision-personal-ai-infrastructure.md:93`, `docs/design/vision-personal-ai-infrastructure.md:101`, and `docs/design/vision-personal-ai-infrastructure.md:115`. But the plan only injects role instructions and then explicitly excludes persistent-agent scheduling and cross-agent coordination in `docs/design/plan-infrastructure-redesign.md:154`, while reducing cross-harness continuity to a risk note in `docs/design/plan-infrastructure-redesign.md:182`. Downstream docs still assume harness-scoped window files in `docs/design/requirements-personal-ai-infrastructure.md:216` and `docs/design/spec-personal-ai-infrastructure.md:285`. Until the plan says where role memory lives, how it is keyed, and how a role resumes across projects without dragging stale project context along, it is not yet implementing the role-based architecture it claims to implement.

High severity: `.current-role` as a single well-known file is not a safe state model. The plan relies on that in `docs/design/plan-infrastructure-redesign.md:40`, `docs/design/plan-infrastructure-redesign.md:89`, and `docs/design/plan-infrastructure-redesign.md:115`. That works only if exactly one session exists. The moment you have two interactive sessions, a review dispatch, or a scheduled agent, one launch can overwrite another and the next hook can inject the wrong role. Given the vision explicitly expects multiple agents and shared roles in `docs/design/vision-personal-ai-infrastructure.md:103`, this is not an edge case. The plan needs a session-scoped manifest keyed by session id, pid, tty, or equivalent, plus lookup and cleanup rules.

Medium-high severity: config ownership is internally inconsistent. The role directory is introduced as the place where harness-specific config lives in `docs/design/plan-infrastructure-redesign.md:20`, but later the document says project-level config replaces global config in `docs/design/plan-infrastructure-redesign.md:78`, and then Phase C migrates hooks/settings into “role/project” `.claude/` directories in `docs/design/plan-infrastructure-redesign.md:136`. That leaves the most important boundary unpinned: which config belongs to the role, which belongs to the project, and how they compose. If role hooks live in every project, you have duplicated plumbing and adding a role no longer costs just a role definition; if they live only in roles, you still need an explicit registration/bootstrap path from projects. Section 4’s composability claim in `docs/design/vision-personal-ai-infrastructure.md:97` and `docs/design/vision-personal-ai-infrastructure.md:226` needs a cleaner contract here.

Medium severity: the plan never defines precedence rules for overlapping instructions. The three-tier model in `docs/design/plan-infrastructure-redesign.md:53` is a good decomposition, but it does not say what wins when role instructions, project-root instructions, and deeper path-scoped instructions disagree, or even what exact ordering each harness must present. Because Claude, Gemini, and OpenCode inject at different points, you can otherwise get three different “correct” behaviors from the same role and project. This is a classic boundary bug, and the plan should make the merge contract explicit before implementation.

Medium severity: the ordering of Phase A and Phase B is wrong unless the manifest is deliberately partial. The manifest example in `docs/design/plan-infrastructure-redesign.md:65` advertises skills like `/launch-model`, `/artifact-store`, `/query-database`, and `/write-design-doc`, but those are only created later in Phase B at `docs/design/plan-infrastructure-redesign.md:123`. Since the dependency section says A and B can run in parallel in `docs/design/plan-infrastructure-redesign.md:169`, there is a period where the system would tell agents capabilities exist when they do not. Either Phase A should only inject currently available skills, or the manifest should land after B.

Medium severity: Phase D is under-specified and partly cuts against the vision’s “view, don’t warehouse” principle. The plan says to define a shared data location and move durable documents out of `thoughts/` in `docs/design/plan-infrastructure-redesign.md:143`, but the vision says data should generally stay where it is most useful in `docs/design/vision-personal-ai-infrastructure.md:206`, and the current requirements/spec already assume in-place indexing of existing files via the filesystem connector in `docs/design/requirements-personal-ai-infrastructure.md:106`, `docs/design/requirements-personal-ai-infrastructure.md:379`, and `docs/design/spec-personal-ai-infrastructure.md:1852`. The plan needs a sharper rule for what is actually being migrated versus merely indexed, how lineage/search survive the move, and how this relates to the artifact store instead of creating a second home for the same material.

Medium severity: “version control as audit trail” is asserted but not planned. The plan elevates git to the safety model in `docs/design/plan-infrastructure-redesign.md:82`, and the vision makes that the answer to write authority in `docs/design/vision-personal-ai-infrastructure.md:173`. But there is no implementation work covering repo boundaries, what gets tracked together, how generated artifacts are committed, or how secrets and machine-local config stay out of history. With permissive shared access, this is not a nice-to-have; it is part of the control plane.

Medium severity: the plan broadens access without introducing even minimal scoping primitives. `docs/design/plan-infrastructure-redesign.md:146` says all roles should access shared data, and the multi-model setup in `docs/design/plan-infrastructure-redesign.md:44` increases the number of execution paths touching that data. The vision is permissive, but it still says discoverability and content access are different, and that security/boundaries must be designed from the start in `docs/design/vision-personal-ai-infrastructure.md:107`, `docs/design/vision-personal-ai-infrastructure.md:222`, and `docs/design/vision-personal-ai-infrastructure.md:246`. I would not block the whole effort on a full policy, but the plan should at least define the basic primitive: globally discoverable metadata versus session-authorized content.

Low severity: a few concrete tasks are simply missing from the phase list. The role directory structure described in `docs/design/plan-infrastructure-redesign.md:20` is foundational, but there is no explicit step to create the role directories, thin wrappers, templates, or migration path from the current state. Likewise `session-archive` is introduced in `docs/design/plan-infrastructure-redesign.md:99` but never scheduled. Those are easy fixes, but they matter in a plan that is otherwise trying to be executable.

So the overall judgment is: sound direction, incomplete execution plan. I think this is buildable by one human directing AI agents if the scope is narrowed to “role bootstrap + hook injection + config cleanup” first. As written, the hardest parts are not the tested hook mechanisms; they are the unpinned boundaries: session identity, role-memory ownership, config composition, data migration, and access scoping.

Beyond the review targets, I read `docs/design/requirements-personal-ai-infrastructure.md` and `docs/design/spec-personal-ai-infrastructure.md` to check how the plan fits the existing continuity, storage, and migration assumptions.


### kimi-k2.5 (complete)

I'll review this infrastructure redesign plan. Let me start by reading the design documents.
Now let me explore the codebase to understand the current implementation state and identify any gaps in the plan.
Now let me check the existing roles directory structure and any existing hooks:

