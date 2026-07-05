[0m
[0m
> build · minimax-m2.5
[0m→ [0mRead thoughts/shared/spec-personal-ai-infrastructure.md[90m [offset=1307][0m
I'll read the rest of the spec to see the hook integration and build order sections, then provide a comprehensive review.
[0m✱ [0mGrep "--no-profile|--no-context"[90m in . · 1 match[0m
Let me verify the actual Claude CLI flags and check a few other items:
[0m
[0m
<bash_metadata>
bash tool terminated command after exceeding timeout 120000 ms
</bash_metadata>
[0m$ [0mclaude --help 2>&1 | head -40
[0m✱ [0mGrep "port.*=.*[0-9]{4}|listen.*[0-9]{4}"[90m in src · 1 match[0m
/home/claude/.local/bin/claude
Usage: claude [options] [command] [prompt]

Claude Code - starts an interactive session by default, use -p/--print for
non-interactive output

Arguments:
  prompt                                            Your prompt

Options:
  --add-dir <directories...>                        Additional directories to allow tool access to
  --agent <agent>                                   Agent for the current session. Overrides the 'agent' setting.
  --agents <json>                                   JSON object defining custom agents (e.g. '{"reviewer": {"description": "Reviews code", "prompt": "You are a code reviewer"}}')
  --allow-dangerously-skip-permissions              Enable bypassing all permission checks as an option, without it being enabled by default. Recommended only for sandboxes with no internet access.
  --allowedTools, --allowed-tools <tools...>        Comma or space-separated list of tool names to allow (e.g. "Bash(git:*) Edit")
  --append-system-prompt <prompt>                   Append a system prompt to the default system prompt
  --betas <betas...>                                Beta headers to include in API requests (API key users only)
  --chrome                                          Enable Claude in Chrome integration
  -c, --continue                                    Continue the most recent conversation in the current directory
  --dangerously-skip-permissions                    Bypass all permission checks. Recommended only for sandboxes with no internet access.
  -d, --debug [filter]                              Enable debug mode with optional category filtering (e.g., "api,hooks" or "!1p,!file")
[0m
[0m$ [0mwhich claude && claude --help 2>&1 | head -20 || echo "claude not in PATH"

[0m
[0m
--append-system-prompt <prompt>                   Append a system prompt to the default system prompt
  --system-prompt <prompt>                          System prompt to use for the session
[0m$ [0mclaude --help 2>&1 | grep -i "profile\|context\|system" | head -20

--add-dir <directories...>                        Additional directories to allow tool access to
  --agent <agent>                                   Agent for the current session. Overrides the 'agent' setting.
  --agents <json>                                   JSON object defining custom agents (e.g. '{"reviewer": {"description": "Reviews code", "prompt": "You are a code reviewer"}}')
  --allow-dangerously-skip-permissions              Enable bypassing all permission checks as an option, without it being enabled by default. Recommended only for sandboxes with no internet access.
  --allowedTools, --allowed-tools <tools...>        Comma or space-separated list of tool names to allow (e.g. "Bash(git:*) Edit")
  --append-system-prompt <prompt>                   Append a system prompt to the default system prompt
  --betas <betas...>                                Beta headers to include in API requests (API key users only)
  --chrome                                          Enable Claude in Chrome integration
  -c, --continue                                    Continue the most recent conversation in the current directory
  --dangerously-skip-permissions                    Bypass all permission checks. Recommended only for sandboxes with no internet access.
  -d, --debug [filter]                              Enable debug mode with optional category filtering (e.g., "api,hooks" or "!1p,!file")
  --debug-file <path>                               Write debug logs to a specific file path (implicitly enables debug mode)
  --disable-slash-commands                          Disable all skills
  --disallowedTools, --disallowed-tools <tools...>  Comma or space-separated list of tool names to deny (e.g. "Bash(git:*) Edit")
  --effort <level>                                  Effort level for the current session (low, medium, high)
  --fallback-model <model>                          Enable automatic fallback to specified model when default model is overloaded (only works with --print)
  --file <specs...>                                 File resources to download at startup. Format: file_id:relative_path (e.g., --file file_abc:doc.txt file_def:img.png)
  --fork-session                                    When resuming, create a new session ID instead of reusing the original (use with --resume or --continue)
  --from-pr [value]                                 Resume a session linked to a PR by PR number/URL, or open interactive picker with optional search term
  -h, --help                                        Display help for command
  --ide                                             Automatically connect to IDE on startup if exactly one valid IDE is available
  --include-partial-messages                        Include partial message chunks as they arrive (only works with --print and --output-format=stream-json)
  --input-format <format>                           Input format (only works with --print): "text" (default), or "stream-json" (realtime streaming input) (choices: "text", "stream-json")
  --json-schema <schema>                            JSON Schema for structured output validation. Example: {"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
  --max-budget-usd <amount>                         Maximum dollar amount to spend on API calls (only works with --print)
  --mcp-config <configs...>                         Load MCP servers from JSON files or strings (space-separated)
  --mcp-debug                                       [DEPRECATED. Use --debug instead] Enable MCP debug mode (shows MCP server errors)
  --model <model>                                   Model for the current session. Provide an alias for the latest model (e.g. 'sonnet' or 'opus') or a model's full name (e.g. 'claude-sonnet-4-6').
  --no-chrome                                       Disable Claude in Chrome integration
  --no-session-persistence                          Disable session persistence - sessions will not be saved to disk and cannot be resumed (only works with --print)[0m[0m$ [0mclaude --help 2>&1 | grep -E "^\s+-" | head -30
Based on my thorough review of the spec, here are my findings:

---

# Spec Review: Personal AI Infrastructure (Draft 2)

## Critical Issues

### 1. Claude CLI Clean-Room Flag Does Not Exist
**Location:** Section 6 (Review Model Registry), line 1373

**Issue:** The spec specifies `"clean_room_args": "--no-profile"` for Claude, but Claude CLI has no `--no-profile` flag. This is confirmed by examining `claude --help`.

**Suggestion:** Remove or change the clean-room approach. Options:
- Use `--system-prompt <empty>` to provide a minimal prompt
- Use `--allowed-tools <empty>` to restrict tools
- Document this as an open decision to resolve during implementation

---

### 2. PreCompact Hook Has Logical Issues
**Location:** Section 7.3 (PreCompact → Context Injection), lines 1485-1527

**Issue:** Several problems:
- The PreCompact hook runs when a session compacts, not when it ends. Reading from `thoughts/ledgers/` at that point is unreliable - the ledger for the current session may not have been written yet.
- The spec says it "injects open threads + active work items" but the actual implementation reads from a static markdown file (lines 1511-1516), which doesn't reflect current session state.
- The hook reads from the mechanical log but the session has likely already been compacted - recent operations may not be available.

**Suggestion:** Reconceptualize PreCompact - it should either inject state from the **previous** session (via artifact store) or acknowledge that it can only inject stable, persisted state. Consider removing the ledger read or making it read from the artifact store instead of markdown files.

---

### 3. SessionStart Outcome Prompting Is Misplaced
**Location:** Section 7.4 (SessionStart), lines 1556-1569

**Issue:** The spec says "SessionStart prompts for outcome ratings on unrated artifacts" but:
- The hook runs at session start before the agent has any context
- The implementation just appends to system message, not a user-facing prompt
- There's no actual prompting mechanism - just a list of artifacts in system message

**Suggestion:** Either remove this feature or implement it differently - perhaps via a separate tool the user can invoke (`artifact_unrated`) rather than attempting to inject it into every session start context.

---

## Important Issues

### 4. Outcome Boost Values May Be Too Small
**Location:** Section 4.1 (artifact_search), lines 596-601

**Issue:** The outcome boost values are +0.1 for SUCCEEDED, -0.1 for FAILED. On a cosine similarity scale of 0-1, a 0.1 boost is only ~10% of the range. This may not meaningfully reorder results when semantic similarity is strong.

**Suggestion:** Increase to +0.2/+0.15 for positive outcomes and -0.2 for failures. Or make the formula use multiplicative boosting rather than additive.

### 5. LATERAL Subquery Missing Deterministic Ordering
**Location:** Section 4.1 (artifact_search), lines 607-611

**Issue:** The `ORDER BY rated_at DESC` could return inconsistent results if multiple ratings have the same timestamp.

**Suggestion:** Add tiebreaker: `ORDER BY rated_at DESC, id DESC` to ensure deterministic ordering.

### 6. Hook HTTP Endpoints Lack Authentication
**Location:** Section 7 (Hook Integration), line 100 and throughout

**Issue:** All hooks access FastAPI via `curl localhost:8420` with no authentication. Any local process could theoretically call these internal endpoints.

**Suggestion:** This is acceptable for a single-user local system, but should be documented as a known limitation in the spec's Open Decisions section.

### 7. Review Model GPT-5.4 Doesn't Exist
**Location:** Section 6 (Review Model Registry), line 1383

**Issue:** The spec references "GPT-5.4" as a model in the registry. This model doesn't exist yet (current is GPT-4o series).

**Suggestion:** Replace with actual model names (e.g., GPT-4o, GPT-4o-mini) or mark as placeholder.

---

## Minor Issues

### 8. Minor Inconsistency: Auto-Detection Threshold
**Location:** Sections 4.5 and 9 (Phase 6)

**Issue:** Line 950 says "triggered after every 10 new session-summary artifacts" but the acceptance test in Phase 6 (line 1737) says "Given 5+ session summaries". 

**Suggestion:** Make these consistent - pick one threshold (recommend 10 to reduce false positives).

### 9. Mechanical Log Silencing Errors
**Location:** Section 7.1 (PostToolUse), line 1434

**Issue:** The hook has `|| true` and "Fail silently" comment. While appropriate for a hot path, this makes debugging impossible if the server is down.

**Suggestion:** Add a debug-mode log when the POST fails, even if it doesn't block the session.

### 10. FilesystemConnector Default Path
**Location:** Section 5.3, line 1357

**Issue:** Default config says `root_path: "thoughts/"` - but on nexus this should be the absolute path.

**Suggestion:** Make it explicit: `/home/claude/claude-hub/thoughts/` or derive from an environment variable.

---

## Internal Consistency Check

**API Surface (31 tools):** The tool list is internally consistent. Each requirement maps to tools, and the tool signatures align with the data model. No contradictions found.

**Build Order:** The dependency graph (lines 1768-1779) is sound. Phases 2-5 can run in parallel after Phase 1, and the dependencies for Phases 6 and 7 are correctly identified.

**Hook Integration:** Generally sound, but PreCompact has the issues noted above. The HTTP-based access is the right design choice for a single-server architecture.

---

## Overall Assessment

**Ready for Implementation?** No — one more revision needed.

**Summary:** The spec is well-structured and comprehensive. Most issues are correctable without major redesign. The critical items are:
1. Fix Claude CLI clean-room implementation (real blocker)
2. Reconsider PreCompact approach (architectural issue)
3. Resolve SessionStart outcome prompting (design issue)

The data model, API surface, and build order are solid. Once these 3 critical issues are addressed, the spec will be ready for implementation.
