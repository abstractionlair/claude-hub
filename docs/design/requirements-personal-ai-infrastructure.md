# Requirements: Personal AI Infrastructure

*Draft 13 — March 22, 2026*
*Derives from: vision-personal-ai-infrastructure.md (Draft 14)*

**Changes in Draft 13:** Updated existing infrastructure table (all stores now PostgreSQL, ledgers decommissioned in favor of window files, window files git-tracked). Updated R3.4 (ledger migration complete). Updated R3.7 window file frontmatter to match ontology (added role, projects array, workstream, component, service, finalized). Marked Phases 1-5 as implemented. Updated derives-from pointer to vision Draft 14.

**Changes in Draft 12:** Aligned R5 vision reference from "outcome-weighted feedback" to "usage-weighted feedback" to match vision Draft 11 reframing. Updated derives-from pointer to vision Draft 11.

**Changes in Draft 10:** Rewrote R5 (renamed "Knowledge Quality" from "Outcome Tracking"). Reoriented from human-initiated rating ceremonies to agent-driven usage feedback. R5.1: usage feedback from agents at point of retrieval. R5.2: confidence annotation at write time. R5.3: quality-weighted retrieval (replaces outcome-weighted). R5.4: retirement for managing store size. R5.5: review quality grading (unchanged — synthesis-driven). Key principle: signal emerges from work already happening, not separate curation sessions.

**Changes in Draft 9:** Phase 3 (Context Continuity) redesigned around window-file architecture. R3.2 clarified: summarization is a forked agent task, not a tool. R3.3 split into Phase 3 (file-based chain loading) and Phase 3.5 (semantic retrieval). R3.5 clarified: mechanical log is a local JSONL file, already implemented. New R3.7: window file architecture (one file per context window, linked via YAML frontmatter). R3.4 updated for window chain migration. Dependencies and constraints updated to reflect file-based approach and existing hook implementations.

**Changes in Draft 8:** Addressed 6-model review of agentic review changes (Gemini, GPT-5.4, GPT-5.3 Codex, GLM-5, Kimi K2.5, MiniMax M2.5). R2.1: bundled-mode reviewers explicitly exempt from exploration criterion; acceptance split by capability tier. R2.2: synthesis must record invocation mode (agentic/bundled) per review and flag bundled reviews as lower-context. R2.6: acceptance changed from proving negative to verifiable prompt construction + audit trail. R2 constraints: intent required for code reviews (optional "mechanical-only" mode for quick checks). Exclude paths narrowed from `thoughts/` to specific subdirectories (`thoughts/ledgers/`, `thoughts/history/`).

**Changes in Draft 7:** R2.1 revised — reviewers are agentic (codebase access, not content bundles) and reviews are paired with intent (spec/requirements). R2.6 revised — clean-room is opinion isolation (don't read process docs), not information deprivation (do read spec, existing code, tests). R2 constraints updated for agentic invocation and capability tiers.

**Changes in Draft 6:** Addressed 6-model review (Gemini, GPT-5.4, GPT-5.3 Codex, GLM-5, Kimi K2.5, MiniMax M2.5). High-consensus fixes: R4.1 automatic detection now has recurrence threshold and trigger mechanism; R6.4 implementation tracking defines explicit state model with human-driven updates; backup promoted to R1.7 with acceptance criteria; implementation-specific details (env vars, hook names, CLI commands) moved to "reference implementation" notes. Also: R3.5 "lossless" corrected; R2.6 acceptance made deterministic; R1.6 archival added; R7.4 federated queries added; Anthropic embeddings reference corrected; R3.3/R3.6 acceptance changed to observable outputs; security section expanded for third-party data flows; R5.4 wording clarified.

## Scope

The vision describes a personal AI infrastructure. These requirements describe the capabilities that infrastructure must provide.

Seven requirements, chosen because they are proven patterns (not speculative), they compound (each makes the others more valuable), and they build on existing infrastructure.

**In scope:**
1. A native store for AI-generated artifacts with semantic search
2. Multi-model review as a formalized, repeatable workflow
3. Context continuity — layered preservation across sessions, windows, and compaction
4. Capability compounding — promoting recurring patterns into durable tools
5. Knowledge quality — usage feedback, confidence annotation, quality-weighted retrieval
6. Spec-driven development as a formalized workflow
7. A connector interface for integrating external data sources

**Out of scope for these requirements:**
- Specific external data source connectors (email, spreadsheets, calendars). R7 defines the connector interface and validates it with reference implementations. Individual connector requirements are separate documents per source.
- Proactive context surfacing (the ambitious end of the retrieval spectrum). The architecture must not preclude it, but we don't yet have enough clarity to write acceptance criteria.
- Agent autonomy policies.
- Cost management infrastructure beyond awareness of subscription boundaries.
- Any integration with work environments.
- Resource management (per ontology: durable infrastructure like databases, storage mounts, email sync). Resources are environmental facts documented in the infrastructure manifest, not software-managed entities.
- Persistent agent infrastructure (agent registry, scheduled invocation, inter-agent messaging). The vision describes persistent agents as architecturally central; existing code (`scheduler.py`, `workspace.py`) provides building blocks. Requirements for agent lifecycle management are deferred until patterns emerge from operational use.

## Existing Infrastructure

These requirements build on what's already running:

| Component | State | Relevant to |
|-----------|-------|-------------|
| Hetzner VPS (nexus), 4GB RAM, Debian 13 | Stable | Everything — this is the host |
| PostgreSQL (claude_hub database) | Working, all stores migrated from SQLite | Native store, all persistent state |
| claude-hub MCP server (FastAPI, port 8420) | Working, OAuth 2.1 | Native store, multi-model review |
| Claude Code on nexus | Working, hooks + skills + roles | All workflows |
| Gemini CLI on nexus | Working | Multi-model review |
| OpenCode on nexus (Zen subscription) | Working, pay-as-you-go API rates | Multi-model review dispatch |
| Window files (git-tracked, ~/roles/) | Working, replaces ledger system | Context continuity |
| Role system (~/roles/{workbench,sysadmin,mcp-server}) | Working, hook-injected | Session context |
| fork-agent.sh | Working | Sub-agent dispatch |
| /remote access | Working | Mobile access to sessions |

---

## Requirement 1: Native Artifact Store

**Vision reference:** "Generated Artifacts Need a Home," "Persistent Context That Compounds"

### What

A persistent, semantically searchable store for AI-generated content: design documents, review results, session summaries, decision logs, captured thoughts, and any other artifact produced by the AI workflow that needs to be retrievable in future sessions.

### Capabilities

**R1.1 — Store artifacts with metadata.**
An artifact has: content (text), a type (e.g., "vision-doc", "review", "decision", "session-summary"), a timestamp, optional tags, an optional source reference (e.g., which session produced it), and an optional `derives_from` reference to a parent artifact (enabling lineage tracking from day one — see R6.3). Artifacts are immutable once stored — updates create new versions, not overwrites. Metadata (including confidence level, utility score, and usage feedback per R5) is mutable and stored separately from artifact content. When searchable metadata fields change, the artifact's search index is updated accordingly.

*Acceptance: Can store a 10K-char document with type, tags, source, and derives_from. Can retrieve it by ID. Stored data persists across server restarts. Updating an artifact creates a new version — the old version remains retrievable by its original ID, and the new version's lineage is queryable. Metadata can be updated independently of content. After updating metadata on an artifact, searches reflecting the new metadata return the artifact.*

**R1.2 — Semantic search across artifacts.**
Given a natural-language query, return the most relevant artifacts ranked by semantic similarity. This is vector-embedding search, not keyword matching — a search for "career planning decisions" should find a note about "considering consulting" even if the word "career" never appears.

*Acceptance: Store 5 artifacts on different topics. Define a fixed evaluation set: 3 queries, each semantically related to one artifact but using different words (e.g., artifact about "considering consulting" retrieved by query "career planning decisions"). The relevant artifact ranks in the top 2 results for each query. Run the evaluation set after any embedding or indexing changes.*

**R1.3 — Keyword and metadata filtering.**
In addition to semantic search, support filtering by type, date range, and tags. These filters compose with semantic search (e.g., "find decisions about infrastructure from the last month").

*Acceptance: Store 10 artifacts of mixed types and dates. Filter by type returns only matching type. Filter by date range returns only matching range. Combining a semantic query with a type filter narrows results correctly.*

**R1.4 — Accessible from Claude Code and via MCP.**
The store is usable both locally (Claude Code sessions on nexus) and remotely (via MCP tools that Chat Claude or other MCP clients can call). The interface is the same — same query, same results.

*Acceptance: Store an artifact from a Claude Code session. Retrieve it via an MCP tool call from a different client. Both return the same content. A semantic search from both interfaces returns the same ranked results.*

**R1.5 — Capture is low-friction.**
Storing an artifact should take one command or tool call, not a multi-step process. The system handles embedding generation, metadata extraction, and indexing automatically on write.

*Acceptance: A single function call with content and type stores the artifact and makes it searchable. No manual embedding or indexing step. If embedding generation fails, the artifact is still stored and retrievable by ID and metadata filters (with status "pending-embedding"), and embedding is retried later.*

**R1.6 — Artifact archival.**
Artifacts can be archived — excluded from default search results but still retrievable by explicit ID lookup or by searching with an "include archived" flag. This supports removing outdated, superseded, or incorrect artifacts from active use without destroying immutability or lineage.

*Acceptance: Archive an artifact. Default semantic search no longer returns it. Search with "include archived" does return it. Retrieve by ID still works. Artifacts that derive from the archived artifact are unaffected.*

**R1.7 — Backup and restore.**
Artifacts can be exported to a portable format and restored from export. The storage format is compatible with standard backup tools (file copy, database dump).

*Acceptance: Export all artifacts. Delete the store. Restore from export. All artifacts, metadata, and embeddings are present and searchable. Export is runnable as a single command. Note: embeddings are regenerated asynchronously after restore — artifacts are immediately retrievable by ID and metadata, but semantic search may take a short period to fully populate.*

### Constraints

- Must run on nexus (4GB RAM). This means API-based embeddings — a local embedding model of sufficient quality would consume too much of the 4GB RAM budget alongside the other services. API-based embedding through Google or lightweight embedding APIs keeps the compute off-box.
- The thoughts/ directory already contains valuable content (ledgers, plans, design docs, research). The store should be able to ingest existing files, not require re-creation. Ledgers are imported into the store (R3.4); other files are indexed in place via the filesystem connector (R7.3).
- The store is append-heavy, read-often. Write performance matters less than query performance.

---

## Requirement 2: Multi-Model Review Workflow

**Vision reference:** "Multiple models produce better results," "Multi-model review has a diminishing returns curve"

### What

A formalized, repeatable workflow for reviewing any text artifact (document, code file, plan) with multiple AI models and synthesizing the results. This is the pattern proven in the VaR API project — but currently done ad hoc with custom scripts each time. This requirement makes it a standard capability.

### Capabilities

**R2.1 — Review an artifact with N models.**
Given a description of what to review and what the code is supposed to do (its intent), dispatch the review to 2-3 models and collect structured results from each. Reviewers are agents with codebase access — they read the changed files, explore adjacent code for context, and form their own understanding. The review request pairs the changed files with intent: a reference to the relevant spec section, requirements document, or acceptance criteria (as a file path, artifact ID, or inline text). This pairing enables reviewers to catch semantic errors (code works but doesn't do what was asked) in addition to mechanical ones (null checks, race conditions).

*Acceptance: Submit a set of changed files and a spec reference for review. Receive feedback from at least 2 different models. Each review's raw output is stored and attributed to its model and invocation mode (agentic or bundled). Agentic reviewers demonstrate codebase exploration (reference files beyond those explicitly listed). Bundled reviewers are flagged as lower-context.*

**R2.2 — Synthesize review findings.**
After collecting individual reviews, produce a synthesis: which findings appear across multiple models (high confidence), which are unique to one model (lower confidence), and any contradictions between models.

*Acceptance: Given 3 model reviews of the same artifact, a synthesis model reads the raw review outputs and produces a prose synthesis identifying consensus findings (2+ models agree), unique findings, and contradictions. The synthesis records each reviewer's invocation mode (agentic or bundled) and notes where bundled reviewers' limited context may affect finding quality. The synthesis is shorter than the combined reviews. No code parses or restructures review output between the reviewer and the synthesis model.*

**R2.3 — Review results are stored.**
Review results (individual reviews and synthesis) are automatically stored in the native artifact store (Requirement 1) with appropriate metadata: what was reviewed, which models, when, the synthesis.

*Acceptance: After a review workflow completes, the synthesis is retrievable from the artifact store by searching for the reviewed artifact's name or topic.*

**R2.4 — Easy to add models.**
Adding a new model to the review portfolio requires configuration, not code. A model entry specifies: name, how to invoke it (CLI command, API call), any model-specific prompt adjustments, and cost tier.

*Acceptance: Add a new model to the review configuration. Run a review that includes it. No code changes required.*

**R2.5 — Invocable as a skill or single command.**
The entire review workflow (dispatch to models, collect results, synthesize, store) is a single invocation — a skill, a script, or a tool call. The human's role is deciding what to review and with what prompt, not managing the mechanics.

*Acceptance: From a Claude Code session, invoke a review of a file with one command. Receive the synthesis without managing individual model dispatches.*

**R2.6 — Clean-room review capability.**
Reviews can be dispatched with opinion isolation: reviewers do not read process preferences, style guides, or design rationale documents that could create anchoring bias (where the reviewer echoes back assumptions instead of challenging them). Reviewers do have access to factual context needed for a good review: the spec or requirements (intent), the codebase itself, API docs, existing code patterns, and tests. The boundary is intent (share it) versus editorial opinion (withhold it). The dispatch mechanism communicates these boundaries to the reviewer as soft instructions ("please do not read files under ..."), not hard access controls.

*Acceptance: Run a review with clean-room enabled. The constructed review prompt verifiably includes boundary instructions specifying which paths to avoid. The reviewer's output demonstrates it engaged with the spec and codebase. For models that report file access (e.g., via tool-use traces), the access log shows no reads of excluded paths. For models without access reporting, the review output is spot-checked for absence of process-document influence. The boundary is soft — verification confirms correct prompt construction, not absolute access control.*

### Constraints

- Uses models available through existing subscriptions and services: Claude (Anthropic subscription), Gemini (Google subscription), and additional models via OpenCode Zen (DeepSeek, Qwen, Mistral, Devstral, etc. at pay-as-you-go API rates).
- Reviewers are agentic — they have codebase access and navigate it themselves. The review engine constructs a task prompt (intent + file list + boundaries) and launches the model as an agent, not as a text function. Models that lack agentic capability (can't read files) may fall back to receiving bundled content, but the primary invocation model is agentic.
- Reviews should work on text artifacts of any size up to ~50K chars (a large design doc). Larger artifacts should be chunked or summarized before review.
- Intent is required for code reviews. The `intent` parameter pairs the review with a spec section, requirements, or acceptance criteria. For quick mechanical-only checks (linting, formatting), intent may be omitted — the review is flagged as "mechanical-only" in the synthesis.
- Clean-room review (R2.6) is the default for independent review. Clean-room means opinion isolation (suppress process docs, design rationale), not information deprivation (the reviewer reads the spec, existing code, and tests). The default exclude paths target opinion-carrying content specifically: continuity ledgers, session history, and project-level instructions — not the entire thoughts/ directory, which also contains specs and requirements that reviewers need. The dispatch mechanism communicates boundaries as soft instructions in the review prompt.

---

## Requirement 3: Context Continuity

**Vision reference:** "Conserve," "Persistent Context That Compounds," incremental summarization

### What

A layered system for preserving context across sessions, context windows, and compaction events. The continuity system uses window files (role-scoped, git-tracked) with automatic narrative capture via forked agents, a mechanical log trace layer, and active influence over what survives compaction — patterns proven in production use.

### Capabilities

**R3.1 — Session summaries are stored as artifacts.**
When a session produces a summary (via window file capture, /clear, or manual capture), that summary is stored in the native artifact store with session metadata. This makes session history semantically searchable — "what did we decide about the MCP authentication approach?" retrieves the relevant session summary even months later.

*Acceptance: After a session that includes a window file capture, the summary is in the artifact store. A semantic search for a topic discussed in that session returns the summary.*

**R3.2 — Automatic incremental summarization.**
The system periodically captures session state without human intervention — triggered by token consumption thresholds (approximately every 20K tokens of work). Each capture forks a background agent (via `fork-agent.sh`) that inherits conversation context, reads the mechanical log (R3.5) for factual grounding, and writes a window file (R3.7). The forked agent is a cognitive task — it decides what matters and writes prose — not a tool that makes an LLM call. On-demand capture is also available for explicit checkpoints. Fork bomb prevention ensures only one summarization fork runs at a time.

*Acceptance: During a session that consumes 40K+ tokens, at least one automatic summary is captured without human intervention. The summary is written as a window file (R3.7) containing references to files edited and commands run (verifiable against the mechanical log). Manual capture is also available via command. A failed fork (process crash, timeout) is logged but does not interrupt the main session.*

**R3.3 — Session start loads relevant context via concrete triggers.**
When a session starts (or resumes after /clear or compaction), the system loads context through specific mechanisms, split across two phases:

**Phase 3 — File-based chain loading (no artifact store required):**
- **Startup/resume**: Load the most recent window file for this session (via pointer file or project-tagged search). Follow the window file's parent links to load recent context from prior windows.
- **Post-compaction**: The SessionStart hook directs the agent to the window file that was written just before compaction (by the pre-compaction fork in R3.6), providing the most recent captured state.

**Phase 3.5 — Semantic retrieval (requires artifact store, R1):**
- **Semantic retrieval**: Query the artifact store for past window files and artifacts relevant to the initial prompt or project context. This requires window files to have been ingested as artifacts.

*Acceptance (Phase 3): After a /clear, the session starts with the current window file loaded. After compaction, the post-compaction context includes references to the active work items and open threads from the pre-compaction window file. A new session can follow the window chain (parent links) to reconstruct prior context. The loaded context is sufficient for the agent to continue work without the human re-explaining the current task.*

*Acceptance (Phase 3.5): Semantic search for a topic discussed in a past session returns relevant window files from the artifact store, even when the current session has no direct parent link to them.*

**R3.4 — Ledger migration.** *(Complete — ledger system decommissioned March 2026)*
The legacy `CONTINUITY_CLAUDE-*.md` ledger files were migrated to the window file system and ingested into the artifact store. The ledger system has been fully decommissioned. Historical content is accessible via window file chain traversal and semantic search.

**R3.5 — Mechanical log of tool operations.**
A structured, append-only log of tool operations (file edits, shell commands, reads) independent of conversation content. This is a **local JSONL file** (role-scoped: `~/roles/{role}/mechanical.jsonl`), already implemented via a PostToolUse hook — no server component, no database. This provides the factual substrate for narrative summarization — the forked agent (R3.2) reads what actually happened, not what the conversation remembers happening. The log is structured (JSONL), timestamped, and captures file paths for edits and command signatures for shell commands. The log is truncated after successful summarization — it is working memory for the narrative layer, not permanent history. No new work is required for Phase 3.

*Acceptance: After a session with file edits and shell commands, a JSONL log exists at the role-scoped path (`~/roles/{role}/mechanical.jsonl`, fallback `thoughts/mechanical.jsonl`) with timestamped entries for each operation. The narrative summarization process (R3.2) reads this log as input. After successful summarization, the log is truncated.*

**R3.6 — Compaction context injection.**
Before context compaction, the system captures critical continuity information and does two things: (1) forks an urgent window file update to save state externally, and (2) injects open threads and active work state into the compaction prompt itself. This influences what the compaction retains, rather than only saving context externally and hoping the post-compaction agent reads it.

*Acceptance: After compaction, the post-compaction context contains references to the open threads and active work items that were injected before compaction (verifiable by inspecting the compaction output or the post-compaction agent's loaded state), without requiring the agent to read external files first.*

**R3.7 — Window file architecture.**
The core data structure for context continuity is the window file: one markdown file per context window, stored in role-scoped directories (`~/roles/{role}/windows/`), git-tracked for persistence. Window files are linked into a directed graph via YAML frontmatter:

- **Mechanical aspects (precisely specified):** File naming convention (`{timestamp}.md`, ISO 8601 with filesystem-safe separators), directory location (`~/roles/{role}/windows/` — role-scoped to support continuity across projects and harnesses), YAML frontmatter schema (parent, children, session_id, harness, role, projects array, workstream, component, service, finalized, created, updated timestamps), creation triggers (Stop hook at ~20K tokens, PreCompact hook, /clear, new session, forked agent), parent/child linking protocol (child records parent reference at creation; parent's children list is updated; parent references can cross harness boundaries via relative paths).
- **Content aspects (model-directed):** The body of a window file is free-form prose. The summarization prompt explains *why* context is being captured (so future sessions can reconstruct what this one knew) and gives examples of what good entries look like (active work items, decisions made, open threads, key file paths), but does not mandate sections or structure. The model in the moment decides what matters.

Window files form a tree within a session (compaction, /clear, or forked agents create children — multiple children from one parent is normal) and a forest across sessions (new sessions create root nodes, or child nodes when explicitly resuming prior work). Parallel workstreams and forked agents are first-class: a forked agent can create its own child window linked to the parent session's current window, and parallel sessions branching from the same point are siblings in the graph.

*Acceptance: After a session spanning 2+ context windows (via compaction or /clear), two linked window files exist in the role-scoped directory (`~/roles/{role}/windows/`, fallback `thoughts/windows/{harness}/`). The second file's parent field points to the first. A new session can follow the parent chain to reconstruct the prior session's context. Window files are readable as standalone markdown documents. Parent links that cross harness boundaries (via relative paths) are traversable by the chain-loading mechanism.*

### Constraints

- The existing SessionStart hook and window file format are the continuity mechanism. The legacy ledger system has been decommissioned.
- Automatic summarization forks must prevent re-triggering (fork bomb prevention) and must not interfere with the main session's context or interaction.
- The mechanical log captures what happened, not why. The narrative layer (R3.2) provides the curated interpretation. The summarization prompt must guard against confabulation — inferring events not present in the transcript (e.g., inferring that someone responded to a message when only the sending is in evidence, or fabricating causal links between concurrent changes).
- The summary quality depends on what's in context at the time of capture. The system can't summarize what it can't see — but the mechanical log provides a factual backstop for tool operations that may have scrolled out of effective attention.
- The mechanical log is a local JSONL file (role-scoped: `~/roles/{role}/mechanical.jsonl`, fallback: `thoughts/mechanical.jsonl`), already implemented via a PostToolUse hook. No server component required.
- **Platform hook dependency:** The hooks required for R3 (Stop, PreCompact, SessionStart, PostToolUse) are already implemented in the current system. This phase adapts them to write and read the window file format (R3.7) rather than implementing hooks from scratch. If a tool environment lacks these hooks, the fallback is: R3.2 falls back to time-based or manual checkpoints; R3.6 falls back to pre-compaction window file capture (the fork still runs) without compaction prompt injection (the post-compaction agent reads the window chain via SessionStart instead).

---

## Requirement 4: Capability Compounding

**Vision reference:** "Persistent Context That Compounds" (capability compounding), "Custom beats generic"

### What

A mechanism for promoting recurring patterns from observations into durable infrastructure — skills, hooks, and rules. The system doesn't just accumulate knowledge; it accumulates capabilities. When the same debugging sequence works three times, it should become a one-command skill. When the same event-triggered behavior is manually invoked repeatedly, it should become an automatic hook.

### Capabilities

**R4.1 — Pattern detection across sessions.**
The system identifies recurring patterns in session history: sequences of commands that recur, types of problems that are solved the same way, heuristics that are applied repeatedly. Detection operates in two modes:
- **On-demand**: Human invokes a review of recent sessions. The system analyzes the artifact store and session summaries for recurring patterns.
- **Automatic**: Triggered when new session summaries accumulate past a configurable threshold (e.g., every 10 new summaries). The system runs the same analysis without human initiation, surfacing candidate patterns that meet a minimum recurrence threshold (pattern appears in 3+ sessions). Previously dismissed candidates are not resurfaced.

*Acceptance: On-demand: Given 5+ session summaries that include a recurring pattern (e.g., the same 3-step debugging sequence), the system identifies and surfaces the pattern with frequency count and examples, invocable as a single command. Automatic: After the configured number of new session summaries, detection runs without human initiation and surfaces candidates meeting the recurrence threshold. Candidates dismissed by the human are not resurfaced in subsequent runs.*

**R4.2 — Pattern-to-artifact escalation.**
Detected patterns can be promoted to the appropriate artifact type based on their nature:
- Recurring command sequences → **Skill** (executable, on-demand)
- Event-triggered behaviors → **Hook** (automatic, fires on events)
- Decision heuristics → **Rule** (advisory, loaded into context)
- Workflow enhancements → **Agent update** (capability extension)

The escalation is human-approved — the system proposes, the human decides.

*Acceptance: The system proposes promoting a detected pattern to a specific artifact type with a draft implementation. The human can approve, modify, or reject. Approved promotions create functioning skills/hooks/rules.*

**R4.3 — Escalated artifacts are stored and tracked.**
Promoted patterns are stored in the artifact store with lineage back to the observations that prompted them. This enables auditing ("why does this skill exist?") and feedback ("did this skill actually help?").

*Acceptance: After promoting a pattern to a skill, the skill's artifact entry includes derives_from references to the session summaries where the pattern was observed.*

### Constraints

- The existing `/compound-learnings` skill provides a starting point. This requirement formalizes and integrates it with the artifact store.
- Escalation must not create rule sprawl. The decision tree (sequence → skill, event → hook, heuristic → rule) prevents promoting everything to the same artifact type.

---

## Requirement 5: Knowledge Quality

**Vision reference:** "Persistent Context That Compounds" (usage-weighted feedback), "Compounding over features"

### What

As the knowledge base grows, retrieval quality degrades — more results, more noise, harder to find what's actually useful. The system needs signal about which stored knowledge is valuable, so that search results stay sharp and stale content can be retired. This signal comes from the AI agents who consume the knowledge, not from human curation.

The key constraint: signal must emerge from work that's already happening, not from separate rating ceremonies. Where a ready-made grader already exists (e.g., the synthesis model during reviews), we use it. Where no natural grading moment exists, we design lightweight feedback that agents can emit during normal work.

### Capabilities

**R5.1 — Usage feedback.**
When an AI agent retrieves knowledge from the artifact store and uses it during work, it can record whether the retrieved content was useful. This is a lightweight signal — a quick annotation at the point of use, not a formal review. Multiple agents contribute feedback over time; an artifact that's consistently useful to different agents in different contexts is high-signal.

*Acceptance: An agent retrieves 3 artifacts during a session. It marks one as useful and one as not useful (the third gets no feedback). The useful artifact's utility score increases. Unfeedback'd artifacts are unaffected.*

**R5.2 — Confidence annotation.**
When storing or updating knowledge, agents can annotate their confidence level. Information known to be provisional, speculative, or time-sensitive gets lower confidence. Confidence is a property of the content at write time, distinct from usage feedback which is a property of retrieval quality.

*Acceptance: Store an artifact with high confidence and another with low confidence on the same topic. Search returns the high-confidence artifact first. An agent later discovers the low-confidence item was wrong and marks it as superseded.*

**R5.3 — Quality-weighted retrieval.**
Search results incorporate usage feedback and confidence. Artifacts that were useful in past retrievals rank higher. Low-confidence items rank lower. Items with no signal get neutral treatment — no penalty for being new.

*Acceptance: Two artifacts on the same topic with similar semantic match. One has positive usage feedback from 3 agents; the other has none. The high-feedback artifact ranks first.*

**R5.4 — Retirement.**
Artifacts with consistently low utility, low confidence, or sufficient age can be archived to manage store size. Archived items are excluded from default search but retrievable with an explicit flag. Retirement can be suggested automatically (based on signal) but requires confirmation before executing.

*Acceptance: An artifact has received negative feedback from multiple agents over several weeks. The system flags it as a retirement candidate. After confirmation, it is archived and no longer appears in default searches.*

**R5.5 — Review quality grading.**
During multi-model review synthesis, each reviewer's output is graded for quality. The synthesis model — which already evaluates findings for consensus, contradictions, and unique contributions — is a ready-made grader. It emits a quality grade per reviewer alongside the synthesis. Grades accumulate over time, building a per-model, per-review-type dataset that informs future model selection.

*Acceptance: After a multi-model review, each reviewer's output has a quality grade stored as feedback on its review artifact. Historical grades are queryable by model and review type. The grading does not require human intervention — it happens as part of synthesis.*

### Constraints

- Signal comes from AI agents, not human curation. The human may occasionally rate something, but the system does not depend on it.
- No signal = neutral. New artifacts are not penalized for having no feedback yet.
- Retirement is suggested, not automatic. The system flags candidates; confirmation is required before archiving.
- Quality grades are advisory — they inform model selection but don't automatically exclude models.

---

## Requirement 6: Spec-Driven Development Workflow

**Vision reference:** "Structured workflows beat ad hoc prompting," "Progressive refinement"

### What

A formalized workflow for the vision → requirements → spec → implementation pipeline, with multi-model review at each transition. Currently this process happens ad hoc — the human knows the steps, invokes them manually, and manages the artifacts. This requirement makes it a repeatable, partially automated workflow.

### Capabilities

**R6.1 — Stage templates.**
Each stage (vision, requirements, spec, implementation) has a template or prompt that guides its creation: what sections to include, what questions to answer, what level of detail is appropriate. These templates encode the lessons from prior projects (e.g., "requirements need acceptance criteria," "specs need to reference the requirements they satisfy").

*Acceptance: When starting a new requirements document, the system provides a template or structured prompt. The template reflects the conventions established in prior projects.*

**R6.2 — Review gates between stages.**
Transitioning from one stage to the next triggers a multi-model review (Requirement 2) of the current stage's artifact. The review results are stored. The human decides whether to proceed, revise, or iterate.

*Acceptance: After completing a vision doc, invoking "ready for review" dispatches it to multiple models, stores the synthesis, and presents findings to the human. The human decides whether to proceed to requirements.*

**R6.3 — Artifact lineage.**
Each artifact knows what it derives from. A requirements doc references its vision doc. A spec references its requirements. Review findings reference what they reviewed. This lineage is stored as metadata, enabling queries like "show me everything related to project X" or "what reviews were done on this spec?"

*Acceptance: Create a vision doc, then a requirements doc that derives from it. Query the artifact store for "artifacts related to [vision doc]." The requirements doc and any reviews appear in results.*

**R6.4 — Workflow state tracking.**
The system tracks where a project is in the pipeline: which stages are complete, which is current, what's next. This state persists across sessions and is loadable on session start. For the implementation stage, the system tracks a set of work items derived from the spec. Work items have a status (pending, in-progress, complete) that the human updates via command or tool call. The system persists this state and presents it on session start.

*Acceptance: Start a project, complete the vision stage. In a new session, the system reports that vision is complete and requirements is the next stage. During implementation, create work items from the spec. Mark items as complete via command. The system reports remaining work. State loads on session start without manual reconstruction.*

### Constraints

- The workflow is advisory, not enforcing. The human can skip stages, revisit earlier stages, or deviate from the pipeline. The system tracks state but doesn't block non-sequential work.
- Templates are starting points, not rigid formats. They should be editable and should evolve as conventions develop.

---

## Requirement 7: Connector Interface

**Vision reference:** "The hard part is connectors," "View, don't warehouse"

### What

A defined interface for integrating data sources — both internal (the artifact store, the filesystem) and external (email, spreadsheets, calendars, etc.) — so that connectors can be added incrementally without redesigning the system.

### Capabilities

**R7.1 — Connector interface specification.**
A documented interface that any connector implements: what it must provide (query, list, authenticate), what it may provide (write-back, subscribe to changes), and how it registers with the system.

*Acceptance: The interface is documented with required methods, error model, and authentication contract. A developer (human or AI) reading the spec could build a new connector without studying the existing codebase.*

**R7.2 — The native artifact store is itself a connector.**
The artifact store (Requirement 1) implements the connector interface. This validates the interface design against a real implementation and ensures the query patterns work.

*Acceptance: The artifact store is queryable through the same interface that other connectors use. A semantic search through the connector interface returns the same results as a direct artifact store query.*

**R7.3 — File system connector as reference implementation.**
A simple connector that indexes markdown files from a directory (e.g., thoughts/). This demonstrates the connector lifecycle: scan, embed, index, query. It serves as the template for building further connectors.

*Acceptance: Point the file system connector at a directory of markdown files. After indexing, semantic search across those files works through the connector interface.*

**R7.4 — Federated queries across connectors.**
A single query can span multiple registered connectors, with results merged and ranked. This is the "unified view" the vision describes — the user asks a question and gets answers drawn from all connected sources, not one source at a time.

*Acceptance: With two connectors registered (artifact store and filesystem), a single semantic query returns results from both sources, merged into a single ranked list. Results indicate their source connector.*

### Constraints

- The interface should be simple enough that building a new connector is days of work, not weeks.
- Connectors should be addable without modifying the core system — registration, not integration.
- The interface must support both "query in place" (the connector queries the source live) and "index and cache" (the connector pre-indexes content for faster retrieval). Different sources will need different strategies.

---

## Cross-Cutting Concerns

### Security

- The artifact store holds personal data (decisions, notes, plans). It must not be publicly accessible.
- MCP access to the store requires authentication (existing OAuth 2.1 flow).
- No credential storage in the artifact store itself. Connector credentials are managed separately.
- Artifacts are sent to third-party APIs for embedding (R1) and review (R2). The user controls which models are used and should be aware of data flows. The system should support marking artifacts as sensitive (local-processing-only) to prevent them from being sent to external APIs.
- **Access boundaries (vision ref: "Security proportional to exposure"):** The vision distinguishes discoverability (any agent can find out what exists) from content access (scoped per role). The current posture is permissive — all roles can access all data — with the infrastructure supporting scoping when a reason emerges. Role-scoped and connector-scoped access are not yet required but the architecture must not preclude them.

### Failure Handling

- **Embedding failure:** Artifact write succeeds even if embedding generation fails (store content and metadata, mark as pending-embedding, retry embedding later). A pending-embedding artifact is retrievable by ID and metadata filters but won't appear in semantic search until embedded.
- **Review model failure:** If one model in a multi-model review fails, the workflow completes with the remaining models' results. The synthesis notes which models were requested vs. which responded. Partial results are stored — a 2-of-3 review is better than no review.
- **Ingestion idempotency:** Re-running ingestion on the same files does not create duplicate artifacts. Deduplication is by content hash or source path + timestamp.
- **Summarization fork failure:** A fork that crashes or times out is logged but does not affect the main session. The mechanical log is not truncated on fork failure (preserving data for the next successful fork).

### Performance

- Semantic search should return results in under 2 seconds for a store of up to 10,000 artifacts (average artifact size ~2K chars, mixed filter/no-filter queries, cold process / warm index, p95 latency).
- The system must run within nexus's 4GB RAM. This likely means API-based embeddings rather than a local model, or a very small local model.

### Data Durability

- Artifacts are stored on the attached Hetzner volume (50GB, separate from boot disk).
- The storage format must support standard backup tools (see R1.7). Backup frequency and retention policy are operational concerns, not requirements.

---

## Dependencies

These requirements have structural dependencies that constrain implementation order but do not prescribe it:

- **R1 (Artifact Store)** is foundational. R2, R3, R5, and R6 all store into or query from it.
- **R7 (Connector Interface)** depends on R1 — the artifact store is both a consumer and a reference implementation of the interface.
- **R2 (Multi-Model Review)** depends on R1 for storing results.
- **R3 (Context Continuity)** has a phased dependency on R1. Internal sub-dependencies: R3.5 (mechanical log) is already implemented, no new work; R3.7 (window file architecture) is the new core with no external dependencies; R3.2 and R3.6 depend on R3.7 and R3.5; R3.3 Phase 3 (chain loading) depends on R3.7; R3.3 Phase 3.5 (semantic retrieval) and R3.1 depend on R1; R3.4 Phase 3 (frontmatter migration) has no external dependencies, R3.4 Phase 3.5 (artifact ingestion) depends on R1.
- **R5 (Knowledge Quality)** depends on R1 for artifact metadata and feedback storage.
- **R4 (Capability Compounding)** depends on R1 (pattern detection queries the store), R3 (session summaries are the input), and R5 (quality data informs which patterns are worth promoting).
- **R6 (Spec-Driven Development)** depends on R2 (review gates) and R1 (artifact lineage).

Note: R3.5 (mechanical log) is already implemented. R3.7 (window file architecture) has no dependency on R1 and is the foundation for Phase 3 — it can be built independently as a standalone improvement. (Naming note: "R3.5" is a requirement ID for the mechanical log. "Phase 3.5" in the build order is the semantic retrieval phase. Different concepts with similar numbering.)

---

## What Success Looks Like

1. You can store any text artifact and find it later by meaning, not just by filename or keyword. You can archive outdated artifacts and back up the entire store.
2. You can review any document with multiple models in one command and get a synthesized set of findings.
3. Session context is richer — past decisions and artifacts are surfaced on session start, mid-session summaries are captured automatically, and compaction preserves what matters.
4. Recurring patterns in your workflow are detected — both on demand and automatically — and can be promoted into durable skills, hooks, or rules. The system's capabilities grow, not just its knowledge.
5. Knowledge quality is tracked through agent usage feedback and confidence, so useful precedents rank higher in future retrieval. The system learns from what worked.
6. Starting a new project follows a structured workflow with review gates from vision through implementation, and the artifacts from that workflow are automatically stored and linked.
7. External data sources can be integrated incrementally through a proven connector interface, with federated queries spanning all connected sources.

---

## What This Document Is For

This narrows the vision into concrete, testable requirements. Next step:

1. **Review these requirements** — with multiple models, as the workflow prescribes
2. **Spec** — technical design: data model, API surface, embedding strategy, CLI/skill interfaces. The spec determines phasing, build order, and incremental delivery strategy.
3. **Implementation** — piece by piece, reviewed at each stage
