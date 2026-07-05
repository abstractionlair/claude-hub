"""TOTP storage for terminal access sessions."""

import psycopg2
import psycopg2.extras
import secrets
from contextlib import contextmanager
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


@dataclass
class TOTPSecret:
    """A user's TOTP secret for terminal access."""
    user_id: str
    secret: str
    created_at: datetime
    enabled: bool


@dataclass
class TOTPSession:
    """An active terminal session."""
    session_id: str
    user_id: str
    created_at: datetime
    expires_at: datetime


class TOTPStore:
    """
    PostgreSQL-backed storage for TOTP secrets and terminal sessions.
    """

    SESSION_TTL_HOURS = 8  # Terminal sessions last 8 hours

    def __init__(self, dsn: str):
        """
        Initialize TOTP store.

        Args:
            dsn: PostgreSQL connection DSN
        """
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
                    CREATE TABLE IF NOT EXISTS totp_secrets (
                        user_id TEXT PRIMARY KEY,
                        secret TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS totp_sessions (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_totp_sessions_expires
                    ON totp_sessions(expires_at)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_totp_sessions_user
                    ON totp_sessions(user_id)
                """)
            conn.commit()

    # -------------------------------------------------------------------------
    # Secret Management
    # -------------------------------------------------------------------------

    def save_secret(self, user_id: str, secret: str) -> TOTPSecret:
        """
        Save a TOTP secret for a user.

        Args:
            user_id: User identifier
            secret: The TOTP secret (base32 encoded)

        Returns:
            TOTPSecret object
        """
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO totp_secrets
                       (user_id, secret, created_at, enabled)
                       VALUES (%s, %s, %s, TRUE)
                       ON CONFLICT (user_id) DO UPDATE
                       SET secret = EXCLUDED.secret,
                           created_at = EXCLUDED.created_at,
                           enabled = TRUE""",
                    (user_id, secret, now)
                )
            conn.commit()

        return TOTPSecret(
            user_id=user_id,
            secret=secret,
            created_at=now,
            enabled=True,
        )

    def get_secret(self, user_id: str) -> Optional[TOTPSecret]:
        """
        Get a user's TOTP secret.

        Args:
            user_id: User identifier

        Returns:
            TOTPSecret if found, None otherwise
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, secret, created_at, enabled FROM totp_secrets WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        user_id, secret, created_at, enabled = row
        return TOTPSecret(
            user_id=user_id,
            secret=secret,
            created_at=created_at,
            enabled=enabled,
        )

    def delete_secret(self, user_id: str) -> bool:
        """
        Delete a user's TOTP secret.

        Args:
            user_id: User identifier

        Returns:
            True if deleted, False if not found
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM totp_secrets WHERE user_id = %s",
                    (user_id,)
                )
            conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def create_session(self, user_id: str) -> TOTPSession:
        """
        Create a new terminal session.

        Args:
            user_id: User identifier

        Returns:
            TOTPSession object
        """
        session_id = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self.SESSION_TTL_HOURS)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO totp_sessions
                       (session_id, user_id, created_at, expires_at)
                       VALUES (%s, %s, %s, %s)""",
                    (session_id, user_id, now, expires_at)
                )
            conn.commit()

        return TOTPSession(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
        )

    def verify_session(self, session_id: str) -> Optional[TOTPSession]:
        """
        Verify a session is valid and not expired.

        Args:
            session_id: Session identifier

        Returns:
            TOTPSession if valid, None otherwise
        """
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT session_id, user_id, created_at, expires_at
                       FROM totp_sessions
                       WHERE session_id = %s AND expires_at > %s""",
                    (session_id, now)
                )
                row = cur.fetchone()

        if not row:
            return None

        session_id, user_id, created_at, expires_at = row
        return TOTPSession(
            session_id=session_id,
            user_id=user_id,
            created_at=created_at,
            expires_at=expires_at,
        )

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session (logout).

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM totp_sessions WHERE session_id = %s",
                    (session_id,)
                )
            conn.commit()
            return cur.rowcount > 0

    def cleanup_expired(self) -> int:
        """
        Remove expired sessions.

        Returns:
            Number of sessions removed
        """
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM totp_sessions WHERE expires_at < %s",
                    (now,)
                )
            conn.commit()
            return cur.rowcount
