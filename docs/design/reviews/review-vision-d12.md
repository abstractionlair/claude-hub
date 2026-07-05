# Review: 2026-03-19 18:05 UTC

**Prompt:** Review this vision document (Draft 12) focusing on the new material. The document governs the design of a personal AI infrastructure. Evaluate internal consistency, completeness, clarity, and appropriate scope for a vision-level document. Be critical — the social cost of being critical is zero. Flag anything that feels like it belongs in requirements or spec rather than vision.
**Files:** docs/design/vision-personal-ai-infrastructure.md
**Job ID:** d8e08e37-17f4-4299-8bc0-b7a89a4e32ae

## Synthesis

## Synthesis: Vision Document Draft 12 Reviews

Three reviewers examined the new material in Draft 12 — Section 4 (role/project/harness architecture), Principles 12–14, Enabling Patterns, and the context rot addition. The reviews converge strongly on two high-severity issues and diverge mainly on how much prescription is acceptable in a vision doc.

### High-Confidence Consensus (all three reviewers)

**Shared-by-default vs. security is the biggest internal tension.** All three flag the conflict between Principle 14's "shared-by-default" stance and the document's own security claims (Principle 10's "access control designed in from the start," the open question about whether a code-review agent should see email). Gemini calls it high severity and proposes distinguishing infrastructure/capabilities (shared) from sensitive data (opt-in). GPT-5.4 calls it high severity and wants discoverability separated from content access. Kimi flags it as a clarity problem — the scope mechanism is missing. The diagnosis is the same: shared-by-default is too aggressive for a system spanning personal finance and communications, and the vision needs to draw a sharper line somewhere between "everything visible" and "everything locked down." **Severity: High.**

**The document is too prescriptive in places.** All three identify specific passages where the vision crosses into requirements/spec territory. The common examples: naming specific harnesses (Claude Code, Gemini CLI, OpenCode), prescribing timers for persistent agents, and specifying shell scripts and HTTP APIs as the abstraction surface. GPT-5.4 and Gemini both note that the discovery principle ("brief triggers in context, full content on demand") dictates mechanism rather than stating the goal. Kimi adds that the incremental summarization mechanism in the context rot section repeats what's already in the requirements. The reviewers agree: state invariants and goals at the vision level, let downstream documents choose mechanism. **Severity: Medium across individual instances, but the pattern is pervasive enough to warrant a systematic pass.**

**Context rot is excellent.** All three single it out as one of the strongest additions. Gemini praises the shift from mechanical token counting to qualitative attention dilution. GPT-5.4 calls it "one of the most useful upgrades in the whole document." Kimi prefers it over the prior "degradation" language. No reservations from anyone.

**The role/project/harness conceptual split is right.** All three endorse the organizing framework. Gemini calls it "a superb mental model." GPT-5.4 says it gives the doc a better frame than earlier drafts. Kimi says it's "the right abstraction." The disagreements are about articulation, not direction.

### Consensus Between Two Reviewers

**The memory/continuity model is ambiguous (GPT-5.4 + Kimi, high severity).** GPT-5.4 warns that "the role's accumulated context should be the same" can be read as one shared continuity stream across unrelated projects — exactly the context pollution the document warns against. Kimi identifies a concrete manifestation: if window files live in `thoughts/windows/{harness}/` per the spec but the vision says roles span projects, where do role-specific window files actually go? Both want an explicit rule distinguishing durable role memory from project-local working context. Gemini doesn't raise this, likely because it deliberately avoided reading downstream documents. **Severity: High** — this will directly mislead implementation.

**Persistent agents need authority and coordination rules (GPT-5.4 + Kimi, medium severity).** GPT-5.4 notes the absence of write authority, provenance, and conflict handling for concurrent agents mutating shared artifacts. Kimi asks what "direct communication" between agents means and whether roles can query each other's continuity. Gemini doesn't address this, focusing more on the timer mechanism than the governance model. **Severity: Medium.**

**Role boundaries vs. personal/professional boundaries (Gemini + GPT-5.4, medium severity).** Gemini asks whether roles are the mechanism enforcing the personal/professional split or whether they cross that boundary. GPT-5.4 frames it more broadly as needing explicit scoping rules. Kimi doesn't raise this specific point. **Severity: Medium.**

### Unique Findings (single reviewer)

**Kimi: Role lifecycle is missing.** What happens when a role is created — empty continuity? Default skills? Can roles be cloned, templated, or archived? No other reviewer raises initialization or lifecycle. Worth addressing at the vision level even if details are deferred. **Severity: Medium.**

**Kimi: Skills pattern acknowledged as formalization.** Principle 13 reads like it's inventing a new discovery pattern, but it's actually formalizing an existing one. A small wording fix avoids confusion. **Severity: Low.**

**Kimi: "Marginal cost" is ambiguous in Principle 12.** Engineering effort? Runtime overhead? Cognitive load? The phrase needs one clarifying word. **Severity: Low.**

**Kimi: Principle 6's compounding language is muddled.** "Compounding applies to capabilities, not just knowledge" conflates know-how and know-that. **Severity: Low.**

**GPT-5.4: Duplication across new sections.** AI-native artifacts appear in both Section 2 and Section 4. Persistent agents are introduced in Section 4 and restated in Enabling Patterns. Orthogonality appears twice. The material feels appended rather than integrated. **Severity: Low**, but signals a structural editing pass is needed.

**GPT-5.4: Implementation status doesn't belong in the vision body.** The current-state notes near the end should live in a roadmap or document header. **Severity: Low.**

**GPT-5.4: Discovery layer needs conceptual sharpening.** What exactly is indexed — capabilities, resources, artifacts, agents? How is this different from semantic retrieval over the artifact store? Directionally good but too slogany to drive requirements. **Severity: Medium.**

**Gemini: Context rot + shared-by-default + discoverable form a consistent triad.** A positive-only observation — the massive data pool created by shared-by-default is anticipated by context rot and bridged by Principle 13. No other reviewer calls out this structural coherence explicitly.

### Contradictions

There are no hard contradictions between the reviewers. The closest is a difference in emphasis: **Gemini treats the prescriptiveness issue as the primary concern** (multiple findings, with specific alternatives offered), while **GPT-5.4 treats the memory model ambiguity as the dominant problem** and spends less time on prescriptiveness. **Kimi splits attention more evenly** across both. This reflects their review approaches — Gemini read only the vision document (enforcing standalone evaluation), GPT-5.4 and Kimi read downstream docs and could therefore spot cross-document inconsistencies.

### Recommended Priority for Draft 13

1. **Reconcile shared-by-default with security** — all three agree, high severity. One short paragraph distinguishing discoverability from access would resolve it.
2. **Clarify the memory model** — two reviewers, high severity. State explicitly what is role memory vs. project context vs. session state, and how they compose.
3. **Add write authority / coordination intent** — two reviewers, medium severity. Even a single sentence about governed writes vs. open reads would help.
4. **Systematic prescriptiveness pass** — all three agree the pattern exists, medium severity in aggregate. Replace mechanisms with invariants throughout.
5. **Role lifecycle and discovery sharpening** — single-reviewer findings but worth addressing in a cleanup pass.

**Models responded:** gemini (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### gemini (complete)

I have completed my review of `docs/design/vision-personal-ai-infrastructure.md`, focusing specifically on the new material introduced in Draft 12 (Section 4, Principles 12-14, Enabling Patterns, and the context rot discussion). 

*Note: I did not read any additional files beyond the target document. A vision document serves as the foundational North Star for a project and must be capable of standing on its own without relying on downstream specifications or external process files.*

Here is my review, organized by the criteria you specified.

### 1. Scope: Bleeding into Requirements and Spec
The most frequent issue with the new additions is that they cross the line from *vision* (the "what" and "why") into *specification* (the "how"). A vision document should avoid prescribing implementation details, as doing so makes the vision brittle to technical shifts.

*   **Finding: Directories as a foundational boundary**
    *   *Location:* Section 4 ("A project... lives in its own directory", "the role directory is a natural place") and Principle 14 ("belongs exclusively in a role directory").
    *   *Severity:* Moderate.
    *   *Critique:* The vision should define the conceptual boundaries of "isolated project environments" and "role-specific configurations." Tying these concepts explicitly to filesystem directories belongs in an architecture or spec document.
*   **Finding: Prescribing a timer for persistent agents**
    *   *Location:* Section 4 ("Persistent agents own ongoing work").
    *   *Severity:* Moderate.
    *   *Critique:* The text states: "The implementation is mechanical — a timer launches a harness..." By explicitly dictating a timer, the vision unnecessarily excludes event-driven architectures (e.g., an agent that wakes up when a file changes or an email arrives). Focus on the *continuous, unattended nature* of the work, not the `cron` job that triggers it.
*   **Finding: Naming specific harnesses and implementations**
    *   *Location:* Section 4 ("Multi-harness by design").
    *   *Severity:* Low.
    *   *Critique:* Listing "Claude Code, Gemini CLI, OpenCode" and "shell scripts, HTTP APIs" risks rapidly dating the document. Stick to generic categories like "interactive CLI harnesses, editor integrations, and autonomous runners."
*   **Finding: Mandating the "Skills pattern" for discovery**
    *   *Location:* Principle 13 ("Discoverable, not preloaded").
    *   *Severity:* Low.
    *   *Critique:* Saying "This is the Skills pattern generalized to everything: brief triggers in context, full content on match" dictates the exact mechanism of discovery. A better vision-level framing would simply be the goal: "Maintain a lightweight index in context, with full content loaded only when relevant."

### 2. Internal Consistency
*   **Finding: "Shared-by-default" clashes with Security Principles**
    *   *Location:* Principle 14 vs. Principle 10.
    *   *Severity:* High.
    *   *Critique:* There is a major tension here. Principle 10 warns that the system accesses highly sensitive data ("financial, communications") and that "access control... need[s] to be designed in from the start." However, the new Principle 14 mandates a "Shared-by-default" model where data is "accessible to any agent unless there's a reason to restrict." If I spin up a quick, experimental agent for web scraping, a shared-by-default model implies it automatically has read access to my tax spreadsheets and private emails. The vision needs to reconcile this—likely by stating that *infrastructure and capabilities* (skills, tools, docs) are shared-by-default, but *sensitive data sources* are opt-in and scoped strictly by role.
*   **Finding: Context Rot vs. Shared-by-default**
    *   *Location:* Section 2 ("Context rot") vs Principle 13 & 14.
    *   *Severity:* None (Positive observation).
    *   *Critique:* The new shared-by-default model creates a massive pool of global data, which could easily overwhelm models. However, the new "context rot" discussion perfectly anticipates this risk, and Principle 13 ("Discoverable, not preloaded") bridges the gap perfectly. This triad of concepts is highly consistent and well-designed.

### 3. Completeness
*   **Finding: Role boundaries vs. Personal/Professional boundaries**
    *   *Location:* Section 4 ("Roles, not tools, are the organizing unit") vs. Open Questions.
    *   *Severity:* Moderate.
    *   *Critique:* Section 4 establishes "Roles" as the core identity. However, the Open Questions section rightly points out that "Personal and professional are separate environments." The vision currently leaves a gap: are roles the mechanism used to enforce this boundary? Does a "researcher" role span both my personal and professional life, or do I need separate roles for each environment? Clarifying how roles interact with environment boundaries would make the architecture section much stronger.

### 4. Clarity
*   **Finding: The definition of Context Rot**
    *   *Location:* Section 2 ("The Context Problem").
    *   *Severity:* None (Positive observation).
    *   *Critique:* The explanation of context rot—"the gradual accumulation of low-value material that dilutes attention on what matters"—is exceptionally clear. It successfully shifts the framing of context limits from a purely mechanical token count to a qualitative measure of attention dilution. This makes the subsequent arguments for active conservation highly compelling.
*   **Finding: Decoupling Identity, Work, and Tools**
    *   *Location:* Section 4.
    *   *Severity:* None (Positive observation).
    *   *Critique:* The conceptual framework that separates *who I am* (role), *what I'm working on* (project), and *what tool I'm using* (harness) provides a superb mental model. It makes a complex, multi-agent ecosystem very easy to reason about.


### gpt-5.4 (complete)

I read `docs/design/vision-personal-ai-infrastructure.md`. For context, I also read selected sections of `docs/design/requirements-personal-ai-infrastructure.md:216`, `docs/design/requirements-personal-ai-infrastructure.md:328`, `docs/design/spec-personal-ai-infrastructure.md:285`, `docs/design/spec-personal-ai-infrastructure.md:998`, and `docs/design/spec-personal-ai-infrastructure.md:1678`. I also searched `docs/design/*.md` for the new terms, but did not read other files in depth.

The new direction is strong. Section 4 gives the doc a better organizing frame than the earlier drafts had, and the context-rot addition in Section 2 is one of the most useful upgrades in the whole document. The problems are mostly around integration: the new architecture introduces role-wide continuity, shared-by-default visibility, and persistent multi-agent work, but the vision does not yet state the scoping and authority rules that make those ideas cohere.

High severity: the role/project/harness split is conceptually right, but the memory model is still ambiguous enough to mislead implementation. At `docs/design/vision-personal-ai-infrastructure.md:89`, `docs/design/vision-personal-ai-infrastructure.md:91`, `docs/design/vision-personal-ai-infrastructure.md:93`, `docs/design/vision-personal-ai-infrastructure.md:95`, and `docs/design/vision-personal-ai-infrastructure.md:99`, the doc says roles are the enduring identity, projects are separate, harnesses are interchangeable, and persistent agents run from the role directory. But `docs/design/vision-personal-ai-infrastructure.md:19` and `docs/design/vision-personal-ai-infrastructure.md:53` make context scarcity and context rot the central constraint, while `docs/design/vision-personal-ai-infrastructure.md:218` says content should be discoverable rather than preloaded. Those ideas are compatible, but the draft never says so explicitly. Right now "the role's accumulated context ... should be the same" can be read as one shared continuity stream across unrelated projects, which would be exactly the kind of context pollution the earlier sections warn about. The vision needs one crisp rule here: what is durable role memory, what is project-local working context, and how role instructions, project instructions, and harness config compose at runtime.

High severity: `shared-by-default` is not yet reconciled with the document's own security and boundary claims. `docs/design/vision-personal-ai-infrastructure.md:103` and `docs/design/vision-personal-ai-infrastructure.md:220` make visibility the default for data, documentation, skills, tools, and prompts. But `docs/design/vision-personal-ai-infrastructure.md:212` says access boundaries must be designed in from the start, `docs/design/vision-personal-ai-infrastructure.md:236` asks whether a code-review agent should see email at all, and `docs/design/vision-personal-ai-infrastructure.md:71` already establishes that some review contexts should exclude opinion-carrying material. That is more than an open question; it is a core architectural tension. For a system spanning personal finance, communications, and code, "shared by default" is too broad unless the doc sharply distinguishes discoverability from access, or metadata visibility from raw-content visibility. As written, the principle reads too aggressive for the rest of the vision.

Medium severity: persistent agents are introduced without an accompanying model of write authority, provenance, or conflict handling. `docs/design/vision-personal-ai-infrastructure.md:97`, `docs/design/vision-personal-ai-infrastructure.md:99`, `docs/design/vision-personal-ai-infrastructure.md:101`, and `docs/design/vision-personal-ai-infrastructure.md:167` treat scheduled agents and multi-agent pipelines as first-class. That is plausible, but the draft only really covers continuity and discoverability. It does not say who is allowed to mutate shared artifacts, how concurrent agents avoid stomping on one another, or how a human audits autonomous changes after the fact. In a shared-data, persistent-agent architecture, those are not spec nits; they are part of the core vision of trustworthiness.

Medium severity: the discovery layer is still too slogan-like to drive downstream requirements. `docs/design/vision-personal-ai-infrastructure.md:218` is directionally good, and `docs/design/vision-personal-ai-infrastructure.md:226` correctly spots index-scale as a problem, but the concept is not yet separated cleanly from the existing search/artifact-store story. What exactly is being indexed here: capabilities, resources, artifacts, agents, all of the above? What minimum metadata makes something "discoverable"? How is this different from semantic retrieval over the artifact store? The draft does not need schema, but it does need one paragraph of conceptual sharpening or implementers will build overlapping registries.

Medium severity: parts of the new material are already too prescriptive for a vision doc. `docs/design/vision-personal-ai-infrastructure.md:95` names shell scripts, HTTP APIs, and file conventions as the preferred abstraction surface. `docs/design/vision-personal-ai-infrastructure.md:99` defines persistence in terms of a timer launching a harness in the role directory. `docs/design/vision-personal-ai-infrastructure.md:218` prescribes a lightweight index that is always in context with full content loaded on demand. Those are reasonable design bets, but they are requirements/spec material, not vision. The vision should state invariants like harness-agnosticism, continuity across invocations, and on-demand loading, then let lower documents choose mechanism.

Low severity: there is some duplication in the new additions. The idea that AI-native artifacts need their own home appears in both `docs/design/vision-personal-ai-infrastructure.md:31` and `docs/design/vision-personal-ai-infrastructure.md:109`. Persistent agents are introduced in Section 4 at `docs/design/vision-personal-ai-infrastructure.md:97` and then restated in Enabling Patterns at `docs/design/vision-personal-ai-infrastructure.md:165`. Orthogonality/composability also appears twice at `docs/design/vision-personal-ai-infrastructure.md:159` and `docs/design/vision-personal-ai-infrastructure.md:216`. None of that is contradictory, but it does make the new material feel appended rather than fully integrated.

Low severity: `docs/design/vision-personal-ai-infrastructure.md:246` mixes current implementation status into the governing vision. That is useful project context, but it belongs more naturally in a roadmap, changelog, or document header note than in the enduring body of the vision.

If I were tightening this draft, I would add one short subsection that makes three distinctions explicit: role memory vs project working context, discoverability vs content access, and shared reads vs governed writes. That would make the new architecture feel internally complete rather than merely promising.


### kimi-k2.5 (complete)

## Review: Vision Document Draft 12

**Files read for context:** requirements (Draft 12), spec (Draft 11), architecture.md, context-management-patterns.md, shared-context.md

---

### Overall Assessment

Draft 12 successfully introduces the role-based architecture, persistent agents, multi-harness support, and discovery patterns. The new material is conceptually sound and addresses real gaps in prior drafts. However, there are internal inconsistencies, scope bleed, and clarity issues that need attention.

---

### 1. Internal Consistency Issues

**Critical: Role/Project/Harness Terminology Conflict**

The vision introduces three key concepts in Section 4:
- **Role**: "a persona with a job description" (researcher, sysadmin, etc.)
- **Project**: "a codebase, a paper, an ongoing investigation"
- **Harness**: "Claude Code, Gemini CLI, OpenCode"

But the spec (Section 2.3) defines window files as living in `thoughts/windows/{harness}/`, and the vision says "the role directory is a natural place for harness-specific config to coexist" (lines 95-96). This creates ambiguity:

- Is the role directory `thoughts/roles/{role}/` or `thoughts/windows/{harness}/`?  
- The vision says roles span projects, but where do role-specific window files live?
- If a researcher role uses both Claude Code and Gemini CLI on the same project, do they have separate window chains or a unified one?

**Severity: High** — This terminology conflict will propagate into implementation confusion.

**Suggested fix:** Explicitly define the directory structure in the vision. Something like:
```
thoughts/roles/{role}/          # Role identity, config, hooks
thoughts/roles/{role}/windows/  # Role's continuity chain
thoughts/projects/{project}/    # Project artifacts, docs
```

**Medium: "Discoverable, not preloaded" vs. Existing Skills Pattern**

Principle 13 (lines 218-219) states: "The system should know what's available... brief triggers in context, full content on demand. This is the Skills pattern generalized to everything."

But the Skills pattern is already documented elsewhere (referenced in hooks, used in practice). The vision should acknowledge this is formalizing an existing pattern, not inventing a new one. Otherwise it reads like Principle 13 conflicts with the existing skills system.

---

### 2. Scope Issues — Too Prescriptive for Vision

**Section 4: "Multi-harness by design" (lines 95-96)**

The vision states: "Shared components should be harness-agnostic (shell scripts, HTTP APIs, file conventions) with thin harness-specific wrappers where needed."

This is *implementation guidance*, not vision. It prescribes the solution (shell scripts, HTTP APIs) rather than the requirement (components work across harnesses). The vision should state the requirement; the spec should specify shell scripts vs. HTTP APIs.

**Section 4: "Persistent agents own ongoing work" (lines 97-102)**

Lines 99-100 describe the implementation: "A persistent agent is a role on a schedule. The implementation is mechanical — a timer launches a harness in the agent's role directory."

This is too specific for vision. "Role on a schedule" is a reasonable vision-level concept. "Timer launches a harness" belongs in requirements/spec.

**Section 2: "Context rot" discussion (lines 53)**

Lines 53-56 describe the incremental summarization mechanism in detail ("forking a summarization task every N tokens..."). This mechanism is already specified in requirements R3.2 and spec Section 7.2. Repeating it in vision adds length without adding clarity. The vision should state the problem (context quality degrades with accumulation) and the principle (conserve proactively), but the mechanism belongs downstream.

**Suggested fix:** Move implementation details to requirements/spec. Keep vision focused on *what* and *why*, not *how*.

---

### 3. Completeness Issues

**Missing: How roles acquire context about projects**

Section 4 says "A role works *on* projects but is not *part of* any single project." But it doesn't explain how a role acquires project context:

- Does the role query the project directory when starting work?
- Is project context loaded into the role's continuity chain?
- How does the role know which projects exist?

The current design implies project context is discoverable, but the mechanism isn't specified.

**Missing: Role initialization and lifecycle**

What happens when a new role is created?
- Does it start with empty continuity?
- Are there default skills/prompts?
- Can roles be cloned or templated?

Similarly, can roles be archived? If a "prediction markets researcher" role becomes inactive, does it retain its continuity for future reference?

**Missing: Discovery layer specifics**

Principle 13 ("Discoverable, not preloaded") and the Open Questions section (lines 226-227) acknowledge the discovery/registry layer is underspecified. This is appropriate for vision, but the vision should at least enumerate *what* needs to be discoverable:

- Skills ✓ (mentioned in R5)
- Data sources ✓ (R7)
- Agents/roles ? (not explicitly mentioned)
- Tools ? (implied but not stated)
- Documentation ✓ (implied)

The vision should explicitly state that agents, tools, and documentation are discoverable resources.

**Missing: Cross-role coordination**

Section 4 says persistent agents "should be expandable into multi-agent processes" with agents coordinating "through shared data and, when needed, direct communication." But it doesn't specify:
- What "direct communication" means (messages? shared window files?)
- Whether roles can query other roles' continuity
- How role-specific permissions affect cross-role access

This is partially acknowledged in Open Questions (lines 227-228), but the vision should at least state the intent: "Roles coordinate through a shared message bus" or "Roles are isolated unless explicitly bridged."

---

### 4. Clarity Issues

**Vague: "Shared-by-default, scoped-by-exception" (lines 103-104)**

Principle 14 states: "Only role-specific configuration (identity, permissions, hooks) belongs exclusively in the role directory."

This is clear at the principle level, but what's missing is the *scope mechanism*. How does an agent know what's shared vs. role-specific? Is there a permissions layer? A search path? The vision should hint at the mechanism even if details are deferred.

**Ambiguous: "The marginal cost of the next agent should approach zero" (lines 216-217)**

Principle 12 uses this phrase, but it's unclear what "marginal cost" means here:
- Engineering effort to add a new role?
- Runtime overhead per role?
- Cognitive overhead of managing roles?

Given the context (orthogonal components), it likely means engineering effort, but this should be explicit.

**Awkward: "Compounding applies to capabilities, not just knowledge" (lines 204-205)**

Principle 6 mixes two ideas: (1) captured context compounds, (2) patterns escalate into tools. These are related but distinct. The phrasing "Compounding applies to capabilities, not just knowledge" is confusing because capabilities *are* a form of knowledge (know-how vs know-that). Better: "The system compounds both knowledge (what we know) and capabilities (what we can do)."

---

### 5. Positive Findings

**Strong: The Architecture Problem framing (Section 4)**

Section 4 successfully elevates organizational principles to vision level. The role/project/harness separation is the right abstraction. The "persistent agents as first-class citizens" concept (line 167) elegantly extends the continuity system.

**Strong: Context rot concept (lines 52-53)**

The "context rot" framing is clearer than the prior "degradation" language. It captures the qualitative decline before hitting capacity limits.

**Strong: Updated Enabling Patterns**

The "Persistent Agents as First-Class Citizens" pattern (lines 165-167) correctly ties the new architecture to existing infrastructure.

---

### Summary of Recommendations

| Issue | Severity | Location | Action |
|-------|----------|----------|--------|
| Role/harness directory ambiguity | High | Section 4, lines 89-96 | Define directory structure explicitly |
| Implementation details in vision | Medium | Section 4, lines 95-100; Section 2, lines 53-56 | Move to requirements/spec |
| Missing role lifecycle | Medium | Section 4 | Add paragraph on role creation/archiving |
| Missing discovery enumeration | Low | Principle 13 | Explicitly list discoverable resources |
| "Marginal cost" ambiguity | Low | Principle 12 | Clarify what cost is being minimized |
| Skills pattern contradiction | Low | Principle 13 | Acknowledge as formalization, not invention |

The document is sound at the conceptual level but needs tightening to avoid implementation confusion downstream.

