# Issues

Operational rough edges, tracked openly. The continuity/window system has its
own detailed running log in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md); the entries
here are repo-wide.

- **Continuity fork handoff.** Claude's session-ID remap after
  `claude --fork-session` does not expose enough stable origin metadata to link
  every fork automatically. The lifecycle now refuses to infer a parent from
  recency or project tags; callers can supply an explicit originating window.
  Narrator forks also reload the full session context via
  `claude --resume --print`, which is heavy on long sessions. See
  [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for the full diagnosis.
- **Gemini integration (partial).** The review engine's Gemini seats run via
  Antigravity's `agy` CLI as of 2026-07-10 (display-name model IDs required;
  slug forms silently serve Flash). Group chat (`GeminiChat`) and the gemini
  stdio adapter still shell out to the standalone `gemini` CLI, which Google
  retired --- those fail to spawn until ported; Claude and GPT-5/Codex are
  unaffected.
- **Docs lag.** Some historical design sections still show older
  ledger/append-log hook examples that predate the artifact store and the
  canonical hook source in a separate private infrastructure project.
- **Single-operator model.** Auth protects the public surface, but there is no
  multi-tenancy or per-user isolation.
