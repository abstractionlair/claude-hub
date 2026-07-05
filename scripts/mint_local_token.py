#!/usr/bin/env python3
"""Mint a long-lived bearer token for the local Claude Hub MCP server.

For headless local CLIs (codex, gemini, etc.) that consume claude-hub's
MCP surface and want a static bearer instead of running the OAuth
authorization-code flow. The minted token is an HS256 JWT signed with
CLAUDE_HUB_JWT_SECRET — the same mechanism the OAuth /token endpoint
uses, so the server can't tell them apart.

The token's `sub` claim is the client_id you choose; pick a distinct
name per CLI ("codex-local", "gemini-local") so audit logs are
readable.

Reads the secret from /etc/claude-hub/claude-hub.env (mode 640
root:claude, group-readable). Override with
CLAUDE_HUB_JWT_SECRET in the environment to skip the file read.

Usage:

    scripts/mint_local_token.py
    scripts/mint_local_token.py --client-id codex-local
    scripts/mint_local_token.py --client-id gemini-local --hours 8760 > ~/.gemini/claude-hub.token
    chmod 600 ~/.gemini/claude-hub.token

Output: the JWT alone on stdout, no trailing newline. Errors to stderr.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from jose import jwt
except ImportError:
    print(
        "error: python-jose is required. "
        "Activate claude-hub's venv: ~/projects/claude-hub/venv/bin/python "
        + sys.argv[0],
        file=sys.stderr,
    )
    sys.exit(2)


ENV_FILE = Path("/etc/claude-hub/claude-hub.env")
ALGORITHM = "HS256"


def load_jwt_secret() -> str:
    """Resolve JWT_SECRET. Env var wins; otherwise read the systemd env file."""
    if v := os.environ.get("CLAUDE_HUB_JWT_SECRET"):
        return v
    if not ENV_FILE.exists():
        sys.exit(
            f"error: {ENV_FILE} not found and CLAUDE_HUB_JWT_SECRET not set"
        )
    try:
        text = ENV_FILE.read_text()
    except PermissionError:
        sys.exit(
            f"error: {ENV_FILE} not readable; you must be in group "
            f"'claude' (current uid={os.getuid()}, gid={os.getgid()})"
        )
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CLAUDE_HUB_JWT_SECRET="):
            value = line.split("=", 1)[1].strip()
            # Strip optional surrounding quotes
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value
    sys.exit(f"error: CLAUDE_HUB_JWT_SECRET not in {ENV_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--client-id",
        default="local-cli",
        help="Identifier embedded in the token's `sub` claim (default: local-cli).",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=8760,  # 1 year
        help="Token lifetime in hours (default: 8760 = 1 year).",
    )
    parser.add_argument(
        "--scope",
        default="mcp",
        help="OAuth scope claim (default: mcp).",
    )
    args = parser.parse_args()

    secret = load_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": args.client_id,
        "iat": now,
        "exp": now + timedelta(hours=args.hours),
        "type": "access_token",
        "grant_type": "local_mint",
        "scope": args.scope,
    }
    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    sys.stdout.write(token)
    # No trailing newline; lets `echo "Bearer $(...)"` work cleanly.


if __name__ == "__main__":
    main()
