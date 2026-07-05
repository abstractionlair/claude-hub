#!/usr/bin/env python3
"""Generate OAuth credentials for claude-hub."""

import secrets


def generate_credentials() -> dict:
    """Generate new client credentials."""
    return {
        "client_id": secrets.token_urlsafe(24),
        "client_secret": secrets.token_urlsafe(32),
        "jwt_secret": secrets.token_urlsafe(32),
    }


def main():
    creds = generate_credentials()

    print("=" * 60)
    print("Claude-Hub OAuth Credentials")
    print("=" * 60)
    print()
    print("Add these to your environment (e.g., systemd service file):")
    print()
    print(f"CLAUDE_HUB_CLIENT_ID={creds['client_id']}")
    print(f"CLAUDE_HUB_CLIENT_SECRET={creds['client_secret']}")
    print(f"CLAUDE_HUB_JWT_SECRET={creds['jwt_secret']}")
    print()
    print("-" * 60)
    print("For the claude.ai custom connector, use:")
    print()
    print(f"  Client ID:     {creds['client_id']}")
    print(f"  Client Secret: {creds['client_secret']}")
    print("-" * 60)
    print()
    print("IMPORTANT: Keep these secret! Anyone with these credentials")
    print("can access your claude-hub instance.")
    print()


if __name__ == "__main__":
    main()
