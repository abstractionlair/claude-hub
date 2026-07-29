"""OAuth 2.1 authentication for claude-hub.

Uses Authorization Code flow with PKCE as the sole authentication method.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel


# Configuration from environment
JWT_SECRET = os.environ.get("CLAUDE_HUB_JWT_SECRET", "")
TOKEN_EXPIRE_HOURS = int(os.environ.get("CLAUDE_HUB_TOKEN_EXPIRE_HOURS", "24"))

# Algorithm for JWT
ALGORITHM = "HS256"

# Token type
TOKEN_TYPE_AUTHORIZATION_CODE = "authorization_code"

# Token scopes.
#
# "mcp" is the full-privilege scope: every token the OAuth flow has ever issued
# carries it, and it admits the MCP endpoint and all the tool routes. "chat" is
# minted only by /chat/token, for browser WebSocket handshakes, and must not
# reach anything else — that separation is the whole point of having scopes,
# since /chat/token is reachable with nothing but proxy auth while the OAuth
# flow requires the owner's TOTP.
SCOPE_MCP = "mcp"
SCOPE_CHAT = "chat"

# Security scheme
security = HTTPBearer(auto_error=False)


class TokenResponse(BaseModel):
    """OAuth token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def is_oauth21_enabled() -> bool:
    """Check if OAuth 2.1 is enabled (requires JWT_SECRET)."""
    return bool(JWT_SECRET)


def create_access_token(
    client_id: str,
    grant_type: str = TOKEN_TYPE_AUTHORIZATION_CODE,
    scope: str = "mcp",
    expires_seconds: Optional[int] = None,
) -> tuple[str, int]:
    """
    Create a JWT access token.

    Args:
        client_id: The client identifier
        grant_type: The OAuth grant type used (for audit)
        scope: The granted scope
        expires_seconds: Lifetime in seconds; defaults to TOKEN_EXPIRE_HOURS.
            Callers that hand a token to a browser want a much shorter one.

    Returns:
        Tuple of (token, expires_in_seconds)
    """
    if expires_seconds is None:
        expires_delta = timedelta(hours=TOKEN_EXPIRE_HOURS)
    else:
        expires_delta = timedelta(seconds=expires_seconds)
    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "sub": client_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access_token",
        "grant_type": grant_type,
        "scope": scope,
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    expires_in = int(expires_delta.total_seconds())

    return token, expires_in


def verify_token(
    token: str,
    allowed_scopes: tuple[str, ...] = (SCOPE_MCP,),
) -> Optional[str]:
    """
    Verify a JWT token and check that its scope may use the calling endpoint.

    Args:
        token: The JWT token to verify
        allowed_scopes: Scopes permitted here. Defaults to the full-privilege
            "mcp" scope so that a call site which has not thought about scope
            gets the restrictive answer rather than the permissive one; only
            endpoints that deliberately admit a lesser scope pass this.

    Returns:
        client_id if the token is valid and carries one of allowed_scopes,
        None otherwise
    """
    if not JWT_SECRET:
        return None

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None

    client_id: str = payload.get("sub")
    if client_id is None:
        return None

    # RFC 6749 §3.3: scope is a space-delimited list, so a token granted a
    # superset ("mcp offline_access") still satisfies an "mcp" requirement.
    # A token carrying no scope at all satisfies nothing.
    granted = set((payload.get("scope") or "").split())
    if not granted.intersection(allowed_scopes):
        return None

    return client_id


async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """
    FastAPI dependency for authentication.

    Requires a valid OAuth 2.1 Bearer token carrying the full-privilege "mcp"
    scope. A browser handshake token from /chat/token is deliberately not
    enough: it opens the chat WebSockets and nothing else.

    Returns:
        client_id if authenticated, None otherwise
    Raises:
        HTTPException if token is invalid or missing when OAuth is enabled
    """
    if not is_oauth21_enabled():
        # OAuth not configured - allow all (development mode)
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required. OAuth token expired or missing — reauthorize Claude Hub "
                "(claude.ai: Settings → Connectors), then retry."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_id = verify_token(credentials.credentials, allowed_scopes=(SCOPE_MCP,))
    if client_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid or expired token. OAuth token expired or missing — reauthorize Claude Hub "
                "(claude.ai: Settings → Connectors), then retry."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return client_id


def require_auth(client: Optional[str]) -> None:
    """
    Verify that authentication was successful.

    Args:
        client: Client ID from get_current_client dependency

    Raises:
        HTTPException if not authenticated and OAuth is enabled
    """
    if is_oauth21_enabled() and client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required. OAuth token expired or missing — reauthorize Claude Hub "
                "(claude.ai: Settings → Connectors), then retry."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )


def generate_credentials() -> dict:
    """Generate new credentials. For setup use."""
    return {
        "jwt_secret": secrets.token_urlsafe(32),
    }
