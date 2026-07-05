# Fractal Delegation System

The Claude Hub delegation system enables hierarchical agent orchestration with resource management, scheduling, and structured handoffs.

## Overview

**Key Features:**
- **Workspace isolation** - Each agent gets its own directory with permission controls
- **Resource constraints** - Deadline propagation and resource limits using min() pattern
- **Scheduling** - Cron-like wake-ups for periodic tasks
- **Handoff protocol** - Structured summaries from delegatees to parents
- **Permissions** - Parent→child write access, child→parent read access

## Architecture

```
thoughts/projects/{project}/
  work/
    main/                           # Main Claude's workspace
      schemas/
      PROJECT.md
    main.research-abc123/           # Child of main
      findings.md
      HANDOFF.md                    # Handoff to parent
    main.research-abc123.analysis/  # Grandchild
      data.json
      HANDOFF.md
  shared/
    ontologies/                     # Shared schemas
    data/                           # Shared datasets
```

**Naming convention:** Child workspaces use `parent.child` naming, making delegation tree visible.

## Core Concepts

### 1. Workspaces

Each agent operates in an isolated workspace with explicit permissions:

```python
# Create workspace for a child agent
workspace = await create_workspace(
    project="prediction-markets",
    agent_id="research-markets",
    parent_id="main",
    deadline=datetime.now() + timedelta(hours=8),
    max_memory_mb=2048,
    max_agents=3,
)
# Returns: thoughts/projects/prediction-markets/work/main.research-markets/
```

**Permission rules:**
- Own workspace: full read/write
- Parent → child: read/write (can intervene)
- Child → parent: read-only (can see context)
- Siblings: no access (must use shared/)

### 2. Resource Constraints

Constraints propagate down the delegation tree using `min()`:

```python
# Parent has 8-hour deadline
parent_deadline = now() + timedelta(hours=8)

# Child estimates 2 hours needed
child_estimate = now() + timedelta(hours=2)

# Actual child deadline = min(parent_deadline, child_estimate)
child_constraints = ResourceConstraints(
    deadline=min(parent_deadline, child_estimate),
    max_memory_mb=min(parent_memory, 2048),
    max_agents=min(parent_agents, 3),
)
```

This ensures:
- Children can't overpromise relative to parent constraints
- Tight time budgets signal urgency
- Resource exhaustion is visible early

### 3. Scheduling

Schedule wake-ups for periodic work or checkpoints:

```python
# One-time wake-up
schedule_id = await schedule_wake_at(
    session_id="main",
    time=datetime(2026, 1, 14, 9, 0),
    prompt="Check prediction markets research status",
)

# Recurring wake-up (every 4 hours)
schedule_id = await schedule_wake_every(
    session_id="main",
    interval_seconds=14400,  # 4 hours
    prompt="Review delegated work in thoughts/projects/prediction-markets/work/",
    start_time=datetime.now(),
)

# Cancel when done
await cancel_schedule(schedule_id)
```

**Use cases:**
- Periodic status checks on delegated work
- Daily market monitoring
- Deadline reminders
- Automatic retries

### 4. Handoffs

Delegatees create handoff documents to summarize their work:

```python
# Delegatee writes handoff
await write_handoff(
    project="prediction-markets",
    agent_id="research-markets",
    parent_id="main",
    status="complete",  # or "in_progress", "blocked", "failed"
    summary="Analyzed 15 prediction market platforms. Found 3 with APIs.",
    findings=[
        "Polymarket has best API (WebSocket + REST)",
        "Kalshi limited to US users",
        "PredictIt has $850 position limits",
    ],
    files_changed=[
        "work/main.research-markets/platforms.json",
        "shared/data/api-comparison.md",
    ],
    questions=[
        "Should we focus on crypto markets or political markets?",
    ],
    recommendations="Start with Polymarket API integration",
)

# Parent reads handoff
handoff = await read_handoff(
    project="prediction-markets",
    agent_id="research-markets",
    parent_id="main",
)

print(handoff.summary)
print(handoff.status)
print(handoff.findings)
```

Handoffs create both human-readable markdown (`HANDOFF.md`) and machine-readable JSON (`.handoff.json`).

## Delegation Patterns

### Pattern 1: Simple Delegation with Periodic Check-ins

```python
# 1. Create workspace for delegatee
workspace = await create_workspace(
    project="prediction-markets",
    agent_id="research-platforms",
    parent_id="main",
    deadline=now() + timedelta(hours=12),
)

# 2. Schedule periodic check-ins
schedule_id = await schedule_wake_every(
    session_id="main",
    interval_seconds=14400,  # Every 4 hours
    prompt=f"Check status of research-platforms. Read handoff at {workspace}/HANDOFF.md",
)

# 3. Spawn delegatee agent
agent = Task(
    "research-platforms",
    prompt="""Research prediction market platforms.

    Working directory: {workspace}

    Tasks:
    1. Catalog platforms (APIs, fees, liquidity)
    2. Document findings in platforms.md
    3. Write handoff when complete

    Update handoff every 2 hours with progress.""",
    model="haiku",  # Use cheaper model for research
)

# 4. Wait for completion or intervene when woken up
```

### Pattern 2: Parallel Delegation

```python
# Spawn multiple parallel agents
agents = [
    create_workspace(project="pm", agent_id="platform-research", parent_id="main"),
    create_workspace(project="pm", agent_id="literature-review", parent_id="main"),
    create_workspace(project="pm", agent_id="api-testing", parent_id="main"),
]

# Each agent works independently
# Parent checks all handoffs periodically
schedule_wake_every(
    session_id="main",
    interval_seconds=21600,  # Every 6 hours
    prompt="Review all handoffs in thoughts/projects/pm/work/main.*/HANDOFF.md",
)
```

### Pattern 3: Recursive Delegation

```python
# Agent can further delegate
# main -> research -> platform-analysis -> polymarket-deep-dive

# Each level creates workspace for its children
child_workspace = await create_workspace(
    project="pm",
    agent_id="platform-analysis",
    parent_id="main.research",  # Child of research agent
    deadline=min(my_deadline, now() + timedelta(hours=4)),
)
```

## Shared Resources

Agents collaborate via `shared/`:

```python
# Create shared ontology
with open("thoughts/projects/pm/shared/ontologies/market-schema.md", "w") as f:
    f.write("""<!-- PERMISSIONS
created_by: work/main/
writers: [work/main/, work/main.research/]
-->

# Market Schema

## Fields
- platform: string
- market_id: string
- question: string
- ...
""")

# Other agents can read this schema
# Only creators and listed writers can modify it
```

## Integration with Existing Tools

The delegation system integrates with Claude Code's `Task` tool:

```python
# Standard Task tool spawns agent
agent = Task(
    "research-agent",
    prompt="Research X",
    subagent_type="research-agent",
)

# Enhanced with workspace + scheduling
workspace = create_workspace(...)
schedule_wake_every(...)
agent = Task(...)  # Same API, but now has workspace isolation
```

## Future: Ralph Mode Integration

Ralph mode will enable iterative agents that continue until completion:

```python
await create_workspace(
    project="pm",
    agent_id="backtest-builder",
    parent_id="main",
    mode="ralph",  # <-- Ralph mode
    completion_promise="TESTS_PASSING",
    max_iterations=50,
)

# Agent will:
# 1. Try to implement backtesting framework
# 2. Run tests
# 3. See failures, fix bugs
# 4. Repeat until tests pass or max_iterations hit
# 5. Write handoff and exit
```

## Examples

See `examples/delegation/` for complete working examples:
- `simple-delegation.py` - Basic parent-child delegation
- `parallel-research.py` - Multiple parallel agents
- `recursive-delegation.py` - Multi-level delegation tree
- `periodic-monitoring.py` - Scheduled wake-ups for monitoring

## API Reference

### Workspace Management

- `create_workspace(project, agent_id, parent_id, constraints)` - Create agent workspace
- `list_children(project, parent_agent_id)` - List child workspaces

### Scheduling

- `schedule_wake_at(session_id, time, prompt, constraints)` - One-time wake-up
- `schedule_wake_every(session_id, interval_seconds, prompt, ...)` - Recurring wake-up
- `list_schedules(session_id)` - List active schedules
- `cancel_schedule(schedule_id)` - Cancel a schedule

### Handoffs

- `write_handoff(project, agent_id, status, summary, ...)` - Create handoff
- `read_handoff(project, agent_id)` - Read handoff
- `list_handoffs(project)` - List all handoffs in project

## Best Practices

1. **Use periodic check-ins for research/discovery phases** - open-ended exploration needs human judgment
2. **Use Ralph mode for implementation with clear success criteria** - tests pass, builds succeed, etc.
3. **Keep handoffs concise** - 2-3 sentence summary, bullet points for findings
4. **Propagate deadlines properly** - always use min() to respect parent constraints
5. **Use shared/ for collaboration** - don't duplicate data across workspaces
6. **Clean up completed work** - LRU eviction handles this automatically (when implemented)

## Troubleshooting

**Issue: Child can't access parent's files**
- This is by design. Children have read-only access to parent workspace.
- Parent should put shared data in `shared/data/`

**Issue: Schedule not firing**
- Check scheduler is running: `systemctl status claude-hub`
- Check schedule exists: `list_schedules()`
- Check time zone - all times are UTC

**Issue: Handoff not found**
- Ensure workspace was created: check `thoughts/projects/{project}/work/`
- Ensure delegatee called `write_handoff()`
- Check file permissions: workspace should be readable

**Issue: Resource constraints not respected**
- Constraints are advisory, not enforced yet
- Agents should check `ResourceConstraints` in workspace metadata
- Future: Hard limits via cgroups/Docker
