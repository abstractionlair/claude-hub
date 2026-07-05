# Infrastructure Redesign Plan

*March 21, 2026*
*Derives from: vision-personal-ai-infrastructure.md (Draft 13)*

## Goal

Reorganize the personal AI infrastructure around roles, shared components, and multi-model access — implementing the architecture described in Vision Draft 13, Section 4.

## Context

The current system grew organically around `claude-hub` as the single project directory. Hooks are global (`~/.claude/`), data is trapped inside project directories, config has drifted between dotfiles and live state, and multi-harness support is ad-hoc. This plan restructures toward the vision's role-based, composable, multi-model architecture.

## Key Decisions Made

### 1. Roles are the organizing unit, not projects or harnesses

A role (researcher, sysadmin, workbench, mcp-server) defines *who* the agent is. A project defines *what* it's working on. The harness (Claude Code, Gemini CLI, OpenCode) is the execution substrate.

Roles live in `~/roles/{name}/`. Each role directory contains:
- `shared.md` — bulk role instructions, harness-agnostic (the source of truth)
- `windows/` — role-scoped window files for continuity across projects and sessions
- `.claude/`, `.gemini/`, `.opencode/` — harness-specific agents, settings as needed

The harness-specific instruction files (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`) in role directories are **not used for instruction loading** — role instructions are injected via hooks from `shared.md`. These files exist only as fallback orientation for edge cases (e.g., launching a harness directly in the role directory without the `role` script).

### 2. Launch from project directory, inject role via hooks

**Problem solved:** Getting both role instructions and project instructions (including deep subdirectory JIT loading) into any harness.

**Approach:** Launch the harness in the project directory so native JIT instruction loading handles all project-level instructions. Inject role instructions via harness-specific hooks that fire on session start and after every compaction/clear.

| Harness | Hook event | Injection mechanism | Survives compaction? |
|---|---|---|---|
| Claude Code | SessionStart | `systemMessage` in hook output | Yes — fires with `source: "compact"` |
| Gemini CLI | BeforeAgent | `additionalContext` in hook output | Yes — fires on every prompt |
| OpenCode | `experimental.chat.system.transform` plugin | Appends to system prompt array | Yes — fires on every LLM call |

The launcher sets the `CURRENT_ROLE` environment variable, which the harness process inherits. Each harness's hook reads `$CURRENT_ROLE` and injects the corresponding role instructions from `~/roles/$CURRENT_ROLE/shared.md`. Environment variables are session-scoped by nature — concurrent sessions in different terminals each have their own `$CURRENT_ROLE` with no race conditions.

**Validated empirically:** All three hook injection mechanisms tested and confirmed working (CARDINAL test).

### 3. Multi-model is the goal, multi-harness is a pricing constraint

The reason we use multiple harnesses is that each model's cheapest access path runs through a different tool:
- Claude → Anthropic subscription → Claude Code
- Gemini → Google subscription → Gemini CLI
- GPT, Kimi, etc. → OpenCode (pay-per-use, cheaper than direct API)

The architecture accommodates multiple harnesses but doesn't chase feature parity across them. Claude Code is the primary interactive harness. Others are functional with minor degradations.

### 4. Three-tier context delivery

| Layer | What | How delivered | When |
|---|---|---|---|
| **Role identity** | Who you are, behavioral guidelines | Hook injection (persists across compaction) | Every session, re-injected after compact/clear |
| **Infrastructure manifest** | What capabilities exist (brief index) | Hook injection (appended to role) | Same as role — always in context |
| **Project instructions** | Codebase conventions, architecture, subdirectory rules | Native JIT loading (harness-specific) | On demand as agent navigates project |

**Instruction precedence (most specific wins):**
1. Path-scoped subdirectory instructions (most specific)
2. Project root instructions
3. Role instructions (most general)

When instructions conflict, the more specific scope wins. Role instructions set defaults; project instructions can override for that codebase; subdirectory instructions can override for that module. This matches the natural intuition: "the researcher role says use 2-space indent, but this project uses 4-space" → project wins.

### 4a. Role memory

The vision says role memory spans projects — "Do you remember when we worked on project Y?" should be answerable from the role's history.

**Window files for role memory live in the role directory:** `~/roles/{name}/windows/`. The continuity hooks are adapted to write window files to this location rather than the project directory. The hook reads `$CURRENT_ROLE` to determine the target directory.

This means:
- When the researcher role works on prediction-markets, window files go to `~/roles/researcher/windows/`
- When it switches to quant-modeling, window files still go to `~/roles/researcher/windows/`
- The role's continuity chain spans both projects
- Project-specific working state (files being edited, current task) is captured in the window file content, but the window file itself lives with the role

**Auto-memory for role-scoped learning:** Claude Code's auto-memory directory can be redirected via `autoMemoryDirectory` in settings. The launcher sets this to `~/roles/{name}/memory/` so that learnings accumulate per role, not per project. Other harnesses handle memory differently — Gemini has `~/.gemini/memory.md` (global), OpenCode has no equivalent — but the window file chain provides cross-harness continuity.

### 5. Infrastructure awareness via manifest + skills

A brief capabilities manifest (~200 tokens) is injected alongside role instructions. It tells the agent what's available without loading details:

```
## Available Infrastructure
- Fork agents or launch other models (Skill: /launch-model, /fork-agent)
- Search past sessions (Skill: /session-search)
- Semantic artifact store (Skill: /artifact-store)
- Postgres database (Skill: /query-database)
- Multi-model review engine (Skill: /review)
- System administration (Skill: /system-admin)
- Design doc workflow (Skill: /write-design-doc)
```

Skills load on demand when the agent's intent matches the skill description. The manifest is the index; skills are the chapters.

### 6. Config ownership: global, role, and project

Three scopes, each with a clear purpose:

| Scope | Location | Contains | Examples |
|---|---|---|---|
| **Global** | `~/.claude/settings.json` etc. | Auth, update preferences, the role-injection hook itself | `forceLoginMethod`, `autoUpdatesChannel`, SessionStart hook that reads `$CURRENT_ROLE` |
| **Role** | `~/roles/{name}/.claude/` etc. | Role-specific agents, role-scoped skills | `.claude/agents/literature-reviewer.md` |
| **Project** | `{project}/.claude/` etc. | Project conventions, project-specific hooks, permissions | `.claude/rules/testing.md`, build hooks |

The role-injection hook must be **global** — it needs to fire regardless of which project directory the harness launches in. Role-specific agents and skills live in the role directory. Project-specific config lives with the project.

When config overlaps, project scope wins over role scope (more specific), and both win over global (most general). This matches the instruction precedence model.

The `claude-hub-dotfiles` repo is superseded by this structure and will be archived.

### 7. Version control as audit trail

Nearly every file the system produces should be git-tracked. This provides history, diffs, attribution, and rollback — the simplest viable write authority mechanism. Access is permissive; audit trail is the safety net.

**Repo boundaries:**
- `~/roles/` — git repo for role definitions, window files, and role memory
- Each project — its own git repo (already the case)
- Shared data location — its own git repo when established

**Commit conventions for generated artifacts:** Agents commit with their role and session ID in the message (e.g., `[researcher] Update window file`). The Co-Authored-By trailer provides model attribution.

**Exclusions:** `.env`, credentials, API keys, and machine-local state (`.claude/settings.local.json`) stay in `.gitignore`. Generated/ephemeral files (mechanical logs, session transcripts) are not committed.

### 8. Role launcher script

`~/bin/role` launches a harness session with a role. It:
1. Sets `CURRENT_ROLE` environment variable (inherited by child process — session-scoped, no race conditions)
2. Changes to the project directory (or `$HOME` if no project specified)
3. Launches the appropriate harness

```bash
role researcher                      # Claude Code (default), in $HOME
role researcher ~/projects/foo       # Claude Code, in project directory
HARNESS=gemini role researcher       # Gemini CLI
HARNESS=opencode role researcher     # OpenCode
```

### 9. Session archive for automated sessions

`~/bin/session-archive` moves `userType=external` sessions to an `archived/` subdirectory after 12 hours. Purges archived sessions after 90 days. Runs via cron every 6 hours. Keeps `/resume` list usable.

## Implementation Phases

### Phase A: Hook infrastructure and role memory (foundation)

1. Create the role-injection hook for each harness:
   - Claude Code: SessionStart hook that reads `$CURRENT_ROLE` and injects role instructions + infrastructure manifest
   - Gemini CLI: BeforeAgent hook, same logic
   - OpenCode: `experimental.chat.system.transform` plugin, same logic

2. Create the infrastructure manifest file (shared across all roles). The initial manifest advertises only currently-existing capabilities and skills. New skills are added to the manifest as they're built in Phase B.

3. Update `~/bin/role` launcher to:
   - Set `CURRENT_ROLE` environment variable
   - Accept an optional project directory argument
   - Launch from the project directory with appropriate harness flags

4. Adapt continuity hooks to write window files to `~/roles/$CURRENT_ROLE/windows/` instead of project-local storage. Adapt SessionStart hook to load from role-scoped window chain.

5. Initialize `~/roles/` as a git repo for role definitions, window files, and role memory.

6. Test: launch each harness via `role`, verify role instructions are present, verify they survive `/compact` or equivalent, verify window files are written to the role directory.

### Phase B: Skills buildout (follows A — manifest updated incrementally)

7. Install proposed new skills (update the infrastructure manifest as each is installed):
   - `query-database` — Postgres connection info, schema, common queries
   - `write-design-doc` — spec-driven development workflow
   - `launch-model` — how to invoke other models/harnesses
   - `artifact-store` — semantic search and artifact management
   - `system-admin` — VPS health checks and service management
   - `debug-python` — debugging patterns for this codebase

8. Review and update existing skills for accuracy with current system state

### Phase C: Config migration

7. Audit `~/.claude/settings.json` — identify what's truly global vs project-specific
8. Move project-specific hooks from `~/.claude/hooks/` to role/project `.claude/hooks/`
9. Move project-specific settings to `.claude/settings.json` per project
10. Slim down `~/.claude/settings.json` to only truly global settings
11. Archive `claude-hub-dotfiles` repo with final documentation

### Phase D: Shared data reorganization

12. Define the rule: data that originates in a project stays in the project (indexed in place via connectors, per "view, don't warehouse"). Data that doesn't belong to any single project (cross-project research, shared reference docs) gets a shared location.
13. Stop R1/R2/R3 document versioning — use git commits for iteration. No files need to move; the convention changes.
14. Set up publication pipeline for documents via simple-publications (can index from wherever documents live).
15. Ensure all roles can access shared data locations (volume mount, project directories).

### Phase E: Context monitor

16. Deploy context-monitor.sh with thresholds updated for 1M context window
17. Wire into the appropriate hook for each harness
18. Test warning/critical thresholds

## What This Plan Does NOT Cover

- Full requirements/spec revision for Vision Draft 13 (deferred — validate architecture first)
- Discovery/registry layer beyond the manifest + skills pattern
- Persistent agent scheduling (cron/systemd setup for autonomous roles)
- Cross-agent coordination mechanisms
- Connector implementations (email, spreadsheet, etc.)
- Capability compounding (pattern detection → skill promotion)

These are deferred to after the foundation is validated.

## Dependencies and Ordering

```
Phase A (hooks + role memory) ← foundation, no dependencies
Phase B (skills) ← follows A (manifest starts minimal, grows as skills are added)
Phase C (config migration) ← follows A (hooks must be project-level before migrating)
Phase D (shared data) ← independent, but wait for parallel prediction-markets session to complete
Phase E (context monitor) ← follows A (needs hook infrastructure in place)
```

A is the foundation. B, C, and E follow A sequentially or with light parallelism. D is independent but has an external dependency.

## Risks

- **Hook approval in non-interactive modes**: Project-level hooks may require interactive approval on first use. The launcher may need to handle this. Global hooks avoid this issue.
- **Gemini's eager loading**: Launching from project directories may still load GEMINI.md files from parent directories. May need exclude settings.
- **Gemini context accumulation**: BeforeAgent fires on every prompt. Verify that `additionalContext` doesn't accumulate in conversation history across turns — it should be per-turn injection, not appended permanently. If it accumulates, consider BeforeModel with request modification instead.
- **OpenCode plugin stability**: `experimental.chat.system.transform` is marked experimental. May change in future OpenCode versions.
- **Window file adaptation for non-Claude harnesses**: Window file writing currently depends on Claude Code hooks (Stop, PreCompact). Gemini and OpenCode need equivalent continuity hooks adapted for their hook/plugin systems.
- **Access scoping deferred but not forgotten**: The initial posture is permissive (all roles see all data). The infrastructure should support scoping when needed, but doesn't enforce it yet. This is a conscious choice, not an oversight — version control provides the safety net. If experience shows certain data needs restriction, scoping primitives (discoverable metadata vs session-authorized content) can be added.
