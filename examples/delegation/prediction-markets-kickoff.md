# Prediction Markets Research - Delegation Example

This example shows how to use the delegation system to kickoff the prediction markets research project.

## Scenario

Main Claude wants to research prediction markets thoroughly without burning context on intermediate details. The research could take hours and involve reading many sources. Solution: delegate to a research agent with periodic check-ins.

## Step 1: Create Workspace

```python
# Via MCP tools (available to Main Claude)
workspace = await create_workspace(
    project="prediction-markets",
    agent_id="market-survey",
    parent_id="main",
    deadline=datetime.now(timezone.utc) + timedelta(hours=12),
    max_memory_mb=2048,
    max_agents=2,  # Research agent can spawn 1-2 sub-agents if needed
)

# Creates: thoughts/projects/prediction-markets/work/main.market-survey/
```

## Step 2: Schedule Check-ins

```python
# Wake up every 4 hours to check progress
schedule_id = await schedule_wake_every(
    session_id="main",
    interval_seconds=14400,
    prompt="""Check prediction markets research progress.

Read handoff at: thoughts/projects/prediction-markets/work/main.market-survey/HANDOFF.md

If status is 'complete', review findings and decide next steps.
If status is 'in_progress', check if redirection needed.
If status is 'blocked', help unblock or reassign work.""",
)
```

## Step 3: Spawn Research Agent

```python
# Use existing Task tool with delegation
agent = Task(
    subagent_type="research-agent",
    description="Market survey research",
    prompt="""Research prediction market platforms systematically.

**Working directory:** thoughts/projects/prediction-markets/work/main.market-survey/

**Tasks:**
1. Catalog platforms: Polymarket, Kalshi, PredictIt, Manifold, Metaculus
   - For each: API access, fees, liquidity, regulatory status, data access
2. Deep dive Polymarket API
   - Test WebSocket connection
   - Document data structures
   - Check historical data availability
3. Research academic literature on prediction market efficiency
4. Update findings in platforms.md

**Deliverable:**
- platforms.md with comparison matrix
- polymarket-api.md with technical details
- literature-notes.md with key papers

**Handoff requirement:**
Update HANDOFF.md every 2 hours with progress. Mark 'complete' when all tasks done.

**Constraints:**
- Deadline: 12 hours from now
- Focus on answering: "Where might edge exist that isn't arbitraged?"
"""
)
```

## Step 4: Agent Works Autonomously

The research agent:
1. Reads project context from `thoughts/projects/prediction-markets/PROJECT.md`
2. Works in its isolated workspace
3. Can spawn sub-agents if needed (e.g., one for literature review, one for API testing)
4. Updates handoff every 2 hours
5. Writes final handoff when complete

## Step 5: Main Claude Woken Up

After 4 hours, Main Claude is woken by scheduler:

```python
# Scheduled prompt executes
prompt = "Check prediction markets research progress. Read handoff at: ..."

# Main Claude reads handoff
handoff = await read_handoff(
    project="prediction-markets",
    agent_id="market-survey",
    parent_id="main",
)

if handoff.status == "complete":
    # Review findings
    print(f"Research complete: {handoff.summary}")
    print(f"Findings: {handoff.findings}")

    # Cancel scheduled wake-ups
    await cancel_schedule(schedule_id)

    # Decide next steps
    # - Start Phase 2: Backtesting?
    # - Need more research on specific platform?
    # - Ready to build data pipeline?

elif handoff.status == "in_progress":
    # Check if on track
    percent_done = ...  # Estimate from handoff
    time_remaining = handoff.deadline - datetime.now()

    if time_remaining < timedelta(hours=2) and percent_done < 0.8:
        # Running out of time - intervene
        # Option 1: Extend deadline
        # Option 2: Narrow scope
        # Option 3: Accept partial results

elif handoff.status == "blocked":
    # Help unblock
    print(f"Agent blocked: {handoff.questions}")
    # Answer questions by writing to agent's workspace
    # Agent will see files next time it reads workspace
```

## Step 6: Use Results

```python
# Results are in workspace
research_output = Path("thoughts/projects/prediction-markets/work/main.market-survey/")

platforms = read_file(research_output / "platforms.md")
api_docs = read_file(research_output / "polymarket-api.md")

# Findings are also in handoff
print(handoff.findings)
# ["Polymarket has WebSocket + REST API",
#  "Kalshi is CFTC-regulated, US-only",
#  "PredictIt has $850 position limits",
#  ...]

# Update project research document
update_research(handoff.findings)

# Decide next phase
if edge_looks_promising(handoff.findings):
    # Spawn next agent: data collection
    next_agent = create_workspace(
        project="prediction-markets",
        agent_id="data-pipeline",
        parent_id="main",
        ...
    )
```

## Benefits of This Approach

1. **Context preservation:** Main Claude doesn't burn tokens reading API docs
2. **Parallelism:** Research agent can spawn sub-agents
3. **Interruptible:** Can check in periodically without blocking
4. **Resumable:** If summary is too terse, can resume agent and ask for detail
5. **Auditable:** All work preserved in workspace for later review

## Alternative: Ralph Mode (Future)

For well-defined tasks with clear success criteria:

```python
workspace = await create_workspace(
    project="prediction-markets",
    agent_id="api-client-builder",
    parent_id="main",
    mode="ralph",
    completion_promise="TESTS_PASSING",
    max_iterations=30,
)

# Agent will iterate until tests pass or max iterations hit
# No need for periodic check-ins - it keeps going automatically
```

## Next Example

See `parallel-research.py` for spawning multiple research agents in parallel.
