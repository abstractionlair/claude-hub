# System Ontology

*March 22, 2026*
*Derives from: review-ontology-and-architecture.md, 4-model review (Gemini, GPT-5.4, Sonnet)*
*Supersedes: role definitions in plan-infrastructure-redesign.md Section 1*

## Concepts

### Role

A job description applied to interactive sessions. Defines responsibilities, expectations, scope, and constraints — not identity. The model brings its own identity.

Current roles: **workbench** (general-purpose interactive work), **sysadmin** (VPS management), **mcp-server** (responding to incoming MCP requests).

### Project

An umbrella for related work. The answer to "what is this about?" A project may encompass code, services, agents, research, and data. The git repo is the project root; non-code subdirectories (services/, agents/, research/, data/) live within it.

Examples: prediction-markets, claude-hub, claude-chat, ai-research-ontology, simple-publications.

Not every project has code. A research project may be primarily documents, analysis, and an agent that ingests papers. Still git-tracked.

### Service

A persistent process that runs continuously or responds to requests without deliberative AI reasoning at runtime. Operationally: always-on or event-driven.

Examples: claude-hub FastAPI server, polymarket data collector, nginx, PostgreSQL.

### Agent

An autonomous work loop that invokes a model for judgment at runtime. Operationally: may be always-on, scheduled, or triggered. Distinguished from a service by the use of a model for decision-making in the loop.

Examples: market scout (classifies markets via LLM), paper ingestion agent (finds and categorizes research), chat instance (answers user queries via web chat).

The agent/service boundary is based on current implementation, not permanent identity. A service that adds model-based reasoning becomes an agent; an agent whose model calls are replaced by deterministic logic becomes a service. This is a label update, not a philosophical change.

### Task

A discrete unit of scheduled work that runs and completes. May or may not involve a model. Simpler than an agent (no ongoing responsibility or continuity).

Examples: weekly data pipeline, daily CBOE options collection, session archiving, database backups.

(Named "task" rather than "job" to avoid collision with roles being described as "job descriptions.")

### Resource

Durable infrastructure that no agent owns, no project defines, and no role constitutes. Persistent environmental facts that other concepts depend on.

Examples: PostgreSQL database (claude_hub), FUSE storage mounts (/storage/), email sync (IMAP via mbsync), GitHub mirror (~/repos/), the attached data volume, SSL certificates.

### Session

A concrete execution — a specific run of an interactive session, agent invocation, or task. The runtime instance of work. Window files describe sessions.

A session has:
- A **role** (who was working, for interactive sessions)
- One or more **projects** (what was being worked on)
- Optionally a **service** or **agent** (what was being operated)
- A **workstream** (what kind of activity)
- A **component** (what kind of thing was being worked on)

This concept bridges the durable ontology (role, project, agent) and the concrete record (window files, logs).

## Tagging Dimensions

Two orthogonal axes classify work within a project:

### Workstream (activity type — what you're doing)

- **development** — writing code, tests, SDLC
- **research** — investigation, literature, analysis, producing documents
- **operations** — running, monitoring, maintaining, deploying

### Component (thing type — what you're working on)

- **codebase** — source code, tests, build system
- **service** — a running process or its configuration
- **agent** — an autonomous work loop or its definition
- **task** — a scheduled job or its configuration
- **dataset** — collected or generated data
- **document** — design docs, specs, research papers

A session can be tagged on both axes independently. "Developing the market-scout agent" is workstream:development + component:agent. "Researching calibration methodology" is workstream:research + component:document.

## Window File Frontmatter

```yaml
---
role: workbench
projects: [prediction-markets, claude-hub]   # array — sessions often touch multiple
workstream: development                       # activity type
component: codebase                           # thing type
service: null                                 # if operating a specific service/agent
session_id: "abc-123"
parent: "2026-03-21T21-58-00Z.md"
children: []
harness: "claude-code"
finalized: false
created: "2026-03-22T12:00:00Z"
updated: "2026-03-22T12:30:00Z"
---
```

## Directory Structure (Option B + D metadata)

```
~/
├── projects/                        # All active projects
│   ├── prediction-markets/          # git repo (project root)
│   │   ├── src/                     # code
│   │   ├── tests/
│   │   ├── collectors/              # collector code
│   │   ├── services/                # systemd units, service configs
│   │   ├── agents/                  # agent definitions
│   │   ├── research/                # analysis, papers, review artifacts
│   │   ├── data/                    # → symlink to volume or .gitignored
│   │   └── docs/
│   ├── claude-hub/                  # git repo
│   │   ├── src/
│   │   ├── docs/
│   │   ├── services/
│   │   └── ...
│   ├── claude-chat/                 # git repo
│   ├── simple-publications/         # git repo (or symlink to volume)
│   └── ai-research-ontology/        # git repo
│
├── roles/                           # git repo — role definitions
│   ├── workbench/
│   │   ├── shared.md                # role instructions
│   │   ├── CLAUDE.md                # harness-specific situating
│   │   ├── GEMINI.md
│   │   ├── AGENTS.md
│   │   └── windows/                 # role-scoped window files
│   ├── sysadmin/
│   └── mcp-server/
│
├── shared/                          # cross-cutting infrastructure
│   └── infrastructure-manifest.md   # capabilities index + environment facts
│
├── bin/                             # scripts: role, session-archive
├── repos/                           # → /storage/local/repos (GitHub mirror, read-only)
├── archive/                         # retired projects/files
│
├── .claude/                         # → volume (hooks, skills, scripts, settings)
├── .gemini/                         # Gemini CLI config + hooks
└── .config/opencode/                # OpenCode config + plugins
```

## Instruction Delivery (Four Tiers)

| Tier | What | How delivered | Precedence |
|------|------|--------------|------------|
| 0. Harness global | `~/.claude/CLAUDE.md`, settings.json | Loaded at harness startup | Most general |
| 1. Role + manifest | Job description, infrastructure index | Hook injection (survives compaction) | General |
| 2. Project | Codebase conventions, architecture | Native JIT loading by harness | Specific |
| 3. Subdirectory | Module-specific rules | Native JIT loading by harness | Most specific |

More specific wins for overridable conventions (formatting, test patterns). Role-level operating constraints (continuity behavior, infrastructure contracts) are non-overridable.

## Manifest Structure

Two sections with different trust levels:

```
## Capabilities (stable)
/fork-agent, /launch-model, /session-search, /artifact-store, /query-database,
/review, /system-admin, /write-design-doc, /debug-python, /publish-simple-publication,
/test-driven-development, /hook-developer, /writing-style

## Environment (verify before acting)
DB: postgres@localhost:5432 (claude_hub)
Web: claude-hub :8420, nginx :80/:443
Storage: /storage/{google,onedrive,pcloud,dropbox} (FUSE — NEVER traverse recursively)
  Safe subdirs: local/, mail/, calendar/, contacts/, dropbox/
Email: IMAP via mbsync → /storage/mail/
Volume: attached data volume — data, postgres tablespace
GitHub mirror: ~/repos/ (read-only, not active working copies)
Collectors: polymarket (persistent), cboe/fred/coingecko (daily), weekly pipeline
```

## What This Document Supersedes

- Role definitions in `plan-infrastructure-redesign.md` Section 1 — replaced by this ontology
- The "persona" framing in `vision-personal-ai-infrastructure.md` Draft 13 Section 4.1 — roles are job descriptions, not personas
- Window file frontmatter schema — expanded with workstream, component, projects (array)
- Manifest structure — split into capabilities (stable) vs environment (verify)
