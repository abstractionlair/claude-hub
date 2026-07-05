# Context Management Patterns

Patterns for managing context across Claude Code sessions, established January 2025.

## Core Problem

Claude has limited context at any moment. Optimizing context usage involves:
- **Backward-looking**: What information should be in context now? (storage/retrieval)
- **Forward-looking**: How to achieve goals with less context usage? (sub-agents)

## Pattern 1: Forked Sub-Agents

Use `--fork-session` to spawn agents that inherit current context but use their own context budget.

### When to Use
- Complex searches that need interpretation
- Tasks that would burn significant context in the main session
- Any work where you want the process hidden and just the result returned

### Basic Pattern
```bash
claude --resume $SESSION_ID --fork-session \
  --dangerously-skip-permissions \
  --max-turns 3 \
  --print \
  -p '[FORKED_AGENT] You are a sub-agent forked to perform a specific task.
Return ONLY a concise summary. Do not continue the main conversation.

TASK: <specific task here>'
```

### Key Flags
- `--fork-session`: Creates new session ID, inherits parent context
- `--dangerously-skip-permissions`: Allows tool execution in non-interactive mode
- `--max-turns N`: Limits agent work (typically 2-4 turns)
- `--print`: Non-interactive output mode

### Agent Framing
The `[FORKED_AGENT]` prefix tells the fork:
1. It's a sub-agent, not the main session
2. Its job is scoped (complete task, return summary)
3. It should not continue general conversation

This is analogous to Unix `fork()` where child processes need to differentiate themselves.

## Pattern 2: Session History Search

Session JSONL files contain complete conversation history. Search them to recover context.

### Script Location
`~/.claude/scripts/session-search.sh`

### Usage
```bash
# Direct search (uses context but fast)
~/.claude/scripts/session-search.sh "query" --project /path/to/project --limit 10

# Forked search (saves context)
claude --fork-session -p "[FORKED_AGENT] Search session history for 'X' and summarize.
Run: ~/.claude/scripts/session-search.sh 'X' --project /path" --print
```

### What This Enables
- Recover decisions lost to compaction/clear
- Window files become summaries, session history is the source of truth
- "What did we decide about X?" queries without burning context

## Pattern 3: Event-Driven Window File Updates

Instead of writing state only when context is high (reactive), capture on meaningful events (accumulative).

### Hooks
- **Stop hook** (`periodic-narrative-update.sh`): After sufficient work (~20K tokens), forks a narrative agent to update the current window file with a summary of recent activity.
- **PreCompact hook**: Before compaction, finalizes the current window file and creates a new child window linked via `parent` frontmatter.
- **PostToolUse hook**: Appends mechanical operations (file edits, bash commands) to `thoughts/mechanical.jsonl` for the narrative agent to reference.

### Why This Matters
- State captured incrementally, not in panic before clear
- Auto-compact or manual /clear both work (state already saved)
- Lower cognitive load - no need to manually update state files
- Finalized windows are immutable history, reachable via parent chain

## Pattern 4: Recursion Safety (CLAUDE_DISABLED_HOOKS)

Prevent hook→agent→hook cycles while allowing healthy agent→agent recursion.

### The Problem
```
Hook X fires → spawns agent A → A works → Hook X fires again → spawns agent → ...
```

The cycle is caused by the hook, not by agent reasoning.

### The Solution
When Hook X spawns a subtree, X is removed from that subtree's hook set.

```bash
# At top of any hook that might spawn agents:
HOOK_NAME="my-hook-name"
if echo "${CLAUDE_DISABLED_HOOKS:-}" | grep -q ":${HOOK_NAME}:"; then
    echo '{"result": "continue"}' | jq -c .
    exit 0
fi

# When spawning sub-agents:
CLAUDE_DISABLED_HOOKS="${CLAUDE_DISABLED_HOOKS:-}:${HOOK_NAME}:" \
  claude --fork-session -p "..." --print
```

### Properties
- Structural, not runtime detection
- X→Y→Z allowed (different hooks)
- X→...→X prevented (same hook in ancestry)
- Agent→agent recursion unaffected (hooks don't prevent it)

### Key Insight
Agent recursion is trusted (scope narrows naturally). Hook injections are controlled (they don't know the call context).

## Pattern 5: Context Monitoring

Track actual context usage by parsing session JSONL files.

### Hook: `context-monitor.sh`
Triggers on: Stop (after every assistant turn)

### Calculation
```bash
# Context = last message's cumulative token count
input_tokens + cache_creation_input_tokens + cache_read_input_tokens
```

### Thresholds
- 80%: Warning message, suggest /clear soon
- 95%: Critical message, run /clear immediately

## Design Principles

### Trust Agent Recursion
Like recursive functions in Lisp/Scheme - if each call narrows scope, termination is guaranteed by structure. Don't over-specify task type grammars at design time.

### Control Side Injections
Hooks don't know their call context. They might fire inappropriately in sub-agent trees. Use CLAUDE_DISABLED_HOOKS to prevent hooks from re-triggering in subtrees they spawned.

### Accumulative Over Reactive
Write state incrementally on meaningful events rather than in panic when context is nearly full. This makes the window file a living document, not an emergency snapshot.

### Session History as Ground Truth
Everything ever discussed is in the JSONL files. Window files are curated summaries. Session search enables recovery of details that weren't captured in window files.
