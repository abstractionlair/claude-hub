"""Notification system for claude-hub."""

import psycopg2
import psycopg2.extras
import json
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Notification:
    """A notification."""
    id: int
    timestamp: datetime
    priority: str  # "info" | "important" | "urgent"
    message: str
    project: Optional[str]
    details: dict
    read: bool


class NotificationManager:
    """Manages notifications with PostgreSQL backend."""

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
                    CREATE TABLE IF NOT EXISTS notifications (
                        id BIGSERIAL PRIMARY KEY,
                        timestamp TIMESTAMPTZ NOT NULL,
                        priority TEXT NOT NULL,
                        message TEXT NOT NULL,
                        project TEXT,
                        details_json JSONB,
                        read BOOLEAN DEFAULT FALSE
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notifications_timestamp ON notifications(timestamp DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read)
                """)
            conn.commit()

    def notify(
        self,
        message: str,
        priority: str = "info",
        project: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> int:
        """
        Create a notification.

        Args:
            message: Notification message
            priority: "info", "important", or "urgent"
            project: Optional project name
            details: Optional additional details as dict

        Returns:
            notification ID
        """
        if priority not in ["info", "important", "urgent"]:
            priority = "info"

        details_json = json.dumps(details) if details else None

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO notifications
                       (timestamp, priority, message, project, details_json, read)
                       VALUES (%s, %s, %s, %s, %s, FALSE)
                       RETURNING id""",
                    (
                        datetime.now(timezone.utc),
                        priority,
                        message,
                        project,
                        details_json,
                    )
                )
                row_id = cur.fetchone()[0]
            conn.commit()
            return row_id

    def list_notifications(
        self,
        unread_only: bool = False,
        limit: int = 100,
        project: Optional[str] = None,
    ) -> List[Notification]:
        """
        List notifications.

        Args:
            unread_only: Only return unread notifications
            limit: Maximum number to return
            project: Filter by project

        Returns:
            List of Notification objects
        """
        query = "SELECT id, timestamp, priority, message, project, details_json, read FROM notifications WHERE TRUE"
        params: list = []

        if unread_only:
            query += " AND read = FALSE"

        if project:
            query += " AND project = %s"
            params.append(project)

        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                notifications = []

                for row in cur.fetchall():
                    details_raw = row[5]
                    if isinstance(details_raw, str):
                        details = json.loads(details_raw)
                    elif isinstance(details_raw, dict):
                        details = details_raw
                    else:
                        details = {}

                    notifications.append(Notification(
                        id=row[0],
                        timestamp=row[1],
                        priority=row[2],
                        message=row[3],
                        project=row[4],
                        details=details,
                        read=row[6],
                    ))

                return notifications

    def mark_read(self, notification_id: int) -> bool:
        """
        Mark notification as read.

        Returns:
            True if notification was found and marked, False otherwise
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE notifications SET read = TRUE WHERE id = %s",
                    (notification_id,)
                )
            conn.commit()
            return cur.rowcount > 0

    def mark_all_read(self, project: Optional[str] = None) -> int:
        """
        Mark all notifications as read.

        Args:
            project: Optional filter by project

        Returns:
            Number of notifications marked as read
        """
        if project:
            query = "UPDATE notifications SET read = TRUE WHERE read = FALSE AND project = %s"
            params = (project,)
        else:
            query = "UPDATE notifications SET read = TRUE WHERE read = FALSE"
            params = ()

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
            return cur.rowcount

    def count_unread(self, project: Optional[str] = None) -> int:
        """Count unread notifications."""
        if project:
            query = "SELECT COUNT(*) FROM notifications WHERE read = FALSE AND project = %s"
            params = (project,)
        else:
            query = "SELECT COUNT(*) FROM notifications WHERE read = FALSE"
            params = ()

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()[0]


def generate_notification_token() -> str:
    """Generate a secure random token for notification access."""
    return secrets.token_urlsafe(32)


def load_or_generate_token(token_file: Path) -> str:
    """
    Load notification token from file, or generate and save if doesn't exist.

    Args:
        token_file: Path to token file

    Returns:
        Notification token
    """
    if token_file.exists():
        return token_file.read_text().strip()

    # Generate new token
    token = generate_notification_token()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token)
    token_file.chmod(0o600)  # Readable only by owner

    return token
