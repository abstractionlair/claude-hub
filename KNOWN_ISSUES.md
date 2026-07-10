# Known Issues — continuity / window system

Running notes on the narrative-window system (the `~/.claude/hooks/*continuity*` +
`periodic-narrative-update.sh` + `src/claude_hub/continuity*.py` machinery). Add dated
entries; pick up from a sysadmin/workbench session.

---

## 2026-07-10 — fork cache probe: forks do NOT reuse the main session's cache

Measured (one `claude --resume <id> --fork-session --print` against a live
~410k-token session, `--output-format json` usage fields):
cache_read 15,497 (the generic system/tools prefix only — cached by other `-p`
calls, not by the session being forked); cache_creation 393,604 (1h tier) — the
entire transcript re-uploaded as a fresh cache write; 29s wall; $7.97
API-equivalent (subscription quota). The `-p` fork's context assembly diverges
from the interactive session's cached prefix at the top, so prefix identity
breaks and nothing of the conversation body cache-hits.

Implications: (a) finding #4's cost is now quantified — ~$8 API-equivalent per
narrator fork on a long session; (b) the write went to the 1-HOUR tier, and a
later fork of the same session is a strict prefix-extension, so consecutive
narrator forks within an hour should partially pay each other back (untested);
(c) the improvement idea in #4 — feed the fork a recent transcript slice
instead of full `--resume` — has a hard number attached. No prior record of
this experiment exists on this box (it may have been run in Scott's work
environment; nothing in windows, docs, memory, or the artifact store).

---

## 2026-06-27 — window-system findings (from a coach session debugging a slow pre-compact)

Investigated why a coach (Health & Fitness) pre-compact ran strangely long and found
several things worth a proper look. **Fixed two; flagged the rest.**

### FIXED

1. **Periodic updater silently skipped role projects with no `thoughts/` dir.**
   `periodic-narrative-update.sh` gates on `[ -d "$PROJECT_DIR/thoughts" ]`. The H&F
   project had no `thoughts/` dir (Cowork-migration gap), so the ~every-N-tokens fork
   never fired there — 5 of 6 coach windows were empty `# New Session` stubs; only the
   one session that *compacted* (pre-compact fork, which is NOT gated) produced content.
   Fix applied: created `Health and Fitness/thoughts/{mechanical.jsonl,windows/claude-code/}`.
   - **Design smell still present:** the gate checks a *project-local* `thoughts/` even
     though role-based projects route windows/mechanical to `~/roles/$ROLE/` (so the
     project-local `thoughts/` stays empty and exists *only* to satisfy the gate).
     Consider making the gate role-aware, e.g.:
     `if [ ! -d "$PROJECT_DIR/thoughts" ] && ! { [ -n "$CURRENT_ROLE" ] && [ -d "$HOME/roles/$CURRENT_ROLE/windows" ]; }; then skip`
     so no future role project silently loses periodic updates.

2. **Stale threshold.** `THRESHOLD` was `20000` (sized for the old 200K context window).
   Bumped to `200000` (~1/5 of the current 1M window) in `periodic-narrative-update.sh`,
   plus comment in `stop-wrapper.sh`. **Global change — affects all roles/projects.**
   (`~/.claude` is not git-tracked; backup at `~/.claude/hooks/periodic-narrative-update.sh.bak-20260627`.)

### FLAGGED (not yet acted on)

3. **`--fork-session` session-ID remap vs `.current-<id>` pointer (the main fragility).**
   Both forks resolve the target window via `.current-${SESSION_ID}` in the window dir.
   But `claude --resume <id> --fork-session` runs under a *remapped* session ID, and a
   resumed interactive session also gets a new ID — so the live ID often has no pointer.
   The code then falls back to `continuity find-latest --session-id <id>`, which can
   return nothing → the fork either writes to the wrong window or creates a stray one.
   - Evidence: this coach session exists under **two** IDs (`b9f0a0f1…` pre-compact,
     `41cb415a…` now). `.current-41cb415a…` exists; **no** `.current-b9f0a0f1…`. The
     2026-06-15 pre-compact fork for `b9f0a0f1` had no pointer to bind to.
   - Worth: make pointer resolution robust to ID remap (e.g. map fork→origin ID, or
     resolve the window by most-recently-updated non-finalized file for the role).

4. **Every fork reads the full context to write a small delta.** Both triggers do
   `claude --resume <session> --print` = reload the entire (near-compaction) context,
   ~150k+ tokens, then append a short window section + artifact-ingest + git commit/push.
   That's the "strangely long pre-compact." The NARRATIVE_PROMPT correctly scopes output
   to the delta (it appends, doesn't re-summarize — verified), so this is an *input*-side
   cost, not redundant writing. At the new 200K cadence it fires less often, but on big
   sessions each run is still heavy. Possible improvement: feed the fork only the recent
   transcript slice instead of a full `--resume`.

5. **Log hygiene (minor).** `~/.claude/cache/narrative-update.log` is shared across all
   roles/sessions, append-only, ~290 KB, never rotated. `stop-wrapper.log` last wrote
   `2026-05-25` during a transient **"No space left on device"** event (disk since
   recovered; now 68% used). No rotation on either.

### Pointers
- Hooks: `~/.claude/hooks/pre-compact-continuity.sh`, `periodic-narrative-update.sh`, `stop-wrapper.sh`, `session-start-continuity.sh`
- Prompt: `~/roles/NARRATIVE_PROMPT.md`
- Code: `src/claude_hub/continuity.py`, `continuity_cli.py`, `continuity_ingest.py`
- Window dirs: `~/roles/$ROLE/windows/` (role sessions) or `<project>/thoughts/windows/claude-code/` (role-less)
