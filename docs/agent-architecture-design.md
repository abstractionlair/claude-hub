# Agent Architecture Design

Status: Early design. Captures the conceptual model and open questions from the Feb 26, 2026 design session (Scott + Main Claude).

## Context

Claude Hub currently runs Claude Code processes for chat and MCP. All processes use the same Linux user (`claude`), the same credentials (Max subscription), and the same model (Opus). The group chat bus enables multi-participant conversations, but every AI participant is the same model with the same identity.

Parallel developments motivating this design:
- Multi-model review findings (Bedrock portfolio at work: different models catch different things)
- Three CLI subscriptions confirmed working: Claude Max, ChatGPT Pro, Gemini
- Rate limits are per-model and per-provider — spreading work extends throughput
- The receptionist concept: a cheap model as the front door, escalating to specialists
- Accumulated experience with ledgers, memory files, and hooks for session continuity

## Core Concept: What Is an Agent?

An agent is **{identity, shared state, responsibilities}**.

An agent is NOT {one model, one set of credentials}. The model is a parameter of each conversation, not a property of the agent. The agent called "reviewer" maintains a single accumulated understanding, but might use Claude for architectural reviews and Gemini for large-context scans.

### Atomic Agent Unit

Four components, all required. 1-3 give you a usable worker. 4 is what makes it an agent
that accumulates knowledge and maintains continuity across conversations.

**1. Identity** — Linux user, credentials, CLI access
- A Linux user with home directory
- Authenticated to whichever CLIs/billing contexts this agent uses
- Own `~/.claude/`, `~/.codex/`, `~/.gemini/` with credentials
- Symlinks for shared config (skills, hooks, rules) from a common source
- Access to CLI binaries (system-wide for codex/gemini, symlink for claude)

**2. Process launcher** — bidirectional pipe to any supported CLI/model
- Takes: CLI name, model, prompt/priming, working directory
- Returns: process handle with stdin/stdout pipes
- Handles CLI differences internally (claude stream-json, codex JSONL, gemini JSON)
- Runs as the agent's Linux user (`sudo -u {agent-user}`)
- The pipe is the universal interface — whoever needs to talk to this model gets the pipe

**3. Permissions** — access to shared resources
- Group membership for read access to project repos, `/storage`, shared databases
- Agent's own directories are `750` — group can read, only owner writes
- Linux file ownership enforces responsibility boundaries (not just conventions)
- Postgres: per-agent database roles with appropriate grants
- Git repos: shared group read, per-user worktrees for concurrent editing

**4. State** — ledger + append log + session-start loading
- Shared state file (ledger): what am I, what do I know, what's my current situation
- Append-only log: where conversations write tagged observations (JSONL)
- Session-start hook that loads the ledger into each new conversation
- Without this, the agent is stateless between conversations — a tool, not an agent
- Model-agnostic: any CLI/model can read a ledger and append to a JSONL log

### Agent Properties (Summary)

| Property | Description |
|---|---|
| **Identity** | Linux user, credentials, billing context |
| **Process launcher** | Bidirectional pipe to any CLI/model, running as this user |
| **Permissions** | Group-read shared resources, user-write own state, enforced by kernel |
| **Shared state** | Ledger, memory, append-only knowledge log, loaded at conversation start |
| **Responsibilities** | What this agent is for (triage, review, implementation, etc.) |
| **Conversations** | Multiple concurrent short-lived threads |

### Ownership and Concurrency

Cross-agent concurrency is solved by responsibility boundaries enforced by Linux file
permissions. Each agent owns its part of the system — the kernel prevents cross-boundary writes.

Intra-agent concurrency (multiple conversations within one agent) uses lighter-weight
coordination: append-only log for knowledge, git worktrees or file locks for code editing.
Forks of the same agent share identity, state, and trust — they're threads in a process,
not separate processes. The owner is never a bottleneck because it can fork itself to handle
concurrent tasks, and the forks know how to coordinate.

### The Git Analogy

- An **agent** is a repo — persistent shared state, accumulated history
- **Conversations** are feature branches — short-lived, focused, branch from and merge back to shared state
- **Shared state** is main — the ledger, memory, knowledge that all conversations read from
- **The append-only log** is the commit history — immutable, tagged by thread
- **Distillation** is like a maintainer curating the changelog from raw commits

## Architecture

### Per-Agent (Linux User)

```
/home/{agent-name}/
├── .claude/              # Claude CLI config + credentials
├── .codex/               # Codex CLI config + credentials
├── .gemini/              # Gemini CLI config + credentials
├── state/
│   ├── ledger.md         # Current shared state (the "main branch")
│   ├── memory/           # Accumulated knowledge (curated)
│   ├── append.log        # Append-only knowledge log (raw, tagged by thread)
│   └── config.json       # Agent config: responsibilities, model preferences
└── conversations/        # Active and recent conversation state
```

### Append-Only Knowledge Log

Concurrent conversations never mutate shared state directly. They append tagged observations:

```jsonl
{"thread_id": "abc123", "timestamp": "2026-02-26T16:30:00Z", "model": "claude-opus-4-6", "type": "observation", "content": "PASS filtering works — no streaming needed in group chat"}
{"thread_id": "def456", "timestamp": "2026-02-26T16:31:00Z", "model": "gemini-2.5-pro", "type": "discovery", "content": "message_router.py line 280 has a potential race if two Claudes finish simultaneously"}
{"thread_id": "abc123", "timestamp": "2026-02-26T16:35:00Z", "model": "claude-opus-4-6", "type": "decision", "content": "Removed streaming from group chat — architectural simplification, not just bug fix"}
```

Properties:
- **Append-only**: No concurrent write conflicts, ever
- **Tagged by thread**: Accumulated knowledge remains interpretable
- **Tagged by model**: Consumers know who wrote what
- **No real-time coordination needed**: Threads write independently

### Distillation Process

A separate systemd service per agent that:
1. Reads the append-only log (read-only consumer)
2. Deduplicates, resolves contradictions, extracts patterns
3. Writes refined insights to the agent's curated memory (separate location)
4. Runs on its own schedule, not in the critical path of any conversation

The distillation model can (and maybe should) be different from the conversation models.
Gemini's strength at "bringing order to large quantities of poorly organized data" makes it a natural candidate. The diversity benefit applies here too — a different model reading accumulated observations might notice patterns the originating models are blind to.

Inspired by [Continuous-Claude-v3](https://github.com/parcadei/Continuous-Claude-v3/).

### Cross-Agent Shared Data

| Resource | Current | Target |
|---|---|---|
| Project repos | `/home/claude/claude-hub/` | Shared via group permissions or bind mounts |
| Persistent storage | `/storage/` | Already shared (bind mount) |
| Databases | Scattered SQLite files | **Postgres** — proper concurrent access, cross-agent queries |
| Conversations DB | `.claude/conversations.db` | Postgres: multi-user, cross-agent queryable |
| Append logs | Per-agent files | Postgres table: `agent_id, thread_id, timestamp, model, type, content` |

Postgres is likely the forcing function for cross-agent coordination. Multiple agents/processes hitting SQLite across users is fragile. Postgres gives concurrent access, connection pooling, and cross-agent queries ("what has any agent learned about message_router.py?").

### Conversation Lifecycle

```
1. Start: Read agent's shared state (ledger + curated memory)
2. Work:  Execute task, accumulate observations
3. Append: Write tagged observations to append-only log
4. End:   Conversation completes, resources freed
```

Conversations should be **short-lived** — this minimizes divergence from shared state, like keeping feature branches small. Long-running work should checkpoint frequently via appends.

## Model Dispatch

The receptionist (or dispatch layer) selects a model for each conversation based on:

```
task_type → model_preference     (from agent config + capability mapping)
quota_state → model_availability (which pools have capacity)
cost_tier → model_selection      (cheapest that meets capability threshold)
```

Model profiles (from `docs/multi-model-registry.md`) encode the options. The dispatch layer handles CLI differences, output format parsing, and credential routing (which Linux user to run as).

## Open Questions

### Multi-Model Authorship of Shared State

The curated memory and ledger are currently single-model-authored (Claude). Introducing other models as authors changes the consistency of the accumulated state. Considerations:

- **The append log is fine** — it's raw data, tagged by model. Any consumer can see who wrote what.
- **Curated memory is harder** — if Gemini distills the log but Claude consumes the result, there's a translation layer. The structured format of ledgers (sections, checkboxes, explicit state) helps — it's already a model-agnostic interop format.
- **Human contributions are the most model-agnostic content.** Scott's direct inputs (pasted artifacts, research, corrections) carry no model-specific assumptions. Preserving these verbatim and tagged as human-sourced could anchor the shared state.

### How Many Agents?

Possible decomposition:

| Agent | Responsibilities | Primary model(s) |
|---|---|---|
| Receptionist | Triage, routing, simple lookups | Haiku, Gemini Flash, Codex Mini |
| Main Claude | Architecture, complex implementation, executive function | Claude Opus |
| Reviewer | Independent code review, locate scans | Codex, Gemini Pro, non-implementing model |
| Builder | Spec-driven feature implementation | Codex (high effort), Claude Sonnet |

Or it might be fewer. The receptionist is the clearest standalone agent. Whether Main Claude and Reviewer need to be separate agents or just different conversations within one agent is TBD.

### Credential Topology

| Approach | Pros | Cons |
|---|---|---|
| One user per agent | Clean isolation, no switching | User management overhead |
| One user per billing context | Fewer users, env var switching | Codex can't switch back to subscription without browser |
| Hybrid: subscription users + API key users | Best of both | More complex |

The Codex limitation (switching back to subscription requires browser OAuth) pushes toward separate users for separate billing contexts at minimum.

### Distillation: Conversation, Not Batch

Initial framing was a batch job (read log, write summary). Better model: **distillation as a group conversation**.

The distiller model joins a conversation with the agent whose sessions produced the observations.
The agent provides context, corrects misinterpretations, explains why seemingly contradictory
entries are both correct. This directly addresses semantic drift — the originating model is
present to catch it.

**Cadence:** Nightly or on-demand, not real-time. Distillation is housekeeping, not a gating
function. New conversations read the raw append log directly (recent entries) plus curated
memory (older, distilled knowledge).

**Filled context windows:** If the session being distilled already hit its context limit and
continued in a new session, the original context is partially lost. For these cases, the append
log entries from the original session serve as the shared reference material — both the distiller
and the resumed agent read them. Accept that distillation of very old sessions relies on the log
alone, not live conversation.

### Concurrent File Modification

The append-only log solves concurrent *thinking*. It does not solve concurrent *editing* of
code, config, or other shared artifacts. Two agents modifying `message_router.py` simultaneously
will corrupt each other's work.

Options:

| Approach | Mechanism | Tradeoff |
|---|---|---|
| Git worktrees | Each conversation gets an isolated worktree, merges back | Merge conflicts in code are hard to resolve automatically |
| File-level locks | Conversations claim files before editing | Simple but coarse-grained |
| Single-writer rule | Only one conversation per agent in "editing mode" at a time | Constraining but safe |
| **Responsibility boundaries** | **Agents own different parts of the system** | **Conflicts mean your boundaries are wrong** |

The responsibility boundary approach is the most architecturally aligned. If agents have defined
responsibilities, they should operate on different parts of the system. The reviewer never edits
code. The builder owns `src/`. The receptionist owns routing config. Ownership boundaries prevent
conflicts by design, and a conflict signals a design problem, not a runtime problem.

Within a single agent running multiple concurrent conversations, git worktrees or single-writer
are the practical options. Claude Code already supports `--worktree`.

## Multi-Model Review Feedback (Feb 26, 2026)

The design was independently reviewed by Codex (GPT-5.1-Max, extra_high reasoning) and
Gemini (3.1 Pro Preview). Both read the design doc and supporting context.

### Convergent Findings (Both Models)

- **Append-only log is right** but needs: strict JSONL schema, validation, size limits, rotation
- **Distillation is harder than summarization** — contradiction resolution requires understanding
  the code, not just the observations. Needs conflict markers, not silent merges.
- **Postgres is not casual** — solves data concurrency but not logical concurrency
- **Schema governance is missing** — typed schemas, versioning, required fields, redaction rules

### Unique Findings

**Codex:**
- Security: untrusted model could inject prompt-injection artifacts into the log
- Human-in-the-loop: need a mechanism to pin facts that distillation cannot overwrite
- Wants: reproducible test harness, structured data over prose, "no internet" mode for
  deterministic runs, clear tool entrypoints with mocks/fixtures

**Gemini:**
- **Codebase concurrency** — concurrent thinking solved, concurrent file editing not addressed
  (the biggest gap identified). Agents editing the same file need a mutex or worktree pattern.
- State reversion: distillation corruption needs snapshots/backups before each run
- Human authority: mechanism for definitive human overrides that distillation respects
- Context window economics: shared state read at conversation start will grow unboundedly
- Receptionist misclassification risk: cheap model routing complex work to weak model costs more
  than using a capable model directly
- Wants: broad read access (leverage large context), tailored system prompts (not Claude's
  copy-pasted), explicit heuristics for contradiction resolution, raw stateless I/O for
  system tasks (not faux-chat wrappers)

### Design Assumptions (implicit, confirmed as intentional)

- Only trusted models participate (no untrusted model concern)
- System prompts will be tailored per model, not one-size-fits-all
- New conversations read raw append log (recent) + curated memory (older), not just distilled
  output — the stale-reads concern only applies if conversations are restricted to curated memory

## Bootstrapping: Reference Implementation Pattern

New agents are not configured via templates, additive config injection, or CLI-specific
wrappers. Instead, they are bootstrapped by pointing them at the **reference implementation**
and telling them to create their own equivalent.

### The Reference Implementation

The current Claude-based system in this project:
- `CLAUDE.md` — entry point, project instructions, role definition
- `~/.claude/settings.json` — hooks registration (SessionStart, PreCompact, Stop, etc.)
- `.claude/hooks/` — shell wrappers → TypeScript handlers
- `thoughts/ledgers/` — continuity ledgers (shared state format)
- `~/.claude/projects/*/memory/` — accumulated knowledge
- The append-only log pattern and distillation model (this design doc)

This is not a template to copy. It is an example to understand and adapt.

### Bootstrapping a New Agent

The first conversation with a new agent is:

> "Read `/home/claude/claude-hub/CLAUDE.md` and the docs it points to, especially
> `docs/agent-architecture-design.md`. This is how the reference agent maintains state
> across conversations. Understand the intent — ledger format, append-only observations,
> session-start loading, periodic checkpoints. Now set up equivalent mechanisms for
> yourself using your native tools. Your state directory is `~/state/`, your append log
> is `~/state/append.log`."

The agent then:
1. Reads and understands the reference implementation
2. Creates its own version using **idiomatic mechanisms for its CLI**
   - Codex: `codex.md`, `config.toml` settings, whatever hooks Codex supports
   - Gemini: `GEMINI.md`, `settings.json`, system instructions
   - Claude (new instance): own `CLAUDE.md`, own hooks, own settings
3. Owns its config files entirely — no composability conflicts with project configs
4. Documents what it set up and why (append to its own log)

### Why This Works

- **No composability conflicts** — each agent owns its own config, never touches
  another project's CLAUDE.md or codex.md
- **Idiomatic per-CLI** — Codex's version uses Codex patterns, Gemini uses Gemini patterns.
  Not Claude patterns crammed into a different CLI.
- **Self-documenting** — the agent understands *why* the state mechanism exists because
  it read the reference, not just *how* to copy config
- **Evolvable** — when the reference improves, ask agents to re-read and update their setup
- **Model-agnostic state format** — the ledger format and JSONL append log are plain text.
  Any model can read and write them regardless of CLI.

### Limitations

Mid-conversation hooks (periodic checkpoints, pre-compaction) are Claude Code-specific.
For CLIs without hook systems, the priming instructions ask the model to output observations
in a parseable format (e.g., `<observations>` blocks) that the process launcher captures
from stdout and writes to the append log. This is model-agnostic but depends on the model
following the instruction reliably.

## Relationship to Existing Infrastructure

This design extends (not replaces) the current system:
- **ConversationBus** becomes one way conversations happen (group chat)
- **ChatProcessManager** becomes one backend for spawning model processes
- **Ledger format** remains the interop format for shared state
- **MCP service** becomes the external interface that the receptionist handles
- **Hooks** continue to work per-conversation for checkpoint/continuity

## Next Steps

1. Design the model profile / dispatch layer (concrete config format)
2. Prototype append-only log (could start as JSONL file, migrate to Postgres)
3. Set up a second Linux user as proof of concept (receptionist agent)
4. Test cross-user process dispatch (`sudo -u`)
5. Prototype distillation as group conversation (not batch)
6. Define responsibility boundaries for initial agent set
7. Design human override / pinning mechanism for curated memory
