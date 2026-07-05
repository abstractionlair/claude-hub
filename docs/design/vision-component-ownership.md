# Vision: Component Ownership and Agent-Mediated Coordination

*Draft 1 — April 1, 2026*

*Derives from: vision-personal-ai-infrastructure.md (Draft 14), ontology.md*

*Addresses open question from the parent vision: "Cross-agent coordination. When multiple persistent agents own parts of a larger process, how do they coordinate?"*

## The Problem

The system has grown organically. Code that changes together doesn't live together. An agent assigned to work on multi-model reviews can't see the review engine — it's inside a monolith alongside unrelated relay code, artifact storage, delegation machinery, and a work graph. An agent assigned to infrastructure work doesn't know about review scripts two directories away. The project boundaries the human drew early on no longer match the work the system actually does.

This is a specific instance of a general failure: when organizational boundaries don't match development lifecycles, agents work with incomplete pictures. The human compensates by knowing where things are and manually bridging the gaps — which defeats the purpose of having agents that maintain their own context.

Three concrete symptoms:

**Monolith accumulation.** Claude-hub started as an MCP server and absorbed six unrelated concerns: message relay, artifact storage, multi-model reviews, delegation, work graph, and session continuity. These have different development cadences, different reasons to change, and different people (human or agent) working on them. But they share a directory, a CLAUDE.md, and a single conceptual identity. An agent pointed at claude-hub to fix a review bug has to wade through relay code, OAuth flows, and embedding pipelines to find what it needs.

**Scattered concerns.** The review system spans two projects — the engine is in claude-hub, the reviewer roles and model-specific guidance are in dev-workflow. Neither project alone contains everything needed to work on reviews. An agent working in either project has a partial view.

**Silent cross-project breakage.** Five projects share PostgreSQL tables. When one project changes a table that another reads, nothing coordinates the change. The agent making the change doesn't know about the downstream consumer. The downstream consumer doesn't know the table changed. The human discovers the breakage later, if they're lucky.

These aren't just organizational inconveniences. They directly undermine the parent vision's promise that agents can do meaningful work without the human spelling everything out. An agent that can't see its full domain *can't* do meaningful work — it will reinvent what already exists, break what it can't see, or ask the human to bridge gaps that should be structural.

## What We Want

**Components organized by development lifecycle, each owned by a semi-persistent agent that knows its domain deeply and can coordinate with peer agents when changes cross boundaries.**

This is two ideas that reinforce each other:

### Modular components that match how work happens

When someone says "work on reviews," everything needed for that work — the dispatch engine, the model registry, the synthesis logic, the reviewer roles, the grading system, the relevant DB tables — should be in one place. Not because it's tidier, but because the agent doing the work needs to see it all.

The organizing principle is development lifecycle: things that change together live together. This is correlated with but not identical to service boundaries, domain boundaries, or agent task scope. The test is practical — when a change is needed, does the project contain everything the change touches?

The components don't need to be services. Most are libraries — importable packages with clean interfaces. The MCP server remains a single process that imports from them and exposes their functionality as tools. The reorganization is about development boundaries, not deployment boundaries.

### Agents that own components and coordinate across them

Each component has an agent that develops deep, persistent context about it — its interfaces, its design decisions, its schema, its consumers. The agent's context isn't rebuilt from scratch each session; it's recovered from the component's own documentation, memory, and state. The component is well-documented enough that recovery is fast and reliable.

When a change crosses component boundaries — a schema migration, an interface change, a new dependency — the owning agent identifies affected peers and initiates coordination. The agents negotiate the change: the upstream agent proposes, downstream agents assess impact, and both sides implement their portions. The human is pulled in for decisions that need judgment, not for bridging gaps that should be structural.

This transforms the current model — one agent, one session, manually pointed at the right project by the human — into something where the human talks to the component agent most relevant to what they want, and that agent handles coordination.

## Why This Matters Now

The parent vision (Draft 14) described the goal: any AI tool gets coherent context, persistent agents handle ongoing responsibilities, multi-model collaboration produces better results. That vision assumed the infrastructure would be organized well enough for agents to operate independently within their domains.

That assumption has broken down. The system is large enough that project boundaries matter — agents can't just "see everything" — but the boundaries were drawn before the system's concerns were clear. Reorganizing now, before more agents and more automation are layered on top, avoids compounding the problem.

The existing infrastructure already supports much of what's needed. The relay handles inter-agent messaging. The delegation system provides structured handoffs. Window files give session continuity. The dev-workflow protocol provides review gates. What's missing is the organizational structure that makes these capabilities useful for component-level coordination rather than just human-directed sessions.

## How Components Relate

Components are not isolated. They share infrastructure and consume each other's interfaces. The key relationships:

**Shared database, owned tables.** Each component owns and migrates its own tables. Some tables are consumed by other components — these are public interfaces with the same expectations as any API: documented, versioned, changed with coordination. The table owner is responsible for compatibility; the consumer is responsible for declaring its dependency.

**Import relationships.** The MCP server imports from component packages and exposes their functionality as tools. Components may also import from each other — the review engine stores results in the artifact store, for instance. These imports are explicit, directional dependencies.

**Protocol relationships.** Some components interact through shared conventions rather than code imports. The dev-workflow protocol defines how specs, reviews, and implementations flow. Multiple components participate in that protocol without importing each other directly.

Each component maintains a manifest of what it exposes (tables, functions, interfaces) and what it consumes from other components. This makes the dependency graph explicit and machine-readable — an agent can consult it to know who to coordinate with before making a change.

## Principles

1. **Development lifecycle is the organizing axis.** Things that change together live together. Not domain, not deployment boundary, not historical accident. When you need to change X, the project should contain everything X touches.

2. **Components are libraries, not services.** Most components are importable packages, not separate processes. The MCP server is the integration point — a thin router that imports component packages and registers their tools. Deployment stays simple; development boundaries are clean.

3. **Ownership means context, not control.** An agent "owns" a component by maintaining deep context about it — knowing its interfaces, its design decisions, its consumers. Ownership is recoverable: any fresh session can become the owner by reading the component's state. The quality of each component's documentation is load-bearing.

4. **Coordination is negotiation, not notification.** When a change crosses boundaries, the owning agent doesn't just announce the change — it proposes, the affected agent assesses, and they negotiate. The human decides when agents disagree or when judgment is needed. The goal is that cross-cutting changes are coordinated before they happen, not discovered after they break.

5. **Dependency manifests are contracts.** Each component declares what it exposes and what it consumes. Changes to exposed interfaces require coordination with consumers. This is the same principle as API versioning, applied to the internal structure of a personal system.

6. **Start with the worst seams.** Not everything needs to be reorganized at once. Start with the components that cause the most confusion — where agents most often have incomplete views or where cross-project breakage is most common. Let experience guide further decomposition.

7. **The human's role shifts, not shrinks.** Instead of manually bridging gaps between projects, the human directs component agents and makes judgment calls on cross-cutting decisions. The coordination mechanics are handled by the agents; the strategic decisions remain human.

## Open Questions

**Agent persistence model.** How persistent are component agents? Full long-running processes are expensive. Spin-up-on-demand with context recovery from project state is cheaper but requires excellent documentation. Somewhere in between — periodic scheduled sessions that maintain continuity — might be the sweet spot. What's the right default?

**Coordination protocol.** What's the medium for inter-agent coordination? Conversational (through the relay, real-time), structured proposals (RFC-like documents, asynchronous), or some combination? Structured proposals have a paper trail and work across time zones; conversations are faster and handle nuance better. The dev-workflow protocol already has review gates — should cross-component coordination use the same machinery?

**Scope of the MCP router.** If the MCP server is a thin router that imports from component packages, how thin can it be? Can tool registration be automated from component manifests, or does each component's integration require hand-written glue? What happens when two components need to compose — e.g., the review engine wants to store in the artifact store?

**Where does the router live?** Claude-hub today is the MCP server and much more. If the "much more" is extracted into component packages, does claude-hub become just the router? Does it keep auth, relay, and session management as its own concern? What's the right residual scope?

**Component granularity.** Some concerns are clearly distinct (review engine vs. prediction market data). Others are judgment calls (is delegation part of the relay or its own component? are observations part of continuity or a separate concern?). What's the right granularity, and how do we know if we've split too fine or too coarse?

**Bootstrap problem.** Reorganizing requires moving code, updating imports, splitting migrations, and rewriting documentation — all while the system is in active use. What's the migration path that doesn't break everything at once? Can components be extracted incrementally, one at a time, with the monolith shrinking gradually?

**Discovery across components.** The parent vision emphasizes discoverability. With more components, the discovery problem gets harder — an agent needs to know what other components exist and what they offer. The infrastructure manifest handles this today at a high level. Does it scale, or does it need to become something richer?

**Authority and trust.** Can an agent modify another component's code as part of coordination, or does it only propose changes that the owning agent implements? The latter is cleaner but slower. The former requires trust in cross-component changes. What's the right default for a personal system?

## What This Document Is For

This is a vision for how the system's components should be organized and how agents should coordinate across them. It extends the parent vision (personal AI infrastructure) with a specific architectural proposal for component ownership.

If we proceed, the next step is requirements: which components to extract, what their boundaries are, what the dependency graph looks like, and what the coordination protocol needs to support. That document should be concrete enough to evaluate against the current system and specific enough to implement from.
