"""OAuth 2.1 Pydantic models for request/response validation."""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse


class ClientRegistrationRequest(BaseModel):
    """
    Dynamic Client Registration Request (RFC 7591).

    Used by MCP clients to register themselves with the authorization server.
    """
    redirect_uris: List[str] = Field(
        ...,
        description="Array of redirect URIs for authorization callbacks",
        min_length=1,
    )
    client_name: Optional[str] = Field(
        None,
        description="Human-readable name of the client",
    )
    grant_types: Optional[List[str]] = Field(
        None,
        description="Grant types the client will use (defaults to authorization_code)",
    )

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: List[str]) -> List[str]:
        """Validate redirect URIs are well-formed and use HTTPS (except localhost)."""
        for uri in v:
            parsed = urlparse(uri)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"Invalid redirect URI: {uri}")
            # Allow http only for localhost (development)
            if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
                raise ValueError(f"HTTPS required for non-localhost redirect URIs: {uri}")
        return v


class ClientRegistrationResponse(BaseModel):
    """
    Dynamic Client Registration Response (RFC 7591).

    Contains the generated client_id and client_secret for the registered client.
    The client_secret is only returned once at registration time.
    """
    client_id: str = Field(
        ...,
        description="Unique client identifier",
    )
    client_secret: str = Field(
        ...,
        description="Client secret (confidential - store securely, shown only once)",
    )
    client_name: Optional[str] = Field(
        None,
        description="Human-readable name of the client",
    )
    redirect_uris: List[str] = Field(
        ...,
        description="Registered redirect URIs",
    )
    grant_types: List[str] = Field(
        ...,
        description="Allowed grant types for this client",
    )


class AuthorizationRequest(BaseModel):
    """
    Authorization Request parameters (RFC 6749 / OAuth 2.1).

    Used to initiate the authorization code flow.
    """
    response_type: str = Field(
        ...,
        description="Must be 'code' for authorization code flow",
    )
    client_id: str = Field(
        ...,
        description="The client identifier",
    )
    redirect_uri: str = Field(
        ...,
        description="URI to redirect to after authorization",
    )
    code_challenge: str = Field(
        ...,
        description="PKCE code challenge (base64url-encoded SHA256 of verifier)",
    )
    code_challenge_method: str = Field(
        default="S256",
        description="PKCE challenge method (must be S256 for OAuth 2.1)",
    )
    scope: Optional[str] = Field(
        default="mcp",
        description="Requested scope",
    )
    state: Optional[str] = Field(
        None,
        description="Opaque state value for CSRF protection",
    )

    @field_validator("response_type")
    @classmethod
    def validate_response_type(cls, v: str) -> str:
        """Ensure response_type is 'code'."""
        if v != "code":
            raise ValueError("response_type must be 'code'")
        return v

    @field_validator("code_challenge_method")
    @classmethod
    def validate_challenge_method(cls, v: str) -> str:
        """Ensure S256 method (OAuth 2.1 requirement)."""
        if v != "S256":
            raise ValueError("code_challenge_method must be 'S256' (OAuth 2.1 requirement)")
        return v


class TokenRequest(BaseModel):
    """
    Token Request for authorization_code grant.

    Exchanges an authorization code for an access token.
    """
    grant_type: str = Field(
        ...,
        description="Must be 'authorization_code'",
    )
    code: str = Field(
        ...,
        description="The authorization code received from /authorize",
    )
    redirect_uri: str = Field(
        ...,
        description="Must match the redirect_uri used in /authorize",
    )
    client_id: str = Field(
        ...,
        description="The client identifier",
    )
    code_verifier: str = Field(
        ...,
        description="PKCE code verifier (original random string)",
    )

    @field_validator("grant_type")
    @classmethod
    def validate_grant_type(cls, v: str) -> str:
        """Ensure grant_type is authorization_code."""
        if v != "authorization_code":
            raise ValueError("grant_type must be 'authorization_code'")
        return v


class TokenResponse(BaseModel):
    """
    Token Response (RFC 6749).

    Contains the access token for authenticated API calls.
    """
    access_token: str = Field(
        ...,
        description="The access token (JWT)",
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type (always Bearer)",
    )
    expires_in: int = Field(
        ...,
        description="Token lifetime in seconds",
    )
    scope: Optional[str] = Field(
        default="mcp",
        description="Granted scope",
    )


class AuthorizationError(BaseModel):
    """
    Authorization Error Response (RFC 6749).

    Returned when authorization fails.
    """
    error: str = Field(
        ...,
        description="Error code",
    )
    error_description: Optional[str] = Field(
        None,
        description="Human-readable error description",
    )
    state: Optional[str] = Field(
        None,
        description="State value from the request (for CSRF correlation)",
    )
