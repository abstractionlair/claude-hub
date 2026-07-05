# Narrative Fork Failure Diagnosis (2026-03-13)

## Symptom
Window file stopped updating mid-session. ~3 hours of work (R4 reviews, literature engagement, forecasting paradox) not captured. On session resume after compaction, stale context was injected.

## Session: 1eadbb63-fcf2-490c-950c-008dc3d0705b

### Timeline
- 13:34, 15:51: Pre-compact forks succeeded
- 13:45–17:49: Periodic narrative forks succeeded (6 total)
- 18:03: Pre-compact fork failed: "No conversation found"
- 18:06: Third compaction completed
- 18:06–20:45: No periodic narrative updates logged at all
- 20:45: Pre-compact fork failed: "No conversation found"

### Prior session (c6770da5, Mar 7)
- 21:59: Periodic fork failed: "Prompt is too long" (at 193,986 tokens)
- 22:08: Pre-compact fork failed: "Prompt is too long"

## Findings

### 1. SessionStart hook not disabled in forks
Both `pre-compact-continuity.sh` and `periodic-narrative-update.sh` set:
```
CLAUDE_DISABLED_HOOKS="narrative-update:mechanical-log:pre-compact-continuity:"
```
But **not** `session-start-continuity`. The fork triggers SessionStart, which injects the window file (~50KB). On a session near the 5% free context threshold, this can push the fork over the limit → "Prompt is too long".

### 2. "No conversation found" — unexplained
The 18:03 and 20:45 failures returned "No conversation found" (different from "Prompt is too long"). We confirmed `--resume --fork-session` works from outside the session and from within it (with proper env). Root cause not identified. Possibly transient (compaction timing, file lock, etc).

### 3. Silent failure
The stop-wrapper.sh swallows fork errors (`|| true`, stdout to `/dev/null`). When forks fail, the narrative update loop silently stops. No state file update, no log entry for the failure mode, no alert.

## Fixes

### Immediate
Add `session-start-continuity` to disabled hooks in both fork commands:
```
CLAUDE_DISABLED_HOOKS="...:session-start-continuity:"
```
Narrative forks don't need window context injected — they're the ones writing it.

### Consider
- Log fork exit codes and stderr explicitly (don't rely on `|| true`)
- Fallback: if fork fails, write mechanical log summary to window file synchronously (no model needed)
- The "No conversation found" failure remains undiagnosed
