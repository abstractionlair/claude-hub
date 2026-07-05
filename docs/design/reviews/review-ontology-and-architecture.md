# Review Request: Infrastructure Ontology and Architecture Decisions

*March 22, 2026*

## Context

We are building a personal AI infrastructure on a VPS. One human (Scott), multiple AI models (Claude, Gemini, GPT, Kimi, etc.), multiple harnesses (Claude Code, Gemini CLI, OpenCode), multiple concurrent sessions. The system has been growing organically and we're now formalizing the architecture.

This document captures our current design decisions and an open ontology question. We want independent review of both.

## Part 1: Decisions Already Made

### 1.1 Roles are job descriptions, not personas

A "role" defines responsibilities, expectations, scope, and constraints — NOT identity. The model brings its own identity; the role tells it what it's been asked to do.

Current roles: workbench (general-purpose interactive work), sysadmin (VPS management), mcp-server (responding to incoming MCP requests from remote clients).

We dropped "researcher" because it described a mode of work (deep investigation) rather than a set of responsibilities. Any role can do research.

### 1.2 Launch from project directory, inject role via hooks

The harness launches in the project directory so native instruction loading (CLAUDE.md, GEMINI.md, AGENTS.md) handles project-specific context. Role instructions are injected via hooks that fire on session start and survive compaction/clear.

Each hook injects three things:
1. **Harness-specific situating context** — explains how the session was launched, how instruction layers work, what the model should expect
2. **Role instructions** (shared.md) — the job description
3. **Infrastructure manifest** — a brief index of available capabilities and infrastructure facts

### 1.3 Three-tier instruction delivery

| Layer | What | How delivered |
|-------|------|--------------|
| Role identity + manifest | Job description, infrastructure awareness | Hook injection (persists across compaction) |
| Project instructions | Codebase conventions, architecture | Native JIT loading by harness |
| Subdirectory instructions | Module-specific rules | Native JIT loading by harness |

Precedence: most specific wins (subdirectory > project > role).

### 1.4 Claude Code is the primary harness

All hooks, continuity (window files, narrative updates), skills, and infrastructure are built for Claude Code. Gemini CLI and OpenCode have basic role injection and can be used for multi-model reviews, but lack window file continuity. Skills use the same SKILL.md format across all three harnesses and are portable. Fork/session management exists in all three (different syntax).

### 1.5 Window files for continuity

Window files are markdown documents that capture session narrative — what was done, decisions made, open threads. They form a linked chain (parent/child pointers in frontmatter). Hooks automatically:
- Create new window files on session start
- Fork narrative agents to update window files periodically and before compaction
- Re-inject window file content after compaction/clear

Window files are currently stored per-role (`~/roles/{name}/windows/`), enabling cross-project continuity within a role.

### 1.6 Version control as audit trail

Nearly everything is git-tracked. Roles directory is a git repo. Each project has its own repo. Commits provide history, diffs, attribution, and rollback.

### 1.7 Infrastructure manifest

A brief (~200 token) document injected into every session listing available capabilities (skills, tools, database, services) and infrastructure facts (storage layout, running services, data sources). The manifest is the index; skills and documentation are the chapters.

## Part 2: Open Question — Ontology

We need a coherent set of concepts for organizing the system. The concepts need to:
- Map to directory structure and file organization
- Serve as tags/metadata on window files for search
- Be intuitive enough that models and humans both understand them
- Cover the actual variety of work happening

### Current candidate concepts

**Role** — a job description applied to interactive sessions. Defines responsibilities, expectations, constraints. Examples: workbench, sysadmin, mcp-server.

**Project** — an umbrella for related work. The answer to "what is this about?" Examples: prediction-markets, claude-hub, ai-research-ontology. A project may encompass multiple kinds of activity.

**Service** — a persistent process that runs continuously or answers requests on demand. Examples: the claude-hub FastAPI server, the polymarket data collector, the MCP endpoint.

**Agent** — an autonomous work loop: a model woken up with context on a schedule to move ongoing work forward. Examples: a paper ingestion agent that periodically finds and classifies new research, a market scout that classifies new prediction markets. An agent combines a role (behavioral expectations) with a schedule and ongoing responsibility.

**Job** — a discrete unit of scheduled work that runs and completes. Examples: weekly data pipeline, daily CBOE options collection, session archiving. Simpler than an agent (may not need a model).

### The tension: project scope

The prediction-markets project illustrates the tension. It includes:
- **Development work**: writing collector code, analysis scripts, trading algorithms (git repo, SDLC, tests, releases)
- **Services**: running collectors that persist data continuously (systemd units consuming released code)
- **Agents**: a market scout that uses an LLM to classify markets (model + schedule + context)
- **Research**: empirical analysis, paper reviews, methodology documents
- **Data**: collected market data, model outputs, analysis results

Similar pattern for claude-hub: the codebase is a development project, the FastAPI server is a service, the chat instance is effectively an agent, the MCP endpoint is a service.

These are different *facets* of the same project. The question is whether/how to represent this:

**Option A: Flat projects, metadata-only facets**
```
~/projects/prediction-markets/    # single git repo
~/projects/claude-hub/            # single git repo
```
Facets (development, services, agents, research) exist only as tags on window files and internal organization within the repo. Simple, but loses structure.

**Option B: Namespaced sub-structure within projects**
```
~/projects/prediction-markets/
├── dev/          # git repo for code
├── research/     # docs, analysis
├── services/     # service definitions
└── data/         # collected data
```
Clear structure, but potentially over-engineered for small projects.

**Option C: Separate top-level directories by concern**
```
~/projects/prediction-markets/    # the code (git repo)
~/services/market-scout/          # service config, references installed code
~/agents/paper-ingestion/         # agent definition
```
Clean separation of concerns, but scatters related things across the filesystem.

**Option D: Project as high-level concept with dot-notation**
```
prediction-markets.development
prediction-markets.services
prediction-markets.agents
```
Conceptual hierarchy without necessarily dictating directory structure. The tags/metadata system captures relationships; physical layout can be whatever's practical.

### Window file tagging

Window files should be tagged with enough metadata to answer queries from multiple angles:
- "What has happened on the prediction-markets project?" (project-oriented)
- "What has the workbench role been doing?" (role-oriented)
- "What work has the market-scout service produced?" (service-oriented)

Proposed frontmatter:
```yaml
---
role: workbench
project: prediction-markets
facet: development     # or: services, agents, research, operations
service: null          # or: market-scout, polymarket-collector, etc.
---
```

### Other infrastructure facts that need homes

- Storage: FUSE mounts for Google Drive, OneDrive, pCloud, Dropbox at /storage/
- Email: Fastmail synced via mbsync to /storage/mail/fastmail/
- Database: PostgreSQL (claude_hub) on localhost
- Web services: claude-hub (port 8420), nginx (80/443), simple-publications
- Data collectors: polymarket (persistent), cboe/fred/coingecko (daily timers)
- GitHub mirror: ~/repos/ (read-only mirror of all GitHub repos, separate from active projects)
- Mechanical logs: per-project activity logs that feed window file narrative updates

### What we want from reviewers

1. Does the ontology (role, project, service, agent, job) cover the space? Are we missing concepts? Are any redundant?
2. Which option (A-D) for project structure makes most sense? Or is there a better approach?
3. Is "facet" the right term for the sub-categories of project work? Better alternatives?
4. Any concerns about the decisions in Part 1? Anything that seems fragile, over-engineered, or likely to cause problems?
5. How should the infrastructure manifest be structured to cover both capabilities (things you can do) and facts (things that exist)?
