"""PostgreSQL persistence for group conversation messages and lifecycle state."""

import json
import logging
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ConversationStatus:
    """Conversation lifecycle statuses."""
    ACTIVE = "active"
    ENDED = "ended"
    INTERRUPTED = "interrupted"


class ConversationStore:
    """PostgreSQL persistence for group conversation messages and lifecycle state."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._ensure_schema()

    @contextmanager
    def _get_conn(self):
        conn = psycopg2.connect(self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        """Ensure database schema exists."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sender_name TEXT NOT NULL,
                        content TEXT NOT NULL,
                        message_type TEXT DEFAULT 'chat',
                        recipient_id TEXT,
                        timestamp TIMESTAMPTZ NOT NULL,
                        metadata JSONB
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_conv
                    ON messages(conversation_id, timestamp)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id TEXT PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        ended_at TIMESTAMPTZ,
                        participant_summary JSONB
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_lifecycle (
                        conversation_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'active',
                        participants JSONB,
                        created_at TIMESTAMPTZ NOT NULL,
                        ended_at TIMESTAMPTZ,
                        last_activity_at TIMESTAMPTZ NOT NULL,
                        shutdown_reason TEXT
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_lifecycle_status
                    ON conversation_lifecycle(status)
                """)
            conn.commit()

    # -----------------------------------------------------------------
    # Message persistence
    # -----------------------------------------------------------------

    def log_message(self, msg) -> None:
        """Persist a GroupMessage to the database."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO messages
                       (id, conversation_id, sender_id, sender_name, content,
                        message_type, recipient_id, timestamp, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (
                        msg.id,
                        msg.conversation_id,
                        msg.sender_id,
                        msg.sender_name,
                        msg.content,
                        msg.message_type.value,
                        msg.recipient_id,
                        msg.timestamp,
                        json.dumps(msg.metadata) if msg.metadata else None,
                    ),
                )
                # Update last_activity_at for the conversation lifecycle record
                cur.execute(
                    """UPDATE conversation_lifecycle
                       SET last_activity_at = %s
                       WHERE conversation_id = %s""",
                    (datetime.now(timezone.utc), msg.conversation_id),
                )
            conn.commit()

    # -----------------------------------------------------------------
    # Legacy conversation tracking
    # -----------------------------------------------------------------

    def log_conversation_start(self, conversation_id: str, participants: list[dict]) -> None:
        """Record a conversation being created."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO conversations
                       (conversation_id, created_at, participant_summary)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (conversation_id) DO NOTHING""",
                    (
                        conversation_id,
                        datetime.now(timezone.utc),
                        json.dumps(participants),
                    ),
                )
            conn.commit()

    def log_conversation_end(self, conversation_id: str) -> None:
        """Mark a conversation as ended."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE conversations SET ended_at = %s WHERE conversation_id = %s""",
                    (datetime.now(timezone.utc), conversation_id),
                )
            conn.commit()

    def get_messages(self, conversation_id: str, limit: Optional[int] = None) -> list[dict]:
        """Retrieve messages for a conversation, ordered by timestamp."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """SELECT id, conversation_id, sender_id, sender_name, content,
                                  message_type, recipient_id, timestamp, metadata
                           FROM messages WHERE conversation_id = %s ORDER BY timestamp"""
                params: list = [conversation_id]
                if limit:
                    query += " LIMIT %s"
                    params.append(limit)
                cur.execute(query, params)
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    # Ensure timestamp is string for JSON serialization
                    if isinstance(d.get("timestamp"), datetime):
                        d["timestamp"] = d["timestamp"].isoformat()
                    if d.get("metadata") is None:
                        d["metadata"] = {}
                    result.append(d)
                return result

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """List recent conversations."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT conversation_id, created_at, ended_at, participant_summary
                       FROM conversations ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    if isinstance(d.get("created_at"), datetime):
                        d["created_at"] = d["created_at"].isoformat()
                    if isinstance(d.get("ended_at"), datetime):
                        d["ended_at"] = d["ended_at"].isoformat()
                    ps = d.get("participant_summary")
                    if ps is None:
                        d["participant_summary"] = []
                    elif isinstance(ps, str):
                        d["participant_summary"] = json.loads(ps)
                    result.append(d)
                return result

    # -----------------------------------------------------------------
    # Conversation lifecycle state
    # -----------------------------------------------------------------

    def track_conversation_active(
        self,
        conversation_id: str,
        participants: Optional[list[dict]] = None,
    ) -> None:
        """Record a conversation as active. Idempotent (INSERT ... ON CONFLICT UPDATE)."""
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO conversation_lifecycle
                       (conversation_id, status, participants, created_at, last_activity_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (conversation_id) DO UPDATE
                       SET status = EXCLUDED.status,
                           participants = EXCLUDED.participants,
                           last_activity_at = EXCLUDED.last_activity_at""",
                    (
                        conversation_id,
                        ConversationStatus.ACTIVE,
                        json.dumps(participants) if participants else None,
                        now,
                        now,
                    ),
                )
            conn.commit()

    def update_participants(
        self,
        conversation_id: str,
        participants: list[dict],
    ) -> None:
        """Update the participant list for an active conversation."""
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE conversation_lifecycle
                       SET participants = %s, last_activity_at = %s
                       WHERE conversation_id = %s""",
                    (json.dumps(participants), now, conversation_id),
                )
            conn.commit()

    def mark_conversation_ended(self, conversation_id: str) -> None:
        """Mark a conversation as cleanly ended."""
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE conversation_lifecycle
                       SET status = %s, ended_at = %s, last_activity_at = %s
                       WHERE conversation_id = %s""",
                    (ConversationStatus.ENDED, now, now, conversation_id),
                )
            conn.commit()

    def mark_conversation_interrupted(
        self,
        conversation_id: str,
        reason: str = "shutdown",
    ) -> None:
        """Mark a conversation as interrupted (graceful shutdown or crash recovery)."""
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE conversation_lifecycle
                       SET status = %s, ended_at = %s, last_activity_at = %s,
                           shutdown_reason = %s
                       WHERE conversation_id = %s""",
                    (ConversationStatus.INTERRUPTED, now, now, reason, conversation_id),
                )
            conn.commit()

    def mark_all_active_interrupted(self, reason: str = "shutdown") -> int:
        """Mark all active conversations as interrupted. Returns count affected."""
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE conversation_lifecycle
                       SET status = %s, ended_at = %s, last_activity_at = %s,
                           shutdown_reason = %s
                       WHERE status = %s""",
                    (
                        ConversationStatus.INTERRUPTED,
                        now,
                        now,
                        reason,
                        ConversationStatus.ACTIVE,
                    ),
                )
            conn.commit()
            return cur.rowcount

    def get_conversations_by_status(self, status: str) -> list[dict]:
        """Get all conversations with a given status."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT conversation_id, status, participants, created_at,
                              ended_at, last_activity_at, shutdown_reason
                       FROM conversation_lifecycle
                       WHERE status = %s
                       ORDER BY last_activity_at DESC""",
                    (status,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    for ts_field in ("created_at", "ended_at", "last_activity_at"):
                        if isinstance(d.get(ts_field), datetime):
                            d[ts_field] = d[ts_field].isoformat()
                    ps = d.get("participants")
                    if ps is None:
                        d["participants"] = []
                    elif isinstance(ps, str):
                        d["participants"] = json.loads(ps)
                    result.append(d)
                return result

    def get_lifecycle_status(self, conversation_id: str) -> Optional[dict]:
        """Get the lifecycle record for a conversation, or None if not tracked."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT conversation_id, status, participants, created_at,
                              ended_at, last_activity_at, shutdown_reason
                       FROM conversation_lifecycle
                       WHERE conversation_id = %s""",
                    (conversation_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = dict(row)
                for ts_field in ("created_at", "ended_at", "last_activity_at"):
                    if isinstance(d.get(ts_field), datetime):
                        d[ts_field] = d[ts_field].isoformat()
                ps = d.get("participants")
                if ps is None:
                    d["participants"] = []
                elif isinstance(ps, str):
                    d["participants"] = json.loads(ps)
                return d

    def recover_on_startup(self) -> dict:
        """Startup recovery: mark any lingering 'active' conversations as interrupted.

        This handles the crash case where the process died without graceful
        shutdown. Returns a summary dict of actions taken.
        """
        # Find conversations that were still "active" -- means we crashed
        stale_active = self.get_conversations_by_status(ConversationStatus.ACTIVE)
        crash_count = 0
        if stale_active:
            crash_count = self.mark_all_active_interrupted(reason="crash_recovery")
            for conv in stale_active:
                logger.warning(
                    "Startup recovery: conversation %s was active at crash time, "
                    "marked as interrupted",
                    conv["conversation_id"],
                )

        # Count interrupted conversations (from both graceful shutdown and crash)
        interrupted = self.get_conversations_by_status(ConversationStatus.INTERRUPTED)

        summary = {
            "crash_recovered": crash_count,
            "total_interrupted": len(interrupted),
            "interrupted_conversation_ids": [
                c["conversation_id"] for c in interrupted
            ],
        }

        if crash_count > 0:
            logger.info(
                "Startup recovery: %d conversations were active at crash time "
                "and have been marked interrupted",
                crash_count,
            )
        if interrupted:
            logger.info(
                "Startup recovery: %d total interrupted conversations on record",
                len(interrupted),
            )

        return summary
