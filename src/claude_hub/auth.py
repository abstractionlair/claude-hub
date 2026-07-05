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
) -> tuple[str, int]:
    """
    Create a JWT access token.

    Args:
        client_id: The client identifier
        grant_type: The OAuth grant type used (for audit)
        scope: The granted scope

    Returns:
        Tuple of (token, expires_in_seconds)
    """
    expires_delta = timedelta(hours=TOKEN_EXPIRE_HOURS)
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


def verify_token(token: str) -> Optional[str]:
    """
    Verify a JWT token.

    Args:
        token: The JWT token to verify

    Returns:
        client_id if valid, None otherwise
    """
    if not JWT_SECRET:
        return None

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        client_id: str = payload.get("sub")
        if client_id is None:
            return None
        return client_id
    except JWTError:
        return None


async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """
    FastAPI dependency for authentication.

    Requires a valid OAuth 2.1 Bearer token.

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

    client_id = verify_token(credentials.credentials)
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
