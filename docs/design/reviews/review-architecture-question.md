# Review: 2026-03-21 15:55 UTC

**Prompt:** # Architecture Question: Multi-Model Agent Infrastructure

## Context

We are building a personal AI infrastructure on a single VPS (Debian, 4GB RAM). The governing vision is in the attached file `docs/design/vision-personal-ai-infrastructure.md` (Draft 13). Please read it — it's the foundation for this question.

The core goal: **any model should be able to operate in any role on any project, with full access to role instructions, project instructions (including deep subdirectory instructions), and shared infrastructure (artifact store, semantic search, review engine, continuity system).**

## The Key Insight We Need Help With

The goal is **multi-model**, not multi-harness. We want Claude, Gemini, GPT, and other models to all have equal access to the system. Harnesses (Claude Code, Gemini CLI, OpenCode) are just the current way to access these models affordably:

- **Claude Opus/Sonnet**: Anthropic subscription → must use Claude Code
- **Gemini 3.1 Pro**: Google subscription → must use Gemini CLI
- **GPT-5.4, GPT-5.3 Codex**: OpenCode Zen (pay-per-use, cheaper than direct API)
- **Open models (Kimi K2.5, GLM-5, etc.)**: OpenCode Go

If all frontier models were accessible through one harness at subscription prices, we'd use one harness. The harness diversity is a pricing artifact, not a design goal.

## What We've Built So Far

- **Role-based architecture**: Roles (researcher, sysadmin, workbench, mcp-server) define *who* the agent is. Projects define *what* it's working on. The harness is just the execution substrate.
- **Role launcher script** (`~/bin/role`): Launches any harness in a role, composing role instructions with project context.
- **DRY instruction structure**: Each role has thin harness-specific wrappers (CLAUDE.md, GEMINI.md, AGENTS.md) that import a shared `shared.md` with harness-agnostic instructions.
- **Shared infrastructure**: Artifact store (Postgres + pgvector), semantic search, multi-model review engine, window file continuity system, mechanical logging — all accessible from any session.
- **MCP server**: FastAPI server with OAuth, providing tool access to remote clients.

## The Problem We're Stuck On

Each harness has a different mechanism for loading instruction files, and they aren't equivalent:

**Claude Code** (best support):
- Instruction file: `CLAUDE.md`
- Loads eagerly from launch directory ancestors
- JIT loads from subdirectories when files are read there (ancestor walk does NOT stop at git roots)
- `--add-dir` flag allows loading instructions from a separate directory tree
- `@import` syntax for file inclusion
- **Can compose role + project instructions from two independent directory trees**

**Gemini CLI** (good but over-eager):
- Instruction file: `GEMINI.md`
- `--include-directories` adds directories to workspace
- Eagerly discovers ALL GEMINI.md files recursively under launch dir AND included dirs
- `@import` syntax works
- **Loads everything, including instruction files from unrelated projects and other roles**

**OpenCode** (limited):
- Instruction file: `AGENTS.md` > `CLAUDE.md` > `CONTEXT.md` (first found wins)
- No `--add-dir` equivalent
- No `@import` syntax
- Has `instructions` config field for loading additional files
- **Cannot compose instructions from two independent directory trees**

We want an agent in any role to work on any project and get:
1. Role instructions (who you are, how you behave)
2. Project root instructions (what this codebase is, conventions)
3. Deep subdirectory instructions (per-module rules, path-specific guidelines) — loaded on demand as the agent navigates the codebase

Claude Code achieves all three via `--add-dir` + JIT loading. The other harnesses can't.

### Approaches We've Tried and Their Limitations

1. **Launch from $HOME, --add-dir role**: Works for Claude Code only. Gemini/OpenCode lack --add-dir.

2. **Launch from role directory**: Role instructions load, but projects aren't subdirectories so their instructions don't JIT-load.

3. **Generate instruction files on the fly**: A build step that composites role + project instructions into a CLAUDE.md. Works for the top-level file, but can't replicate JIT loading of deep subdirectory instructions (a large codebase may have instruction files in every module directory, loaded on demand as the agent navigates).

4. **Temp directory with symlinks**: Claude Code can't follow symlinks without --dangerously-skip-permissions.

5. **Temp directory with --add-dir $HOME**: Files are readable but subdirectories of --add-dir paths don't get JIT instruction loading.

## What We're Asking

Given the vision (attached) and these constraints, what's the right architecture? Specifically:

1. **Is there an approach we haven't considered** for getting consistent instruction loading across harnesses? We may be too anchored on each harness's native instruction mechanism.

2. **Should we accept asymmetry** — Claude Code gets the full experience, other harnesses get a degraded but functional version? If so, what's the minimum viable experience for non-Claude harnesses?

3. **Are there alternative mechanisms** we should explore? For example:
   - A SessionStart hook that injects all instructions via system message
   - An MCP server that serves instructions on demand
   - A custom thin harness/wrapper that provides uniform behavior
   - Using the harness's native agent definition systems differently
   - Something else entirely

4. **Is the multi-harness approach even right** given that it's driven by pricing, not design? Should we instead:
   - Invest in a single harness and accept higher costs for non-subscription models?
   - Build a minimal custom harness that wraps all model APIs uniformly?
   - Use MCP as the universal interface instead of harness-native features?

5. **What should we prioritize?** We have limited engineering bandwidth (one human directing AI agents). What's the highest-value next step that makes the most models useful with the least harness-specific complexity?

We value concrete, actionable suggestions over theoretical frameworks. Tell us what to build, not what to think about.
**Files:** docs/design/vision-personal-ai-infrastructure.md
**Job ID:** 529ce361-9c51-44ac-9fba-c7149da3e57c

## Synthesis

## Synthesis: Vision Document (Draft 13) + Multi-Model Instruction Loading Architecture

Five reviewers examined Draft 13 of the vision document against the multi-model architecture question. The reviews show strong convergence on the core diagnosis and significant divergence on one key mechanism.

### High-Confidence Consensus

**The vision doesn't acknowledge instruction-loading asymmetry as a first-class problem.** All five reviewers flag this independently, most at high severity. The vision promises "thin harness-specific adapters where needed" and "multi-harness by design" without confronting the structural reality that Claude Code's JIT subdirectory instruction loading has no equivalent in any other current harness. Claude-Sonnet puts it most directly: "the vision sets up a false equivalence that will mislead downstream documents into designing for a uniformity that doesn't exist." GPT-5.4 calls this the "highest severity" issue — the vision assumes harness interchangeability while implicitly depending on harness-native instruction semantics. Draft 14 needs to name this gap explicitly.

**Multi-model is the design goal; multi-harness is a pricing constraint.** Four of five reviewers (Claude, Claude-Sonnet, GPT-5.4, Kimi) converge on this distinction. The vision's Principle 1 currently elevates both to equal status, but the architecture question is right that harness diversity exists because each model's cheapest access path runs through a different tool. GPT-5.4 recommends rewriting the principle toward "multi-model by default; harnesses are replaceable adapters." Claude-Sonnet notes this distinction matters because it changes what gets built — multi-model says make it easy to swap models; multi-harness says make every harness first-class. The first is correct; the second leads to engineering cost proportional to harness count. Gemini partially dissents, arguing harness diversity is also a necessary hedge against the frontier shifting, but still agrees you shouldn't chase feature parity across them.

**Accept asymmetry with Claude Code as the primary harness.** Universal agreement. Claude Code gets the full automatic experience. Other harnesses get a functional but degraded version. The disagreement is only about what "degraded but functional" looks like (see contradictions below).

**The vision's own Principle 13 ("discoverable, not preloaded") is the right architecture for this problem, but the document doesn't apply it to instructions.** Claude, Claude-Sonnet, and GPT-5.4 all independently note this. The principle describes exactly the mechanism needed — a lightweight index stays cheap in context, full content loads on demand — but the vision never connects it to the instruction-loading problem. The connection is latent but unstated. This is the most consistently identified gap in the document.

**The three-kinds-of-memory model is missing a category.** Claude and Claude-Sonnet both flag that session state, project context, and role memory don't account for instruction files — meta-level directives about how to behave. These straddle project context and role memory without fitting cleanly into either. Medium severity; naming this sharpens the design space.

**Don't build a full custom harness.** Claude and Gemini state this explicitly. The engineering cost is prohibitive for a solo operation, and existing harnesses are improving rapidly. Investment is better spent on the shared infrastructure layer.

### The Central Disagreement: MCP Instruction Tool Viability

This is the most important divergence across the five reviews and deserves careful weighing.

**Four reviewers recommend building an MCP `get_instructions` tool** as the primary cross-harness solution. Claude calls it "the highest-value finding in this review" — a single endpoint on the existing MCP server that, given a path and role, returns composed instructions. Claude-Sonnet calls it "probably the most actionable path forward." GPT-5.4 proposes "one shared instruction resolver accessible via MCP and local CLI." Kimi recommends a `get_directory_context` MCP tool for explicit context retrieval. The logic is consistent: MCP converts instruction loading from "how do harnesses discover files?" (unanswerable uniformly) to "how do agents call a tool?" (answerable uniformly).

**Gemini is the sole dissenter, calling MCP-based instruction serving a "false solution."** The argument: "Models are terrible at proactively asking 'Do you have specific instructions for this folder?' before taking action. JIT loading only works when the harness intercepts the action and forces the context in." Gemini proposes semantic search as the alternative — index subdirectory instructions into shared search so they surface naturally when agents search for context.

This is the review's most consequential disagreement. The four-reviewer consensus has the stronger argument: frontier models do follow concrete meta-instructions ("call this tool when you navigate to a new directory") reliably, especially when the instruction is an explicit action rather than a vague guideline. Claude acknowledges the behavioral gap but argues it's narrower than it looks, since JIT loading also has failure modes (the model never reads a file in that directory). That said, Gemini's concern is not baseless — there is a real difference between a harness forcing context in and a model remembering to request it. The pragmatic resolution is probably to build the MCP tool (low cost, high potential leverage) and empirically test whether models actually call it unprompted. If they don't, Gemini's semantic-search alternative becomes the fallback.

### Unique Findings Worth Noting

**Gemini identified a concrete bug in `~/bin/role`** that no other reviewer caught. The script launches Gemini with `--include-directories "$HOME"`, which causes Gemini CLI to eagerly traverse the entire home directory and load every `GEMINI.md` from every unrelated project. The fix is to reverse the inclusion direction: launch from the project directory with `--include-directories "$ROLE_DIR"`. This is marked critical severity by Gemini and is the most immediately actionable finding across all five reviews — a one-line fix that eliminates the "Gemini loads everything" problem described in the architecture question.

**GPT-5.4 uniquely flags the need for explicit merge/precedence semantics** when role, project root, and subdirectory instructions overlap. Today Claude Code provides implicit ordering through its ancestor walk. A harness-independent system needs explicit rules: role bootstrap first, then project root, then nearest path-scoped instructions, with clear override semantics. Without this, two harnesses can both be "correct" and still behave differently on the same task. Medium severity.

**GPT-5.4 also notes that downstream documents (requirements Draft 12, spec Draft 11) are stale** relative to Draft 13 of the vision. There are no acceptance criteria for cross-harness instruction parity, no spec for a resolver, no test fixtures for nested path rules. This is the highest-value gap to close next for implementation readiness. Medium severity.

**GPT-5.4 proposes a conformance fixture** — a test repository with nested instructions that verifies all harnesses resolve the same instruction stack for the same `(role, project, path)` tuple. No other reviewer suggests a concrete testing approach.

**Kimi points out the role directory structure described in the architecture doesn't exist yet** — there's no `roles/` directory, no `shared.md` files, no `PROJECT.md` convention. This is an implementation gap rather than a vision gap, but it's worth noting that the architecture question discusses mechanisms for structures that haven't been built. Medium severity.

### A Second Disagreement: Session-Start Injection

Three reviewers address session-start injection with incompatible conclusions. Claude proposes a "briefing" (not full instructions) injected at session start as a complementary mechanism alongside the MCP tool. Claude-Sonnet calls it the "fastest path to acceptable cross-harness instruction loading" and estimates it gives non-Claude harnesses 90% of the value. Gemini explicitly calls it an "anti-pattern" — injecting all deep subdirectory instructions upfront causes exactly the context rot the vision warns against.

The disagreement partially dissolves on closer reading: Claude and Claude-Sonnet both specify injecting only role + project-root instructions (not deep subdirectory instructions) at session start. Gemini's objection is about injecting *all* deep subdirectory instructions, which nobody actually proposes. The real consensus is: inject role + project root at launch (cheap, high value), handle deep subdirectory instructions through on-demand mechanisms (MCP tool or search).

### Kimi's Thin Wrapper Proposal

Kimi proposes building a `run-agent` universal wrapper that composites instructions and invokes the appropriate model CLI. This sits in mild tension with the "don't build a custom harness" consensus from Claude and Gemini. The distinction is one of scope — Kimi's proposal is a dispatch script, not a full harness with tool use, file editing, and context management. It's closer to what the review engine already does for headless dispatch. Whether this is worth building depends on whether the MCP instruction tool approach succeeds; if models reliably call the tool, a dispatch wrapper is less necessary.

### Severity Summary

- **High:** Vision doesn't acknowledge instruction-loading asymmetry; vision conflates multi-model with multi-harness; Gemini launch config bug in `~/bin/role`; instruction delivery needs to become shared infrastructure (MCP tool or equivalent)
- **Medium:** Three-memory model missing instruction category; no merge/precedence semantics for overlapping instructions; downstream documents stale; "shared-by-default" too coarse (GPT-5.4 — distinguish discoverable metadata from session-authorized content)
- **Low:** Implementation status marker still in vision body; open questions section should name the instruction loading problem explicitly

### Recommended Actions for Draft 14

1. Name instruction delivery as a first-class problem in the vision, not an assumed implementation detail
2. Reframe Principle 1: multi-model is the goal, multi-harness is an adapter concern
3. Connect Principle 13 explicitly to instruction loading as the mechanism
4. Fix the `~/bin/role` Gemini launch configuration immediately
5. Build the MCP `get_instructions` tool and test empirically whether models call it reliably
6. Define three tiers of harness experience: full (Claude Code), tool-assisted (MCP-capable), bundled (headless dispatch)

**Models responded:** claude (agentic), claude-sonnet-4.6 (agentic), gemini-3.1-pro (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### claude (complete)

Now I have the full picture. Let me write my review.

---

## Review: Vision Document (Draft 13) + Multi-Model Instruction Loading Architecture

### Files Read Beyond Review Targets

- `/home/claude/bin/role` — the role launcher script
- `/home/claude/roles/*/` — role directory structure (CLAUDE.md, GEMINI.md, AGENTS.md, shared.md per role)
- `docs/shared-context.md`, `docs/architecture.md`, `docs/context-management-patterns.md` — infrastructure docs
- `config/review_models.yaml` — multi-model review dispatch configuration
- `src/claude_hub/review_engine.py`, `src/claude_hub/review_cli.py` — review engine implementation
- `src/claude_hub/server.py` — MCP server and tool exposure
- Window files in `thoughts/windows/claude-code/` — for continuity context

---

### Part 1: The Vision Document Itself

The vision document is remarkably well-structured. The problem decomposition into data/context/quality/architecture is clean and the problems interact exactly the way described. The writing is precise without being dry, and the principles follow logically from the problems. A few observations:

**The document is mostly harness-agnostic, but the architecture section has a gap.** Section 4 ("The Architecture Problem") talks about roles, projects, persistent agents, shared-by-default, and three kinds of memory. This is the right conceptual framework. But it doesn't address the mechanism by which a role's instructions actually reach the model. The document says "thin harness-specific adapters where needed" (line 97) but doesn't explore what those adapters need to do or what happens when the adapters can't achieve parity. This is not a defect in the vision — the vision should stay wide — but it is the exact gap that makes the architecture question hard. The vision promises "any model, any harness, any role" without acknowledging that the instruction delivery mechanism is a load-bearing detail that differs fundamentally across harnesses.

**The "discoverable, not preloaded" principle (13) is the one that matters most here.** The instruction loading problem is a special case of the general discovery problem. Role instructions, project conventions, subdirectory rules — these are all things the agent needs to discover and load at the right time. The harnesses that support JIT loading of subdirectory instruction files are implementing a primitive form of principle 13. The ones that don't are forcing you to choose between preloading everything (violating context economics) or missing context (violating the "right context at the right time" goal).

**The "model-forward, not code-forward" principle (3) applies to this problem.** The question "how do we get instructions into the model?" is instinctively a code-forward question — you think about file loading mechanisms, build steps, symlinks, hook scripts. But the model-forward answer is: the model should be able to ask for the instructions it needs. This reframes the problem from "how do we push instructions in" to "how does the model pull instructions when it needs them."

---

### Part 2: Answering the Architecture Questions

#### 1. An approach you haven't fully explored: MCP as the instruction delivery layer

You have an MCP server. It already exposes `files_read` and `files_search`. Gemini CLI and OpenCode both support MCP tool servers. The instruction loading problem can be reframed as a tool problem:

**Build an `instructions` MCP tool** that any harness can call. When the model navigates to a new directory or starts working on a project, it calls `get_instructions(path="/home/claude/projects/prediction-markets/collectors")` and gets back the composed instructions for that path — the project root instructions, any subdirectory-specific rules, and the role's behavioral guidelines.

This sidesteps the entire harness instruction-loading mechanism. The model doesn't need the harness to load instructions from a file called CLAUDE.md or GEMINI.md. It needs to *have the instructions*. If it can call a tool to get them, the delivery mechanism is harness-agnostic.

The key question is: will the model actually call this tool at the right time? Claude Code's JIT loading is triggered automatically when the agent reads a file in a new directory. An MCP tool requires the model to know it should call it. This is solvable:

- **In the role's top-level instructions** (which all harnesses can load — that part works), include a rule: "When you start working on a project or navigate to a new directory, call `get_instructions(path)` to load relevant context for that location."
- **In practice**, frontier models follow meta-instructions like this reliably, especially when the instruction is a concrete action ("call this tool") rather than a vague guideline.

This isn't a guaranteed replacement for JIT loading — there's a behavioral gap between "the harness automatically injects instructions" and "the model is told to request instructions and usually does." But the gap is narrower than it looks, because:
- JIT loading also has failure modes (the model doesn't read a file in a directory, so the instructions never load)
- The instruction-via-tool approach gives the model richer instructions than JIT loading can (it can return composed, context-aware instructions rather than a raw file)
- The model can call the tool proactively ("what instructions apply to what I'm about to do?") rather than reactively

**Severity: This is the highest-value finding in this review.** The MCP instruction server approach handles the hardest part of the problem (deep subdirectory instructions on demand) for all harnesses simultaneously, with one implementation.

#### 2. Accept asymmetry — but define the tiers clearly

Yes, accept asymmetry. The question is where to draw the line. I'd propose three tiers:

**Tier 1 — Full experience (Claude Code):** Automatic JIT instruction loading from subdirectories, `--add-dir` for role composition, native `@import`, hooks for context management. This is the primary interactive harness and should stay that way.

**Tier 2 — Tool-assisted experience (any harness with MCP support):** Role instructions load natively (all harnesses can do this from the launch directory). Project and subdirectory instructions are available via MCP `get_instructions` tool. The model is instructed to call it. Context management via MCP tools (window files, artifact store). This is the target for Gemini CLI and OpenCode.

**Tier 3 — Bundled experience (headless/review dispatch):** For non-interactive use (multi-model reviews), instructions are composed at dispatch time and included in the prompt. This is what the review engine already does. No instruction discovery needed because the dispatcher already knows the full context.

The Gemini "loads everything" problem (line 43-45 of the architecture question) is a tier 2 problem. If you switch to MCP-based instruction delivery for project/subdirectory context, Gemini's over-eager recursive loading becomes irrelevant — you'd give it a minimal GEMINI.md in the role directory that says "use the instructions MCP tool" and it doesn't matter what else it finds.

**Severity: Medium.** The tier definition matters for resource allocation — it tells you what to build and what to not bother trying to make equivalent.

#### 3. Concrete alternative mechanisms

Beyond MCP instruction delivery, here are mechanisms worth considering:

**A. Session-start hook that injects a "briefing."** Not full instructions (too much context upfront), but a briefing that tells the model: here's who you are, here are the tools available for getting more context, here's what you were last working on. Think of it as a consistent preamble that all harnesses can receive. The role launcher script could generate this dynamically. For Claude Code, it's redundant (CLAUDE.md does this). For others, it fills the gap.

The problem: not all harnesses support session-start hooks that inject into the system message. This works for Claude Code. For Gemini/OpenCode, you'd need to either pipe it as the first user message or rely on the instruction file. If the instruction file is the only injection point, this collapses back to the build-step approach you've already tried.

**B. A thin wrapper harness.** You mentioned this. The idea: a script that wraps any model API call, injecting instructions into the system message before forwarding. This gives you complete control over instruction composition regardless of harness.

The problem: it bypasses the harness entirely for instruction management, which means you lose all the harness's native features (caching, tool use, file editing, etc.). You'd be building a new harness, not wrapping an existing one. The engineering cost is enormous relative to the MCP tool approach.

**C. Bind mounts to compose directory trees.** You already use bind mounts for `thoughts/`. You could bind-mount project directories into the role directory tree, making them appear as subdirectories. Then launching from the role directory would give all harnesses access to project instruction files as if they were local.

The problem: this is filesystem-level composition, which is fragile and hard to make dynamic (which project is the agent working on today?). It also doesn't solve the "multiple projects" case — if a researcher role works across three projects in one session, you can't bind-mount all three into the same tree without conflicts.

**My recommendation: MCP instruction tool (option from Q1) + session-start briefing for harnesses that support hooks.** The MCP tool is the universal solution. The briefing is a harness-specific optimization for Claude Code where hooks are well-supported.

#### 4. Is the multi-harness approach right?

Yes, but not for the reason you think. The framing in the architecture question says "harness diversity is a pricing artifact, not a design goal." This is true today but understates the value of harness diversity even beyond pricing:

- **Harnesses improve at different rates.** Claude Code's JIT loading, `--add-dir`, hooks, MCP support — these features didn't exist a year ago. Six months from now, one of the other harnesses might leapfrog. Not betting everything on one harness is the same logic as not betting everything on one model.
- **Harness features matter for specific tasks.** Claude Code is best for interactive development. A future harness might be best for autonomous long-running agents. The "best harness" depends on the use case, not just the model.
- **The infrastructure you build to support multiple harnesses (MCP tools, role launcher, shared instructions) makes you less dependent on any single vendor.** This is the same argument as multi-model but applied to the tooling layer.

That said: **don't build a custom harness.** The engineering cost is prohibitive for a single-person operation. The existing harnesses are improving rapidly. Your effort is better spent on the MCP tool layer (which works across all harnesses) than on a custom harness (which replaces them).

**Should you use MCP as the universal interface?** Partially. MCP is the right universal interface for *tool access* (instructions, artifacts, search, review dispatch). It is not the right universal interface for *session management* (each harness handles its own context window, compaction, file editing). Use MCP for what crosses harness boundaries; use harness-native features for what's local to a session.

#### 5. What to prioritize

Given one human directing AI agents, here's the highest-value sequence:

**Step 1 (highest value, lowest cost): Build the MCP `get_instructions` tool.** This is a single endpoint on your existing MCP server. Given a filesystem path, it returns the composed instructions for that location — walking up to find project root instructions, including any subdirectory-specific rules, and prepending the role identity. This immediately makes Tier 2 viable for all MCP-capable harnesses.

Implementation sketch:
```python
@app.tool()
async def get_instructions(path: str, role: str = None) -> str:
    """Get composed instructions for working at the given path."""
    instructions = []
    # Walk up from path to find project root (look for .git, pyproject.toml, etc.)
    project_root = find_project_root(path)
    if project_root:
        # Collect instruction files from project root down to path
        for dir in walk_down(project_root, path):
            for name in ["INSTRUCTIONS.md", "shared.md", "CONTEXT.md"]:
                inst_file = os.path.join(dir, name)
                if os.path.exists(inst_file):
                    instructions.append(f"## Instructions from {dir}\n{read(inst_file)}")
    if role:
        role_shared = os.path.join(HOME, "roles", role, "shared.md")
        if os.path.exists(role_shared):
            instructions.insert(0, f"## Role: {role}\n{read(role_shared)}")
    return "\n\n".join(instructions) or "No instructions found for this path."
```

**Step 2: Update role instruction files to reference the MCP tool.** In each role's `shared.md`, add a standard instruction: "When starting work on a project, call `get_instructions` with the project path to load its conventions and rules. Call again when navigating to a new module directory." This is a one-line addition to four files.

**Step 3: Test with Gemini CLI and OpenCode.** Launch a researcher role in each harness, start working on a project, and verify the model calls `get_instructions` without being reminded. Iterate on the instruction wording if needed.

**Step 4 (later): Build a lightweight instruction index.** As the number of projects grows, the model needs to know *which* projects have instructions without calling the tool for every directory. A simple index — "these 7 project roots have instructions" — can live in the role's shared.md or be served by another MCP tool (`list_projects`).

---

### Part 3: Gaps in the Vision Document

**Gap 1: The vision doesn't address instruction delivery as a first-class problem.** The role/project/harness decomposition is correct, but the document assumes instructions "just get there" via thin harness-specific adapters. In practice, instruction delivery is the hardest part of multi-harness support and deserves a paragraph in the vision explaining the approach. Something like: "Instruction delivery varies by harness. The infrastructure provides a universal mechanism (MCP tool) for models to request instructions on demand, with harness-native instruction loading as an optimization where available."

**Gap 2: The "three kinds of memory" section doesn't mention instruction files.** Session state, project context, and role memory are all described — but the mechanism by which project conventions and role behavioral rules reach the model is left implicit. Instruction files are a fourth kind of context that straddles project context (conventions) and role memory (behavioral rules). The vision should acknowledge that this context has a delivery problem distinct from the retrieval problem.

**Gap 3: The open questions section should include the instruction loading problem explicitly.** The "window files across harnesses in a shared role" question (line 235) is adjacent but doesn't capture the core issue: how do instructions compose across role + project + subdirectory when harnesses have incompatible loading mechanisms? This is arguably the most pressing open question for multi-harness support and should be named.

**Gap 4: The "discoverable, not preloaded" principle lacks a mechanism.** Principle 13 says the system should know what's available and make it findable on demand. But the document doesn't propose how. An MCP-based registry/discovery layer is the natural answer, and the instruction delivery tool is an instance of it. The vision would benefit from naming MCP as the discovery mechanism, not just a tool interface.

---

### Summary of Recommendations

1. **Build an MCP `get_instructions` tool** — the universal solution to instruction delivery across all harnesses. Highest value, lowest cost.
2. **Accept three-tier asymmetry** — Claude Code (full/automatic), MCP-capable harnesses (tool-assisted), headless dispatch (bundled). Don't try to make all harnesses equivalent.
3. **Don't build a custom harness.** Use MCP as the universal extension layer instead.
4. **Update the vision document** to name instruction delivery as a first-class concern and MCP as the discovery/delivery mechanism.
5. **Deprioritize harness-specific workarounds** (symlinks, bind mounts, generated files). The MCP approach makes them unnecessary.


### claude-sonnet-4.6 (complete)

Now I have enough context. Let me write the review.

---

**Files read beyond review targets:**
- `.review-external/multi-model-architecture-question.md` (the context document — required reading)
- `docs/architecture.md` (adjacent architecture context)
- `docs/design/reviews/review-vision-d12.md` (prior review synthesis for D12 → D13 changes)
- `docs/design/reviews/review-2026-03-20.md` (most recent review, different subject)

---

## Review: Vision Document (Draft 13) Against Multi-Model Architecture Question

### Framing

The architecture question asks whether Draft 13 provides the right foundation for solving the instruction-loading problem across harnesses. The question is partly a vision review ("does the vision commit to the right things?") and partly an architectural design question ("what should we build?"). I'll address both, but the review target is the vision document, so I'll weight findings there.

---

### Finding 1: The Vision Makes a Commitment It Cannot Deliver — and Doesn't Acknowledge the Gap

**Location:** Section 4, "Multi-harness by design": *"Shared components should be harness-agnostic, with thin harness-specific adapters where needed."*

**Also:** Principle 1: *"Build for pluggability across both dimensions [model and harness]."*

**Also:** "What This Enables": *"You open any AI tool — Claude, Gemini, GPT, whatever's next — and it already knows your context."*

The architecture question documents a structural asymmetry that thin adapters can't bridge: Claude Code does JIT loading of deep subdirectory instructions; no other current harness does anything equivalent. This isn't a configuration gap — it's a capability gap. Gemini CLI loads everything eagerly (flooding context). OpenCode can't compose instructions from two independent directory trees at all.

The vision's multi-harness commitment, as stated, is an aspiration that current harnesses can't fulfill. That's acceptable for a vision document. What's not acceptable is treating it as if thin adapters are a sufficient bridge. The vision should name the gap — something like: *"The goal is equal access across harnesses; today this is achieved only for Claude Code, and the mechanism for non-Claude harnesses is an open problem requiring either harness-native improvements or infrastructure-layer solutions."*

Without naming the gap, the vision sets up a false equivalence that will mislead downstream documents into designing for a uniformity that doesn't exist.

**Severity: High.** This is the central unresolved problem in the architecture question, and the vision document doesn't acknowledge it.

---

### Finding 2: The Vision's Own Principle Is the Right Answer — But Isn't Applied to Instructions

**Location:** Principle 13: *"Discoverable, not preloaded. The system should know what's available — skills, data sources, documentation, agents, tools — and make it findable on demand. A lightweight index of what exists stays in context cheaply; full content loads only when relevant."*

This is described as a generalization of the skills pattern. But it's also exactly the right architecture for instruction loading: rather than relying on harness-native file loading (which is asymmetric and uncontrollable), have a registry that serves instructions on demand when an agent navigates to a subdirectory.

The vision already has an MCP server. If that server exposes a `get_instructions(role, project, path)` tool, any MCP-capable harness gets on-demand instruction loading that behaves identically to Claude Code's JIT loading — not through harness-native file discovery, but through an explicit tool call. This converts the instruction-loading problem from *"how do harnesses discover files?"* (unanswerable uniformly) to *"how do agents call a tool to get context?"* (answerable uniformly via MCP).

The vision describes this mechanism in general terms but fails to apply it to the specific instruction-loading challenge. The connection is latent but not made.

**Severity: High** for the architecture question specifically. This is probably the most actionable path forward, and it flows directly from principles the vision has already articulated. The vision should make this connection explicit — at minimum in the Open Questions section.

---

### Finding 3: The Vision Conflates Multi-Model (Design Goal) with Multi-Harness (Pricing Constraint)

**Location:** Principle 1: *"Multi-model, multi-harness by default."* and Section 4: *"Multi-harness by design."*

The architecture question articulates this clearly: *"The goal is multi-model, not multi-harness. Harness diversity is a pricing artifact, not a design goal."* This is correct, and the vision doesn't make the distinction.

Multi-model is a genuine quality principle: different models bring different analytical lenses, the best model changes over time, lock-in to one provider is a bad long-term position. These are timeless arguments.

Multi-harness is a pricing constraint: if you could run Claude, Gemini, GPT, and Kimi all at subscription prices through one harness, you'd use one harness. Harness diversity exists only because each model's most economical access path runs through a different tool.

These are different in kind. Treating them as parallel principles in Principle 1 obscures this. The correct framing is: *"The system must support any model (design goal). The current execution path for each model runs through its cheapest harness (pricing constraint). The infrastructure must accommodate multiple harnesses without treating multi-harness as a goal in itself."*

This distinction matters because it changes what you build toward. Multi-model says: make it easy to swap in new models. Multi-harness says: make every harness a first-class citizen. The first is correct. The second leads to engineering complexity in proportion to harness count.

**Severity: Medium.** This is a conceptual precision issue with downstream consequences for what gets built.

---

### Finding 4: The Vision Doesn't Address the Context-Cost Implication of Eager-Loading

**Location:** Section 2: *"Context scarcity is the fundamental constraint that shapes the entire system."* Contrast with the architecture question's description of Gemini CLI: *"Eagerly discovers ALL GEMINI.md files recursively under launch dir AND included dirs — including instruction files from unrelated projects and other roles."*

The vision makes context its central framing concern. It introduces "context rot" and argues that even a context window within capacity but full of stale material degrades output quality. It argues for Principle 13 (discoverable, not preloaded) as the solution.

But the architecture question documents that Gemini CLI does the opposite: it eagerly loads everything, including files from unrelated roles. This is exactly context rot induced by the harness's instruction loading behavior. The vision's own principles predict this as a problem, but the document doesn't connect those principles to the instruction loading mechanism.

The vision should either acknowledge that harness-native instruction loading (at least for Gemini) violates Principle 13, or explain how the role launcher or other mechanism prevents eager loading from poisoning the context budget.

**Severity: Medium.** The vision's logic leads directly to this conclusion, but the connection is left implicit.

---

### Finding 5: The Session-Start Hook as Minimum Viable Cross-Harness Mechanism Is Unaddressed

**Location:** Architecture question: *"A SessionStart hook that injects all instructions via system message"*

The vision mentions hooks but only in the context of Claude Code. The role launcher script (`~/bin/role`) already exists and composes role + project instructions. The natural extension is: at launch time, the launcher assembles the composite instruction set and injects it as a preamble (via `--system-prompt`, environment variable, or pre-conversation message) into whatever harness it's launching.

This gives every harness:
- Role instructions ✓
- Project root instructions ✓
- Deep subdirectory instructions ✗ (static, not JIT)

The degradation vs. Claude Code is specifically in deep JIT loading, which is a secondary concern for most tasks. For many use cases (review dispatch, research, code generation with flattened context), a static composite instruction set at session start is sufficient.

The vision doesn't describe this mechanism, even though it would close most of the gap between Claude Code and other harnesses immediately. This belongs either in the vision (as a mechanism) or as an explicit minimum viable behavior for non-Claude harnesses.

**Severity: Medium.** This is the fastest path to "acceptable but not ideal" cross-harness instruction loading, and it's missing from the document.

---

### Finding 6: The Three-Kinds-of-Memory Model Doesn't Include Instructions

**Location:** Section 4: *"Three kinds of memory: Session state, Project context, Role memory."*

The architecture question implicitly introduces a fourth kind: **role and project instructions** (CLAUDE.md, AGENTS.md, GEMINI.md files and their deep-directory variants). These are not role memory (accumulated experience), not project context in the traditional sense, and not session state. They are meta-level directives — how to behave, what to prioritize, what conventions to follow.

The vision's memory model doesn't have a slot for this. Instructions are treated as a file-loading implementation detail rather than as a first-class memory type with design decisions attached. But the architecture question shows that instruction loading is one of the hardest cross-harness problems. Elevating instructions to a distinct category in the memory model would clarify the design space: where do instructions live, how are they fetched, how do they interact with role memory and project context?

**Severity: Low-Medium.** Naming this as a distinct category would sharpen both the vision and downstream design work.

---

### Finding 7: The Vision Treats the Open Questions Too Shallowly on the Architecture Problem

**Location:** Open Questions section, "Architecture" subsection.

The current open questions cover: window files across harnesses in shared roles, the discovery/registry layer, and cross-agent coordination. These are all legitimate questions.

But the most operationally urgent open question — the instruction loading problem documented in the architecture question — is absent. The vision's open questions are forward-looking (where are we going?) but miss this present-tense blocking problem (what's stopping us now?).

Adding a question like: *"How should agents in non-Claude harnesses receive role and project instructions, including deep-subdirectory instructions, when harness-native file loading mechanisms are asymmetric?"* would flag this as a known problem requiring architectural resolution, and would invite readers of downstream documents to address it.

**Severity: Low.** The open questions section is a good place to surface this, even if the vision doesn't resolve it.

---

### Finding 8: Implementation Status Marker Remains in Vision Body

**Location:** Top of document: *"Implementation status: Requirements (Draft 12) and spec (Draft 11) cover Phases 1-8. Phases 1-4 are implemented. Phase 5 is in progress."*

GPT-5.4 flagged this in the D12 review: "Implementation status doesn't belong in the vision body." It's still here in D13. This is a minor but real violation of the vision document's purpose — it conflates the governing north star (vision) with a project status report (not vision). It also implies that Phase 5–8 content is "new" and not yet in downstream documents, which anchors reviewers on incompleteness rather than evaluating the vision on its own terms.

Move this to a document history section, a separate ROADMAP file, or drop it from the standalone vision.

**Severity: Low.** Easy fix.

---

### On the Architecture Question's Five Questions Directly

**Q1 (approach not yet considered):** MCP-based instruction serving. The existing MCP server, extended with a `get_instructions(role, project, path)` tool, converts harness-native instruction loading into a protocol-layer concern. Any harness that can call tools gets JIT instruction loading through the same mechanism. This is not in the list of approaches tried, and it flows directly from principles the vision already articulates (Principle 13, MCP server existence).

**Q2 (accept asymmetry?):** Yes, explicitly and with a clear minimum viable bar. Claude Code gets the full experience. Non-Claude harnesses get static composite instructions injected at session start (role + project root, assembled by the role launcher). Deep JIT loading is Claude Code-only until MCP-based instruction serving is built. The vision should endorse this posture rather than implying eventual uniformity.

**Q3 (alternative mechanisms):** Session-start injection (fastest path, good baseline) + MCP instruction tool (right long-term architecture). These are complementary: session-start injection gives non-Claude harnesses 90% of the value today; MCP tool serving gets the last 10% when ready.

**Q4 (is multi-harness even right?):** Multi-model yes; multi-harness as a first-class design goal, no. Claude Code should be the primary interactive harness. Other harnesses are secondary execution paths for models that aren't cost-effectively accessible through Claude Code. The vision should reframe accordingly.

**Q5 (what to prioritize?):** In order: (1) MCP instruction tool — highest leverage, most models can call tools, converges on the "discoverable, not preloaded" principle already in the vision; (2) session-start injection in the role launcher for immediate baseline; (3) accept Claude Code asymmetry as a deliberate, time-bounded choice. Don't invest in making Gemini CLI or OpenCode instruction-loading equivalent to Claude Code through harness-native mechanisms — those paths are dead ends.

---

### Summary

The vision document is strong in its organizing principles. The role/project/harness tripartite split is correct. Context as the primary concern is correct. The "discoverable, not preloaded" principle is exactly right and points toward the solution.

The main gaps relative to the architecture question: the vision doesn't acknowledge the instruction-loading asymmetry as a real problem; it doesn't apply its own Principle 13 to instructions as the solution; and it conflates multi-model (genuine design goal) with multi-harness (pricing constraint), obscuring the priority ordering.

The most actionable path forward — MCP-based instruction serving extending the existing FastAPI MCP server — is derivable from principles already in the vision but isn't stated. That's what Draft 14 should add.


### gemini-3.1-pro (complete)

**Files Read Beyond Targets**
- `~/bin/role` (inspected via shell command to understand the exact launch mechanisms causing the behavior described in your context)

---

### Findings & Architectural Recommendations

**Severity: Critical | Location: `~/bin/role` (Gemini Launch Logic)**
**Finding 1: Gemini CLI launch configuration is actively harmful to context health.**
The reason the Gemini CLI is "over-eager" and loading instruction files from unrelated projects is a self-inflicted wound in your launcher script. Currently, `~/bin/role` changes directory to `$ROLE_DIR` and then runs `gemini --include-directories "$HOME"`. This forces the Gemini CLI to eagerly traverse your entire home directory, grabbing every `GEMINI.md` from every unrelated project and role. This violently violates the "Context Conservation" principle in Draft 13 by immediately saturating the context window with irrelevant constraints.
**Action:** Reverse the inclusion direction. The script should launch Gemini from the *Project Directory* (where the work is actually happening) and include only the *Role Directory*: `gemini --include-directories "$ROLE_DIR"`. This strictly scopes Gemini's eager loading to the active project and the active role, eliminating cross-project pollution.

**Severity: High | Location: Overall Architecture Strategy**
**Finding 2: Fighting harness asymmetry violates "Boring Foundations."**
You asked if you should accept asymmetry between the harnesses. The answer is an emphatic **yes**. Claude Code handles deep JIT context loading cleanly because Anthropic engineered the harness to intercept file reads and inject context automatically. You cannot replicate this in other harnesses without building a custom execution engine (a massive engineering trap) or relying on models to proactively ask for instructions (which they reliably fail to do).
**Action:** Accept that Claude Code provides the premium "heavy IDE" experience for deep architectural work. The Minimum Viable Experience (MVE) for OpenCode and Gemini should simply be: **Role Instructions + Project Root Instructions**. Accept the degradation for deep subdirectory instructions in these harnesses.

**Severity: Medium | Location: Context Assembly Mechanisms (Alternative Exploration)**
**Finding 3: Upfront injection and MCP servers are false solutions to JIT loading.**
You proposed a few alternative mechanisms that run counter to your vision:
- **SessionStart Hook Injection:** Injecting all deep subdirectory instructions upfront via a system message is an anti-pattern. If a codebase has 50 module-specific instruction files, injecting them all at launch will immediately cause the "context rot" your vision document warns against.
- **MCP On-Demand Instructions:** This fails structurally. Models are terrible at proactively asking, "Do you have specific instructions for this folder?" before taking action. JIT loading only works when the harness intercepts the action and forces the context in.
**Action:** Do not build complex symlink forests or custom JIT loaders. Instead, index your deep subdirectory instructions into your shared semantic search (the "discovery/registry layer"). When non-Claude models search the codebase for context, they will naturally surface the relevant instruction files alongside the code.

**Severity: Medium | Location: Multi-Harness Strategy**
**Finding 4: Multi-harness is not just a pricing artifact; it is a necessary hedge.**
While pricing is driving the immediate pain, your vision document correctly states: "Multi-model, multi-harness by default. Never assume one model or one tool is best for everything." The frontier shifts. Today Claude Code is the best tool; tomorrow a different lab may release a better harness. 
**Action:** Do not build a custom wrapper harness that attempts to normalize all model APIs. That violates the principle that "Integration is harder than implementation" and will consume all your engineering bandwidth. Keep the multi-harness approach, but stop trying to force feature parity across them. 

**Severity: High | Location: Next Steps Prioritization**
**Finding 5: High-leverage actions for a solo engineer.**
Given your limited engineering bandwidth, the highest-value next step is standardizing the launch environment, not writing a universal instruction loader.
**Action:** Prioritize the following sequence:
1. **Rewrite `~/bin/role`:** Ensure all agents execute from the project root, never the role directory.
2. **Fix Gemini:** Use `gemini --include-directories "$ROLE_DIR"` to fix the eager-loading pollution.
3. **Bridge OpenCode:** For OpenCode, write a lightweight step in `~/bin/role` that generates a transient `.opencode-launch.json` in the project root. This config should explicitly point to `$ROLE_DIR/AGENTS.md` and the project root's `AGENTS.md`. 
4. **Elevate Critical Context:** Since non-Claude models will not get JIT subdirectory instructions, ensure your most critical "must-know" codebase constraints are moved out of deep directories and placed directly into the project root's `shared.md`. Leave the deep directories for detail-oriented constraints that can be found via search.


### gpt-5.4 (complete)

I think the document has the right conceptual center — especially the role/project/harness separation in `docs/design/vision-personal-ai-infrastructure.md:91` and the “discoverable, not preloaded” principle in `docs/design/vision-personal-ai-infrastructure.md:228`. But the core architecture gap is that it never turns instruction loading itself into shared infrastructure. High severity: the vision assumes harness interchangeability while still implicitly depending on harness-native instruction semantics. You can see the tension between `docs/design/vision-personal-ai-infrastructure.md:97` (“multi-harness by design”), `docs/design/vision-personal-ai-infrastructure.md:112` (project context lives with the project), and `docs/design/vision-personal-ai-infrastructure.md:236` (discovery/registry is still an open question). For the problem in the prompt, that missing abstraction is the whole issue. If instruction composition remains “whatever CLAUDE.md / GEMINI.md / AGENTS.md happen to do,” non-Claude parity is unattainable. The concrete fix is to define a first-class instruction resolver/registry as part of shared infrastructure: given role + project + current path, it returns the ordered instruction stack. Harness-native loading then becomes an optimization for Claude Code, not the system contract.

A second high-severity issue is priority drift: the vision currently elevates multi-harness to a principle instead of treating it as an adapter problem in service of multi-model access. That shows up in `docs/design/vision-personal-ai-infrastructure.md:97` and again in principle 1 at `docs/design/vision-personal-ai-infrastructure.md:204`. But the question file is explicit that harness diversity is a pricing artifact, not a product goal. If the vision keeps “multi-harness by default” as a top-level invariant, it will bias implementation toward chasing behavioral parity across tools that may never offer equivalent primitives. I would rewrite that principle toward “multi-model by default; harnesses are replaceable adapters.” Practically, that means: keep Claude Code’s native behavior where it helps, define a minimum cross-harness contract around bootstrap + instruction resolution, and do not build a full custom harness yet.

Medium severity: “shared-by-default” is too coarse for the exact failure mode you are hitting. In `docs/design/vision-personal-ai-infrastructure.md:105`, `docs/design/vision-personal-ai-infrastructure.md:107`, and `docs/design/vision-personal-ai-infrastructure.md:230`, the document treats broad visibility as the default. But Gemini’s over-eager recursive loading is precisely what happens when visibility and session scope are conflated. The design needs a sharper distinction between globally discoverable metadata and session-authorized content. I would make registry metadata shared-by-default, but actual instruction resolution project-scoped by default. That preserves discoverability without polluting sessions with unrelated role/project instructions and also fits the clean-room review posture described elsewhere in the system.

Medium severity: the document separates role memory from project context, but it does not define merge or precedence semantics for overlapping instructions. The relevant conceptual pieces are in `docs/design/vision-personal-ai-infrastructure.md:91`, `docs/design/vision-personal-ai-infrastructure.md:95`, and `docs/design/vision-personal-ai-infrastructure.md:115`. Today Claude Code gives you an implicit rule through ancestor walks and JIT subdirectory loading. A harness-independent system cannot rely on implicit behavior; it needs explicit ordering such as: role bootstrap, then project root, then nearest path-scoped instructions, with clear rules about what can override what. Without that, two harnesses can both be “correct” and still behave differently on the same task.

Medium severity: the implementation path is underspecified because the downstream requirements and spec still target the older architecture. The vision itself admits this at `docs/design/vision-personal-ai-infrastructure.md:5`, and the drift is visible in `docs/design/requirements-personal-ai-infrastructure.md:4` and `docs/design/spec-personal-ai-infrastructure.md:4`, which still derive from older drafts. That means the architecture question has no acceptance criteria yet. There is no requirement for cross-harness instruction parity, no spec for a resolver, no test fixture for nested path rules, and no definition of minimum viable behavior for weaker harnesses. Given limited bandwidth, that is the highest-value gap to close next.

If I were turning this into a build plan, I would not try to coerce all three harnesses into identical native instruction behavior. I would build one shared instruction resolver accessible via MCP and local CLI, make each harness load only a tiny bootstrap that tells the agent to use that resolver, keep Claude Code’s native JIT as a fast path, and define non-Claude MVP as: role bootstrap + project-root context at session start + explicit on-demand path instruction lookup before working in a new subtree. Then I would add a conformance fixture repo with nested instructions and verify that Claude, Gemini, and OpenCode all resolve the same instruction stack for the same `(role, project, path)` tuple.

Beyond the review target, I read `docs/design/requirements-personal-ai-infrastructure.md`, `docs/design/spec-personal-ai-infrastructure.md`, and `docs/multi-model-registry.md` for downstream alignment, plus the suggested context file `.review-external/multi-model-architecture-question.md`.


### kimi-k2.5 (complete)

I'll read the vision document and the architecture question file to understand the context and constraints.
Now let me explore the current implementation to understand how roles, projects, and instructions are structured.
Let me continue reading the spec to understand the implementation details, then explore what actually exists.
Now I have a complete picture. Let me provide my review with concrete, actionable suggestions.

---

## Review: Multi-Model Agent Infrastructure Architecture

**Files Read:**
- `docs/design/vision-personal-ai-infrastructure.md` (Draft 13)
- `.review-external/multi-model-architecture-question.md`
- `docs/design/requirements-personal-ai-infrastructure.md` (Draft 12)
- `docs/design/spec-personal-ai-infrastructure.md` (Draft 11, partial)
- `config/review_models.yaml`
- `src/claude_hub/review_engine.py` (partial)
- `src/claude_hub/artifact_store.py` (partial)
- `CLAUDE.md` (root)

**Severity Legend:** HIGH = blocks core goal, MEDIUM = significant friction, LOW = nice-to-have

---

### Finding 1: You're Fighting the Wrong Battle (HIGH)

The fundamental issue is that you're trying to make three different harnesses behave identically at the instruction-loading layer, but they have fundamentally different architectures. Claude Code's `--add-dir` is a unique capability. Gemini's recursive loading is a different design philosophy. OpenCode's limited support is yet another.

**The insight you're missing:** The goal is *multi-model*, not *multi-harness*. You want Claude, Gemini, and GPT to all have access to your infrastructure. But you're conflating "access to models" with "using each model's preferred harness."

**What to build instead:**

Create a **thin universal harness** that wraps all models uniformly. This is a small Python script (call it `run-agent`) that:

```bash
# Universal invocation, regardless of underlying model
run-agent --role researcher --project claude-hub --model claude-opus
run-agent --role researcher --project claude-hub --model gemini-3.1-pro
run-agent --role researcher --project claude-hub --model gpt-5.4
```

The script:
1. Composites role instructions + project instructions into a single prompt
2. Writes that prompt to a temp file
3. Invokes the appropriate model CLI with the prompt file
4. Returns the response

This eliminates the "JIT loading of deep subdirectory instructions" problem entirely. Instead of hoping each harness will discover `docs/design/reviews/review-2026-03-20.md`'s local instructions when read, you inject the relevant instructions into the initial prompt based on what the agent is being asked to do.

**Location in codebase:** New file `src/claude_hub/agent_runner.py`

---

### Finding 2: The Role Directory Structure Doesn't Exist (MEDIUM)

The vision describes a role-based architecture with role directories containing `CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, and `shared.md`. But this doesn't exist in the current codebase. You have:

- `CLAUDE.md` in the root (Main Claude)
- `CLAUDE.md` in `/home/claude/claude-chat/` (Chat instances)
- No `roles/` directory
- No `shared.md` files

**What to build:**

Create the role directory structure at `roles/`:

```
roles/
  researcher/
    shared.md          # Harness-agnostic instructions
    CLAUDE.md          # Imports shared.md, adds Claude-specific config
    GEMINI.md          # Imports shared.md, adds Gemini-specific config
    AGENTS.md          # Imports shared.md, adds OpenCode-specific config
  sysadmin/
    shared.md
    CLAUDE.md
    GEMINI.md
    AGENTS.md
  workbench/
    ...
  mcp-server/
    ...
```

The harness-specific wrappers are thin — they just import `shared.md` and add any harness-specific configuration (e.g., tool preferences, output formatting).

**Location in codebase:** New directory `roles/`

---

### Finding 3: Project Instructions Are Scattered (MEDIUM)

Project instructions currently live in `CLAUDE.md` files at the project root (for claude-hub itself). But per the vision, projects should have their own instruction files that any role can read. Currently there's no standard location for project-level instructions that work across harnesses.

**What to build:**

Standardize on `PROJECT.md` as the cross-harness project instruction file:

```
/home/claude/claude-hub/
  PROJECT.md          # What this project is, conventions, architecture
  docs/
  src/
  ...
```

The `PROJECT.md` is harness-agnostic. The `run-agent` script (from Finding 1) loads both:
1. Role instructions from `roles/{role}/shared.md`
2. Project instructions from `{project}/PROJECT.md`

And composites them into the initial system prompt.

**Location in codebase:** New file `claude-hub/PROJECT.md` (convert from existing `CLAUDE.md` content)

---

### Finding 4: Deep Subdirectory Instructions — Solve It Differently (HIGH)

You want "JIT loading of deep subdirectory instructions" so that when an agent reads `src/claude_hub/review_engine.py`, it also discovers and loads `src/claude_hub/CLAUDE.md` if it exists.

**Why this is the wrong approach:**

You're trying to replicate Claude Code's file-system-walking behavior across all harnesses. But:
1. It only works in Claude Code
2. It creates non-deterministic context (what gets loaded depends on file access order)
3. It's fragile (move a file, change the loaded context)

**What to build instead:**

Use the **MCP server as the instruction provider**. When an agent needs context about a specific directory, it calls an MCP tool:

```python
# MCP tool: get_directory_context
result = await mcp.get_directory_context(path="src/claude_hub/")
# Returns: {"instructions": "...", "relevant_files": [...]}
```

The MCP server looks for:
- `src/claude_hub/CLAUDE.md` (Claude-specific)
- `src/claude_hub/GEMINI.md` (Gemini-specific)
- `src/claude_hub/AGENTS.md` (OpenCode-specific)
- `src/claude_hub/PROJECT.md` (harness-agnostic fallback)
- `.docs/` subdirectory with convention docs

This is deterministic, explicit, and works the same across all harnesses. The agent explicitly requests context when it needs it, rather than hoping the harness will discover it.

**Location in codebase:** New MCP tool in `src/claude_hub/server.py`

---

### Finding 5: The Role Launcher Script is Missing (HIGH)

The architecture question mentions a `~/bin/role` script that "launches any harness in a role, composing role instructions with project context." This doesn't exist in the codebase.

**What to build:**

Create `bin/role` (a shell script or Python CLI):

```bash
#!/bin/bash
# Usage: role <role-name> [--project <project>] [--model <model>]

ROLE=$1
PROJECT=${PROJECT:-$PWD}  # Default to current directory
MODEL=${MODEL:-claude}    # Default to Claude

# Composite instructions
cat roles/${ROLE}/shared.md > /tmp/instructions.md
echo -e "\n\n## Project Context\n" >> /tmp/instructions.md
cat ${PROJECT}/PROJECT.md >> /tmp/instructions.md

# Launch appropriate harness
case $MODEL in
  claude*|opus|sonnet)
    claude --add-dir roles/${ROLE} --add-dir ${PROJECT} -p "$(cat /tmp/instructions.md)"
    ;;
  gemini*)
    gemini --include-directories roles/${ROLE},${PROJECT} -p "$(cat /tmp/instructions.md)"
    ;;
  gpt*|kimi*|glm*|minimax*|grok*|mimo*)
    opencode run -m opencode/${MODEL} "$(cat /tmp/instructions.md)"
    ;;
esac
```

This gives you a unified interface across all harnesses. It doesn't solve the JIT loading problem, but it gives you 80% of the value with 20% of the complexity.

**Location in codebase:** New file `bin/role`

---

### Finding 6: Multi-Harness is Right, But MCP is the Interface (MEDIUM)

You ask: "Is the multi-harness approach even right given that it's driven by pricing, not design?"

**Answer:** Yes, multi-harness is right because pricing is real. But you should de-emphasize harness-native features (like instruction file loading) and emphasize MCP as the universal interface.

**What this means:**

Instead of trying to make each harness load instructions the same way, make the MCP server the source of truth for:
- Role definitions
- Project context
- Shared infrastructure access
- Instruction retrieval

The harness is just a shell. The MCP server provides the intelligence. This is the pattern already emerging in your codebase (artifact store, review engine, connectors) — extend it to instruction management.

**Location in codebase:** Extend existing MCP server in `src/claude_hub/server.py`

---

### Finding 7: Prioritize Claude Code, Degrade Gracefully for Others (LOW)

You ask: "Should we accept asymmetry — Claude Code gets the full experience, other harnesses get a degraded but functional version?"

**Answer:** Yes. Claude Code is your primary harness (subscription model, best tool support). The other harnesses are for specific models that you can't access through Claude Code (Gemini 3.1 Pro, GPT-5.4, etc.).

**Minimum viable experience for non-Claude harnesses:**
1. Composite role + project instructions at startup (no JIT loading)
2. Access to MCP tools for context retrieval
3. Manual instruction loading via explicit tool calls

This is "degraded" compared to Claude Code's automatic JIT loading, but it's functional and consistent across all non-Claude harnesses.

---

### Summary: What To Build

**Immediate (this week):**
1. Create `bin/role` launcher script (Finding 5) — unifies harness invocation
2. Create `roles/` directory structure (Finding 2) — separates roles from projects
3. Create `PROJECT.md` in claude-hub root (Finding 3) — project-level instructions

**Short-term (next 2 weeks):**
4. Build `run-agent` universal harness wrapper (Finding 1) — abstracts model invocation
5. Add `get_directory_context` MCP tool (Finding 4) — explicit context retrieval

**Medium-term (next month):**
6. Migrate existing `CLAUDE.md` files to new structure
7. Update review engine to use `run-agent` for model invocation
8. Document the new architecture

This approach accepts that harness-native instruction loading is irreconcilably different, provides a unified abstraction layer at the orchestration level, and uses MCP as the universal interface for shared infrastructure.

