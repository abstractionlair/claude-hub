# Vision: Personal AI Infrastructure

*Draft 14 — March 22, 2026*

*Implementation status: Requirements (Draft 13) and spec (Draft 12) cover Phases 1-8. Phases 1-5 are implemented. This draft incorporates the formalized ontology (role, project, service, agent, task, resource, session), corrects the role-as-persona framing to role-as-job-description, and reflects the infrastructure restructuring (project extraction, git-based persistence, SDLC standardization).*

## The Problem

AI output depends on context. What the AI knows about your work, your decisions, your constraints, the people you work with — that's what determines whether you get a generic answer or a useful one.

Right now, that context is fragmented. It's in Claude's memory, in email, in spreadsheets, in documents, in your head. Every time you open a new conversation, you re-explain. Every time you switch tools, you lose continuity. Every time an agent tries to help, it's missing the picture.

Meanwhile, your data already lives in many places for good reasons. Investment data belongs in spreadsheets where you can model and chart it. Email belongs in email where you can read and compose it naturally. Documents belong in document tools. The answer is not to centralize everything into a single store — that just creates a new silo. The answer is to build an infrastructure layer that can see across all of it.

But having context available is only the first problem. The second problem is getting the right context into the right model at the right time — and then managing the finite context window as work proceeds. A model with access to everything you know but no ability to find what's relevant is no better than one that starts from zero. And a model that loads everything relevant at the start but can't manage its context budget as work unfolds will degrade before it finishes.

## What We Want

**A personal AI infrastructure that gives any AI tool — any model, any harness, any autonomous agent — a coherent view of your world, the ability to find and assemble the right context for a given task, and the ability to manage that context effectively as work proceeds.**

Context scarcity is the fundamental constraint that shapes the entire system. If context windows were infinite and performance didn't degrade with length, most of the problems described here would dissolve. But context is finite, expensive, and degrades with overuse. Every design decision in this document is ultimately a context management decision: how to get the right information into a limited window at the right time, and how to keep that window healthy as work proceeds.

This breaks down into three connected problems and a premise about the human's role in the system.

### 1. The Data Problem: A unified view across data that lives everywhere

Data should stay where it's most useful in its native form. Investments in spreadsheets. Emails in email. Code in repositories. Documents in document tools. What's missing is a layer that can query across all of it — that gives an agent (or you) the ability to ask "what do I know about X?" and get answers drawn from everywhere.

This is a view, not a warehouse. It indexes and makes queryable. It doesn't demand that you change how you store things or interact with them outside of AI contexts.

The same pattern appears in tooling, not just data. Capabilities that exist but can't be found or assembled when needed are functionally absent. A system with extensive features that most users never discover has a view problem, not a capability problem.

Some data is generated specifically for AI consumption — session notes, decision logs, captured thoughts. That data does need a home, and a semantically searchable one. But it's a complement to your existing data, not a replacement for it.

The hard part is connectors. Each data source — email, spreadsheets, code repositories, documents — is its own integration problem with its own authentication, API, and update cadence. This is where similar projects often get stuck: not in the vision but in the grind of building and maintaining reliable access to heterogeneous sources. The design needs to account for this being an incremental, source-by-source effort rather than a single integration step.

### 2. The Context Problem: Getting the right information into the model

Having a unified view of all your data doesn't help if the model can't find what it needs for the task at hand. Context windows are finite. You can't dump everything in and hope.

Empirically, comprehension dominates generation. In a recent major project (86 sessions, 2,508 tool calls), 50% of all tool calls were reading or searching — not writing. The AI spent most of its effort on understanding, not producing. This held across every phase: design sessions were read-heavy (understanding the existing codebase), implementation sessions were read-heavy (consulting design docs), even test-writing was read-heavy (reading the implementation to test it). The edit/write fraction never dominated.

This means the context problem isn't a supporting concern — it's the primary work. The system needs to:

**Retrieve** — find what's relevant out of everything available. This is more than keyword search. When you're working on a project plan, the system should surface past decisions about similar projects, relevant constraints, lessons from what didn't work before — connections that wouldn't occur to you to search for explicitly.

There's a spectrum here. At the simple end: search for what's explicitly requested. At the ambitious end: proactively surface connections the user didn't think to ask about. The simple end is well-understood engineering. The ambitious end is research. The system should start simple and grow toward proactive retrieval as the knowledge base and the tooling mature — but the architecture shouldn't preclude it.

**Assemble** — compose a context window from retrieved pieces. What goes in, what gets summarized, what gets left out, in what order. Different tasks need different context compositions. A code review needs different context than a strategic planning session, even when they're about the same project.

**Conserve** — manage context as work proceeds. You start with a finite budget and spend it with every exchange. The conversation itself generates new information — decisions made, code written, problems identified — that competes for space with the context you started with.

In practice, conservation means: recognizing when earlier context has been consumed and can be released (a question that's been answered, a file that's been read), preserving what still matters (the overall goal, key constraints, decisions made so far), and making room for what's being generated (new code, new problems, evolving understanding). The risk is that without active management, the model's output quality degrades exactly when the work gets hardest — toward the end, when the context window is fullest and the remaining problems are the ones that weren't easy.

Conservation is not just about avoiding the hard limit — it's about maintaining quality throughout. A context window that's technically within capacity but full of stale exploration, resolved questions, and irrelevant earlier work degrades output quality well before the window is full. Context rot — the gradual accumulation of low-value material that dilutes attention on what matters — is a more practical threat than hitting the capacity ceiling. Active conservation means compacting or clearing proactively at natural milestones, not waiting until the system forces it.

The proven approach to conservation across long-running work is incremental summarization — periodically capturing a narrative snapshot of the current state while details are still fresh in context, rather than trying to summarize everything at the end when early details have already been pushed out of effective attention. In practice, this means forking a summarization task every N tokens of work, producing a compressed but accurate record that the next context window can load to resume seamlessly. The alternative — either very long sessions that hit context limits and lose information, or the human manually re-briefing the AI at each restart — is more expensive and less reliable. In one project, this mechanism turned 23 separate interactive sessions into what functioned as a single continuous project.

These three don't have clean boundaries. Retrieval quality affects what's available to assemble. Assembly choices determine how fast you burn context. Conservation strategies feed back into what you need to retrieve next. The system needs to handle them together, not as independent problems.

### 3. The Quality Problem: Getting the best output from models

Given that you have the right context in the right model, how do you maximize the quality of what comes out?

**Multiple models produce better results than any single model.** Different models bring genuinely different analytical lenses. Claude thinks differently from GPT-5 thinks differently from Gemini. The best answers often come from having multiple models review, critique, and build on each other's work. In practice — four models collaborating on a research framework self-organized into natural specializations and produced solutions none would have reached alone.

**Multi-model review has a diminishing returns curve.** The first 2-3 reviewers per artifact catch most of the bugs. In a recent project that ran ~80 reviews across 10+ models, consensus findings converged within 3 models — when 3+ models agreed on a finding, it was always real. The long tail of additional reviewers provided data about model capabilities but diminishing returns for bug-finding. The infrastructure should make multi-model review easy to invoke, but the workflow should be calibrated to where the value actually is: a handful of diverse perspectives per artifact, not exhaustive coverage.

**The best model changes over time.** The frontier shifts. A year ago the best coding model was different from today's. Six months from now it'll shift again. Betting everything on one provider's ecosystem is a bad long-term position. The infrastructure should make it trivially easy to adopt a new model — plug it in and it has your full context on day one.

**How models review matters as much as which models review.** A model reviewing code is an agent, not a text processor. The reviewer that can explore the codebase — read adjacent files, check how a function is called, look at test coverage, understand conventions from surrounding code — will find things that the one reading a bundled excerpt won't. The difference is the same as between asking a colleague to "look at this diff" versus "look at this branch" — one sees a fragment, the other sees the fragment in context and can follow threads.

This means two things for how reviews are dispatched. First, the reviewer needs intent — not just "find bugs in this code" but "this code is supposed to implement these requirements, with these acceptance criteria; verify it does and find bugs." Pairing the review with the spec gives the reviewer the ability to catch semantic errors (the code works but doesn't do what was asked) in addition to mechanical ones (null checks, race conditions). Second, clean-room isolation is about opinions, not facts. The reviewer should not read process preferences, style guides, or design rationale — these create anchoring bias where the reviewer echoes back assumptions instead of challenging them. But the reviewer should read the spec, API docs, existing code patterns, and tests — these are the evaluative context needed to review well. The boundary is: share the spec and codebase (required context for a good review), withhold process docs and editorial preferences (sources of anchoring bias).

**Structured workflows beat ad hoc prompting.** A specific pattern has proven effective in practice: progressive refinement from intent to implementation, with multi-model review at each transition.

```
Vision → [review] → Requirements → [review] → Spec → [review] → Implementation → [review]
```

Each stage produces a durable artifact. Each review pulls in multiple perspectives. The progression naturally constrains scope — you can't hand-wave in a spec that three models are about to critique. The artifacts persist and inform future projects.

This has been tested on a substantial project: a full API with 9 backend files, 16 frontend files, and 304 tests, built over 6 working days. The design phase consumed an entire day producing documents with zero shipped code. That cost was directly repaid by the pace of implementation — when coding started, each module was essentially translating the detailed spec into code. One-pass generation of large, structurally sound artifacts (16 frontend files in 14 minutes, 158 tests in 20 minutes) was possible because the specs existed first. The generation was translation, not invention.

This pattern works for software, but it's the same underlying structure for any work that moves from fuzzy intent to concrete output: strategic planning, research, writing, decision-making.

### 4. The Architecture Problem: Organizing agents, roles, and shared infrastructure

The first three problems — data, context, quality — describe what the system needs to do. This fourth problem describes how the system itself should be organized to do it. As the number of models, harnesses, and use cases grows, the infrastructure needs a coherent organizing principle.

**Roles are job descriptions, not personas.** A role defines responsibilities, scope, and constraints for interactive sessions — workbench (general-purpose work), sysadmin (VPS management), mcp-server (responding to incoming requests). The model brings its own identity; the role tells it what job it's doing. The same role can be filled by different models (Claude, Gemini, GPT) running in different harnesses (Claude Code, Gemini CLI, OpenCode). The model and harness are interchangeable execution substrates.

This decouples three things that are easily conflated: *what job I'm doing* (the role), *what I'm working on* (the project), and *what tool I'm using* (the harness). A workbench session doing research on prediction markets using Claude Code is a different session from a workbench session writing code in claude-hub using Gemini CLI — but the role's accumulated context, its continuity chain, its access to shared infrastructure, is the same.

**Projects are separate from roles.** A project is an umbrella for related work — it may encompass code, services, agents, research, and data. It lives in its own directory with its own conventions and instructions. A role works *on* projects but is not *part of* any single project. Over the course of its life, the workbench role might work on prediction markets, then claude-hub, then a literature review. The role's continuity spans all of these. "Do you remember when we worked on project Y?" is answerable from the role's history.

**Multi-harness by design.** The infrastructure that sessions depend on — continuity, semantic search, the artifact store, review dispatch, skills — cannot be tied to a single harness's conventions. Shared components should be harness-agnostic, with thin harness-specific adapters where needed. Each major harness supports project-level configuration, and the role directory holds harness-specific situating files (CLAUDE.md, GEMINI.md, AGENTS.md) that explain how instructions are layered.

**Persistent agents own ongoing work.** Some responsibilities are continuous, not one-shot: data collection that runs daily, system maintenance that needs regular attention, eval scouting that monitors a changing landscape. These are poorly served by humans remembering to ask for them or by stateless scheduled jobs that start from zero each time. Humans are unreliable schedulers — tasks fall through the cracks, context is lost between manual invocations, and the overhead of re-briefing discourages delegation.

An agent is distinct from a role — roles apply to interactive sessions; agents are autonomous work loops. But the same continuity infrastructure serves both. An agent reads its window files, picks up where it left off, does its work, captures its state. The infrastructure that gives interactive sessions continuity across compaction gives persistent agents continuity across invocations.

**Tasks complement agents.** Not everything needs autonomous judgment. A weekly data pipeline or a daily backup is a scheduled task — it runs and completes without model-driven decision-making. The distinction matters: agents use models for judgment at runtime; tasks are deterministic. Both are scheduled, both may be persistent, but they have different operational profiles and failure modes.

These persistent agents should be expandable into multi-agent processes. Several agents might own different parts of a larger pipeline — one scouts, one evaluates, one ingests — coordinating through shared data and, when needed, direct communication. Each agent maintains its own continuity while participating in a larger collaborative process.

**Shared-by-default, scoped-by-exception.** Most data, documentation, skills, and tools should be accessible to any session in any role. Skills for code review, prompts for writing vision docs, documentation about system databases — these are useful regardless of which role is active. Only role-specific configuration (job description, permissions, hooks) belongs exclusively in the role directory. The default is visibility, not isolation.

Shared-by-default applies to *discoverability* — any agent can find out what exists and query for what's relevant. Access to content can be scoped per role where needed. For a personal infrastructure, the initial posture is permissive: all roles can read all shared data, and restrictions are added consciously when a reason emerges (e.g., a role interacting with external services might have narrower access). The infrastructure should support scoping, but doesn't need to enforce it everywhere from the start. What it does need from the start is an audit trail — see "Version Control as Audit Trail" below.

**Three kinds of memory.** A session produces context at three levels that should not be conflated:

- **Session state** is the working context within a single invocation — the conversation, the files being edited, the current task. It's managed by the harness (compaction, clearing) and is ephemeral by nature.
- **Project context** is knowledge specific to a codebase, paper, or investigation — its architecture, conventions, open issues. It lives with the project (in its directory, its CLAUDE.md, its own git history) and is relevant to any role working on that project.
- **Role memory** is the accumulated experience of a role across projects and sessions — what it was last working on, what it learned, cross-project patterns it noticed. It lives with the role and provides continuity across projects. "Do you remember when we worked on project Y?" draws on role memory, not project context.

The window file system serves role memory. Project context lives in the project. Session state is managed by the harness. Keeping these distinct prevents context pollution — a role switching from one project to another should not carry stale project-specific details in its continuity chain.

**Roles have a lifecycle.** A role is created with a job description and configuration; it begins with empty continuity. Over time it accumulates memory through window files. Roles can become inactive — their continuity is retained for future reference or reactivation, not deleted. The infrastructure should make role creation lightweight (a directory with instructions and config) so that spinning up a new role for an experiment carries minimal overhead.

**Work is classified on two orthogonal axes.** Sessions, whether interactive or autonomous, are tagged by *workstream* (what you're doing: development, research, or operations) and *component* (what you're working on: codebase, service, agent, task, dataset, or document). These tags in window file frontmatter enable cross-cutting queries — "show me all research sessions across any project" or "find sessions where we operated the collector services" — without requiring rigid directory structures.

### Generated Artifacts Need a Home

The system doesn't just read — it produces. Design documents, code, reviews, session notes, decision logs, analysis results. These generated artifacts are a significant and growing fraction of the data in the system, and they need somewhere to live.

Some generated artifacts belong in existing systems — code gets committed to repositories, analysis results might update a spreadsheet. But much of what the AI produces is new data that has no natural pre-existing home: the vision doc for a project, the review findings from three models, the narrative summary that carries context across sessions. This is the "AI-native" data that the view layer indexes but doesn't originate from an external source.

The infrastructure should provide a native store for this AI-generated content — a scratchpad that is persistent, searchable, and semantically indexed. This is not a warehouse for all data (the view principle still applies), but a home specifically for artifacts that the AI workflow produces and that future work needs to retrieve. Without this, generated artifacts scatter across ad hoc locations and become unfindable, undermining the compounding effect that makes the whole system valuable.

### The Human's Role: Judgment and Direction

The infrastructure augments human judgment — it doesn't replace it and isn't trying to. The human's comparative advantage is deciding what to build, how to evaluate it, and which problems matter. The AI's comparative advantage is volume and consistency — generating many files coherently, running many reviews, maintaining detailed state across sessions.

In practice, this means the human contributes: business framing (what the work is for, who needs it, why it matters), design principles (tie-breaking rules, quality criteria, the workflow itself), review dispatch (what to review, with which models, how aggressively), and judgment on findings (which review findings are real vs. noise, which bugs are severe, what to prioritize). The human writes no code, runs no commands, does no mechanical work. The contribution is entirely judgment and direction.

Neither side is redundant. The same AI without direction would not produce the same artifacts. The same human without the AI's capacity for volume, consistency, and sustained context would produce them much more slowly, if at all. The infrastructure should be designed to amplify this division of labor — making it easy for the human to direct and judge, and easy for the AI to execute and maintain state.

## How These Problems Interact

These four problems aren't orthogonal. They're deeply entangled:

- The data layer determines what's available for retrieval. If email isn't indexed, the model can't find the decision you made over email last week.
- Retrieval quality determines what context each model gets. In a multi-model review, different reviewers might benefit from different slices of context.
- Context conservation strategies change depending on whether you're doing single-model deep work (manage one window carefully) or multi-model review (each reviewer gets a fresh window, parallelism is cheap).
- The artifacts produced by structured workflows become data that feeds back into the data layer — future projects retrieve past specs, past decisions, past reviews.
- The architecture determines what's discoverable and by whom. A skill that exists but isn't indexed is functionally absent. An agent that owns a data pipeline but can't be found by other agents is an isolated silo.
- The role/project separation determines how continuity works. A role that spans projects accumulates cross-project insight. A project-bound agent loses that context every time the user moves on.
- The human's judgment is load-bearing at every transition. The infrastructure handles the mechanics — retrieval, assembly, conservation, dispatch, agent coordination — but the human decides what matters.

The system works as a whole or not at all. A perfect data layer with bad retrieval is useless. Perfect retrieval with no context management means quality degrades mid-task. Great context management with only one model leaves performance on the table. A clean architecture with no discovery layer means capabilities exist but can't be found. And all of it without human judgment to direct it produces volume without value.

## Enabling Patterns

### Custom Tooling Over Generic

Generic AI tools are designed for the average user. They can't know your workflow, your preferences, your specific combination of professional and personal contexts. A custom-built infrastructure, optimized for how you actually work, will always outperform off-the-shelf solutions for the person who builds it. This is the same reason developers build their own dotfiles and toolchains — the compound returns on personalized infrastructure are enormous.

### Persistent Context That Compounds

Every interaction with the system should make the next interaction better. When you make a decision, it's captured. When you learn something, it's recorded. When you try something that doesn't work, that's noted too. Over months, this builds into a knowledge base that no amount of re-explaining in a chat window could replicate.

This isn't just memory — it's compound interest on thinking. The value of captured context grows super-linearly as connections between pieces emerge.

The mechanism matters: context continuity is infrastructure, not overhead. The cost is real — maintaining narrative state across sessions requires ongoing effort. But the alternative, losing context every few hours and manually rebuilding it, is more expensive and less reliable. The system should treat continuity maintenance as a first-class concern, not an afterthought.

But knowledge compounding is only half the story. The system should also compound *capabilities* — when a pattern recurs across sessions, the infrastructure should be able to promote it from an observation to a durable tool: a reusable skill, an automated hook, a codified rule. The system doesn't just accumulate better data over time; it accumulates better processes. A debugging sequence that works three times should become a one-command skill on the fourth. An event-triggered behavior that's manually invoked repeatedly should become an automatic hook. This is the difference between a system that remembers more and a system that gets better at getting better.

For this to work well, usage feedback matters. Not just "what was stored" but "what proved useful when retrieved." When an agent retrieves a past artifact and it helps with the current task — or doesn't — that signal should feed back into the system's recommendations. Over time, this builds a knowledge base weighted by retrieval usefulness — the system can answer "what knowledge has proven valuable for problems like this?" rather than just "what was stored about similar topics?" The feedback loop between storage, retrieval, and usage-weighted quality is what turns linear accumulation into genuine compounding.

### The Agent Interface Is Additive

The agent layer does not replace existing interfaces. You don't stop reading your own email because agents can read it. You don't stop using spreadsheets because agents can query the data. You don't start dictating emails to agents instead of writing them yourself.

The agent interface is a new lens on information you already have. Over time, as agent capabilities improve and trust develops, more tasks might shift to agent-mediated workflows. But that should happen naturally, not because the system forced it by making agent access the only access.

### Version Control as Audit Trail

Almost every file the system produces — window files, documents, role configurations, shared data, review results — should be managed in version control. This provides history, diffs, attribution, and rollback for free. When any agent in any role writes or modifies a file, that change is a commit with provenance.

This is the simplest viable answer to the write authority question. In a personal infrastructure with permissive access, preventing writes is less important than being able to see what changed, when, by which agent, and to undo it if needed. Version control makes writes auditable and reversible without requiring a complex permissions system. Restrictions can be layered on later if experience shows they're needed.

### Boundary Bugs Are the Hard Part

Individual components tend to be moderate complexity. The hard problems are at the seams between systems — between tools that share mutable state, between storage layers with different conventions, between protocols that make different assumptions. This is the general software engineering observation that integration is harder than implementation, and it holds even when the AI is doing both.

The infrastructure should be designed with boundaries as a first-class concern: clean interfaces between components, explicit contracts at integration points, and the expectation that the most subtle bugs will live where systems meet.

## What This Enables

When this works:

- You open any AI tool — Claude, Gemini, GPT, whatever's next — and it already knows your context. Not because that tool has memory — because your infrastructure provides context to any tool that asks.
- You try a new model and it's immediately useful. No ramp-up period, no re-explaining your world. Plug it in; it has your full context on day one.
- You say "let's work on prediction markets" and the agent picks up where you left off — regardless of which model or harness you last used for that work.
- The system finds relevant context you wouldn't have thought to provide — past decisions, related constraints, lessons from similar work.
- Context is managed actively as work proceeds, not just loaded at the start and hoped for the best. The system compacts proactively rather than degrading gracefully.
- A handful of diverse models review your work at each stage, catching things you wouldn't catch alone and catching different things from each other.
- You make a decision and it's captured once, queryable forever, from anywhere, by any agent.
- Agents working on your behalf have the context they need to do meaningful work without you spelling everything out. They know what skills are available, what data sources exist, what other agents are doing.
- Persistent agents handle ongoing responsibilities — data collection, system maintenance, monitoring — maintaining continuity across invocations without human re-briefing.
- A new capability — a skill, a data source, a prompt template — becomes available to every agent automatically once registered, without per-agent configuration.
- You still use spreadsheets for spreadsheet things and email for email things. Nothing changed about how you interact with your data — you just added a new way of accessing it.
- Your role is judgment and direction. The system handles the volume, consistency, and state management.

## Principles

1. **Multi-model, multi-harness by default.** Never assume one model or one tool is best for everything. Build for pluggability across both dimensions. Use different models for different tasks. Use different harnesses for different workflows. The best model today is not the best model tomorrow, and the best harness for interactive work is not the best for autonomous agents. But calibrate effort to where the value is — a few diverse perspectives per artifact, not exhaustive coverage.

2. **View, don't warehouse.** Data stays where it's useful. The infrastructure indexes, queries, and connects — it doesn't demand migration.

3. **Model-forward, not code-forward.** Models do understanding; code does mechanics. When data flows from one model to another — or from a model to a human — don't insert code that parses, restructures, or interprets the output. The consumer can read it directly. Write code for invocation, file management, parallel dispatch, timeout handling, and job tracking — the mechanical scaffolding. The self-similarity test: if a human would just read the output and ask a model to synthesize, the system should work the same way. Model capability at these comprehension tasks is the fastest-improving variable in the system — infrastructure that rides this trend gets better for free; infrastructure that fights it accumulates debt.

4. **Context is the bottleneck.** Retrieval, assembly, and conservation of context matter as much as model selection. Comprehension dominates generation. Invest in getting the right context to the right model at the right time. Context windows are a resource to be managed, not a reservoir to be filled — quality degrades with accumulation, not just at the limit.

5. **Custom beats generic.** The compound returns on infrastructure tailored to your specific workflow and preferences outweigh the convenience of off-the-shelf tools.

6. **Compounding over features.** Every design decision should ask: does this compound? Captured context compounds. Dashboards don't. Prioritize the flywheel. The system should compound both knowledge (what we know) and capabilities (what we can do) — recurring patterns should escalate into durable tools (skills, hooks, rules), and usage feedback should weight future retrieval so the system surfaces what has proven valuable.

7. **Progressive refinement.** Vision → requirements → spec → implementation. Each transition narrows scope and increases precision. The day spent on design documents is repaid by the pace of implementation. Ship the smallest useful thing, then iterate.

8. **Additive, not replacement.** The agent interface adds capability without removing existing interfaces. Don't force everything through a conversational bottleneck.

9. **Boring foundations, pragmatic ambition.** Standard protocols and well-understood technology for the base layers. Experimental and ambitious at the higher layers where iteration is cheap and failure is recoverable. The distinction matters — proactive context surfacing is a goal, not a foundation.

10. **Security proportional to exposure.** The infrastructure sees across multiple personal data sources — financial, communications, documents, notes. Access control, credential management, and data boundaries need to be designed in from the start, not bolted on. The more sources the system can see, the higher the stakes if it's compromised or if an agent acts on context it shouldn't have.

11. **Design for boundaries.** Integration is harder than implementation. The most subtle bugs live where systems meet. Clean interfaces, explicit contracts, and the expectation that boundary problems will dominate difficulty.

12. **Orthogonal and composable.** Infrastructure components — continuity, search, review, publication — should be independent and usable by any agent in any role. Adding a new role or agent should cost a role definition, not new plumbing. The engineering effort to stand up the next agent should approach zero — it inherits all shared infrastructure by default.

13. **Discoverable, not preloaded.** The system should know what's available — skills, data sources, documentation, agents, tools — and make it findable on demand. A lightweight index of what exists stays in context cheaply; full content loads only when relevant. This formalizes and generalizes an existing pattern (skills already work this way) to all shared resources.

14. **Shared-by-default.** Data, documentation, skills, tools, and prompts are accessible to any agent unless there's a reason to restrict. Only role-specific configuration (identity, permissions, hooks) belongs exclusively in a role directory. The default is visibility, not isolation.

## Open Questions

**Architecture:**
- ~~**Window files across harnesses in a shared role.**~~ *Resolved:* window files are role-scoped and shared across harnesses. Different models writing to the same role's windows is conceptually correct (the role's memory is the role's memory) and implemented.
- **The discovery/registry layer.** What's the right mechanism for agents to discover available resources — skills, data sources, documentation, other agents and roles, tools, prompt templates? At what scale does even the lightweight index become expensive, and does the registry itself need semantic search? *Partially addressed:* the infrastructure manifest provides a lightweight capabilities index (~25 tokens) plus environment facts, injected via hooks. Whether this scales or needs to become queryable is an open question.
- **Cross-agent coordination.** When multiple persistent agents own parts of a larger process, how do they coordinate? Shared data handles loose coupling. Direct communication handles tighter coupling. What's the right default?

**Context management:**
- **How context conservation should work in practice.** What gets released, what gets summarized, what gets kept verbatim. Whether these decisions should be automatic, user-guided, or model-guided. Empirically, context rot (quality degradation from accumulation) is a more immediate threat than capacity limits, especially as context windows grow.
- **Context decay and retention.** Not all context ages well. The system needs some mechanism for context to lose weight over time or be explicitly superseded — but aggressive forgetting undermines the compounding effect. The right default is probably "everything is retrievable, but recency and explicit supersession affect ranking."
- **Proactive retrieval.** The spectrum from explicit search to proactively surfacing connections the user didn't think to ask about. Where to start, how to grow.

**Boundaries and trust:**
- **Agent autonomy.** How much should agents be able to do without checking in? This is a trust question that evolves over time, not a design question with a fixed answer.
- **Access boundaries.** When an agent is working on a code review, should it see your email? The infrastructure needs to support scoped access, but the scoping policy will be context-dependent.
- **Personal and professional are separate environments.** This infrastructure is personal. Professional data stays in professional systems. This is a conscious boundary, not a gap to be closed.

**Practical:**
- **Inference cost management.** The system should be cost-aware for marginal uses beyond subscription-covered models: choosing the cheapest model that meets the need, avoiding redundant calls, and making the cost/value tradeoff visible rather than hidden.
- **Packaging for public use.** The right public artifact is reference documentation and examples that an LLM can use to set up and maintain a similar system, not an installable package. What's the right scope and format?

## What This Document Is For

This is the governing vision for a spec-driven development cycle. The downstream artifacts — requirements, spec, implementation — derive from this document and should be updated when the vision evolves. The vision stays wide. Everything after it gets progressively narrower.
