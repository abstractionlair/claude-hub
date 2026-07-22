"""Owner-authentication gate on the OAuth authorize flow (finding C1).

Before this gate, anyone could POST /authorize/consent and mint an authorization
code with no owner check. Consent now requires a valid owner TOTP session plus a
session-bound CSRF token.
"""
import pytest
from fastapi.testclient import TestClient

import claude_hub.auth as auth_module
import claude_hub.server as server_module
from claude_hub.server import app, _authorize_csrf_token

TEST_SECRET = "test-secret-for-authorize-tests"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def oauth_enabled(monkeypatch):
    monkeypatch.setattr(auth_module, "JWT_SECRET", TEST_SECRET)


def _consent_form(action="approve"):
    # A well-formed consent submission WITHOUT an owner session cookie or CSRF token.
    return {
        "client_id": "c-test",
        "redirect_uri": "https://example.com/cb",
        "code_challenge": "abc",
        "code_challenge_method": "S256",
        "scope": "mcp",
        "state": "",
        "action": action,
    }


def test_consent_without_owner_session_cannot_mint(client, oauth_enabled):
    resp = client.post(
        "/authorize/consent", data=_consent_form("approve"), follow_redirects=False
    )
    assert resp.status_code == 403


def test_consent_deny_also_requires_owner_session(client, oauth_enabled):
    resp = client.post(
        "/authorize/consent", data=_consent_form("deny"), follow_redirects=False
    )
    assert resp.status_code == 403


def test_csrf_token_is_session_bound_and_stable(monkeypatch):
    monkeypatch.setattr(server_module, "JWT_SECRET", TEST_SECRET)
    a1 = _authorize_csrf_token("session-a")
    a2 = _authorize_csrf_token("session-a")
    b = _authorize_csrf_token("session-b")
    assert a1 == a2  # stable for a given session
    assert a1 != b  # bound to the session id
    assert len(a1) == 64  # sha256 hex digest
