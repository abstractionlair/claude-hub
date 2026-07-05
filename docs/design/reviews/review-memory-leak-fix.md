# Review: 2026-03-23 14:03 UTC

**Prompt:** Review these changes that fix a memory leak and broken graceful shutdown in the claude-hub MCP server. The server grew from 130MB to 4.3GB over 5.7 days and SIGTERM never resulted in clean exit. Focus your review on:

1. SIGTERM handler fix (server.py ~line 269): chains to previous handler instead of clobbering it. Is this correct? Any edge cases?
2. Periodic cleanup task (server.py _periodic_cleanup): evicts stale pending_responses, reaps idle chat processes, cleans routing table counters. Any race conditions? Is the cleanup interval/TTL reasonable?
3. ChatProcessManager.reap_idle() (chat_process.py): kills processes idle >30min. Thread safety with the async lock? Any risk of killing a process that's about to receive work?
4. Connection leak fix (_get_conn as @contextmanager in 6 store modules): psycopg2 with-conn only handles transactions, not closing. Now uses contextmanager+finally. Any callers that will break?
5. /debug/memory endpoint: useful? Missing anything important?
6. Are there any OTHER memory leak sources in these files that we missed?

The sysadmin brief: 148 MCP sessions, 2221 HTTP requests, 26 embedding sweeps over 5.7 days. ~750MB/day growth rate.
**Files:** src/claude_hub/server.py, src/claude_hub/chat_process.py, src/claude_hub/observations.py, src/claude_hub/scheduler.py, src/claude_hub/conversation_store.py, src/claude_hub/notifications.py, src/claude_hub/oauth_store.py, src/claude_hub/totp_store.py, tests/test_conversation_store.py
**Job ID:** 7b1c8ff3-2e0e-43db-a0ef-5ea171e5607d

## Synthesis

## Review Synthesis

Three reviewers examined the memory leak and graceful shutdown fixes. Here's where they converge, diverge, and what each uniquely surfaced.

### Consensus Findings (High Confidence)

**The `_get_conn` context manager fix is correct and non-breaking.** All three reviewers audited the six store modules and confirmed every caller uses the context manager pattern with explicit commits. No compatibility break. This is the core leak fix and it's sound.

**The SIGTERM handler is correct.** All three agree the chaining approach (save previous handler, call it if callable, fall back to SIG_DFL + re-raise) is the right fix. GPT-5.4 noted minor edge cases — SIG_IGN passthrough and handler stacking on repeated lifespan runs — but rated them low severity.

**`reap_idle()` has a race condition.** All three independently identified the TOCTOU window: idle candidates are identified under the lock, the lock is released, then `kill_process()` re-acquires it. A request arriving in that gap can mark the process busy, but it gets killed anyway. Severity ranged from medium (GPT-5.4, Kimi) to critical (Gemini). Gemini additionally flagged that `kill_process()` holds the lock during a 5-second `wait()`, blocking all process management. GPT-5.4 added a subtler point: `last_activity` is only refreshed when the prompt is *written*, never when output streams or when the turn completes, so a long-running turn can appear idle the instant it finishes and be reaped almost immediately.

**`/debug/memory` is useful but incomplete.** All three want MessageRouter state (conversation count, bus count, queue depths) and subscriber/task counts added. Without those, the endpoint can't surface the stranded-listener and leaked-queue problems the reviewers found elsewhere.

**Reaped group-chat participants are permanently lost.** Both Gemini and GPT-5.4 flagged this at high severity. When `reap_idle()` kills a Claude process that was in a group chat, the writer task in `MessageRouter._claude_writer` exits (process gone from dict), and there's no path to respawn or re-register the participant. GPT-5.4 added that `kill_process()` cancels the stdout reader first, so the listener task can block forever — no terminal error is delivered to subscriber queues.

### Unique Findings

**GPT-5.4 — `pending_responses` cleanup is a correctness regression (high severity).** This is the most important unique finding. The `hub_send` completion/error path replaces the whole entry and drops `created_at`. The cleanup task then sees a missing timestamp, treats the entry as infinitely old, and evicts it on the very next pass — even if the response hasn't been polled yet. Worse, genuinely long-running requests (>10 min) get deleted while still pending, causing `hub_poll` to return "Unknown request_id" even though the background task is alive. This turns the leak fix into a data-loss bug.

**Gemini — Abandoned MessageRouter conversations and infinite poll queues (high severity).** If an MCP client calls `group_join` but disconnects without `group_leave`, the `Conversation` object (with its ever-growing `message_log`) lives in memory forever. Similarly, MCP poll queues (`asyncio.Queue`) grow without bound if a client joins but stops calling `group_poll`. The periodic cleanup task doesn't sweep any of these.

**Gemini — `get_messages` returns oldest, not newest (low severity).** `ORDER BY timestamp LIMIT %s` returns the oldest N messages. Likely wants `ORDER BY timestamp DESC LIMIT %s` with a Python reverse.

**GPT-5.4 — `_session_observations_loaded` leak (outside reviewed files).** In `session.py`, this set grows on first use per session and is never pruned in `terminate_session()`.

**Kimi — Missing OAuth authorization code cleanup (medium severity).** Auth codes have a 10-minute TTL but no periodic cleanup is scheduled. The table could grow unbounded, though OAuth flows are infrequent enough that this is slow-burn.

**Kimi — Subscriber queues not cleared on process death (medium severity).** When a process dies, subscribers get an error event but the `_subscribers` dict retains references to dead queues. Only explicit `unsubscribe()` removes them. Abrupt WebSocket disconnects leave queues leaking.

### Contradictions

Severity assessments for the `reap_idle()` race vary — Gemini says critical, GPT-5.4 says medium, Kimi says medium-high — but this is a gradient, not a real disagreement. All three agree it needs fixing. The disagreement is whether it's "will corrupt data" (Gemini's framing around lock contention during 5s waits) or "can lose in-flight work in a narrow window" (GPT-5.4/Kimi's framing).

No outright contradictions on correctness. The reviewers largely found the same core issues and then each explored different adjacent code for secondary leaks.

### Priority Summary

1. **Fix the `pending_responses` created_at regression** (GPT-5.4, high) — the cleanup actively breaks long-running requests.
2. **Fix `reap_idle()` race condition** (all three, high) — double-check `busy` inside `kill_process()`, move the `wait()` outside the lock.
3. **Protect group-chat participants from reaping** (Gemini + GPT-5.4, high) — either exempt `group-*` processes or implement respawn logic.
4. **Add MessageRouter conversation/queue cleanup** (Gemini, high) — abandoned conversations and poll queues are unbounded.
5. **Enrich `/debug/memory`** with router state, task counts, queue depths (all three, medium).
6. **Subscriber queue and minor leaks** (Kimi, GPT-5.4, medium) — cleanup on death, OAuth codes, `_session_observations_loaded`.

**Models responded:** gemini-3.1-pro (agentic), gpt-5.4 (agentic), kimi-k2.5 (agentic)

## Individual Reviews

### gemini-3.1-pro (complete)

Here is my review of the changes aimed at fixing the memory leak and graceful shutdown issues, based on the provided files and adjacent context. 

### 1. SIGTERM Handler Fix (`server.py`)
**Severity:** None (Correct)
The approach to handling SIGTERM is correct. By keeping a reference to the previous handler (`_prev_sigterm = signal.getsignal(signal.SIGTERM)`) and calling it if it's callable, you ensure that Uvicorn's shutdown sequence executes (which then naturally triggers the `lifespan` teardown). Resetting to `SIG_DFL` and re-raising via `os.kill` is also a safe fallback for environments without a Uvicorn handler.

### 2. Periodic Cleanup Task (`server.py`)
**Severity:** Low / Medium
The background task properly uses standard asyncio dictionary deletion, which is thread-safe here because `asyncio` is single-threaded and there are no `await` yields during the iteration/deletion loops. The 10m TTL and 2m interval are perfectly reasonable.
*Note:* In `_periodic_cleanup`, you clear stale counters from `routing_table._message_counts` if the route is missing from `routing_table._routes`. However, there does not appear to be any code that evicts abandoned sessions from `_routes` itself. If `_routes` is never cleaned up, this specific cleanup logic will be ineffective.

### 3. `ChatProcessManager.reap_idle()` (`chat_process.py`)
**Severity:** Critical (Race Condition & Lock Contention)
There are two major issues in how idle processes are killed:
1. **Race Condition (Killing Busy Processes):** `reap_idle` acquires `self._lock` to identify idle processes, adds them to `to_reap`, and then **drops the lock**. It loops over `to_reap` and calls `await self.kill_process(chat_id)`. During the time the lock is dropped, a new request could call `get_or_spawn`, grab that same idle process, and mark it `busy = True`. When `kill_process` runs, it blindly pulls the process from the dict and terminates it mid-request. 
2. **Lock Contention:** Inside `kill_process`, you call `await asyncio.wait_for(cp.process.wait(), timeout=5.0)` **inside** the `async with self._lock:` block. This means the entire `ChatProcessManager` is blocked from routing or spawning any new processes for up to 5 seconds per reaped process. 
*Fix:* In `kill_process`, you should `pop()` the process from `self._processes` inside the lock (after double-checking it hasn't become `busy`), release the lock, and *then* await its termination.

### 4. Connection Leak Fix (`_get_conn` contextmanager)
**Severity:** None (Correct)
This fix is spot on. Using a `@contextmanager` with a `yield conn` and `finally: conn.close()` ensures the connection is actually closed and returned to the system. 
You asked if any callers will break: **No.** I audited the 6 store modules (`conversation_store.py`, `oauth_store.py`, `totp_store.py`, `notifications.py`, `observations.py`, `scheduler.py`). Every single caller explicitly calls `conn.commit()` after their cursor blocks. Because uncommitted transactions in Postgres are safely and implicitly rolled back when the connection is closed, this pattern perfectly replicates the transaction-safety of the old psycopg2 connection block while adding the missing connection teardown. 

### 5. `/debug/memory` Endpoint
**Severity:** Medium (Observability gap)
The endpoint is incredibly useful, but it misses a critical area. It currently tracks `chat_processes` and `session_manager_sessions`, but it completely omits the `MessageRouter` state. You should add tracking for `len(message_router._conversations)`, `len(message_router._buses)`, and `len(message_router._participant_index)`.

### 6. OTHER Memory Leaks Missed
**Severity:** High (Unbounded growth)
There are massive leaks hiding in `message_router.py` related to group chats:
1. **Abandoned Conversations:** If an MCP client calls `group_join`, a `Conversation` object is created and cached in `MessageRouter._conversations`. If the client disconnects or abandons the session without explicitly calling `group_leave`, that conversation (and its ever-growing `message_log` list) lives in memory forever. `_periodic_cleanup` does not sweep idle router conversations.
2. **Infinite Poll Queues:** In `MessageRouter.add_mcp_client`, an `asyncio.Queue` is instantiated as a `poll_queue`. The conversation bus blindly pushes messages into this queue. If an MCP client joins but stops calling `group_poll`, this queue will grow infinitely with every message sent to the group.

### Bonus Finding: Reaped Processes Break Group Chats
**Severity:** High (Functional Bug)
If `reap_idle` successfully kills an idle Claude instance that was participating in a group chat, that Claude is permanently broken. In `MessageRouter._claude_writer` (`message_router.py`), if `self._cpm._processes.get(chat_id)` returns `None` (because it was reaped), the while loop simply breaks and the writer task exits. Future messages to that group chat will never wake that Claude process back up.

### Bonus Finding: `get_messages` Limit Logic
**Severity:** Low (Functional Bug)
In `ConversationStore.get_messages`, the query uses `ORDER BY timestamp LIMIT %s`. Because it orders ascending, a limit of 200 will always return the **oldest 200 messages ever sent**, rather than the 200 most recent ones. You likely want `ORDER BY timestamp DESC LIMIT %s` and then reverse the results in Python.


### gpt-5.4 (complete)

I read the requested files and, for context, also read `src/claude_hub/routing.py`, `src/claude_hub/message_router.py`, `src/claude_hub/conversation.py`, and `src/claude_hub/session.py`.

I found three substantive issues. The most important is in `src/claude_hub/server.py:175` and `src/claude_hub/server.py:855`. `_periodic_cleanup()` expires `pending_responses` by comparing `now` to `created_at`, but the completion/error writes in `hub_send` replace the whole entry and drop `created_at`. That means finished entries look infinitely old and get evicted on the very next cleanup pass, not after 10 minutes. More seriously, requests that are still genuinely running past 10 minutes are deleted while still pending, so `hub_poll` starts returning `Unknown request_id` even though the background task is still alive. I would call that high severity because it turns the leak fix into a correctness regression for long-running work.

The second high-severity issue is that the idle reaper is global, but group-Claude participants are not restartable after reap. `src/claude_hub/server.py:185` calls `reap_idle()` for every managed process. In adjacent router code, a group participant is registered once at `src/claude_hub/message_router.py:460`; there is no path that respawns and re-registers it later. If a `group-*` process sits idle for 30 minutes and gets reaped in `src/claude_hub/chat_process.py:338`, the writer task later exits when it sees no process at `src/claude_hub/message_router.py:228`, and the listener in `src/claude_hub/message_router.py:241` can block forever because `kill_process()` cancels the stdout reader first at `src/claude_hub/chat_process.py:323`, so no terminal error is delivered to subscriber queues. Functionally, an active but quiet group conversation can lose a Claude participant after 30 minutes; memory-wise, that can also strand a listener task until full conversation cleanup.

The third issue is medium severity and is the direct answer to your “about to receive work” question. `reap_idle()` snapshots candidates under the lock at `src/claude_hub/chat_process.py:345`, then releases the lock and kills them later via `src/claude_hub/chat_process.py:355` without rechecking `busy` or `last_activity`. A request can start in that window and still get killed. On top of that, `last_activity` is only refreshed when the prompt is written at `src/claude_hub/chat_process.py:261`; the reader clears `busy` on `result` at `src/claude_hub/chat_process.py:237` but never refreshes activity as output streams or when the turn completes. So a long-running turn can become “idle >30m” the instant it finishes and be reaped almost immediately afterward.

On the SIGTERM handler itself, I think the change in `src/claude_hub/server.py:273` is directionally correct. Chaining to the previous handler is the right fix for the uvicorn case and is much better than clobbering it. The edge cases I see are low severity: if the prior handler is `SIG_IGN`, shutdown is still ignored, and because the old handler is never restored after lifespan teardown, repeated lifespan runs in one process will stack wrappers and duplicate logging.

The `_get_conn` fix looks sound. I searched the repo and every caller in these six store modules still uses `with self._get_conn() as conn:`; I did not find any caller expecting `_get_conn()` to return a raw connection object. `tests/test_conversation_store.py:168` was updated consistently. I do not see a compatibility break from that change.

`/debug/memory` in `src/claude_hub/server.py:1047` is useful, especially the current `VmRSS` and the core dict/process counts, but it is still missing the data I would want for the next leak hunt: per-process subscriber counts from `ChatProcess._subscribers`, message-router conversation/bus/task counts, and queue depths for group/MCP participants. As written, it would not surface the stranded group-listener case above. One adjacent leak I did notice outside the requested file set is `src/claude_hub/session.py:82`: `_session_observations_loaded` grows on first use and is never pruned in `terminate_session()`.

Within the reviewed files, beyond the issues above, I did not see another obvious unbounded in-memory structure that looks as plausible as the original `pending_responses`, routing counters, and long-lived process table.


### kimi-k2.5 (complete)

Let me explore adjacent code for context:
Now I have sufficient context. Let me write my review:

---

## Code Review: Memory Leak and Graceful Shutdown Fixes

**Files read beyond targets**: `src/claude_hub/routing.py`, `src/claude_hub/message_router.py` (for context on routing table usage and message router lifecycle)

---

### 1. SIGTERM Handler Fix (server.py:273-284)

**Status: Correct implementation**

The handler properly chains to the previous handler:
- Saves `_prev_sigterm` before registering (line 273)
- Calls previous handler if callable (line 278-279)
- Handles SIG_DFL by reinstalling and re-sending signal (lines 280-282)

**Minor edge case**: If uvicorn hasn't registered its handler yet when this runs (unlikely in lifespan), the chaining is harmless. The `os.kill()` approach for SIG_DFL is correct but note it will re-trigger the signal handler; since SIG_DFL is restored first, this results in immediate termination.

---

### 2. Periodic Cleanup Task (server.py:165-198)

**Status: Generally sound with minor issues**

**TTL/Intervals are reasonable**:
- 10 min for pending_responses, 30 min for idle processes, 2 min cleanup interval — appropriate for the workload described.

**Race condition in routing table cleanup (lines 190-195)**:
```python
stale_counts = [
    cid for cid in routing_table._message_counts
    if cid not in routing_table._routes
]
for cid in stale_counts:
    del routing_table._message_counts[cid]
```

The RoutingTable class has no synchronization. If `record_message()` is called on a conversation between the list comprehension and the deletion, that message count will be lost. **Severity: Low** — counts are best-effort metrics, not correctness-critical.

**Dictionary modification during iteration**: The `pending_responses` cleanup iterates the dict while potentially another coroutine adds entries. In CPython 3, this is safe due to dict implementation, but relying on this is subtle. Consider `list(pending_responses.items())` for clarity.

**Missing cleanup**: Authorization codes in oauth_store have a 10-minute TTL (line 48 in oauth_store.py) but no periodic cleanup is scheduled. The table could grow unbounded. **Severity: Medium** — OAuth flows are infrequent, but 148 sessions × potential retries could accumulate.

---

### 3. ChatProcessManager.reap_idle() (chat_process.py:338-357)

**Status: Race condition exists**

```python
async with self._lock:
    for chat_id, cp in self._processes.items():
        if cp.busy:  # Check 1
            continue
        idle = (now - cp.last_activity).total_seconds()
        if idle > max_idle_seconds:
            to_reap.append(chat_id)

reaped = 0
for chat_id in to_reap:
    if await self.kill_process(chat_id):  # Check 2
        reaped += 1
```

**The race**: A process is identified as idle (not busy, >30min inactivity) while holding the lock. The lock is released, then `kill_process()` is called which re-acquires the lock. Between these two points:
1. A new message could arrive, setting `busy=True` and updating `last_activity`
2. The process gets killed despite being actively processing

**Severity: Medium-High** — Killing a busy process could lose in-flight work. The `busy` flag is set in `write_message()` (line 260), but there's a window between the check and the kill.

**Recommendation**: Move the busy check inside `kill_process()` or pass the ChatProcess object directly to avoid the TOCTOU race.

---

### 4. Connection Leak Fix (@contextmanager in 6 store modules)

**Status: Correct implementation**

All six modules (oauth_store, totp_store, notifications, conversation_store, scheduler, observations) implement the pattern correctly:

```python
@contextmanager
def _get_conn(self):
    conn = psycopg2.connect(self.dsn)
    try:
        yield conn
    finally:
        conn.close()
```

**Potential issue**: If a caller uses `_get_conn()` but doesn't commit/rollback before exiting the context, psycopg2 will rollback on close (good). However, in error paths where `conn.commit()` isn't reached, the connection is still properly closed.

**No breaking changes expected**: All existing usage patterns (context manager or explicit commit inside) continue to work. The only behavioral change is connections are now actually closed.

---

### 5. /debug/memory Endpoint (server.py:1047-1107)

**Status: Useful but incomplete**

**What's good**:
- Process RSS from both `getrusage()` and `/proc/self/status`
- Key collection sizes (pending_responses, routing table, sessions, chat processes)
- Attempts to count SSE sessions from fastapi_mcp internals
- tracemalloc integration when available

**What's missing** (for memory leak detection):
- **asyncio task count**: `len(asyncio.all_tasks())` — leaked tasks are common in async code
- **Event loop statistics**: Slow tasks can queue up
- **File descriptor count**: Leaked connections, pipes, or subprocess file descriptors
- **ObservationStore connection pool**: If DSN is set, how many connections are open?
- **Per-conversation breakdown**: How many messages in each conversation log?
- **Subscriber queue sizes**: In chat_process.py, `_subscribers` dict size per process

**Severity: Low** — The endpoint provides sufficient coarse-grained data for the immediate issue, but richer metrics would help future debugging.

---

### 6. Other Potential Memory Leak Sources

**A. ObservationStore instantiation in websocket_chat (server.py:1903)**

```python
obs_store = ObservationStore(dsn=os.environ.get("CLAUDE_HUB_PG_DSN", ""))
```

Each WebSocket message creates a new ObservationStore. The store creates a new connection on every method call (via `_get_conn`), which is now properly closed. However, the store object itself accumulates. **Severity: Very Low** — objects are small and short-lived, will be GC'd.

**B. Subscriber queue cleanup in chat_process.py**

When a process dies (EOF in `_stdout_reader`, line 217), subscribers are notified of error but not removed:
```python
for q in list(cp._subscribers.values()):
    await q.put(error_event)
cp._dead = True
```

The `_subscribers` dict retains references to dead queues. Only `unsubscribe()` removes entries. If callers don't unsubscribe on error, queues leak. **Severity: Medium** — Each WebSocket group chat participant subscribes; if they disconnect abruptly, their queue remains.

**C. Message log growth in Conversation class**

`Conversation.message_log` (accessed in message_router.py) grows without bound. No truncation or rotation is visible. For long-running group conversations, this could consume significant memory. **Severity: Medium-High** for long-lived conversations.

**D. Routing table message counts**

`routing_table._message_counts` (routing.py:19) accumulates entries for every conversation ever seen. Cleanup in `_periodic_cleanup()` only removes entries for conversations no longer in `_routes`. For short-lived conversations, this is fine. For long-running servers with many transient conversations, this dict grows. **Severity: Low** — int values are small, but unbounded growth is a concern.

**E. Scheduler thread safety**

Scheduler uses a background thread (`_run_loop`) that accesses PostgreSQL via `_get_conn()`. The contextmanager closes connections properly. However, the thread is daemon=True (line 86) which could leave transactions in-progress during abrupt shutdown. **Severity: Low** — PostgreSQL will rollback on connection loss.

**F. Unbounded pending_responses growth under high load**

The TTL cleanup runs every 2 minutes. If request volume spikes, pending_responses could grow large before cleanup runs. Consider a max_size limit with LRU eviction for pathological cases. **Severity: Low** — 10-min TTL limits worst-case growth to ~10 min of traffic.

---

### Summary Table

| Finding | Location | Severity | Recommended Action |
|---------|----------|----------|-------------------|
| Race in reap_idle (busy check) | chat_process.py:338-357 | Medium-High | Check busy flag inside kill_process or pass process object |
| Routing table counts race | server.py:190-195 | Low | Acceptable for metrics; document or add lock |
| Missing auth code cleanup | oauth_store.py | Medium | Add periodic cleanup task |
| Subscriber queue leak | chat_process.py:219-221 | Medium | Clear _subscribers on process death or track liveness |
| Unbounded message_log | message_router.py Conversation | Medium-High | Add truncation or pagination |
| Memory endpoint gaps | server.py:1047-1107 | Low | Add task count, FD count, per-conversation sizes |

**Overall assessment**: The fixes address the primary memory leak (unclosed DB connections) and the SIGTERM issue. The cleanup task is a good defensive addition. The most concerning remaining issue is the race condition in `reap_idle()` that could kill busy processes.

