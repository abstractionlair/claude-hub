# Minimal Continuous Claude Setup

This is a self-contained prompt for setting up Continuous Claude patterns in a corporate environment with no external dependencies.

---

## Instructions

Copy everything below the line into your Claude Code session. It will create the minimal infrastructure for session continuity.

---

## Setup Prompt

I need you to set up a minimal Continuous Claude infrastructure in this project. This should work entirely locally with no external API dependencies.

Create the following structure:

### 1. Directory Structure

```
.claude/
  hooks/
    session-start.sh
  skills/
    SKILL.md (template)
  settings.json
thoughts/
  ledgers/
    LEDGER_TEMPLATE.md
  handoffs/
    HANDOFF_TEMPLATE.md
```

### 2. Ledger Template (thoughts/ledgers/LEDGER_TEMPLATE.md)

Create a ledger template with these sections:
- **Goal**: What success looks like (concrete, measurable)
- **Constraints**: Technical requirements, patterns to follow
- **Key Decisions**: Choices made with rationale (dated)
- **State**: Done/Now/Next with checkboxes for multi-phase work
- **Open Questions**: Mark uncertain items as UNCONFIRMED
- **Working Set**: Key files, branch name, test commands

The State section should use checkboxes:
- `[x]` = Completed
- `[→]` = In progress (current)
- `[ ]` = Pending

### 3. Handoff Template (thoughts/handoffs/HANDOFF_TEMPLATE.md)

Create a handoff template with:
- **Context**: What was being worked on
- **Status**: Current state (working/blocked/complete)
- **Key Files**: Files that were modified or are relevant
- **What's Next**: Concrete next steps
- **Blockers**: Any issues encountered
- **Notes**: Anything the next session should know

### 4. Session Start Hook (.claude/hooks/session-start.sh)

Create a shell script that:
1. Checks if a ledger exists in thoughts/ledgers/
2. If found, outputs a JSON message telling Claude to read it
3. The hook should be simple - just echo the JSON, no external dependencies

The output format should be:
```json
{"result": "continue", "message": "Active ledger found: [filename]. Read it to restore context."}
```

### 5. Settings (.claude/settings.json)

Register the session-start hook:
```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"
      }]
    }]
  }
}
```

### 6. Skill Template (.claude/skills/SKILL.md)

Create a template showing the skill format:
```yaml
---
name: skill-name
description: What this skill does
---
```

Followed by the skill instructions in markdown.

### 7. A Working Example

After creating the templates, create an actual ledger for this setup task:
- `thoughts/ledgers/CONTINUITY_setup-complete.md`
- Mark the infrastructure setup as complete
- Add a "Next" item: "Create first project-specific skill"

### Key Principles

1. **Ledgers are the source of truth** - Update them before clearing context
2. **Handoffs transfer work** - Create one when passing to another session
3. **Hooks inject context** - Session start loads the ledger automatically
4. **Skills encapsulate workflows** - Reusable patterns get their own skill file

### Usage Pattern

When starting work:
1. Check for active ledger (hook does this automatically)
2. Read the ledger to restore context
3. Find the `[→]` marker for current work

When ending work:
1. Update ledger with current state
2. Move `[→]` to next item or mark `[x]` complete
3. Note any UNCONFIRMED items

When handing off:
1. Create handoff document with full context
2. Reference it in the ledger
3. Clear session with confidence

Now please implement this structure. Make the files executable where needed, and ensure everything works without any external services or API calls.
