"""Auth-gating tests for /debug/*, /chat/send, and /ws/group/{id}.

These routes were previously reachable without in-app auth. They must now
honor the same OAuth 2.1 gate as the MCP tool endpoints: open in
development mode (no JWT secret), Bearer-token-protected once
CLAUDE_HUB_JWT_SECRET is set. The WebSocket checks the token at handshake
(Authorization header or `token` query param) and closes with 1008 on
failure.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import claude_hub.auth as auth_module
import claude_hub.server as server_module
from claude_hub.server import app

TEST_SECRET = "test-secret-for-endpoint-auth-tests"

DEBUG_PATHS = [
    "/debug/headers",
    "/debug/routes",
    "/debug/sessions",
    "/debug/pending",
    "/debug/memory",
]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def oauth_enabled(monkeypatch):
    """Enable OAuth 2.1 by setting the JWT secret the auth module reads."""
    monkeypatch.setattr(auth_module, "JWT_SECRET", TEST_SECRET)


@pytest.fixture
def oauth_disabled(monkeypatch):
    monkeypatch.setattr(auth_module, "JWT_SECRET", "")


def _bearer() -> dict:
    token, _ = auth_module.create_access_token("test-client")
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    token, _ = auth_module.create_access_token("test-client")
    return token


def _mock_message_router():
    """A message_router stub that lets the WS handler run without lifespan."""
    conv = MagicMock()
    conv.message_log = []
    participant = MagicMock()
    participant.participant_id = "p-test"
    participant.to_dict.return_value = {}

    router = MagicMock()
    router.get_or_create_conversation.return_value = conv
    router._ensure_bus_started = AsyncMock()
    router.add_human.return_value = participant
    router.subscribe.return_value = asyncio.Queue()
    router._buses = {}
    router.remove_participant.return_value = None
    return router


# ---------------------------------------------------------------------------
# /debug/* endpoints
# ---------------------------------------------------------------------------


class TestDebugEndpointAuth:
    @pytest.mark.parametrize("path", DEBUG_PATHS)
    def test_401_without_token_when_oauth_enabled(self, client, oauth_enabled, path):
        response = client.get(path)
        assert response.status_code == 401

    @pytest.mark.parametrize("path", DEBUG_PATHS)
    def test_401_with_invalid_token_when_oauth_enabled(self, client, oauth_enabled, path):
        response = client.get(path, headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    def test_200_with_valid_token(self, client, oauth_enabled):
        response = client.get("/debug/headers", headers=_bearer())
        assert response.status_code == 200
        assert "headers" in response.json()

    def test_200_with_valid_token_pending(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(server_module, "pending_responses", {}, raising=False)
        response = client.get("/debug/pending", headers=_bearer())
        assert response.status_code == 200

    def test_open_in_dev_mode(self, client, oauth_disabled):
        # Development mode (no JWT secret) keeps the routes reachable.
        response = client.get("/debug/headers")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# /chat/send
# ---------------------------------------------------------------------------


class TestChatSendAuth:
    def test_401_without_token_when_oauth_enabled(self, client, oauth_enabled):
        response = client.post("/chat/send", json={"message": "hi"})
        assert response.status_code == 401

    def test_401_with_invalid_token_when_oauth_enabled(self, client, oauth_enabled):
        response = client.post(
            "/chat/send",
            json={"message": "hi"},
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401

    def test_200_with_valid_token(self, client, oauth_enabled, monkeypatch):
        session_manager = MagicMock()
        session_manager.send_message.return_value = "hello back"
        monkeypatch.setattr(server_module, "session_manager", session_manager, raising=False)

        response = client.post("/chat/send", json={"message": "hi"}, headers=_bearer())
        assert response.status_code == 200
        assert response.json()["response"] == "hello back"

    def test_open_in_dev_mode(self, client, oauth_disabled, monkeypatch):
        session_manager = MagicMock()
        session_manager.send_message.return_value = "dev mode"
        monkeypatch.setattr(server_module, "session_manager", session_manager, raising=False)

        response = client.post("/chat/send", json={"message": "hi"})
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# /ws/group/{conversation_id}
# ---------------------------------------------------------------------------


class TestGroupWebSocketAuth:
    def test_handshake_rejected_without_token(self, client, oauth_enabled):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/group/test-conv"):
                pass
        assert exc_info.value.code == 1008

    def test_handshake_rejected_with_invalid_token(self, client, oauth_enabled):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/group/test-conv?token=not-a-jwt"):
                pass
        assert exc_info.value.code == 1008

    def test_handshake_accepted_with_query_token(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)
        with client.websocket_connect(f"/ws/group/test-conv?token={_token()}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_handshake_accepted_with_bearer_header(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)
        with client.websocket_connect("/ws/group/test-conv", headers=_bearer()) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_handshake_open_in_dev_mode(self, client, oauth_disabled, monkeypatch):
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)
        with client.websocket_connect("/ws/group/test-conv") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
