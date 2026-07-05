"""OAuth 2.1 storage for registered clients and authorization codes."""

import psycopg2
import psycopg2.extras
import json
import uuid
import secrets
import hashlib
import hmac
from contextlib import contextmanager
from typing import Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


@dataclass
class OAuthClient:
    """A registered OAuth client."""
    client_id: str
    client_secret: str  # Hashed secret for confidential clients
    redirect_uris: List[str]
    client_name: Optional[str]
    grant_types: List[str]
    created_at: datetime


@dataclass
class AuthorizationCode:
    """An authorization code for the code grant flow."""
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    scope: str
    state: Optional[str]
    expires_at: datetime
    used: bool


class OAuthStore:
    """
    PostgreSQL-backed storage for OAuth 2.1 data.

    Stores registered clients and authorization codes.
    """

    AUTH_CODE_TTL_MINUTES = 10  # OAuth 2.1 recommends short-lived codes

    def __init__(self, dsn: str):
        """
        Initialize OAuth store.

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
                    CREATE TABLE IF NOT EXISTS oauth_clients (
                        client_id TEXT PRIMARY KEY,
                        client_secret_hash TEXT NOT NULL,
                        redirect_uris JSONB NOT NULL,
                        client_name TEXT,
                        grant_types JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS authorization_codes (
                        code TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL REFERENCES oauth_clients(client_id),
                        redirect_uri TEXT NOT NULL,
                        code_challenge TEXT NOT NULL,
                        code_challenge_method TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        state TEXT,
                        expires_at TIMESTAMPTZ NOT NULL,
                        used BOOLEAN NOT NULL DEFAULT FALSE
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_auth_codes_client
                    ON authorization_codes(client_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_auth_codes_expires
                    ON authorization_codes(expires_at)
                """)
            conn.commit()

    # -------------------------------------------------------------------------
    # Client Management
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_secret(secret: str) -> str:
        """Hash a client secret using SHA256."""
        return hashlib.sha256(secret.encode()).hexdigest()

    def register_client(
        self,
        redirect_uris: List[str],
        client_name: Optional[str] = None,
        grant_types: Optional[List[str]] = None,
    ) -> Tuple[OAuthClient, str]:
        """
        Register a new OAuth client (RFC 7591 Dynamic Client Registration).

        Args:
            redirect_uris: List of allowed redirect URIs
            client_name: Human-readable name for the client
            grant_types: Allowed grant types (defaults to authorization_code)

        Returns:
            Tuple of (OAuthClient, plaintext_client_secret)
            The plaintext secret is only returned once at registration.
        """
        client_id = str(uuid.uuid4())
        client_secret = secrets.token_urlsafe(32)  # 256-bit secret
        client_secret_hash = self._hash_secret(client_secret)

        if grant_types is None:
            grant_types = ["authorization_code"]

        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO oauth_clients
                       (client_id, client_secret_hash, redirect_uris, client_name, grant_types, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        client_id,
                        client_secret_hash,
                        json.dumps(redirect_uris),
                        client_name,
                        json.dumps(grant_types),
                        now,
                    )
                )
            conn.commit()

        client = OAuthClient(
            client_id=client_id,
            client_secret=client_secret_hash,  # Store hash in object
            redirect_uris=redirect_uris,
            client_name=client_name,
            grant_types=grant_types,
            created_at=now,
        )

        return client, client_secret  # Return plaintext secret only at registration

    def get_client(self, client_id: str) -> Optional[OAuthClient]:
        """
        Get a registered client by ID.

        Args:
            client_id: The client ID to look up

        Returns:
            OAuthClient if found, None otherwise
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT client_id, client_secret_hash, redirect_uris, client_name, grant_types, created_at "
                    "FROM oauth_clients WHERE client_id = %s",
                    (client_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        client_id, client_secret_hash, redirect_uris_raw, client_name, grant_types_raw, created_at = row
        # psycopg2 auto-deserializes JSONB to Python objects
        redirect_uris = redirect_uris_raw if isinstance(redirect_uris_raw, list) else json.loads(redirect_uris_raw)
        grant_types = grant_types_raw if isinstance(grant_types_raw, list) else json.loads(grant_types_raw)
        return OAuthClient(
            client_id=client_id,
            client_secret=client_secret_hash,
            redirect_uris=redirect_uris,
            client_name=client_name,
            grant_types=grant_types,
            created_at=created_at,
        )

    def verify_client_secret(self, client_id: str, client_secret: str) -> bool:
        """
        Verify a client's secret.

        Args:
            client_id: The client ID
            client_secret: The plaintext secret to verify

        Returns:
            True if the secret is valid for this client
        """
        client = self.get_client(client_id)
        if not client:
            return False

        provided_hash = self._hash_secret(client_secret)
        return hmac.compare_digest(provided_hash, client.client_secret)

    def validate_redirect_uri(self, client_id: str, redirect_uri: str) -> bool:
        """
        Validate that a redirect URI is registered for a client.

        OAuth 2.1 requires exact match (no wildcards).

        Args:
            client_id: The client ID
            redirect_uri: The redirect URI to validate

        Returns:
            True if the redirect URI is registered for this client
        """
        client = self.get_client(client_id)
        if not client:
            return False
        return redirect_uri in client.redirect_uris

    # -------------------------------------------------------------------------
    # Authorization Code Management
    # -------------------------------------------------------------------------

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: str = "mcp",
        state: Optional[str] = None,
    ) -> str:
        """
        Create a new authorization code.

        Args:
            client_id: The client requesting authorization
            redirect_uri: Where to redirect after authorization
            code_challenge: PKCE code challenge
            code_challenge_method: Challenge method (S256 required for OAuth 2.1)
            scope: Requested scope
            state: Optional state for CSRF protection

        Returns:
            The generated authorization code
        """
        code = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.AUTH_CODE_TTL_MINUTES)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO authorization_codes
                       (code, client_id, redirect_uri, code_challenge, code_challenge_method,
                        scope, state, expires_at, used)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)""",
                    (
                        code,
                        client_id,
                        redirect_uri,
                        code_challenge,
                        code_challenge_method,
                        scope,
                        state,
                        expires_at,
                    )
                )
            conn.commit()

        return code

    def get_authorization_code(self, code: str) -> Optional[AuthorizationCode]:
        """
        Get an authorization code.

        Args:
            code: The authorization code

        Returns:
            AuthorizationCode if found and valid, None otherwise
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT code, client_id, redirect_uri, code_challenge,
                              code_challenge_method, scope, state, expires_at, used
                       FROM authorization_codes WHERE code = %s""",
                    (code,)
                )
                row = cur.fetchone()

        if not row:
            return None

        (code, client_id, redirect_uri, code_challenge, code_challenge_method,
         scope, state, expires_at, used) = row

        return AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            state=state,
            expires_at=expires_at,
            used=used,
        )

    def use_authorization_code(self, code: str) -> Optional[AuthorizationCode]:
        """
        Consume an authorization code (mark as used).

        This is atomic: if the code is already used or expired, returns None.
        OAuth 2.1 requires codes to be single-use.

        Args:
            code: The authorization code to consume

        Returns:
            AuthorizationCode if successfully consumed, None if invalid/expired/used
        """
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                # Atomically check and mark as used
                cur.execute(
                    """UPDATE authorization_codes
                       SET used = TRUE
                       WHERE code = %s AND used = FALSE AND expires_at > %s
                       RETURNING code, client_id, redirect_uri, code_challenge,
                                 code_challenge_method, scope, state, expires_at, used""",
                    (code, now)
                )
                row = cur.fetchone()
            conn.commit()

        if not row:
            return None

        (code, client_id, redirect_uri, code_challenge, code_challenge_method,
         scope, state, expires_at, used) = row

        return AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            state=state,
            expires_at=expires_at,
            used=True,
        )

    def cleanup_expired_codes(self) -> int:
        """
        Remove expired authorization codes.

        Returns:
            Number of codes removed
        """
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM authorization_codes WHERE expires_at < %s",
                    (now,)
                )
            conn.commit()
            return cur.rowcount
