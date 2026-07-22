"""Environment scrubbing for model-CLI subprocesses.

The service launches model CLIs (Claude Code, codex, gemini) with
``--dangerously-skip-permissions``, so the operating-system user is the only thing
containing what such a subprocess can do. Those subprocesses authenticate to their
model providers via credentials under ``$HOME`` and call back into the service with
a filesystem bearer token; they never need the service's own secrets. Strip those
secrets from the child environment so a compromised or prompt-injected model
process cannot read them out of ``os.environ``.

``CLAUDE_HUB_PG_DSN`` is deliberately *not* stripped yet: the continuity hooks these
sessions run persist state to Postgres via ``psql`` using the DSN directly, and they
skip cleanly when it is unset — so removing it would silently disable continuity
rather than fail loudly. Move that persistence onto the authenticated API surface
first, then add the DSN here.
"""
from __future__ import annotations

import os

# Service secrets that no model subprocess — nor its MCP shims or continuity hooks —
# reads. Verified against every launch surface and hook script.
MODEL_SUBPROCESS_SECRETS = frozenset(
    {
        "CLAUDE_HUB_JWT_SECRET",     # signs MCP access tokens; a leak enables token forgery
        "GITHUB_PAT",                # repository write access
        "GITHUB_WEBHOOK_SECRET",     # webhook signature verification
        "GEMINI_API_KEY",            # also forces pay-per-use billing over subscription auth
        "GEMINI_EMBEDDING_API_KEY",  # embedding API key
    }
)


def scrub_model_subprocess_secrets(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``env`` (default ``os.environ``) with service secrets removed.

    Build the ``env=`` for any model-CLI subprocess from this so the child cannot read
    the service's secrets from its process environment.
    """
    source = os.environ if env is None else env
    return {k: v for k, v in source.items() if k not in MODEL_SUBPROCESS_SECRETS}
