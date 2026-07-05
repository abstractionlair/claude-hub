#!/usr/bin/env python3
"""One-time migration: copy data from SQLite databases to PostgreSQL."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

PG_DSN = os.environ["CLAUDE_HUB_PG_DSN"]
CLAUDE_DIR = Path.home() / "claude-hub" / ".claude"


def parse_timestamp(ts_str: str) -> str:
    """Parse various timestamp formats into ISO with timezone."""
    if not ts_str:
        return None
    # Unix timestamp (numeric string)
    try:
        val = float(ts_str)
        return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
    except ValueError:
        pass
    # Already has timezone info
    if ts_str.endswith("+00:00") or ts_str.endswith("Z"):
        return ts_str.replace("Z", "+00:00")
    # Naive ISO format - assume UTC
    return ts_str + "+00:00"


def migrate_notifications(pg_conn):
    """Migrate notifications table."""
    db_path = CLAUDE_DIR / "notifications.db"
    if not db_path.exists():
        print("  notifications.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    rows = sq.execute("SELECT id, timestamp, priority, message, project, details_json, read FROM notifications").fetchall()
    sq.close()

    if not rows:
        print("  No notification rows to migrate")
        return

    cur = pg_conn.cursor()
    # Use a sequence value based on max id to avoid conflicts
    for row in rows:
        sid, ts, priority, message, project, details_json, read_int = row
        ts_pg = parse_timestamp(ts)
        details = json.loads(details_json) if details_json else None
        cur.execute(
            """INSERT INTO notifications (id, timestamp, priority, message, project, details_json, read)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (sid, ts_pg, priority, message, project, json.dumps(details) if details else None, bool(read_int)),
        )
    # Reset sequence to max id + 1
    cur.execute("SELECT setval('notifications_id_seq', (SELECT COALESCE(MAX(id), 0) FROM notifications))")
    pg_conn.commit()
    print(f"  Migrated {len(rows)} notifications")


def migrate_oauth(pg_conn):
    """Migrate oauth_clients and authorization_codes."""
    db_path = CLAUDE_DIR / "oauth.db"
    if not db_path.exists():
        print("  oauth.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    cur = pg_conn.cursor()

    # oauth_clients
    clients = sq.execute(
        "SELECT client_id, client_secret_hash, redirect_uris, client_name, grant_types, created_at FROM oauth_clients"
    ).fetchall()
    for row in clients:
        client_id, secret_hash, redirect_uris, client_name, grant_types, created_at = row
        cur.execute(
            """INSERT INTO oauth_clients (client_id, client_secret_hash, redirect_uris, client_name, grant_types, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (client_id) DO NOTHING""",
            (client_id, secret_hash, redirect_uris, client_name, grant_types, parse_timestamp(created_at)),
        )
    print(f"  Migrated {len(clients)} oauth_clients")

    # authorization_codes
    codes = sq.execute(
        "SELECT code, client_id, redirect_uri, code_challenge, code_challenge_method, scope, state, expires_at, used FROM authorization_codes"
    ).fetchall()
    for row in codes:
        code, client_id, redirect_uri, code_challenge, code_challenge_method, scope, state, expires_at, used = row
        cur.execute(
            """INSERT INTO authorization_codes (code, client_id, redirect_uri, code_challenge, code_challenge_method, scope, state, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (code) DO NOTHING""",
            (code, client_id, redirect_uri, code_challenge, code_challenge_method, scope, state, parse_timestamp(expires_at), bool(used)),
        )
    print(f"  Migrated {len(codes)} authorization_codes")

    sq.close()
    pg_conn.commit()


def migrate_totp(pg_conn):
    """Migrate totp_secrets and totp_sessions."""
    db_path = CLAUDE_DIR / "oauth.db"
    if not db_path.exists():
        print("  oauth.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    cur = pg_conn.cursor()

    # totp_secrets
    secrets = sq.execute("SELECT user_id, secret, created_at, enabled FROM totp_secrets").fetchall()
    for row in secrets:
        user_id, secret, created_at, enabled = row
        cur.execute(
            """INSERT INTO totp_secrets (user_id, secret, created_at, enabled)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id) DO NOTHING""",
            (user_id, secret, parse_timestamp(created_at), bool(enabled)),
        )
    print(f"  Migrated {len(secrets)} totp_secrets")

    # totp_sessions
    sessions = sq.execute("SELECT session_id, user_id, created_at, expires_at FROM totp_sessions").fetchall()
    for row in sessions:
        session_id, user_id, created_at, expires_at = row
        cur.execute(
            """INSERT INTO totp_sessions (session_id, user_id, created_at, expires_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (session_id) DO NOTHING""",
            (session_id, user_id, parse_timestamp(created_at), parse_timestamp(expires_at)),
        )
    print(f"  Migrated {len(sessions)} totp_sessions")

    sq.close()
    pg_conn.commit()


def migrate_conversations(pg_conn):
    """Migrate messages, conversations, and conversation_lifecycle."""
    db_path = CLAUDE_DIR / "conversations.db"
    if not db_path.exists():
        print("  conversations.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    cur = pg_conn.cursor()

    # conversations
    convos = sq.execute("SELECT conversation_id, created_at, ended_at, participant_summary FROM conversations").fetchall()
    for row in convos:
        conversation_id, created_at, ended_at, participant_summary = row
        cur.execute(
            """INSERT INTO conversations (conversation_id, created_at, ended_at, participant_summary)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (conversation_id) DO NOTHING""",
            (conversation_id, parse_timestamp(created_at), parse_timestamp(ended_at) if ended_at else None, participant_summary),
        )
    print(f"  Migrated {len(convos)} conversations")

    # messages
    msgs = sq.execute(
        "SELECT id, conversation_id, sender_id, sender_name, content, message_type, recipient_id, timestamp, metadata FROM messages"
    ).fetchall()
    for row in msgs:
        mid, conv_id, sender_id, sender_name, content, msg_type, recipient_id, ts, metadata = row
        cur.execute(
            """INSERT INTO messages (id, conversation_id, sender_id, sender_name, content, message_type, recipient_id, timestamp, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (mid, conv_id, sender_id, sender_name, content, msg_type, recipient_id, parse_timestamp(ts), metadata),
        )
    print(f"  Migrated {len(msgs)} messages")

    # conversation_lifecycle
    lifecycles = sq.execute(
        "SELECT conversation_id, status, participants, created_at, ended_at, last_activity_at, shutdown_reason FROM conversation_lifecycle"
    ).fetchall()
    for row in lifecycles:
        conv_id, status, participants, created_at, ended_at, last_activity_at, shutdown_reason = row
        cur.execute(
            """INSERT INTO conversation_lifecycle (conversation_id, status, participants, created_at, ended_at, last_activity_at, shutdown_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (conversation_id) DO NOTHING""",
            (conv_id, status, participants, parse_timestamp(created_at),
             parse_timestamp(ended_at) if ended_at else None,
             parse_timestamp(last_activity_at), shutdown_reason),
        )
    print(f"  Migrated {len(lifecycles)} conversation_lifecycle records")

    sq.close()
    pg_conn.commit()


def migrate_scheduler(pg_conn):
    """Migrate schedules."""
    db_path = CLAUDE_DIR / "scheduler.db"
    if not db_path.exists():
        print("  scheduler.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    rows = sq.execute(
        "SELECT schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at FROM schedules"
    ).fetchall()
    sq.close()

    if not rows:
        print("  No schedule rows to migrate")
        return

    cur = pg_conn.cursor()
    for row in rows:
        schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at = row
        cur.execute(
            """INSERT INTO schedules (schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (schedule_id) DO NOTHING""",
            (schedule_id, session_id, parse_timestamp(next_wake), interval_seconds, prompt,
             constraints_json, parse_timestamp(end_time) if end_time else None, parse_timestamp(created_at)),
        )
    pg_conn.commit()
    print(f"  Migrated {len(rows)} schedules")


def migrate_observations(pg_conn):
    """Migrate observations."""
    db_path = CLAUDE_DIR / "observations.db"
    if not db_path.exists():
        print("  observations.db not found, skipping")
        return

    sq = sqlite3.connect(db_path)
    rows = sq.execute(
        "SELECT id, created_at, last_referenced, category, confidence, content, tags, source_session, confirmations, refutations FROM observations"
    ).fetchall()
    sq.close()

    if not rows:
        print("  No observation rows to migrate")
        return

    cur = pg_conn.cursor()
    for row in rows:
        oid, created_at, last_referenced, category, confidence, content, tags, source_session, confirmations, refutations = row
        cur.execute(
            """INSERT INTO observations (id, created_at, last_referenced, category, confidence, content, tags, source_session, confirmations, refutations)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (oid, parse_timestamp(created_at), parse_timestamp(last_referenced), category, confidence,
             content, tags, source_session, confirmations, refutations),
        )
    pg_conn.commit()
    print(f"  Migrated {len(rows)} observations")


def main():
    print("Connecting to PostgreSQL...")
    pg_conn = psycopg2.connect(PG_DSN)

    print("\n1. Migrating notifications...")
    migrate_notifications(pg_conn)

    print("\n2. Migrating OAuth clients and codes...")
    migrate_oauth(pg_conn)

    print("\n3. Migrating TOTP secrets and sessions...")
    migrate_totp(pg_conn)

    print("\n4. Migrating conversations...")
    migrate_conversations(pg_conn)

    print("\n5. Migrating scheduler...")
    migrate_scheduler(pg_conn)

    print("\n6. Migrating observations...")
    migrate_observations(pg_conn)

    pg_conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    main()
