"""Auth-gating tests for /debug/*, /chat/send, /ws/chat, and /ws/group/{id},
plus the /chat/token endpoint that lets the browser pages satisfy those gates.

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
from jose import jwt
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


def _bearer(scope: str = auth_module.SCOPE_MCP) -> dict:
    return {"Authorization": f"Bearer {_token(scope)}"}


def _token(scope: str = auth_module.SCOPE_MCP) -> str:
    token, _ = auth_module.create_access_token("test-client", scope=scope)
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


def _mock_chat_process_manager():
    """A chat_process_manager stub so the /ws/chat handler needs no subprocess."""
    manager = MagicMock()
    manager.get_chat_summary.return_value = None
    return manager


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
# /ws/chat
#
# This socket forwards every message to a Claude Code subprocess launched with
# --dangerously-skip-permissions, so an unauthenticated handshake here is a
# direct path to a permission-skipping agent. Same gate as /ws/group.
# ---------------------------------------------------------------------------


class TestChatWebSocketAuth:
    def test_handshake_rejected_without_token(self, client, oauth_enabled):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/chat"):
                pass
        assert exc_info.value.code == 1008

    def test_handshake_rejected_with_invalid_token(self, client, oauth_enabled):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/chat?token=not-a-jwt"):
                pass
        assert exc_info.value.code == 1008

    def test_handshake_accepted_with_query_token(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        with client.websocket_connect(f"/ws/chat?token={_token()}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_handshake_accepted_with_bearer_header(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        with client.websocket_connect("/ws/chat", headers=_bearer()) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_handshake_open_in_dev_mode(self, client, oauth_disabled, monkeypatch):
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


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


# ---------------------------------------------------------------------------
# /chat/token
#
# The two browser chat pages cannot set an Authorization header on a WebSocket
# connect, so they mint a short-lived token here and pass it as a query param.
# ---------------------------------------------------------------------------


class TestChatToken:
    def test_mints_a_token_the_gates_accept(self, client, oauth_enabled):
        response = client.get("/chat/token")
        assert response.status_code == 200

        token = response.json()["token"]
        assert token
        assert auth_module.verify_token(token, allowed_scopes=(auth_module.SCOPE_CHAT,)) == "web-chat"

        # And only there: the default scope requirement rejects it.
        assert auth_module.verify_token(token) is None

    def test_token_is_short_lived(self, client, oauth_enabled):
        body = client.get("/chat/token").json()
        assert body["expires_in"] == server_module.CHAT_TOKEN_TTL_SECONDS

        claims = jwt.decode(
            body["token"], TEST_SECRET, algorithms=[auth_module.ALGORITHM]
        )
        assert claims["exp"] - claims["iat"] == server_module.CHAT_TOKEN_TTL_SECONDS

    def test_dev_mode_returns_no_token(self, client, oauth_disabled):
        """No secret means the handshake gates are inert; the pages connect bare."""
        response = client.get("/chat/token")
        assert response.status_code == 200
        assert response.json()["token"] is None

    def test_response_is_not_cacheable(self, client, oauth_enabled):
        assert client.get("/chat/token").headers["cache-control"] == "no-store"

    def test_serves_no_cors_headers(self, client, oauth_enabled):
        """A cross-origin page must not be able to read a token out of this.

        That unreadability is what makes the handshake gates worth having
        against cross-site WebSocket hijacking — the socket itself is not
        origin-checked, so the token is the only thing an attacker's page
        lacks.
        """
        response = client.get("/chat/token", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers

    def test_minted_token_opens_ws_chat(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        token = client.get("/chat/token").json()["token"]
        with client.websocket_connect(f"/ws/chat?token={token}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_minted_token_opens_ws_group(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)
        token = client.get("/chat/token").json()["token"]
        with client.websocket_connect(f"/ws/group/test-conv?name=Scott&token={token}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


# ---------------------------------------------------------------------------
# Scope separation
#
# /chat/token is reachable with nothing but proxy auth, while the OAuth flow
# that issues "mcp" tokens requires the owner's TOTP (see the /authorize gate).
# A chat token must therefore open the two chat sockets and nothing else,
# otherwise /chat/token is a TOTP-free path to full MCP access.
# ---------------------------------------------------------------------------


class TestScopeSeparation:
    """A "chat" token opens the sockets; only "mcp" reaches the tool surface."""

    def test_chat_token_opens_ws_chat(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        with client.websocket_connect(f"/ws/chat?token={_token(auth_module.SCOPE_CHAT)}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_chat_token_opens_ws_group(self, client, oauth_enabled, monkeypatch):
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)
        conv = f"/ws/group/test-conv?token={_token(auth_module.SCOPE_CHAT)}"
        with client.websocket_connect(conv) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_chat_token_rejected_by_chat_send(self, client, oauth_enabled, monkeypatch):
        session_manager = MagicMock()
        session_manager.send_message.return_value = "should never run"
        monkeypatch.setattr(server_module, "session_manager", session_manager, raising=False)

        response = client.post(
            "/chat/send", json={"message": "hi"}, headers=_bearer(auth_module.SCOPE_CHAT)
        )
        assert response.status_code == 401
        session_manager.send_message.assert_not_called()

    @pytest.mark.parametrize("path", DEBUG_PATHS)
    def test_chat_token_rejected_by_debug_endpoints(self, client, oauth_enabled, path):
        assert client.get(path, headers=_bearer(auth_module.SCOPE_CHAT)).status_code == 401

    def test_chat_token_rejected_by_mcp_middleware(self, client, oauth_enabled):
        """The pure-ASGI middleware must reject before the MCP app sees anything."""
        response = client.post(
            "/mcp",
            headers={
                **_bearer(auth_module.SCOPE_CHAT),
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 401

    def test_mcp_token_still_reaches_the_mcp_app(self, client, oauth_enabled):
        """Regression guard: every token the OAuth flow issues carries "mcp"."""
        response = client.post(
            "/mcp",
            headers={**_bearer(), "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        # The MCP app answers (a session-protocol error here); the point is that
        # the middleware did not reject it. Asserting the exact status would
        # couple this test to the MCP session handshake.
        assert response.status_code != 401

    def test_mcp_token_still_works_on_chat_send(self, client, oauth_enabled, monkeypatch):
        session_manager = MagicMock()
        session_manager.send_message.return_value = "hello back"
        monkeypatch.setattr(server_module, "session_manager", session_manager, raising=False)

        response = client.post("/chat/send", json={"message": "hi"}, headers=_bearer())
        assert response.status_code == 200

    def test_mcp_token_still_opens_both_sockets(self, client, oauth_enabled, monkeypatch):
        """A higher-privilege token may open a socket; only climbing is blocked."""
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        monkeypatch.setattr(server_module, "message_router", _mock_message_router(), raising=False)

        with client.websocket_connect(f"/ws/chat?token={_token()}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

        with client.websocket_connect(f"/ws/group/test-conv?token={_token()}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_scope_is_parsed_as_a_space_delimited_list(self, oauth_enabled):
        """RFC 6749 §3.3 — a superset grant still satisfies an "mcp" requirement."""
        token = _token("mcp offline_access")
        assert auth_module.verify_token(token) == "test-client"

    def test_token_without_a_scope_claim_is_rejected(self, oauth_enabled):
        """Fail closed: no scope satisfies nothing, at any call site."""
        token = _token("")
        assert auth_module.verify_token(token) is None
        assert auth_module.verify_token(token, allowed_scopes=(auth_module.SCOPE_CHAT,)) is None

    def test_dev_mode_ignores_scope_entirely(self, client, oauth_disabled, monkeypatch):
        """No secret means no gate — unchanged by scope enforcement."""
        monkeypatch.setattr(
            server_module, "chat_process_manager", _mock_chat_process_manager(), raising=False
        )
        session_manager = MagicMock()
        session_manager.send_message.return_value = "dev mode"
        monkeypatch.setattr(server_module, "session_manager", session_manager, raising=False)

        assert client.post("/chat/send", json={"message": "hi"}).status_code == 200
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
