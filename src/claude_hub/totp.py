"""TOTP authentication for terminal access."""

import io
import base64
import time
from typing import Optional
from collections import defaultdict

import pyotp
import qrcode
from qrcode.image.pil import PilImage

from .totp_store import TOTPStore


class RateLimiter:
    """Simple in-memory rate limiter for TOTP verification attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_attempts: Maximum attempts allowed per window
            window_seconds: Time window in seconds
        """
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """
        Check if an action is allowed for the given key.

        Args:
            key: Rate limit key (e.g., IP address)

        Returns:
            True if allowed, False if rate limited
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old attempts
        self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]

        # Check if under limit
        return len(self._attempts[key]) < self.max_attempts

    def record_attempt(self, key: str) -> None:
        """
        Record an attempt for the given key.

        Args:
            key: Rate limit key
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old attempts and add new one
        self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
        self._attempts[key].append(now)

    def remaining_attempts(self, key: str) -> int:
        """
        Get remaining attempts for the given key.

        Args:
            key: Rate limit key

        Returns:
            Number of remaining attempts
        """
        now = time.time()
        cutoff = now - self.window_seconds
        recent = [t for t in self._attempts[key] if t > cutoff]
        return max(0, self.max_attempts - len(recent))


class TOTPManager:
    """Manages TOTP generation, verification, and QR codes."""

    ISSUER = "claude-hub"
    VALID_WINDOW = 1  # Accept codes from 1 period before/after (30-90 seconds total)

    def __init__(self, store: TOTPStore):
        """
        Initialize TOTP manager.

        Args:
            store: TOTPStore for secret/session persistence
        """
        self.store = store
        self.rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)

    def generate_secret(self, user_id: str) -> tuple[str, str]:
        """
        Generate a new TOTP secret for a user.

        Args:
            user_id: User identifier

        Returns:
            Tuple of (secret, provisioning_uri)
        """
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user_id,
            issuer_name=self.ISSUER,
        )

        return secret, provisioning_uri

    def generate_qr_data_uri(self, provisioning_uri: str) -> str:
        """
        Generate a QR code as a data URI.

        Args:
            provisioning_uri: The TOTP provisioning URI

        Returns:
            Data URI (data:image/png;base64,...)
        """
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=4,
        )
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        img: PilImage = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def verify_code(self, user_id: str, code: str, client_ip: str) -> bool:
        """
        Verify a TOTP code for a user.

        Args:
            user_id: User identifier
            code: The 6-digit TOTP code
            client_ip: Client IP for rate limiting

        Returns:
            True if valid, False otherwise
        """
        # Check rate limit
        if not self.rate_limiter.is_allowed(client_ip):
            return False

        # Record attempt
        self.rate_limiter.record_attempt(client_ip)

        # Get user's secret
        totp_secret = self.store.get_secret(user_id)
        if not totp_secret or not totp_secret.enabled:
            return False

        # Verify code with window tolerance
        totp = pyotp.TOTP(totp_secret.secret)
        return totp.verify(code, valid_window=self.VALID_WINDOW)

    def is_enrolled(self, user_id: str) -> bool:
        """
        Check if a user has TOTP enrollment.

        Args:
            user_id: User identifier

        Returns:
            True if enrolled, False otherwise
        """
        totp_secret = self.store.get_secret(user_id)
        return totp_secret is not None and totp_secret.enabled

    def enroll_user(self, user_id: str, secret: str, code: str, client_ip: str) -> bool:
        """
        Complete TOTP enrollment by verifying the test code.

        Args:
            user_id: User identifier
            secret: The TOTP secret to enroll
            code: Test code to verify enrollment
            client_ip: Client IP for rate limiting

        Returns:
            True if enrollment successful, False otherwise
        """
        # Check rate limit
        if not self.rate_limiter.is_allowed(client_ip):
            return False

        # Record attempt
        self.rate_limiter.record_attempt(client_ip)

        # Verify the test code
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=self.VALID_WINDOW):
            return False

        # Save the secret
        self.store.save_secret(user_id, secret)
        return True

    def get_remaining_attempts(self, client_ip: str) -> int:
        """
        Get remaining verification attempts for a client.

        Args:
            client_ip: Client IP address

        Returns:
            Number of remaining attempts
        """
        return self.rate_limiter.remaining_attempts(client_ip)
