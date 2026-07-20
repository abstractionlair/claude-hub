# MCP Tool Reference

Last audited: 2026-07-09. Written by GPT-5.5 (Codex) from the source;
verified claim-by-claim by Claude the same day, including a set-diff of the
documented tools against the live manifest.

This document describes the MCP tools exposed by the `claude-hub` FastAPI
service. The current manifest is generated in `src/claude_hub/server.py` by
`FastApiMCP`. Descriptions below are taken from endpoint docstrings and
Pydantic request models where they exist; otherwise they are inferred from the
handler code.

## Manifest Caveat

Update 2026-07-10: the two accidentally exposed web routes
(`add_codex_to_conversation`, `add_gemini_to_conversation`) are now excluded
from the manifest (commit 081045c, with a regression test), so the live
manifest exposes 48 tools, all backed by `POST /tools/*` endpoints. Their
table entries below are kept for reference as web-API routes. The remaining
long-term fix is switching MCP registration from the exclude-list to an
explicit `include_operations` allowlist (work-graph schm-0).

## Core Hub Relay

These tools connect an external MCP client to a persistent Claude Code backend.
Use this family for simple request/response delegation to Main Claude.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `hub_init` | Start a new conversation with Main Claude and get a `conversation_id`. | None. | Also pre-warms a persistent Claude process for the conversation. |
| `hub_send` | Send a message to Main Claude. | `conversation_id`, `message`. | Returns immediately with a `request_id`; it does not return the final answer. |
| `hub_poll` | Poll for a response from a previous `hub_send`. | `request_id`. | Returns `pending`, `complete`, or `error`, plus response text when complete. |
| `hub_status` | Inspect hub routing and session state. | Optional `conversation_id`. | Includes active sessions, routing info, main-session token status, and observation stats. |

Typical flow: `hub_init` -> `hub_send` -> repeated `hub_poll`.

## Delegation, Scheduling, and Handoffs

These tools support delegated-agent workspace management, scheduled wake-ups,
and structured handoff files.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `create_workspace` | Create an isolated workspace directory for an agent. | `project`, `agent_id`, optional `parent_id`, optional constraints. | Parent agents can create child workspaces; response includes path and agent directory name. |
| `list_children` | List child workspaces for a parent agent. | `project`, `parent_agent_id`. | Reads from the workspace manager's project work tree. |
| `schedule_wake_at` | Schedule a one-time wake-up prompt for a session. | `session_id`, `time`, `prompt`, optional constraints. | Useful for deferred follow-up. |
| `schedule_wake_every` | Schedule a recurring wake-up prompt. | `session_id`, `interval_seconds`, `prompt`, optional start/end and constraints. | Interval is stored as seconds. |
| `list_schedules` | List scheduled wake-ups. | Optional `session_id`. | Returns schedule IDs, next wake time, interval, prompt, and creation time. |
| `cancel_schedule` | Cancel a scheduled wake-up. | `schedule_id`. | Returns `success`. |
| `write_handoff` | Write a structured handoff document from an agent. | `project`, `agent_id`, `summary`, `status`, optional findings/files/questions/recommendations. | Requires the target workspace to exist. |
| `read_handoff` | Read a specific agent's handoff document. | `project`, `agent_id`, optional `parent_id`. | Returns parsed handoff data and raw Markdown when present. |
| `list_handoffs` | List all handoffs in a project. | `project`. | Scans the project's work directory. |

## Persistent File Storage and GitHub

These tools operate on claude-hub's persistent storage area or read a file from
GitHub. Storage paths are relative to the configured storage root and are
checked for traversal.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `files_read` | Read a file from persistent storage. | `path`. | Returns file content and path. |
| `files_write` | Write a file to persistent storage. | `path`, `content`. | Creates parent directories as needed. |
| `files_list` | List files and directories. | Optional `path`, optional `recursive`. | Returns entries with name, type, size, and modified time. |
| `files_append` | Append content to a storage file. | `path`, `content`. | Creates the file if it does not exist. |
| `files_search` | Search text within storage files. | `query`, optional `path`, optional `glob_pattern`. | Defaults to searching Markdown files. |
| `github_read_file` | Read a file from a GitHub repository via the GitHub API. | `owner`, `repo`, `path`, optional `ref`. | Requires configured GitHub credentials. Defaults to `ref = main`. |

## Notifications

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `notify` | Send a fire-and-forget notification to the human user. | `message`, optional `priority`, `project`, `details`. | Writes to the notification store and appears in the web UI. This is not a message to Main Claude. |

## Group Chat

These tools expose the multi-participant conversation bus to MCP clients. Use
this family when multiple participants, humans, or model processes need to share
a conversation. For simple Main Claude delegation, prefer `hub_send` and
`hub_poll`.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `group_join` | Join or create a group conversation as an MCP client. | `conversation_id`, `name`. | Returns `participant_id`, current participants, and recent message history. |
| `group_send` | Send a message to a group conversation. | `conversation_id`, `participant_id`, `message`, optional `recipient_id`. | Delivery is asynchronous through the message bus. |
| `group_poll` | Receive pending group messages. | `participant_id`. | Drains the MCP participant's poll queue. |
| `group_leave` | Leave a group conversation. | `conversation_id`, `participant_id`. | Removes the participant and broadcasts a leave event. |

### Currently Exposed Web API Routes

These appear in the MCP manifest today but are likely not intended MCP tools.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `add_codex_to_conversation` | Add a Codex CLI participant to an existing group conversation. | Path `conversation_id`; body `name`, optional `model`, optional `thread_id`. | Inferred from web API handler. Spawns/resumes Codex per turn through `CodexChat`. |
| `add_gemini_to_conversation` | Add a Gemini CLI participant to an existing group conversation. | Path `conversation_id`; body `name`, optional `model`, optional `session_id`. | Inferred from web API handler. Spawns/resumes Gemini per turn through `GeminiChat`. |

## Artifact Store

These tools expose durable, searchable knowledge artifacts stored in Postgres
with embedding support. They require the Postgres pool to be configured.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `artifact_store` | Store a new artifact. | `content`, `artifact_type`, optional `tags`, `source_ref`, `derives_from`, `sensitive`, `metadata`. | Creates version 1 and queues an embedding unless sensitive handling disables it. |
| `artifact_get` | Retrieve an artifact by ID. | `id`, optional `include_versions`, optional `include_feedback`. | `include_outcomes` is a deprecated alias for `include_feedback`. |
| `artifact_search` | Semantic search across artifacts. | `query`, optional filters: `artifact_type`, `tags`, date range, `confidence`, `include_archived`, `limit`. | Returns quality-weighted relevance scores. |
| `artifact_list` | Browse artifacts without semantic search. | Optional filters: `artifact_type`, `tags`, `include_archived`, `limit`, `offset`. | Use for listing and pagination. |
| `artifact_archive` | Archive an artifact. | `id`. | Preserves the artifact but excludes it from normal search/list behavior unless archived items are included. |
| `artifact_update` | Create a new content version for an artifact. | `id`, `content`, optional `metadata`. | Preserves previous versions. |
| `artifact_update_metadata` | Update artifact metadata, tags, or archived status. | `id`, optional `metadata`, `tags`, `archived`. | Does not create a new content version. |
| `artifact_export` | Export artifacts to a backup file. | Optional `format`, optional `artifact_type`. | Handler delegates to `artifact_store.export_artifacts`. |
| `artifact_import` | Import artifacts from an export file. | `path`, optional `dry_run`. | Deduplicates by content hash/source behavior in the store. |
| `artifact_feedback` | Record whether an artifact was useful. | `artifact_id`, `useful`, optional `note`, optional `agent_id`. | Updates Bayesian `utility_score`. |
| `artifact_set_confidence` | Set confidence for an artifact. | `artifact_id`, `confidence`, optional `reason`. | Confidence values are `HIGH`, `MEDIUM`, `LOW`, or `SUPERSEDED`. |
| `artifact_retirement_candidates` | Find old, low-utility artifacts that may be retired. | Optional `min_age_days`, `max_utility`, `limit`. | Returns candidates with preview, utility, confidence, retrieval, and creation metadata. |

## Connectors and Federated Search

Connectors register external or internal data sources and build searchable
indexes. Currently configured connector implementations include
`artifact_store` and `filesystem`.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `connector_register` | Register a new data-source connector. | `name`, `connector_type`, optional connector `config`. | Validates the connector; failed validation stores status `error` and returns error detail. |
| `connector_index` | Trigger indexing for a registered connector. | `connector_id`, optional `path`. | Updates `last_indexed`; returns scanned/indexed/skipped/deleted counts and errors. |
| `query_federated` | Search across registered connectors. | `query`, optional `connector_names`, optional `filters`, optional `limit`. | Returns merged ranked results with source, connector name, score, and metadata. |

## Work Graph

The `wg_*` tools are a gateway to a separate local work-graph service. The graph
is global; sessions only provide a per-client cursor and breadcrumb trail.

| Tool | Purpose | Key Inputs | Notes |
| --- | --- | --- | --- |
| `wg_session_start` | Start a work-graph session. | None. | Returns `session_token`. New sessions start cursorless. |
| `wg_brief` | Return a curated read-only brief of current work state. | Optional `max_captured`, optional `include_notes`. | Safe first call for "what is on my plate?" style questions. |
| `wg_capture` | Capture a new work item. | `text`, optional `notes`, `status`, `session_token`, `parent_id`, `root`. | Can create a root or child. With a session token, updates cursor and breadcrumbs. |
| `wg_goto` | Move a session cursor to a node and return its context. | `session_token`, `node_id`. | Returns node, provenance path, direct children, and dependency edges. |
| `wg_status` | Show session state. | `session_token`. | Cursorless sessions get roots; cursor sessions get node context and breadcrumbs. |
| `wg_query` | Run structural graph queries. | `session_token`, `type`, optional `scope`, optional `days`. | Query types: `overview`, `ready`, `recent`, `deferred`, `blocked`. |
| `wg_search` | Search nodes by text substring. | `text`. | Case-insensitive; returns provenance path and root text. |
| `wg_add_dependency` | Add a cross-cutting dependency edge. | `from_id`, `to_id`, `type`. | Edge type is `blocks` or `related`; provenance tree edges are not created here. |
| `wg_update` | Update a node's text and/or status. | `node_id`, optional `text`, optional `status`. | Status values: `captured`, `in-progress`, `done`, `won't-do`. |

## Non-MCP Features In This Repo

Several nearby systems are intentionally not exposed as MCP tools:

- Multi-model reviews use `python3 -m claude_hub.review_cli`, not MCP tools.
- Window-file continuity uses hooks and the `claude_hub.continuity` CLI.
- The web dashboard, chat UI, terminal UI, OAuth endpoints, webhooks, and debug
  endpoints are HTTP/WebSocket surfaces, not MCP tools.

