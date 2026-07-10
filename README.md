# claude-hub

Claude Hub started as an MCP service running on a VPS which would allow a Claude at claude.ai to chat with a Claude in Claude Code running on the VPS with permissions to do things like stand up web apps. It was inspired, in part, by an experience in a claude.ai chat where Claude did a great job creating a simple web app as an artifact which then failed to allow full functionality because of CORS errors. The initial idea was that this could be very simple --- just allowing the two Claudes to chat in natural language. Both the VPS and the MCP service grew more functionality over time. This repo covers the service (and non-service features it accrued over time), not the VPS.

---

## Things that really belong here

### MCP tools

Originally claude.ai was the only client of these. That's expanded to Claude Code and Codex, even when running on the same machine as the service. The utility to me is having (much of) the same context wherever I happen to be interacting with models.

#### Persistent Claude Code backend (`hub_*`)

MCP tools `hub_init`, `hub_send`, `hub_poll`, and `hub_status` transport messages between Chat Claudes and a long-running Claude Code process that
has the facilities of a well-equipped VPS. The session manager resumes existing sessions first, tracks token usage (self-reported context markers, not metered), and triggers a graceful restart when context is critical. This was the initial purpose of claude-hub but it ended up less used than I'd expected. Once I had the VPS running, Claude Code, Codex, Gemini (at the time) installed and authorized, along with all the tools, libraries, ... that I could want, just logging in there and
using Claude Code supplanted a lot of my use of the web chat interface.

#### Artifact store (`artifact_*`)

Semantic knowledge storage with `pgvector` embeddings, confidence levels (`HIGH`, `MEDIUM`, `LOW`, `SUPERSEDED`), Bayesian utility tracking from feedback, and age-based decay. `artifact_search` reranks by embedding similarity plus confidence, usage-utility, and recency; `artifact_retirement_candidates` finds low-utility artifacts for cleanup.

Getting less use than I expected, but not none.

#### Work Graph (`wg_*`)

A DAG of the work on my plate: things I have committed to deliver, things I might do, and things instrumentally required by the others --- not just work in progress. Its first job is keeping me oriented across many concurrent AI-assisted threads; models help maintain it and often execute from it. `wg_capture` creates a node; provenance parent-child edges are automatic, and cross-cutting `blocks`/`related` edges are explicit via `wg_add_dependency`. `wg_brief` returns a curated read-only prose brief so a fresh agent --- or I, coming back after a weekend --- can orient in seconds. `wg_query` (`overview`, `ready`, `recent`, `deferred`, `blocked`), `wg_search`, `wg_goto`, and `wg_update` cover navigation and lifecycle.

The graph itself lives in a separate internal service (see Architecture); the hub is its MCP gateway.

I'm finding this very useful. 

#### Multi-model group chat (`group_*`)

A shared room for humans, Claude, Codex, and Gemini. REST endpoints and WebSocket `/ws/group/{conversation_id}` add participants, stream messages, and persist history to Postgres. MCP tools `group_join`, `group_send`, `group_poll`, and `group_leave` let programmatic participants join the same room.

Note that this is different than the multi-model chat _app_ in a different repo. That calls inference APIs. This allows existing sessions with models to _join_ a chat. In addition to a page on the VPS's web page which will launch some sessions for you and open a window for chatting. I can do things like give a conversation ID to a Claude in Chrome so it can chat with a Claude in Claude Code which can look for data in other files, etc. It should also allow two Claudes in Chrome(s) in different workbooks to coordinate, though I haven't needed that yet.

#### Supporting tools

Fractal delegation (isolated workspaces, handoff documents, cron-like wake-ups via `schedule_*`), `files_*` persistent storage, `github_read_file`, `notify`, and connectors for federated search across artifact and filesystem sources.

I still like this idea but didn't find myself using it after implementing. Agent teams may cover this ground.

### Not exposed over MCP

- **OAuth 2.1 boundary.** Dynamic client registration, PKCE, consent, and Bearer-token issuance gate the MCP endpoint; TOTP gates the human web surfaces.
- **Web surfaces.** Browser chat (WebSocket streaming against the same persistent backend), the group-chat UI, a notifications viewer, a terminal page, and read-only work-graph views.
- **Live rendering.** A watched-directory view layer: any project that creates a `live/` directory gets an auto-refreshing web view of its contents at `/live/<project>/` on the same domain. A session writes a file --- `plt.savefig("live/forecast.png")` --- and the open browser tab refreshes itself; no commit, no publish step. Images and short Markdown render inline; self-contained HTML embeds in an iframe, so a Plotly chart is fully interactive in place; subdirectories serve as documents via their `index.html`. This is a large part of what makes sessions in Claude Code cover the same use cases as chats at claude.ai: the chat interface can pop up charts and documents as artifacts, which isn't native to Claude Code in the terminal --- writing to `live/` fills that gap. (Its own small service and repo, `live-board`; listed here because it completes the picture.)
- **Background internals.** Startup migrations, an embedding retry loop, the wake-up scheduler, and periodic cleanup run inside the service process.

---

## Things that should have gone in a different project

These live in this repo because the VPS is where the work happened, but they serve the local development process rather than the network service. None of them are in the hub's MCP manifest.

### MCP, but local

#### Codex and Gemini stdio adapters

`python3 -m claude_hub.codex_mcp` and `gemini_mcp` expose persistent Codex and Gemini conversations (`codex_send`, `gemini_send`, session listing and reset) as stdio MCP servers. They speak the MCP protocol, but they register with a local harness such as Claude Code --- they are not tools of the claude-hub service.

The idea here was to allow a Claude in Claude code to easily ask for an opinion from Codex or Gemini. (The Gemini CLI is no more. This could be migrated to Antigravity.) The Multi-model review engine below, though, is what gets all the use now.

### Not MCP

#### Multi-model review engine

Infrastructure for getting reviews of code, mostly, but also of other artifacts by multiple models, synthesizing the reviews, grading them, and recording the grades to help in choosing which models to use going forward.

##### Plumbing
Every review is a subprocess invocation of a model CLI --- `claude`, `codex`, `agy` (Antigravity), `opencode`, historically `gemini`. There are no direct inference-API calls anywhere in the engine. Each model runs in one of two modes: *agentic* --- it receives a prompt and explores the codebase itself --- or *bundled* --- the content under review is shipped to it in a temp file. Why both exist: agentic is the primary mode, because a reviewer that can follow imports, callers, and tests produces a better-grounded review; bundling is the fallback for models whose CLI cannot read files, and bundled reviews are recorded as lower-context and treated accordingly downstream. Bundling is also, incidentally, the only way to get a *hard* clean room --- a bundled reviewer physically cannot read what you didn't send it --- and earlier drafts of the design worked that way, with reviewers as text processors receiving content bundles. The recorded resolution went the other way: anchoring is handled by opinion isolation (next paragraph), not information deprivation, because cutting a reviewer off from the spec, the surrounding code, and the tests costs more review quality than a soft boundary risks. Prompts are piped via stdin to dodge ARG_MAX, and each review's harness session ID is captured so the session can be resumed later.

##### Configuration
`config/review_models.yaml` defines the roster generically: per model, an `invoke` argv template, the mode, timeouts and input-size caps, a `resume_cmd` for follow-ups, and a `grading_cmd`. Reviewers run in a clean room by default --- opinion isolation, not information deprivation. A reviewer reads everything a good review needs (the intent or spec, the code, the tests) but is asked not to read process preferences or design-rationale documents, which per the requirements doc "could create anchoring bias (where the reviewer echoes back assumptions instead of challenging them)". The boundary is intent (share it) versus editorial opinion (withhold it). And it is deliberately a soft boundary: an agentic reviewer could read anything, so the design (after debate, in the requirements doc's draft history) trades hard enforcement for review quality --- the acceptance criterion is verifiable prompt construction plus an audit trail (reviewers must report which files they read beyond the targets), not a proof of abstinence. The config reserves per-model `clean_room_flags` for hard enforcement once the CLIs support profiles. Adding or dropping a model is a yaml edit, not code.

##### Pipeline
A job fans out to every configured model as parallel async tasks, tracked as rows in Postgres. When the last review lands, a synthesizer model (itself a config knob) writes a consensus report: agreements, single-reviewer catches, contradictions, severities. When a job mixed modes, findings that came *only* from bundled reviewers are flagged: a reviewer that could not explore the repo cannot check its claims against it, so its unique findings carry extra false-positive risk. A second structured pass extracts the contradictions as data, and for each one the engine resumes the *original sessions* of the reviewers involved and asks each, anonymously, to concede or defend with evidence. Finally the reviewers themselves are graded --- `EXCELLENT`, `ADEQUATE`, `INADEQUATE`, `HARMFUL`, with a failure-mode taxonomy (`false_positive`, `false_negative`, `wrong_severity`, `hallucinated_evidence`, `credulous`, `shallow`, `no_output`) --- using the synthesis as an approximate answer key. Cross-grading policy: every grader grades every review for the first twenty jobs, again whenever contradictions surfaced, and on every fifth job; otherwise the synthesizer grades alone. The smaller Claude seat hands its grading duty to Opus; the commit message says why: "grading requires judgment, not just formatting."

##### Storage
Reviews, syntheses, contradictions with their resolutions, and grades land in Postgres (`reviews`, `review_syntheses`, `review_grades`); reviews and syntheses are also stored as artifacts, so they are semantically searchable later. The entrypoint is a blocking local CLI (`python3 -m claude_hub.review_cli`) that writes a Markdown report --- no HTTP, no MCP.

##### As of writing (July 2026)
The registry holds six seats: two Claude, two Gemini (via Antigravity's `agy` --- wired July 2026 after Google retired the standalone CLI, with the flash seat upgrading to 3.5 in the move), one GPT (via `codex`), and Grok 4.5 (direct xAI, seated July 2026 after a debut review graded EXCELLENT). The roster is curated by its own grades, and the history shows it working: eight seats at launch in March 2026, ten after a refresh, then a graded cull to four --- six models dropped in one pass, open-weight and proprietary alike, a GPT variant and Grok among them, with the config recording "0-67% pass rates with false negatives and HARMFUL grades" --- then a fifth seat added (Gemini Flash). The dropped entries stay in the yaml, disabled, in case a rematch is ever warranted. The registry is a point-in-time snapshot and still lags practice in one respect: newer open-weight models that have done well in recent ad-hoc side work --- GLM-5.2 in particular, impressive for its cost --- are queued to be seated and graded next month. Fittingly, the engine's first job was reviewing itself: that first multi-model self-review found six bugs, all fixed.

#### Window-file continuity

As a preface, when I was creating this I was thinking in terms of terminology that I don't think is standard. In long running Claude Code sessions, by default, compaction occurs when context space is exhausted. (Or earlier if you set a smaller limit.) I'd been thinking of this as creating a _new_ context window and seeding it with the summary of the previous one. In this view, a long session is a sequence of such windows. That view led to the naming/wording below. This is to be contrasted with thinking of there being exactly one context window which periodically gets cleared and the summary placed at the start. That view would have led to different naming and wording below.

For long running sessions in Claude Code, which spanned multiple context windows, I was unsatisfied with compaction as the continuity mechanism. It sometimes, but only sometimes, was sufficient for continuing what I'd been doing near the end of the previous context window. But things further in the past were typically lost. I attribute part of this to the fact that at any moment we have just the one summary available, not the previous summary, or the previous previous summary, ... And I attribute another part to models having difficulty summarizing a very long context window because of context rot. The window file system creates a "window file" for each context window and uses hooks to have the agent write summaries of what it has been doing to the file, periodically so that it never has to summarize too large of a chunk and the chunk being summarized is always the most recent. Before compaction, one last write to the window file is made and it is finalized; the successor window file is created (and linked to it) when the next session starts. After the compaction, information from the previous window is inserted into the new window. This does overlap with the compaction summary, so far with no negative effects. Perhaps more importantly, the files are kept and can be searched to retrieve information far back in the history. This also allows retrieval of context from the histories of other sessions which has proven useful when I recall that something done as part of a different project has relevance to what I'm working on at the moment.

In my casual, subjective experience this has been very helpful. It would be worth doing a proper eval though. It's on a todo list.

##### Mechanism

Hook-driven, so no session has to remember to do it. As a session approaches its context limit --- and periodically along the way, roughly every 200k tokens of transcript --- a forked narrator (`claude --fork-session --print`) appends the era's delta to the current window file without consuming the main session's budget. Because this is forked, the narrator _is_ the agent that has been doing the work. (Identity of models/model instances is nuanced.) YAML frontmatter links each window to its parent and children (chain-shaped in practice; the links are DAG-ready for forked sessions), and files route to `~/roles/$ROLE/windows/`, so each role accumulates its own lineage. A session-start hook loads the parent window file into the next session, and selected information from the grandparent window file, and `continuity_ingest` feeds finalized windows into the artifact store, where they get embeddings.

##### What it buys

- **Fresh sessions start better oriented.** Information from the chain of window files supplements the compaction summary.
- **The whole history stays searchable --- not just the latest summary.** Compaction answers "what was I just doing?"; the ingested window chain answers "what did we decide about X?" weeks later, semantically.
- **Operational knowledge survives session death.** Two examples from a single week of this repo's own history: the CLI incantation that revived the review engine's dead Gemini seats was recovered from a window file another session had written; the review grade that justified seating Grok 4.5 was found the same way. Neither fact lived anywhere else that a search would reach.
- **Contemporaneous beats retrospective.** The narrator writes while the context is hot, so windows preserve reasoning, dead ends, and open threads --- exactly what an after-the-fact summary flattens. Reconstructing what one pre-window-era project had done took real archaeology across raw transcripts; anything from the window era is a search query instead.
- **The narration is nearly free to the session that benefits from it.** The fork does the writing; the main session spends no output budget on its own memoir.

##### Position in the memory stack

Three layers, in increasing curation: session JSONL is the raw ground truth --- complete, kept, consulted when it matters, but not a working memory; window files are the curated persistent layer --- the deliberate compromise between raw-log completeness and searchability; the artifact store provides semantic recall over the result. Compaction still runs --- window files just stop it from being the *only* memory.

##### Limits

Tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md), which is this subsystem's own running log: the `--fork-session` session-ID remap can leave the narrator pointing at the wrong window (the main open fragility); each fork reloads the full session context to write a small delta, which is heavy on long sessions; and the `children` side of the frontmatter links is not yet exercised --- parent links are what carry the chain today.

#### Role system

Over time as I added packages, components, tools, services, ... to the VPS I wanted Claude Code or other harness sessions, in whatever project I was working in, to know about them. E.g. "We have a Postgres server.". And I also wanted information about workflow preferences, and various documentation either inserted into context or pointers inserted into context. And, finally, I wanted that to be customized to what I planned to do in the session. The `role` script is a launcher which is given a role name like 'sysadmin', or 'workbench' and launches a Claude Code or other harness session with my preferred setup. It also sents an environment variable which influences where window files are stored so that are grouped by role.

---

## Tool surface

The service exposes 50 MCP tools. [`docs/mcp-tools.md`](docs/mcp-tools.md) is the per-tool reference; [`docs/non-mcp-facilities.md`](docs/non-mcp-facilities.md) covers everything callable that is not in the MCP manifest --- the review and continuity CLIs, local stdio MCP adapters for Codex and Gemini, the web surfaces, maintenance scripts, and background tasks. Both documents were written by GPT-5.5 from the source and then verified claim-by-claim by Claude, including a set-diff of the documented tools against the live manifest.

---

## Architecture

```
Chat claude.ai ──┐
Codex ───────────┼──► claude-hub (MCP gateway) ──┬── Main Claude Code (persistent)
Gemini ──────────┘    :8420                      │
                     ├── work-graph service ───── 127.0.0.1:8421
                     ├── PostgreSQL (claude_hub) ─ 127.0.0.1:5432
                     ├── GitHub API
                     └── /storage/ (file I/O)
```

**API Gateway + BFF.** Claude-hub terminates auth at the public boundary and forwards to internal subservices over localhost HTTP. Internal services bind to `127.0.0.1` only; the gateway is the only public door. The database is a schema-isolated shared Postgres (`claude_hub`). The work-graph service at `127.0.0.1:8421` is the canonical reference internal subservice: it owns its own schema and is reached through a thin forwarder in `server.py`.

The MCP surface is exposed via Streamable HTTP (`/mcp`) and SSE (`/mcp-sse`), with Bearer-token auth when `CLAUDE_HUB_JWT_SECRET` is set.

---

## Status

This is a production-deployed personal system (see `deploy.yaml` and `scripts/services/`). The Python source is roughly 18k lines, and the test suite collects 679 tests. The project is spec-driven; the review engine described above gates its own development, invoked as a CLI rather than an automated CI gate.

Known rough edges are tracked in [`ISSUES.md`](ISSUES.md); the continuity/window system additionally keeps a detailed running log in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

---

## Where things live

| Area | Entry points |
|---|---|
| MCP gateway + tool routes | `src/claude_hub/server.py` |
| MCP tool reference | `docs/mcp-tools.md` |
| Non-MCP facilities reference | `docs/non-mcp-facilities.md` |
| Known issues | `ISSUES.md`, `KNOWN_ISSUES.md` |
| Persistent Claude backend | `src/claude_hub/session.py`, `chat_process.py`, `routing.py` |
| Work graph integration | `src/claude_hub/work_graph_models.py`, forwarders in `server.py`; service runs separately at `127.0.0.1:8421` |
| Multi-model review | `src/claude_hub/review_engine.py`, `review_cli.py`, `review_models.py`, `config/review_models.yaml` |
| Artifact store | `src/claude_hub/artifact_store.py`, `artifact_models.py`, `tests/test_artifact_store.py` |
| Continuity | `src/claude_hub/continuity.py`, `continuity_cli.py`, `continuity_ingest.py`, `KNOWN_ISSUES.md` |
| Group chat | `src/claude_hub/conversation.py`, `conversation_store.py`, `message_router.py`, `codex_chat.py`, `gemini_chat.py` |
| Delegation / scheduling | `src/claude_hub/workspace.py`, `handoff.py`, `scheduler.py` |
| Auth | `src/claude_hub/auth.py`, `oauth_store.py`, `pkce.py`, `totp.py` |
| Connectors | `src/claude_hub/connectors/` |
| Files / GitHub / notifications | `src/claude_hub/storage.py`, `github_tools.py`, `notifications.py` |
| Database migrations | `migrations/` |
| Deployment references | `deploy.yaml`, `scripts/services/` |
| Design docs | `docs/` |

## Running locally

```bash
cd claude-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# PostgreSQL is required to run the server (not to run the tests).
# The server connects at startup and will not start without a reachable
# database; it applies migrations/*.sql itself on first start.
# Requires the pgvector extension to be installed.
createdb claude_hub
export CLAUDE_HUB_PG_DSN="postgresql:///claude_hub"
export CLAUDE_HUB_PROJECT_DIR="$PWD"   # where migrations/ and runtime state live

# Start the server on localhost
uvicorn claude_hub.server:app --host 127.0.0.1 --port 8420

# Run tests (no Postgres needed)
pytest tests/ -v
```
