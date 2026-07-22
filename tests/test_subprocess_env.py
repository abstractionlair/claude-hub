"""Tests for model-subprocess environment scrubbing."""
import os

from claude_hub.subprocess_env import (
    MODEL_SUBPROCESS_SECRETS,
    scrub_model_subprocess_secrets,
)


def test_strips_every_declared_secret():
    env = {name: "sensitive" for name in MODEL_SUBPROCESS_SECRETS}
    env.update(
        {
            "HOME": "/home/claude",
            "PATH": "/usr/bin",
            "CURRENT_ROLE": "mcp-server",
            "CLAUDE_HUB_PG_DSN": "postgres://localhost/claude_hub",
        }
    )
    out = scrub_model_subprocess_secrets(env)
    for secret in MODEL_SUBPROCESS_SECRETS:
        assert secret not in out, f"{secret} should have been stripped"
    # Non-secret vars the model child needs are preserved.
    assert out["HOME"] == "/home/claude"
    assert out["PATH"] == "/usr/bin"
    assert out["CURRENT_ROLE"] == "mcp-server"


def test_pg_dsn_is_intentionally_retained():
    # The continuity hooks these sessions run persist to Postgres via psql using
    # the DSN directly; stripping it would silently disable continuity. It must
    # not be in the secret set until that persistence moves onto the API surface.
    assert "CLAUDE_HUB_PG_DSN" not in MODEL_SUBPROCESS_SECRETS
    env = {"CLAUDE_HUB_PG_DSN": "postgres://localhost/claude_hub"}
    assert scrub_model_subprocess_secrets(env)["CLAUDE_HUB_PG_DSN"]


def test_defaults_to_os_environ_without_mutating_it():
    out = scrub_model_subprocess_secrets()
    assert isinstance(out, dict)
    assert out is not os.environ
    assert all(secret not in out for secret in MODEL_SUBPROCESS_SECRETS)
