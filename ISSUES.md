# Issues

Operational rough edges, tracked openly. The continuity/window system has its
own detailed running log in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md); the entries
here are repo-wide.

- **Continuity fork.** The session-ID remap after `claude --fork-session` can
  leave the `.current-<id>` pointer stale, so a fork may write to the wrong
  window or create a stray one. Every fork also reloads the full session
  context via `claude --resume --print`, which is heavy on long sessions. See
  [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for the full diagnosis.
- **Gemini integration (partial).** The review engine's Gemini seats run via
  Antigravity's `agy` CLI as of 2026-07-10 (display-name model IDs required;
  slug forms silently serve Flash). Group chat (`GeminiChat`) and the gemini
  stdio adapter still shell out to the standalone `gemini` CLI, which Google
  retired --- those fail to spawn until ported; Claude and GPT-5/Codex are
  unaffected.
- **MCP manifest over-exposure.** Tool registration uses an exclude-list, so
  two group-chat web routes (`add_codex_to_conversation`,
  `add_gemini_to_conversation`) currently leak into the MCP manifest.
  Diagnosed in [`docs/mcp-tools.md`](docs/mcp-tools.md); the fix (switching to
  an explicit allowlist) is queued behind per-tool usage telemetry so the
  decision is made on data.
- **Docs lag.** Some design docs still reference untracked `~/.claude` shell
  hooks and older ledger/append-log patterns that predate the artifact store
  and observation store.
- **Single-operator model.** Auth protects the public surface, but there is no
  multi-tenancy or per-user isolation.
