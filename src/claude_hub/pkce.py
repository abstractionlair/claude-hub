"""PKCE (Proof Key for Code Exchange) implementation for OAuth 2.1."""

import hashlib
import base64
import secrets
import hmac


def generate_code_verifier(length: int = 128) -> str:
    """
    Generate a cryptographically random code verifier.

    OAuth 2.1 requires verifiers to be 43-128 characters from
    the unreserved character set [A-Z, a-z, 0-9, -, ., _, ~].

    Args:
        length: Length of the verifier (default 128, max allowed)

    Returns:
        Random code verifier string
    """
    # token_urlsafe produces base64url-safe characters
    # 96 bytes -> 128 chars after base64url encoding
    return secrets.token_urlsafe(96)[:length]


def compute_code_challenge(verifier: str, method: str = "S256") -> str:
    """
    Compute the code challenge from a verifier.

    OAuth 2.1 requires S256 method (plain is deprecated).

    Args:
        verifier: The code verifier
        method: Challenge method (only "S256" supported per OAuth 2.1)

    Returns:
        Base64url-encoded SHA256 hash of verifier

    Raises:
        ValueError: If method is not S256
    """
    if method != "S256":
        raise ValueError("Only S256 method is supported (OAuth 2.1 requirement)")

    # SHA256 hash of the verifier
    digest = hashlib.sha256(verifier.encode("ascii")).digest()

    # Base64url encode without padding
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return challenge


def verify_pkce(verifier: str, challenge: str, method: str = "S256") -> bool:
    """
    Verify a PKCE code verifier against a stored challenge.

    Uses timing-safe comparison to prevent timing attacks.

    Args:
        verifier: The code verifier from the token request
        challenge: The stored code challenge from the authorization request
        method: Challenge method (only "S256" supported)

    Returns:
        True if verifier matches challenge, False otherwise
    """
    if method != "S256":
        return False

    try:
        computed = compute_code_challenge(verifier, method)
        # Use hmac.compare_digest for timing-safe comparison
        return hmac.compare_digest(computed, challenge)
    except (ValueError, UnicodeDecodeError):
        return False
