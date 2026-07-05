"""
claude-hub MCP Server

A thin relay enabling chat Claude instances to converse with
a persistent Claude Code backend.

MCP Tools exposed:
- hub_init: Initialize a conversation, get a conversation ID
- hub_send: Send a message, receive response (blocking)
- hub_status: Check conversation/session status
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import signal
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict

import asyncpg

from fastapi import FastAPI, HTTPException, Depends, Form, Request, WebSocket, WebSocketDisconnect, Body
from pydantic import BaseModel
from fastapi_mcp import FastApiMCP

from .models import (
    InitRequest,
    InitResponse,
    SendRequest,
    SendResponse,
    PollRequest,
    PollResponse,
    GroupJoinRequest,
    GroupJoinResponse,
    GroupSendRequest,
    GroupSendResponse,
    GroupPollRequest,
    GroupPollResponse,
    GroupLeaveRequest,
    GroupLeaveResponse,
)
from .routing import RoutingTable
from .session import SessionManager, MAIN_SESSION_UUID
from .auth import (
    TokenResponse,
    create_access_token,
    get_current_client,
    is_oauth21_enabled,
    require_auth,
    JWT_SECRET,
    TOKEN_TYPE_AUTHORIZATION_CODE,
)
from .oauth_store import OAuthStore
from .totp_store import TOTPStore
from .totp import TOTPManager
from .oauth_models import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    AuthorizationRequest,
    TokenRequest as OAuth21TokenRequest,
    TokenResponse as OAuth21TokenResponse,
    AuthorizationError,
)
from .pkce import verify_pkce
from .workspace import WorkspaceManager, ResourceConstraints
from .scheduler import Scheduler
from .handoff import HandoffManager
from .notifications import NotificationManager
from .delegation_models import (
    CreateWorkspaceParams, CreateWorkspaceResponse,
    ListChildrenParams, ListChildrenResponse,
    ScheduleWakeAtParams, ScheduleWakeEveryParams,
    ScheduleResponse, ListSchedulesParams, ListSchedulesResponse,
    ScheduleInfo, CancelScheduleParams, CancelScheduleResponse,
    WriteHandoffParams, WriteHandoffResponse,
    ReadHandoffParams, ReadHandoffResponse, HandoffInfo,
    ListHandoffsParams, ListHandoffsResponse,
)
from .storage import StorageManager, StorageError, PathTraversalError
from .storage_models import (
    FilesReadParams, FilesReadResponse,
    FilesWriteParams, FilesWriteResponse,
    FilesListParams, FilesListResponse, FileEntry,
    FilesAppendParams, FilesAppendResponse,
    FilesSearchParams, FilesSearchResponse, SearchResult,
    GitHubFileReadParams, GitHubFileReadResponse,
)
from .github_tools import GitHubClient, GitHubError
from .chat_process import ChatProcessManager
from .message_router import MessageRouter
from .conversation_store import ConversationStore
from .conversation import GroupMessage, MessageType, ParticipantType, make_message_id
from .codex_chat import CodexChat
from .gemini_chat import GeminiChat
from .observations import ObservationStore, parse_observation_markers
from claude_hub import database, embedding
from claude_hub import artifact_store as artifact_store_module
from claude_hub.artifact_store import ArtifactNotFoundError
from claude_hub.connectors import ArtifactConnector, ConnectorRegistry, FilesystemConnector
from claude_hub.connectors.base import ConnectorError
from claude_hub.connector_models import (
    ConnectorRegisterRequest, ConnectorRegisterResponse,
    ConnectorIndexRequest, ConnectorIndexResponse,
    QueryFederatedRequest, QueryFederatedResponse, FederatedSearchResult,
)
import httpx
from claude_hub.work_graph_models import (
    WgSessionStartParams, WgBriefParams, WgCaptureParams, WgGotoParams, WgStatusParams,
    WgQueryParams, WgSearchParams, WgAddDependencyParams, WgUpdateParams,
    WgSessionStartResponse, WgBriefResponse, WgCaptureResponse, WgGotoResponse,
    WgStatusResponse, WgQueryResponse, WgSearchResponse,
    WgAddDependencyResponse, WgUpdateResponse,
)

# Work-graph service runs as a separate process on the host, bound to
# localhost only. claude-hub forwards /tools/wg_* calls to it rather
# than importing its code, so the two services can be deployed
# independently and don't share a Python process.
WG_SERVICE_URL = os.environ.get("WORK_GRAPH_URL", "http://127.0.0.1:8421")
from claude_hub.artifact_models import (
    ArtifactStoreRequest, ArtifactStoreResponse,
    ArtifactGetRequest, ArtifactGetResponse,
    ArtifactSearchRequest, ArtifactSearchResponse,
    ArtifactListRequest, ArtifactListResponse,
    ArtifactArchiveRequest, ArtifactArchiveResponse,
    ArtifactUpdateRequest, ArtifactUpdateResponse,
    ArtifactUpdateMetadataRequest, ArtifactUpdateMetadataResponse,
    ArtifactExportRequest, ArtifactExportResponse,
    ArtifactImportRequest, ArtifactImportResponse,
    ArtifactFeedbackRequest, ArtifactFeedbackResponse,
    ArtifactSetConfidenceRequest, ArtifactSetConfidenceResponse,
    ArtifactRetirementCandidatesRequest, ArtifactRetirementCandidatesResponse,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from urllib.parse import urlencode


logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# Configuration
CLAUDE_BINARY = os.environ.get("CLAUDE_HUB_CLAUDE_BINARY", "claude")
PROJECT_DIR = Path(os.environ.get("CLAUDE_HUB_PROJECT_DIR", str(Path.home() / "claude-hub")))
# Source tree: where docs, CLAUDE.md, and window files live. Group-chat
# participants (Main Claude, codex, gemini) launch with this as cwd so they
# can read/refer to the source rather than the deploy artifact tree.
SOURCE_DIR = Path(os.environ.get("CLAUDE_HUB_SOURCE_DIR", str(Path.home() / "projects" / "claude-hub")))


# Global state (initialized in lifespan)
routing_table: RoutingTable
session_manager: SessionManager
workspace_manager: WorkspaceManager
scheduler: Scheduler
handoff_manager: HandoffManager
notification_manager: NotificationManager
oauth_store: OAuthStore
totp_store: TOTPStore
totp_manager: TOTPManager
storage_manager: StorageManager
github_client: GitHubClient
chat_process_manager: ChatProcessManager
message_router: MessageRouter
pending_responses: dict  # request_id -> {"status": str, "response": str, "conversation_id": str, "created_at": float}
pg_pool: asyncpg.Pool | None = None
embedding_task: asyncio.Task | None = None
_cleanup_task: asyncio.Task | None = None
_connector_registry: ConnectorRegistry | None = None

# Cleanup constants
_PENDING_RESPONSE_TTL_SECONDS = 600  # 10 minutes
_CHAT_PROCESS_IDLE_SECONDS = 1800  # 30 minutes
_CLEANUP_INTERVAL_SECONDS = 120  # Run cleanup every 2 minutes


async def _periodic_cleanup() -> None:
    """Background task: clean up stale pending_responses and idle chat processes."""
    import time as _time
    logger.info("Periodic cleanup task started (interval=%ds)", _CLEANUP_INTERVAL_SECONDS)
    try:
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
            now = _time.monotonic()

            # 1. Evict stale pending_responses
            stale_keys = [
                rid for rid, entry in pending_responses.items()
                if now - entry.get("created_at", 0) > _PENDING_RESPONSE_TTL_SECONDS
            ]
            for rid in stale_keys:
                del pending_responses[rid]
            if stale_keys:
                logger.info("[Cleanup] Evicted %d stale pending_responses", len(stale_keys))

            # 2. Reap idle chat processes
            reaped = await chat_process_manager.reap_idle(max_idle_seconds=_CHAT_PROCESS_IDLE_SECONDS)
            if reaped:
                logger.info("[Cleanup] Reaped %d idle chat processes", reaped)

            # 3. Clean up stale routing table entries (no route = no need for counter)
            stale_counts = [
                cid for cid in routing_table._message_counts
                if cid not in routing_table._routes
            ]
            for cid in stale_counts:
                del routing_table._message_counts[cid]

    except asyncio.CancelledError:
        logger.info("Periodic cleanup task cancelled — shutting down")


# Map connector_type strings to their implementation classes
CONNECTOR_TYPES: dict[str, type] = {
    "artifact_store": ArtifactConnector,
    "filesystem": FilesystemConnector,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup global state."""
    global routing_table, session_manager, workspace_manager, scheduler, handoff_manager, notification_manager, oauth_store, totp_store, totp_manager, storage_manager, github_client, chat_process_manager, message_router, pending_responses, pg_pool, embedding_task, _cleanup_task, _connector_registry

    routing_table = RoutingTable()
    session_manager = SessionManager(
        claude_binary=CLAUDE_BINARY,
        project_dir=PROJECT_DIR,
    )
    workspace_manager = WorkspaceManager(base_dir=PROJECT_DIR)
    handoff_manager = HandoffManager()

    # All SQLite stores now use PostgreSQL via CLAUDE_HUB_PG_DSN
    app_dsn = os.environ.get("CLAUDE_HUB_PG_DSN", "")

    # Initialize OAuth 2.1 store
    oauth_store = OAuthStore(dsn=app_dsn)

    # Initialize TOTP store
    totp_store = TOTPStore(dsn=app_dsn)
    totp_manager = TOTPManager(store=totp_store)

    # Initialize notifications
    notification_manager = NotificationManager(dsn=app_dsn)

    # Initialize scheduler with wake-up callback
    def wake_callback(session_id: str, prompt: str, constraints: dict):
        """Called when a scheduled wake-up is due."""
        try:
            # Send the scheduled prompt to the session
            session_manager.send_message(session_id, prompt)
        except Exception as e:
            print(f"[Scheduler] Error waking session {session_id}: {e}")

    scheduler = Scheduler(dsn=app_dsn, wake_callback=wake_callback)
    scheduler.start()

    # Initialize file storage
    storage_manager = StorageManager()

    # Initialize GitHub client
    github_client = GitHubClient()

    # Initialize streaming chat process manager. Use SOURCE_DIR (not
    # PROJECT_DIR) so Main Claude lands in the source tree, and chat-mode
    # Claudes get --add-dir to it.
    chat_process_manager = ChatProcessManager(
        project_dir=SOURCE_DIR,
        claude_binary=CLAUDE_BINARY,
        observations_dsn=app_dsn,
    )

    # Initialize group conversation message router with persistent store
    _conv_store = ConversationStore(dsn=app_dsn)
    message_router = MessageRouter(chat_process_manager, store=_conv_store)

    # Startup recovery: mark any stale "active" conversations as interrupted
    recovery_summary = message_router.startup_recovery()
    if recovery_summary["crash_recovered"] > 0:
        logger.info(
            "Startup recovery: %d conversations recovered from crash",
            recovery_summary["crash_recovered"],
        )

    # Log SIGTERM but chain to uvicorn's handler so shutdown actually happens
    _prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _sigterm_handler(signum, frame):
        logger.info("Received SIGTERM — graceful shutdown initiated")
        # Chain to uvicorn's handler (or default) so shutdown proceeds
        if callable(_prev_sigterm):
            _prev_sigterm(signum, frame)
        elif _prev_sigterm == signal.SIG_DFL:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # Async response store for hub_send/hub_poll
    pending_responses = {}

    # Postgres pool (optional — graceful degradation)
    try:
        pg_dsn = os.environ.get("CLAUDE_HUB_PG_DSN")
        if pg_dsn:
            pg_pool = await database.create_pool(pg_dsn)
            database.set_pool(pg_pool)
            await database.run_migrations(pg_pool, PROJECT_DIR / "migrations")
            embedding.configure_gemini()
            embedding_task = asyncio.create_task(embedding.embedding_retry_loop(pg_pool))
            logger.info("Artifact store initialized (Postgres + embeddings)")

            # Load active connectors from database
            _connector_registry = ConnectorRegistry()
            try:
                async with pg_pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT id, name, connector_type, config FROM connectors WHERE status = 'active'"
                    )
                loaded = 0
                for row in rows:
                    ctype = row["connector_type"]
                    cls = CONNECTOR_TYPES.get(ctype)
                    if cls is None:
                        logger.warning("Unknown connector type '%s' for connector '%s', skipping", ctype, row["name"])
                        continue
                    config = json.loads(row["config"]) if isinstance(row["config"], str) else (row["config"] or {})
                    config["connector_id"] = str(row["id"])
                    try:
                        instance = cls(name=row["name"], config=config, pool=pg_pool)
                        _connector_registry.register(instance)
                        loaded += 1
                    except Exception as e:
                        logger.warning("Failed to load connector '%s': %s", row["name"], e)
                logger.info("Loaded %d active connector(s) from database", loaded)
            except Exception as e:
                logger.warning("Failed to load connectors from database: %s", e)

        else:
            logger.info("CLAUDE_HUB_PG_DSN not set — artifact store disabled")
    except Exception as e:
        logger.warning("Postgres unavailable, artifact tools disabled: %s", e)
        pg_pool = None

    # Work graph: runs as a separate service on WG_SERVICE_URL; nothing
    # to initialize in-process. See work-graph repo for deployment.

    # Start periodic cleanup task (pending_responses TTL, idle process reaping)
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    # Cleanup: stop periodic cleanup
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass

    # Cleanup: shut down artifact store
    if embedding_task is not None:
        embedding_task.cancel()
        try:
            await embedding_task
        except asyncio.CancelledError:
            pass
    if pg_pool is not None:
        await database.close_pool()

    # Cleanup: shut down group conversations first (they own Claude processes too)
    # This marks active conversations as interrupted in SQLite before cleanup
    await message_router.shutdown()

    # Cleanup: shut down chat processes
    await chat_process_manager.shutdown()

    # Cleanup: stop scheduler and terminate sessions
    scheduler.stop()
    for session_id in session_manager.list_sessions():
        session_manager.terminate_session(session_id)


def require_pg_pool() -> asyncpg.Pool:
    """Return the Postgres pool or raise 503 if unavailable."""
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="Artifact store unavailable — Postgres not configured")
    return pg_pool


def require_connector_registry() -> ConnectorRegistry:
    """Return the connector registry or raise 503 if unavailable."""
    if _connector_registry is None:
        raise HTTPException(status_code=503, detail="Connector registry unavailable — Postgres not configured")
    return _connector_registry


app = FastAPI(
    title="claude-hub",
    description="MCP server for persistent Claude Code backend",
    version="0.2.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# MCP Auth Middleware (pure ASGI — no BaseHTTPMiddleware)
#
# Claude.ai doesn't proactively check /.well-known/oauth-protected-resource.
# It only discovers auth requirements when the MCP endpoint itself returns
# 401 + WWW-Authenticate. This middleware gates /mcp on Bearer token presence.
#
# NOTE: Must be pure ASGI, not @app.middleware("http"). BaseHTTPMiddleware
# buffers responses and breaks SSE streaming, causing AssertionError in
# starlette when FastApiMCP dispatches internal ASGI tool calls.
# -----------------------------------------------------------------------------

BASE_URL = os.environ.get("HUB_BASE_URL", "http://localhost:8420")


class MCPAuthMiddleware:
    """Pure ASGI middleware for MCP auth. Avoids BaseHTTPMiddleware SSE issues."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_oauth21_enabled():
            path = scope.get("path", "")
            if path.startswith("/mcp"):
                # Check for Bearer token in headers
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                if not auth.lower().startswith("bearer "):
                    # Return 401 directly without touching the app
                    body = b'{"detail":"Authentication required"}'
                    www_auth = f'Bearer resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource"'
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            [b"content-type", b"application/json"],
                            [b"content-length", str(len(body)).encode()],
                            [b"www-authenticate", www_auth.encode()],
                        ],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": body,
                    })
                    return
        await self.app(scope, receive, send)


app.add_middleware(MCPAuthMiddleware)


# -----------------------------------------------------------------------------
# OAuth 2.1 Endpoints
# -----------------------------------------------------------------------------


@app.get("/.well-known/oauth-protected-resource", operation_id="protected_resource_metadata")
async def protected_resource_metadata():
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Tells MCP clients that this resource requires authentication
    and where to find the authorization server.
    """
    base_url = BASE_URL
    return {
        "resource": base_url,
        "authorization_servers": [base_url],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata():
    """
    OAuth 2.1 Authorization Server Metadata (RFC 8414).

    Allows MCP clients to discover OAuth endpoints.
    """
    base_url = BASE_URL

    return {
        "issuer": base_url,
        "registration_endpoint": f"{base_url}/register",
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "grant_types_supported": ["authorization_code"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp"],
    }


# Initialize Jinja2 templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Mount static files (PWA assets, icons, nav, service worker)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.post("/register", response_model=ClientRegistrationResponse)
async def register_client(request: ClientRegistrationRequest):
    """
    Dynamic Client Registration (RFC 7591).

    Register a new OAuth client. Returns client_id and client_secret.
    The client_secret is shown only once - store it securely.
    """
    if not is_oauth21_enabled():
        raise HTTPException(
            status_code=503,
            detail="OAuth 2.1 not configured. Set CLAUDE_HUB_JWT_SECRET.",
        )

    client, client_secret = oauth_store.register_client(
        redirect_uris=request.redirect_uris,
        client_name=request.client_name,
        grant_types=request.grant_types or ["authorization_code"],
    )

    return ClientRegistrationResponse(
        client_id=client.client_id,
        client_secret=client_secret,  # Plaintext, shown only once
        client_name=client.client_name,
        redirect_uris=client.redirect_uris,
        grant_types=client.grant_types,
    )


@app.get("/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    scope: str = "mcp",
    state: Optional[str] = None,
):
    """
    Authorization Endpoint (OAuth 2.1).

    Displays a consent page for the user to approve or deny the authorization request.
    """
    if not is_oauth21_enabled():
        raise HTTPException(
            status_code=503,
            detail="OAuth 2.1 not configured. Set CLAUDE_HUB_JWT_SECRET.",
        )

    # Validate request
    errors = []

    if response_type != "code":
        errors.append("response_type must be 'code'")

    if code_challenge_method != "S256":
        errors.append("code_challenge_method must be 'S256' (OAuth 2.1 requirement)")

    # Validate client exists
    client = oauth_store.get_client(client_id)
    if not client:
        errors.append(f"Unknown client_id: {client_id}")

    # Validate redirect_uri is registered
    if client and not oauth_store.validate_redirect_uri(client_id, redirect_uri):
        errors.append(f"redirect_uri not registered for this client")

    if errors:
        # If we can't redirect safely, show error page
        if not client or redirect_uri not in (client.redirect_uris if client else []):
            return templates.TemplateResponse(
                request,
                "authorize.html",
                context={
                    "error": "invalid_request",
                    "error_description": "; ".join(errors),
                },
            )
        # Otherwise redirect with error
        error_params = {
            "error": "invalid_request",
            "error_description": "; ".join(errors),
        }
        if state:
            error_params["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(error_params)}")

    # Truncate redirect_uri for display
    redirect_uri_display = redirect_uri
    if len(redirect_uri_display) > 50:
        redirect_uri_display = redirect_uri_display[:47] + "..."

    # Show consent page
    return templates.TemplateResponse(
        request,
        "authorize.html",
        context={
            "client_id": client_id,
            "client_name": client.client_name,
            "redirect_uri": redirect_uri,
            "redirect_uri_display": redirect_uri_display,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope,
            "state": state,
        },
    )


@app.post("/authorize/consent")
async def authorize_consent(
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    scope: str = Form("mcp"),
    state: str = Form(""),
    action: str = Form(...),
):
    """
    Handle consent form submission.

    Creates an authorization code if approved, redirects with error if denied.
    """
    if not is_oauth21_enabled():
        raise HTTPException(
            status_code=503,
            detail="OAuth 2.1 not configured.",
        )

    # Validate redirect_uri again (defense in depth)
    if not oauth_store.validate_redirect_uri(client_id, redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    # Handle state - empty string means no state
    state_value = state if state else None

    if action == "deny":
        # User denied - redirect with error
        error_params = {"error": "access_denied", "error_description": "User denied the request"}
        if state_value:
            error_params["state"] = state_value
        return RedirectResponse(f"{redirect_uri}?{urlencode(error_params)}", status_code=303)

    # User approved - create authorization code
    code = oauth_store.create_authorization_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        state=state_value,
    )

    # Redirect with code
    params = {"code": code}
    if state_value:
        params["state"] = state_value

    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=303)


@app.post("/token")
async def token_endpoint(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
):
    """
    Token Endpoint (OAuth 2.1).

    Exchanges an authorization code for an access token.
    Requires PKCE verification.
    """
    if grant_type != "authorization_code":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported grant_type: {grant_type}. Use 'authorization_code'.",
        )

    if not is_oauth21_enabled():
        raise HTTPException(
            status_code=503,
            detail="OAuth 2.1 not configured. Set CLAUDE_HUB_JWT_SECRET.",
        )

    # Validate required parameters
    if not all([code, redirect_uri, client_id, code_verifier, client_secret]):
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: code, redirect_uri, client_id, code_verifier, client_secret",
        )

    # Verify client secret FIRST (before consuming the code)
    if not oauth_store.verify_client_secret(client_id, client_secret):
        raise HTTPException(
            status_code=401,
            detail="Invalid client_secret",
        )

    # Consume the authorization code (atomic - returns None if already used)
    auth_code = oauth_store.use_authorization_code(code)
    if not auth_code:
        raise HTTPException(
            status_code=400,
            detail="Invalid, expired, or already-used authorization code",
        )

    # Validate client_id matches
    if auth_code.client_id != client_id:
        raise HTTPException(status_code=400, detail="client_id mismatch")

    # Validate redirect_uri matches exactly
    if auth_code.redirect_uri != redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri mismatch")

    # Verify PKCE (defense in depth - secret already verified)
    if not verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
        raise HTTPException(status_code=400, detail="Invalid code_verifier (PKCE verification failed)")

    # Issue access token
    token, expires_in = create_access_token(
        client_id=client_id,
        grant_type=TOKEN_TYPE_AUTHORIZATION_CODE,
        scope=auth_code.scope,
    )

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": auth_code.scope,
    }


# -----------------------------------------------------------------------------
# MCP Tool Endpoints
#
# These endpoints are exposed as MCP tools to chat Claudes.
# Authentication is handled via OAuth 2.1 Bearer tokens.
# -----------------------------------------------------------------------------


@app.post("/tools/hub_init", response_model=InitResponse, operation_id="hub_init")
async def hub_init(
    client: str = Depends(get_current_client),
) -> InitResponse:
    """
    Initialize a conversation with Main Claude.

    Call this once at the start of a conversation where you want to
    delegate work to the persistent Claude Code backend. Returns a
    conversation_id to use in subsequent hub_send calls.

    Main Claude has full tooling, stored context, and direct system access.
    Just describe what you need—implementation, deployment, research, etc.
    """
    require_auth(client)

    conversation_id = routing_table.generate_conversation_id()

    # Pre-warm a persistent Claude process so the first hub_send is fast
    chat_id = f"mcp-{conversation_id}"
    asyncio.create_task(
        chat_process_manager.get_or_spawn(chat_id, cwd=chat_process_manager.project_dir)
    )
    logger.info(f"[hub_init] Created {conversation_id}, pre-warming process {chat_id}")

    return InitResponse(
        conversation_id=conversation_id,
        status="connected",
    )


@app.post("/tools/hub_send", response_model=SendResponse, operation_id="hub_send")
async def hub_send(
    params: SendRequest,
    client: str = Depends(get_current_client),
) -> SendResponse:
    """
    Send a message to Main Claude and get a request_id back (Step 1 of 2).

    WORKFLOW: hub_send → hub_poll (BOTH steps required)
    1. Call hub_send with your message. It returns a request_id immediately.
    2. Call hub_poll with that request_id to get Main Claude's response.

    IMPORTANT: This tool only SENDS the message. It does NOT return a response.
    Calling hub_send again does NOT check status — it creates a NEW request.
    You MUST use hub_poll with the returned request_id to retrieve the response.

    Use natural language. Main Claude has full tooling and system access.

    For multi-participant conversations (multiple Claude instances or humans),
    use group_join/group_send/group_poll instead.
    """
    require_auth(client)

    import uuid
    import asyncio

    conversation_id = params.conversation_id
    request_id = f"req-{uuid.uuid4().hex[:12]}"

    # Get routing target
    target = routing_table.get_target(conversation_id)
    routing_table.record_message(conversation_id)

    # Store pending entry with timestamp for TTL cleanup
    import time as _time
    pending_responses[request_id] = {
        "status": "pending",
        "response": "",
        "conversation_id": conversation_id,
        "created_at": _time.monotonic(),
    }

    # Fire background task using persistent Claude process (warm after first message)
    async def _process():
        try:
            chat_id = f"mcp-{conversation_id}"
            logger.info(f"[hub_send] Processing {request_id} via persistent process {chat_id}")

            # Frame the message so Main Claude knows who sent it and how
            framed_message = (
                f"[Incoming request from a Chat Claude via MCP (conversation: {conversation_id})]\n\n"
                f"{params.message}"
            )

            full_text = ""
            async for event in chat_process_manager.send_message(
                chat_id, framed_message, cwd=chat_process_manager.project_dir
            ):
                etype = event.get("type")

                if etype == "stream_event":
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            full_text += delta.get("text", "")

                elif etype == "assistant" and not full_text:
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            full_text += block["text"]

                elif etype == "result":
                    if not full_text:
                        full_text = event.get("result", "")

                elif etype == "error":
                    full_text = f"[Error: {event.get('error', 'Unknown')}]"

            final = session_manager._truncate_response(full_text) if full_text else "[No response]"
            logger.info(f"[hub_send] Completed {request_id}: {len(final)} chars")

            pending_responses[request_id]["status"] = "complete"
            pending_responses[request_id]["response"] = final
        except Exception as e:
            logger.error(f"[hub_send] Error {request_id}: {e}", exc_info=True)
            pending_responses[request_id]["status"] = "error"
            pending_responses[request_id]["response"] = str(e)

    asyncio.create_task(_process())

    return SendResponse(
        conversation_id=conversation_id,
        request_id=request_id,
        status="pending",
    )


@app.post("/tools/hub_poll", response_model=PollResponse, operation_id="hub_poll")
async def hub_poll(
    params: PollRequest,
    client: str = Depends(get_current_client),
) -> PollResponse:
    """
    Get Main Claude's response to a hub_send message (Step 2 of 2).

    This is the ONLY way to retrieve Main Claude's response after hub_send.

    WORKFLOW: hub_send → hub_poll (you are here)
    1. Pass the request_id you received from hub_send.
    2. If status is "pending", Main Claude is still working — wait 3-5 seconds and poll again.
    3. If status is "complete", the response field contains Main Claude's answer.
    4. If status is "error", something went wrong — check the response field for details.

    This tool is for request-response with Main Claude. For multi-participant
    conversations, use group_poll instead.
    """
    require_auth(client)

    entry = pending_responses.get(params.request_id)
    if not entry:
        return PollResponse(
            request_id=params.request_id,
            status="error",
            response="Unknown request_id",
        )

    return PollResponse(
        request_id=params.request_id,
        status=entry["status"],
        response=entry["response"],
        conversation_id=entry["conversation_id"],
    )


class HubStatusParams(BaseModel):
    """Parameters for hub_status tool."""
    conversation_id: str | None = None


class MainSessionStatus(BaseModel):
    """Status of the main session."""
    session_id: str
    tokens_used: int
    tokens_total: int
    usage_percent: float
    tokens_remaining: int
    status: str  # "healthy", "warning", "critical"


class ObservationStats(BaseModel):
    """Statistics about the observation store."""
    total_observations: int
    by_category: dict[str, int]
    average_confidence: float


class HubStatusResponse(BaseModel):
    """Response for hub_status."""
    active_sessions: list[str]
    routes: dict[str, str]
    conversation_target: str | None = None
    main_session: MainSessionStatus | None = None
    observation_stats: ObservationStats | None = None


@app.post("/tools/hub_status", response_model=HubStatusResponse, operation_id="hub_status")
async def hub_status(
    params: HubStatusParams = HubStatusParams(),
    client: str = Depends(get_current_client),
) -> HubStatusResponse:
    """
    Check the status of claude-hub.

    Returns active sessions and routing information.
    If conversation_id is provided, shows where that conversation routes to.
    """
    require_auth(client)

    routes = {
        entry.conversation_id: entry.target
        for entry in routing_table.get_all_routes().values()
    }

    target = None
    if params.conversation_id:
        target = routing_table.get_target(params.conversation_id)

    # Get main session token status
    # Note: MAIN_SESSION_UUID is None (sentinel for --continue mode), so check
    # whether the main session exists in the session manager instead.
    main_session_status = None
    main_info = session_manager.get_session_info("main")
    if main_info is not None:
        usage_pct = session_manager.calculate_usage_percentage("main")
        status_str = "healthy"
        if usage_pct >= 95:
            status_str = "critical"
        elif usage_pct >= 80:
            status_str = "warning"

        main_session_status = MainSessionStatus(
            session_id="main",
            tokens_used=session_manager.get_token_usage("main"),
            tokens_total=session_manager.get_token_total("main"),
            usage_percent=usage_pct,
            tokens_remaining=session_manager.get_tokens_remaining("main"),
            status=status_str,
        )

    # Get observation stats
    obs_stats_raw = session_manager.get_observation_stats()
    obs_stats = ObservationStats(
        total_observations=obs_stats_raw["total_observations"],
        by_category=obs_stats_raw["by_category"],
        average_confidence=obs_stats_raw["average_confidence"],
    )

    return HubStatusResponse(
        active_sessions=session_manager.list_sessions(),
        routes=routes,
        conversation_target=target,
        main_session=main_session_status,
        observation_stats=obs_stats,
    )


# -----------------------------------------------------------------------------
# Health & Debug Endpoints
# -----------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "oauth21_enabled": is_oauth21_enabled(),
    }


@app.get("/debug/headers")
async def debug_headers(request: Request):
    """Debug: show incoming headers."""
    return {"headers": dict(request.headers)}


@app.get("/debug/routes")
async def debug_routes():
    """Debug: show all routes."""
    return routing_table.get_all_routes()


@app.get("/debug/sessions")
async def debug_sessions():
    """Debug: show all sessions."""
    return {"sessions": session_manager.list_sessions()}


@app.get("/debug/pending")
async def debug_pending():
    """Debug: show pending hub_send responses."""
    return {
        rid: {"status": entry["status"], "response_len": len(entry.get("response", "")), "conversation_id": entry.get("conversation_id")}
        for rid, entry in pending_responses.items()
    }


@app.get("/debug/memory")
async def debug_memory():
    """Debug: memory diagnostics for leak detection.

    Shows process RSS, key dict sizes, chat process count, and
    optionally tracemalloc top allocators if tracemalloc is active.
    """
    import resource
    result: dict = {}

    # Process RSS (in MB)
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    result["rss_mb"] = round(rusage.ru_maxrss / 1024, 1)  # Linux: ru_maxrss is in KB

    # Current RSS from /proc (more accurate than peak)
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    result["vm_rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmSwap:"):
                    result["vm_swap_mb"] = round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass

    # Key dict/collection sizes
    result["pending_responses_count"] = len(pending_responses)
    result["routing_table_routes"] = len(routing_table._routes)
    result["routing_table_message_counts"] = len(routing_table._message_counts)
    result["session_manager_sessions"] = len(session_manager._sessions)
    result["chat_processes"] = chat_process_manager.list_chats()
    result["chat_process_count"] = len(chat_process_manager._processes)

    # SSE session tracking (upstream mcp library)
    try:
        from fastapi_mcp import FastApiMCP
        # Access the SSE transport's session dict if available
        for attr_name in dir(mcp):
            obj = getattr(mcp, attr_name, None)
            if hasattr(obj, '_read_stream_writers'):
                result["sse_sessions"] = len(obj._read_stream_writers)
                break
    except Exception:
        pass

    # MessageRouter state (conversations, buses, queues)
    try:
        result["message_router_conversations"] = len(message_router._conversations)
        result["message_router_buses"] = len(message_router._buses)
        result["message_router_participants"] = len(message_router._participant_index)
    except Exception:
        pass

    # Per-process subscriber counts
    try:
        result["chat_process_subscribers"] = {
            cid: len(cp._subscribers) for cid, cp in chat_process_manager._processes.items()
        }
    except Exception:
        pass

    # asyncio task count
    result["asyncio_tasks"] = len(asyncio.all_tasks())

    # File descriptor count (leaked connections, pipes)
    try:
        import os as _os
        result["open_fds"] = len(_os.listdir("/proc/self/fd"))
    except OSError:
        pass

    # tracemalloc snapshot (if active)
    try:
        import tracemalloc
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            top = snapshot.statistics("lineno")[:15]
            result["tracemalloc_top"] = [
                {"file": str(s.traceback), "size_kb": round(s.size / 1024, 1), "count": s.count}
                for s in top
            ]
        else:
            result["tracemalloc"] = "not tracing (start with PYTHONTRACEMALLOC=1)"
    except ImportError:
        result["tracemalloc"] = "not available"

    return result


# -----------------------------------------------------------------------------
# Delegation & Project Management Endpoints
# -----------------------------------------------------------------------------


@app.post("/tools/create_workspace", response_model=CreateWorkspaceResponse, operation_id="create_workspace")
async def create_workspace(
    params: CreateWorkspaceParams,
    client: str = Depends(get_current_client),
) -> CreateWorkspaceResponse:
    """
    Create a workspace directory for an agent.

    Use this when spawning a delegated agent to give them isolated workspace.
    Parent agents can write to child workspaces, but not vice versa.
    """
    require_auth(client)

    # Build constraints from parameters
    constraints = ResourceConstraints(
        deadline=params.deadline,
        max_memory_mb=params.max_memory_mb,
        max_agents=params.max_agents,
        max_iterations=params.max_iterations,
    )

    workspace = workspace_manager.create_workspace(
        project=params.project,
        agent_id=params.agent_id,
        parent_id=params.parent_id,
        constraints=constraints,
    )

    # Determine agent_dir_name
    if params.parent_id:
        agent_dir_name = f"{params.parent_id}.{params.agent_id}"
    else:
        agent_dir_name = params.agent_id

    return CreateWorkspaceResponse(
        workspace_path=str(workspace),
        agent_dir_name=agent_dir_name,
    )


@app.post("/tools/list_children", response_model=ListChildrenResponse, operation_id="list_children")
async def list_children(
    params: ListChildrenParams,
    client: str = Depends(get_current_client),
) -> ListChildrenResponse:
    """List all child workspaces of a parent agent."""
    require_auth(client)

    children = workspace_manager.list_children(
        project=params.project,
        parent_agent_id=params.parent_agent_id,
    )

    return ListChildrenResponse(children=children)


@app.post("/tools/schedule_wake_at", response_model=ScheduleResponse, operation_id="schedule_wake_at")
async def schedule_wake_at(
    params: ScheduleWakeAtParams,
    client: str = Depends(get_current_client),
) -> ScheduleResponse:
    """
    Schedule a one-time wake-up.

    Use this to wake a session at a specific time with a prompt.
    """
    require_auth(client)

    constraints = {
        'deadline': params.deadline.isoformat() if params.deadline else None,
        'max_memory_mb': params.max_memory_mb,
        'max_agents': params.max_agents,
        'max_iterations': params.max_iterations,
    }

    schedule_id = scheduler.schedule_wake_at(
        session_id=params.session_id,
        time=params.time,
        prompt=params.prompt,
        constraints=constraints,
    )

    return ScheduleResponse(schedule_id=schedule_id)


@app.post("/tools/schedule_wake_every", response_model=ScheduleResponse, operation_id="schedule_wake_every")
async def schedule_wake_every(
    params: ScheduleWakeEveryParams,
    client: str = Depends(get_current_client),
) -> ScheduleResponse:
    """
    Schedule a recurring wake-up.

    Use this to periodically wake a session (e.g., check on delegated work every 4 hours).
    """
    require_auth(client)

    from datetime import timedelta

    constraints = {
        'deadline': params.deadline.isoformat() if params.deadline else None,
        'max_memory_mb': params.max_memory_mb,
        'max_agents': params.max_agents,
        'max_iterations': params.max_iterations,
    }

    schedule_id = scheduler.schedule_wake_every(
        session_id=params.session_id,
        interval=timedelta(seconds=params.interval_seconds),
        prompt=params.prompt,
        start_time=params.start_time,
        end_time=params.end_time,
        constraints=constraints,
    )

    return ScheduleResponse(schedule_id=schedule_id)


@app.post("/tools/list_schedules", response_model=ListSchedulesResponse, operation_id="list_schedules")
async def list_schedules(
    params: ListSchedulesParams = ListSchedulesParams(),
    client: str = Depends(get_current_client),
) -> ListSchedulesResponse:
    """List scheduled wake-ups."""
    require_auth(client)

    schedules = scheduler.list_schedules(session_id=params.session_id)

    return ListSchedulesResponse(
        schedules=[
            ScheduleInfo(
                schedule_id=s.schedule_id,
                session_id=s.session_id,
                next_wake=s.next_wake,
                interval_seconds=int(s.interval.total_seconds()) if s.interval else None,
                prompt=s.prompt,
                end_time=s.end_time,
                created_at=s.created_at,
            )
            for s in schedules
        ]
    )


@app.post("/tools/cancel_schedule", response_model=CancelScheduleResponse, operation_id="cancel_schedule")
async def cancel_schedule(
    params: CancelScheduleParams,
    client: str = Depends(get_current_client),
) -> CancelScheduleResponse:
    """Cancel a scheduled wake-up."""
    require_auth(client)

    success = scheduler.cancel_schedule(params.schedule_id)

    return CancelScheduleResponse(success=success)


@app.post("/tools/write_handoff", response_model=WriteHandoffResponse, operation_id="write_handoff")
async def write_handoff(
    params: WriteHandoffParams,
    client: str = Depends(get_current_client),
) -> WriteHandoffResponse:
    """
    Write a handoff document from delegatee to parent.

    Use this to summarize your work and provide status to parent agent.
    """
    require_auth(client)

    # Get workspace
    workspace = workspace_manager.get_workspace(
        project=params.project,
        agent_id=params.agent_id,
        parent_id=params.parent_id,
    )

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    handoff_path = handoff_manager.write_handoff(
        workspace=workspace,
        summary=params.summary,
        status=params.status,
        findings=params.findings,
        files_changed=params.files_changed,
        questions=params.questions,
        recommendations=params.recommendations,
    )

    return WriteHandoffResponse(handoff_path=str(handoff_path))


@app.post("/tools/read_handoff", response_model=ReadHandoffResponse, operation_id="read_handoff")
async def read_handoff(
    params: ReadHandoffParams,
    client: str = Depends(get_current_client),
) -> ReadHandoffResponse:
    """
    Read a handoff document from a delegatee.

    Use this to check status of delegated work.
    """
    require_auth(client)

    # Get workspace
    workspace = workspace_manager.get_workspace(
        project=params.project,
        agent_id=params.agent_id,
        parent_id=params.parent_id,
    )

    if not workspace:
        return ReadHandoffResponse(handoff=None, markdown=None)

    handoff = handoff_manager.read_handoff(workspace)
    markdown = handoff_manager.read_handoff_markdown(workspace)

    if not handoff:
        return ReadHandoffResponse(handoff=None, markdown=None)

    return ReadHandoffResponse(
        handoff=HandoffInfo(
            status=handoff.status,
            summary=handoff.summary,
            started_at=handoff.started_at,
            last_updated=handoff.last_updated,
            findings=handoff.findings,
            files_changed=handoff.files_changed,
            questions=handoff.questions,
            recommendations=handoff.recommendations,
        ),
        markdown=markdown,
    )


@app.post("/tools/list_handoffs", response_model=ListHandoffsResponse, operation_id="list_handoffs")
async def list_handoffs(
    params: ListHandoffsParams,
    client: str = Depends(get_current_client),
) -> ListHandoffsResponse:
    """List all handoffs in a project."""
    require_auth(client)

    project_work_dir = workspace_manager.projects_dir / params.project / "work"
    handoffs_dict = handoff_manager.list_handoffs(project_work_dir)

    return ListHandoffsResponse(
        handoffs={
            agent_dir: HandoffInfo(
                status=handoff.status,
                summary=handoff.summary,
                started_at=handoff.started_at,
                last_updated=handoff.last_updated,
                findings=handoff.findings,
                files_changed=handoff.files_changed,
                questions=handoff.questions,
                recommendations=handoff.recommendations,
            )
            for agent_dir, handoff in handoffs_dict.items()
        }
    )


# -----------------------------------------------------------------------------
# File Storage Endpoints
# -----------------------------------------------------------------------------


@app.post("/tools/files_read", response_model=FilesReadResponse, operation_id="files_read")
async def files_read(
    params: FilesReadParams,
    client: str = Depends(get_current_client),
) -> FilesReadResponse:
    """
    Read a file from persistent storage.

    Path is relative to the storage root (/storage/).
    """
    require_auth(client)

    try:
        content = storage_manager.read_file(params.path)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return FilesReadResponse(content=content, path=params.path)


@app.post("/tools/files_write", response_model=FilesWriteResponse, operation_id="files_write")
async def files_write(
    params: FilesWriteParams,
    client: str = Depends(get_current_client),
) -> FilesWriteResponse:
    """
    Write a file to persistent storage.

    Creates parent directories as needed. Path is relative to the storage root.
    """
    require_auth(client)

    try:
        abs_path = storage_manager.write_file(params.path, params.content)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FilesWriteResponse(path=abs_path, size=len(params.content.encode("utf-8")))


@app.post("/tools/files_list", response_model=FilesListResponse, operation_id="files_list")
async def files_list(
    params: FilesListParams = FilesListParams(),
    client: str = Depends(get_current_client),
) -> FilesListResponse:
    """
    List files and directories in persistent storage.

    Path is relative to the storage root. Use recursive=true to list all nested contents.
    """
    require_auth(client)

    try:
        entries = storage_manager.list_files(params.path, params.recursive)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return FilesListResponse(
        entries=[FileEntry(**e) for e in entries],
        path=params.path or "/",
    )


@app.post("/tools/files_append", response_model=FilesAppendResponse, operation_id="files_append")
async def files_append(
    params: FilesAppendParams,
    client: str = Depends(get_current_client),
) -> FilesAppendResponse:
    """
    Append content to a file in persistent storage.

    Creates the file if it doesn't exist. Path is relative to the storage root.
    """
    require_auth(client)

    try:
        abs_path = storage_manager.append_file(params.path, params.content)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FilesAppendResponse(path=abs_path)


@app.post("/tools/files_search", response_model=FilesSearchResponse, operation_id="files_search")
async def files_search(
    params: FilesSearchParams,
    client: str = Depends(get_current_client),
) -> FilesSearchResponse:
    """
    Search for text within files in persistent storage.

    Searches files matching glob_pattern (default: *.md) for the query string.
    """
    require_auth(client)

    try:
        results = storage_manager.search_files(
            params.query, params.path, params.glob_pattern
        )
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FilesSearchResponse(
        results=[SearchResult(**r) for r in results],
        query=params.query,
    )


# -----------------------------------------------------------------------------
# GitHub Endpoints
# -----------------------------------------------------------------------------


@app.post("/tools/github_read_file", response_model=GitHubFileReadResponse, operation_id="github_read_file")
async def github_read_file(
    params: GitHubFileReadParams,
    client: str = Depends(get_current_client),
) -> GitHubFileReadResponse:
    """
    Read a file from a GitHub repository.

    Fetches file content via the GitHub API using a configured PAT.
    """
    require_auth(client)

    try:
        result = github_client.read_file(
            owner=params.owner,
            repo=params.repo,
            path=params.path,
            ref=params.ref,
        )
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return GitHubFileReadResponse(
        content=result["content"],
        path=result["path"],
        sha=result["sha"],
        size=result["size"],
    )


# -----------------------------------------------------------------------------
# GitHub Webhook
# -----------------------------------------------------------------------------


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhooks/github")
async def github_webhook(request: Request):
    """
    Handle GitHub webhook events.

    Verifies the webhook signature using GITHUB_WEBHOOK_SECRET.
    On push events, auto-pulls local repo clones if they exist.
    """
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature header")

    payload = await request.body()
    if not _verify_github_signature(payload, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse event
    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return {"status": "ok", "message": f"Ignored event: {event}"}

    # Handle push event
    try:
        body = json.loads(payload)
    except Exception:
        return {"status": "ok", "message": "Could not parse payload"}

    repo_name = body.get("repository", {}).get("name", "")
    if not repo_name:
        return {"status": "ok", "message": "No repository name in payload"}

    # Check if we have a local clone
    repo_path = Path(f"/home/claude/repos/{repo_name}")
    if not repo_path.exists():
        return {"status": "ok", "message": f"No local clone: {repo_name}"}

    # Pull latest changes
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "message": f"Pulled {repo_name}",
                "output": result.stdout.strip(),
            }
        else:
            return {
                "status": "error",
                "message": f"Pull failed for {repo_name}",
                "error": result.stderr.strip(),
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Pull timed out for {repo_name}"}
    except Exception as e:
        return {"status": "error", "message": f"Error pulling {repo_name}: {e}"}


# -----------------------------------------------------------------------------
# Notification Endpoints
# -----------------------------------------------------------------------------



@app.get("/", response_class=HTMLResponse)
async def dashboard_view():
    """Serve dashboard / PWA landing page."""
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    return HTMLResponse(content=template_path.read_text())


@app.get("/notifications/view", response_class=HTMLResponse)
async def notifications_view(request: Request):
    """Serve notification viewer HTML page (TOTP protected)."""
    session_id = get_notifications_session(request)
    if session_id:
        session = totp_store.verify_session(session_id)
        if session:
            template_path = Path(__file__).parent / "templates" / "notifications.html"
            return HTMLResponse(content=template_path.read_text())

    # No valid session - check if user is enrolled
    if totp_manager.is_enrolled(TERMINAL_USER):
        return RedirectResponse("/notifications/verify", status_code=303)
    else:
        return RedirectResponse("/terminal/setup", status_code=303)


@app.get("/notifications/verify")
async def notifications_verify_get(request: Request):
    """Show TOTP verification form for notifications."""
    client_ip = get_client_ip(request)
    remaining = totp_manager.get_remaining_attempts(client_ip)

    return templates.TemplateResponse(
        request,
        "notifications_verify.html",
        context={
            "remaining_attempts": remaining,
        },
    )


@app.post("/notifications/verify")
async def notifications_verify_post(request: Request, code: str = Form(...)):
    """Verify TOTP code and create notifications session."""
    client_ip = get_client_ip(request)

    if not totp_manager.verify_code(TERMINAL_USER, code, client_ip):
        remaining = totp_manager.get_remaining_attempts(client_ip)
        error = "Invalid code. Please try again."
        if remaining == 0:
            error = "Too many attempts. Please wait a minute."

        return templates.TemplateResponse(
            request,
            "notifications_verify.html",
            context={
                "error": error,
                "remaining_attempts": remaining,
            },
        )

    session = totp_store.create_session(TERMINAL_USER)

    response = RedirectResponse("/notifications/view", status_code=303)
    response.set_cookie(
        key=NOTIFICATIONS_SESSION_COOKIE,
        value=session.session_id,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/notifications",
    )
    return response


@app.post("/notifications/logout")
async def notifications_logout(request: Request):
    """Log out of notifications session."""
    session_id = get_notifications_session(request)
    if session_id:
        totp_store.delete_session(session_id)

    response = RedirectResponse("/notifications/verify", status_code=303)
    response.delete_cookie(
        key=NOTIFICATIONS_SESSION_COOKIE,
        path="/notifications",
    )
    return response


class ListNotificationsParams(BaseModel):
    """Parameters for listing notifications."""
    unread_only: bool = False
    limit: int = 100
    project: Optional[str] = None


class ListNotificationsResponse(BaseModel):
    """Response for listing notifications."""
    notifications: List[Dict]
    unread_count: int
    total_count: int


@app.get("/notifications/api/list", response_model=ListNotificationsResponse)
async def list_notifications_api(
    request: Request,
    unread_only: bool = False,
    limit: int = 100,
    project: Optional[str] = None,
):
    """List notifications (API endpoint for web UI, TOTP protected)."""
    session_id = get_notifications_session(request)
    if not session_id or not totp_store.verify_session(session_id):
        raise HTTPException(status_code=401, detail="Authentication required")

    notifications = notification_manager.list_notifications(
        unread_only=unread_only,
        limit=limit,
        project=project,
    )

    unread_count = notification_manager.count_unread(project=project)

    return ListNotificationsResponse(
        notifications=[
            {
                "id": n.id,
                "timestamp": n.timestamp.isoformat(),
                "priority": n.priority,
                "message": n.message,
                "project": n.project,
                "details": n.details,
                "read": n.read,
            }
            for n in notifications
        ],
        unread_count=unread_count,
        total_count=len(notifications),
    )


class MarkReadParams(BaseModel):
    """Parameters for marking notification as read."""
    notification_id: int


@app.post("/notifications/api/mark-read")
async def mark_read_api(request: Request, params: MarkReadParams):
    """Mark notification as read (TOTP protected)."""
    session_id = get_notifications_session(request)
    if not session_id or not totp_store.verify_session(session_id):
        raise HTTPException(status_code=401, detail="Authentication required")

    success = notification_manager.mark_read(params.notification_id)
    return {"success": success}


class NotifyParams(BaseModel):
    """Parameters for creating a notification."""
    message: str
    priority: str = "info"
    project: Optional[str] = None
    details: Optional[dict] = None


class NotifyResponse(BaseModel):
    """Response from creating notification."""
    notification_id: int


@app.post("/tools/notify", response_model=NotifyResponse, operation_id="notify")
async def notify_tool(
    params: NotifyParams,
    client: str = Depends(get_current_client),
) -> NotifyResponse:
    """
    Send a notification to the human user (fire-and-forget).

    Notifications appear in the web UI dashboard. Use this to alert the user
    about completed tasks, errors, or anything they should see.

    This does NOT communicate with Main Claude — use hub_send for that.
    This does NOT wait for a response — it's one-way to the human user.
    """
    require_auth(client)

    notification_id = notification_manager.notify(
        message=params.message,
        priority=params.priority,
        project=params.project,
        details=params.details,
    )

    return NotifyResponse(notification_id=notification_id)


# -----------------------------------------------------------------------------
# Web Chat Interface
# -----------------------------------------------------------------------------


@app.get("/chat", response_class=HTMLResponse)
async def chat_view():
    """Serve chat interface HTML page."""
    template_path = Path(__file__).parent / "templates" / "chat.html"
    return HTMLResponse(content=template_path.read_text())


@app.post("/chat/verify")
async def chat_verify(request: Request):
    """Verify chat access - auth handled by nginx basic auth."""
    # Token auth removed - nginx basic auth handles security
    return {"status": "ok"}


class ChatSendParams(BaseModel):
    """Parameters for sending a chat message."""
    message: str


class ChatSendResponse(BaseModel):
    """Response from sending a chat message."""
    response: str
    status: str


@app.post("/chat/send", response_model=ChatSendResponse)
async def chat_send(
    params: ChatSendParams,
    request: Request,
):
    """
    Send a message to Main Claude via web chat.

    Auth: nginx basic auth only (enforced at proxy layer).
    This endpoint is excluded from MCP tools so OAuth is not needed.
    """

    # Prepend context so Main Claude knows this is from web chat
    contextualized_message = f"[Web Chat] {params.message}"

    try:
        # Send to the main session (use "main" to trigger get_or_create)
        response = session_manager.send_message(
            "main",
            contextualized_message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatSendResponse(
        response=response,
        status="ok"
    )


def _append_chat_history(summary: dict) -> None:
    """Append a chat session summary to the daily history file.

    Creates thoughts/chat-history/ lazily. Daily files are human-readable markdown.
    """
    try:
        history_dir = PROJECT_DIR / "thoughts" / "chat-history"
        history_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        history_file = history_dir / f"{today}.md"

        duration_s = summary.get("duration_seconds", 0)
        if duration_s >= 3600:
            duration_str = f"{duration_s // 3600}h {(duration_s % 3600) // 60}m"
        elif duration_s >= 60:
            duration_str = f"{duration_s // 60}m {duration_s % 60}s"
        else:
            duration_str = f"{duration_s}s"

        entry = (
            f"\n### {summary.get('ended_at', 'unknown')} UTC\n"
            f"- **Chat ID:** {summary.get('chat_id', 'unknown')}\n"
            f"- **Session:** {summary.get('session_id', 'unknown')}\n"
            f"- **Messages:** {summary.get('message_count', 0)}\n"
            f"- **Duration:** {duration_str}\n"
        )

        # Create file with header if new
        if not history_file.exists():
            header = f"# Chat History — {today}\n"
            history_file.write_text(header + entry, encoding="utf-8")
        else:
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(entry)
    except Exception as e:
        print(f"[ChatHistory] Warning: failed to log history: {e}")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """Streaming chat via persistent Claude Code process.

    Protocol:
        Client sends: {"type": "message", "text": "...", "chat_id": "..."}
        Server sends: {"type": "text", "text": "..."}         — streamed text chunk
                      {"type": "result", "text": "...", "duration_ms": N}  — turn complete
                      {"type": "status", "status": "..."}     — status updates
                      {"type": "error", "error": "..."}       — error
    """
    await websocket.accept()
    chat_id = "default"

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                text = data.get("text", "").strip()
                chat_id = data.get("chat_id", chat_id)

                if not text:
                    await websocket.send_json({"type": "error", "error": "Empty message"})
                    continue

                await websocket.send_json({"type": "status", "status": "thinking"})

                # Stream response from Claude process
                full_text = ""
                async for event in chat_process_manager.send_message(chat_id, text):
                    etype = event.get("type")

                    if etype == "stream_event":
                        # Token-level streaming from --include-partial-messages
                        inner = event.get("event", {})
                        if inner.get("type") == "content_block_delta":
                            delta = inner.get("delta", {})
                            if delta.get("type") == "text_delta":
                                chunk = delta.get("text", "")
                                if chunk:
                                    full_text += chunk
                                    await websocket.send_json({
                                        "type": "text",
                                        "text": chunk,
                                    })

                    elif etype == "assistant":
                        # Complete message (arrives after all deltas)
                        # Only use if we didn't get streaming deltas
                        if not full_text:
                            msg = event.get("message", {})
                            for block in msg.get("content", []):
                                if block.get("type") == "text":
                                    chunk = block["text"]
                                    full_text += chunk
                                    await websocket.send_json({
                                        "type": "text",
                                        "text": chunk,
                                    })

                    elif etype == "result":
                        # Parse observation markers from chat output (best-effort)
                        try:
                            obs_store = ObservationStore(dsn=os.environ.get("CLAUDE_HUB_PG_DSN", ""))
                            recorded = parse_observation_markers(
                                full_text, obs_store, session_id=f"chat-{chat_id}"
                            )
                            if recorded:
                                print(f"[ChatObs] Recorded {len(recorded)} observations from chat-{chat_id}")
                        except Exception as e:
                            print(f"[ChatObs] Warning: observation parsing failed: {e}")

                        result_text = event.get("result", full_text)
                        await websocket.send_json({
                            "type": "result",
                            "text": result_text,
                            "duration_ms": event.get("duration_ms", 0),
                            "session_id": event.get("session_id", ""),
                        })

                    elif etype == "error":
                        await websocket.send_json({
                            "type": "error",
                            "error": event.get("error", "Unknown error"),
                        })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        # Log chat session history on disconnect
        summary = chat_process_manager.get_chat_summary(chat_id)
        if summary and summary.get("message_count", 0) > 0:
            _append_chat_history(summary)
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Web Terminal Interface (TOTP Protected)
# -----------------------------------------------------------------------------

# Default user for TOTP (basic auth user is trusted)
TERMINAL_USER = os.environ.get("HUB_TERMINAL_USER", "admin")
TERMINAL_SESSION_COOKIE = "terminal_session"
NOTIFICATIONS_SESSION_COOKIE = "notifications_session"


def get_client_ip(request: Request) -> str:
    """Get client IP from request, handling proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def get_terminal_session(request: Request) -> Optional[str]:
    """Get terminal session ID from cookie."""
    return request.cookies.get(TERMINAL_SESSION_COOKIE)


def get_notifications_session(request: Request) -> Optional[str]:
    """Get notifications session ID from cookie."""
    return request.cookies.get(NOTIFICATIONS_SESSION_COOKIE)


@app.get("/terminal")
async def terminal_main(request: Request):
    """
    Main terminal entry point.

    Checks for valid TOTP session, redirects to verify or setup if needed.
    """
    session_id = get_terminal_session(request)

    # Check if session is valid
    if session_id:
        session = totp_store.verify_session(session_id)
        if session:
            # Valid session - serve terminal
            return templates.TemplateResponse(
                request,
                "terminal.html",
            )

    # No valid session - check if user is enrolled
    if totp_manager.is_enrolled(TERMINAL_USER):
        # Enrolled - redirect to verify
        return RedirectResponse("/terminal/verify", status_code=303)
    else:
        # Not enrolled - redirect to setup
        return RedirectResponse("/terminal/setup", status_code=303)


@app.get("/terminal/verify")
async def terminal_verify_get(request: Request):
    """Show TOTP verification form."""
    client_ip = get_client_ip(request)
    remaining = totp_manager.get_remaining_attempts(client_ip)

    return templates.TemplateResponse(
        request,
        "terminal_verify.html",
        context={
            "remaining_attempts": remaining,
        },
    )


@app.post("/terminal/verify")
async def terminal_verify_post(request: Request, code: str = Form(...)):
    """Verify TOTP code and create session."""
    client_ip = get_client_ip(request)

    # Verify code
    if not totp_manager.verify_code(TERMINAL_USER, code, client_ip):
        remaining = totp_manager.get_remaining_attempts(client_ip)
        error = "Invalid code. Please try again."
        if remaining == 0:
            error = "Too many attempts. Please wait a minute."

        return templates.TemplateResponse(
            request,
            "terminal_verify.html",
            context={
                "error": error,
                "remaining_attempts": remaining,
            },
        )

    # Create session
    session = totp_store.create_session(TERMINAL_USER)

    # Redirect to terminal with session cookie
    response = RedirectResponse("/terminal", status_code=303)
    response.set_cookie(
        key=TERMINAL_SESSION_COOKIE,
        value=session.session_id,
        max_age=8 * 60 * 60,  # 8 hours
        httponly=True,
        secure=True,
        samesite="strict",
        path="/terminal",
    )
    return response


@app.get("/terminal/setup")
async def terminal_setup_get(request: Request):
    """Show TOTP setup page with QR code."""
    # Generate new secret
    secret, provisioning_uri = totp_manager.generate_secret(TERMINAL_USER)
    qr_data_uri = totp_manager.generate_qr_data_uri(provisioning_uri)

    return templates.TemplateResponse(
        request,
        "terminal_setup.html",
        context={
            "secret": secret,
            "qr_data_uri": qr_data_uri,
        },
    )


@app.post("/terminal/setup")
async def terminal_setup_post(
    request: Request,
    secret: str = Form(...),
    code: str = Form(...),
):
    """Complete TOTP enrollment."""
    client_ip = get_client_ip(request)

    # Verify test code and enroll
    if not totp_manager.enroll_user(TERMINAL_USER, secret, code, client_ip):
        # Failed - show setup again with error
        provisioning_uri = f"otpauth://totp/{TERMINAL_USER}?secret={secret}&issuer=claude-hub"
        qr_data_uri = totp_manager.generate_qr_data_uri(provisioning_uri)

        return templates.TemplateResponse(
            request,
            "terminal_setup.html",
            context={
                "secret": secret,
                "qr_data_uri": qr_data_uri,
                "error": "Invalid code. Please try again with a fresh code.",
            },
        )

    # Enrollment successful - create session and redirect
    session = totp_store.create_session(TERMINAL_USER)

    response = RedirectResponse("/terminal", status_code=303)
    response.set_cookie(
        key=TERMINAL_SESSION_COOKIE,
        value=session.session_id,
        max_age=8 * 60 * 60,  # 8 hours
        httponly=True,
        secure=True,
        samesite="strict",
        path="/terminal",
    )
    return response


@app.post("/terminal/logout")
async def terminal_logout(request: Request):
    """Log out of terminal session."""
    session_id = get_terminal_session(request)
    if session_id:
        totp_store.delete_session(session_id)

    response = RedirectResponse("/terminal/verify", status_code=303)
    response.delete_cookie(
        key=TERMINAL_SESSION_COOKIE,
        path="/terminal",
    )
    return response


@app.head("/terminal/ping")
async def terminal_ping(request: Request):
    """Check if terminal session is still valid."""
    session_id = get_terminal_session(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="No session")

    session = totp_store.verify_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")

    return Response(status_code=200)


# -----------------------------------------------------------------------------
# Group Chat Interface
# -----------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """Request body for creating a group conversation."""
    conversation_id: Optional[str] = None


class AddClaudeRequest(BaseModel):
    """Request body for adding a Claude process to a conversation."""
    name: str = "Claude"
    role: str = "chat"  # "chat" or "main" — main gets full CLAUDE.md + context access


class AddCodexRequest(BaseModel):
    """Request body for adding a codex CLI participant to a conversation."""
    name: str = "Codex"
    # model=None lets the codex CLI use its configured default — picks up
    # newer models (e.g. gpt-5.5 → gpt-5.6) without a code change. Pass an
    # explicit id to pin a specific version.
    model: Optional[str] = None
    thread_id: Optional[str] = None


class AddGeminiRequest(BaseModel):
    """Request body for adding a gemini CLI participant to a conversation."""
    name: str = "Gemini"
    model: Optional[str] = None
    session_id: Optional[str] = None


@app.get("/group", response_class=HTMLResponse, operation_id="group_chat_view")
async def group_chat_view():
    """Serve the group chat HTML page."""
    template_path = Path(__file__).parent / "templates" / "group_chat.html"
    return HTMLResponse(content=template_path.read_text())


@app.get("/api/conversations", operation_id="list_conversations")
async def list_conversations():
    """List all active group conversations."""
    return {"conversations": message_router.list_conversations()}


@app.post("/api/conversations", operation_id="create_conversation")
async def create_conversation(params: CreateConversationRequest = CreateConversationRequest()):
    """Create a new group conversation."""
    conv = message_router.create_conversation(params.conversation_id)
    return conv.to_dict()


@app.delete("/api/conversations/{conversation_id}", operation_id="delete_conversation")
async def delete_conversation(conversation_id: str):
    """Stop and clean up a conversation, killing all Claude processes."""
    conv = message_router.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await message_router.cleanup_conversation(conversation_id)
    return {"status": "stopped", "conversation_id": conversation_id}


@app.get("/api/conversations/{conversation_id}/messages", operation_id="get_conversation_messages")
async def get_conversation_messages(conversation_id: str, limit: int = 200):
    """Get messages for a conversation from persistent storage."""
    if not message_router._store:
        raise HTTPException(status_code=503, detail="Conversation store not available")
    messages = message_router._store.get_messages(conversation_id, limit)
    return {"conversation_id": conversation_id, "messages": messages}


@app.post("/api/conversations/{conversation_id}/add_claude", operation_id="add_claude_to_conversation")
async def add_claude_to_conversation(conversation_id: str, params: AddClaudeRequest = AddClaudeRequest()):
    """Add a Claude process participant to a group conversation."""
    conv = message_router.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    participant = await message_router.add_claude_process(conversation_id, params.name, role=params.role)
    return participant.to_dict()


@app.post("/api/conversations/{conversation_id}/add_codex", operation_id="add_codex_to_conversation")
async def add_codex_to_conversation(conversation_id: str, params: AddCodexRequest = AddCodexRequest()):
    """Add a codex CLI participant to a group conversation.

    Each turn spawns a fresh `codex exec` (or `codex exec resume`) subprocess.
    State (the codex thread id) is held in the CodexChat instance and persists
    for the lifetime of the conversation. Pass thread_id to resume an existing
    codex thread instead of starting fresh.
    """
    conv = message_router.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    chat = CodexChat(model=params.model, thread_id=params.thread_id, cwd=str(SOURCE_DIR))
    participant = await message_router.add_cli_chat(conversation_id, params.name, chat)
    return participant.to_dict()


@app.post("/api/conversations/{conversation_id}/add_gemini", operation_id="add_gemini_to_conversation")
async def add_gemini_to_conversation(conversation_id: str, params: AddGeminiRequest = AddGeminiRequest()):
    """Add a gemini CLI participant to a group conversation.

    Each turn spawns a fresh `gemini` subprocess (with `--resume <session_id>`
    on every turn after the first). Pass session_id to resume an existing
    gemini session instead of starting fresh.
    """
    conv = message_router.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    chat = GeminiChat(model=params.model, session_id=params.session_id, cwd=str(SOURCE_DIR))
    participant = await message_router.add_cli_chat(conversation_id, params.name, chat)
    return participant.to_dict()


@app.websocket("/ws/group/{conversation_id}")
async def websocket_group_chat(websocket: WebSocket, conversation_id: str):
    """WebSocket endpoint for group conversations.

    Protocol:
        Client sends:
            {"type": "message", "text": "..."}               -- chat message
            {"type": "add_claude", "name": "Claude"}          -- add Claude participant
            {"type": "add_codex", "name": "Codex"}            -- add codex CLI participant (model optional, defaults to harness default)
            {"type": "add_gemini", "name": "Gemini"}          -- add gemini CLI participant (model optional, defaults to harness default)
            {"type": "ping"}                                  -- keepalive

        Server sends:
            {"type": "group_message", ...}                    -- message from any participant
            {"type": "stream_chunk", "sender_id", "text"}     -- Claude streaming token
            {"type": "stream_end", "sender_id"}               -- Claude finished
            {"type": "participant_joined", ...}               -- someone joined
            {"type": "participant_left", ...}                 -- someone left
            {"type": "catch_up", "messages": [...]}           -- recent history on connect
            {"type": "pong"}                                  -- keepalive reply
            {"type": "keepalive"}                             -- periodic keepalive
            {"type": "error", "error": "..."}                 -- error
    """
    await websocket.accept()

    # Get human participant name from query param, default "User"
    name = websocket.query_params.get("name", "User")

    # Get or create the conversation
    conv = message_router.get_or_create_conversation(conversation_id)

    # Ensure the bus is started
    await message_router._ensure_bus_started(conversation_id)

    # Add the human participant (also subscribes to bus outbound queue)
    participant = message_router.add_human(conversation_id, name, websocket)
    participant_id = participant.participant_id

    # Get the outbound queue for this participant
    outbound = message_router.subscribe(participant_id)

    try:
        # Send catch-up: last 50 messages from conversation log
        if conv.message_log:
            catch_up_messages = [m.to_dict() for m in conv.message_log[-50:]]
            await websocket.send_json({
                "type": "catch_up",
                "messages": catch_up_messages,
            })

        # Broadcast join notification to all participants via bus
        join_msg = GroupMessage(
            id=make_message_id(),
            conversation_id=conversation_id,
            sender_id=participant_id,
            sender_name=name,
            content=f"{name} joined the conversation",
            message_type=MessageType.JOIN,
        )
        conv.append_message(join_msg)

        join_event = {
            "type": "participant_joined",
            "participant": participant.to_dict(),
            "message": join_msg.to_dict(),
        }
        bus = message_router._buses.get(conversation_id)
        if bus:
            bus._broadcast_to_outbound(join_event)

        # Reader: WS -> bus
        async def ws_reader():
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "message")

                if msg_type == "message":
                    text = data.get("text", "").strip()
                    if not text:
                        await outbound.put({"type": "error", "error": "Empty message"})
                        continue
                    await message_router.post_message(participant_id, text)

                elif msg_type == "add_claude":
                    claude_name = data.get("name", "Claude")
                    claude_role = data.get("role", "chat")
                    try:
                        claude_participant = await message_router.add_claude_process(
                            conversation_id, claude_name, role=claude_role
                        )

                        # Broadcast participant_joined
                        claude_join_msg = GroupMessage(
                            id=make_message_id(),
                            conversation_id=conversation_id,
                            sender_id=claude_participant.participant_id,
                            sender_name=claude_name,
                            content=f"{claude_name} joined the conversation",
                            message_type=MessageType.JOIN,
                        )
                        conv.append_message(claude_join_msg)

                        claude_join_event = {
                            "type": "participant_joined",
                            "participant": claude_participant.to_dict(),
                            "message": claude_join_msg.to_dict(),
                        }
                        current_bus = message_router._buses.get(conversation_id)
                        if current_bus:
                            current_bus._broadcast_to_outbound(claude_join_event)
                    except Exception as e:
                        await outbound.put({
                            "type": "error",
                            "error": f"Failed to add Claude: {e}",
                        })

                elif msg_type in ("add_codex", "add_gemini"):
                    kind = "codex" if msg_type == "add_codex" else "gemini"
                    default_name = "Codex" if kind == "codex" else "Gemini"
                    cli_name = data.get("name", default_name)
                    try:
                        if kind == "codex":
                            chat = CodexChat(
                                model=data.get("model"),  # None = harness default
                                thread_id=data.get("thread_id"),
                                cwd=str(SOURCE_DIR),
                            )
                        else:
                            chat = GeminiChat(
                                model=data.get("model"),  # None = harness default
                                session_id=data.get("session_id"),
                                cwd=str(SOURCE_DIR),
                            )
                        cli_participant = await message_router.add_cli_chat(
                            conversation_id, cli_name, chat
                        )

                        cli_join_msg = GroupMessage(
                            id=make_message_id(),
                            conversation_id=conversation_id,
                            sender_id=cli_participant.participant_id,
                            sender_name=cli_name,
                            content=f"{cli_name} joined the conversation",
                            message_type=MessageType.JOIN,
                        )
                        conv.append_message(cli_join_msg)

                        cli_join_event = {
                            "type": "participant_joined",
                            "participant": cli_participant.to_dict(),
                            "message": cli_join_msg.to_dict(),
                        }
                        current_bus = message_router._buses.get(conversation_id)
                        if current_bus:
                            current_bus._broadcast_to_outbound(cli_join_event)
                    except Exception as e:
                        await outbound.put({
                            "type": "error",
                            "error": f"Failed to add {kind}: {e}",
                        })

                elif msg_type == "ping":
                    await outbound.put({"type": "pong"})

        # Writer: outbound queue -> WS (with keepalive on timeout)
        async def ws_writer():
            while True:
                try:
                    event = await asyncio.wait_for(outbound.get(), timeout=15)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "keepalive"})

        await asyncio.gather(
            asyncio.create_task(ws_reader()),
            asyncio.create_task(ws_writer()),
        )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        # Remove participant and broadcast departure
        removed = message_router.remove_participant(participant_id)
        if removed:
            leave_msg = GroupMessage(
                id=make_message_id(),
                conversation_id=conversation_id,
                sender_id=participant_id,
                sender_name=name,
                content=f"{name} left the conversation",
                message_type=MessageType.LEAVE,
            )
            conv.append_message(leave_msg)

            leave_event = {
                "type": "participant_left",
                "participant_id": participant_id,
                "message": leave_msg.to_dict(),
            }
            current_bus = message_router._buses.get(conversation_id)
            if current_bus:
                current_bus._broadcast_to_outbound(leave_event)

            # Auto-stop when last human leaves
            humans = conv.get_participants_of_type(ParticipantType.HUMAN_WS)
            if not humans:
                logger.info("Last human left conversation %s — stopping", conversation_id)
                await message_router.cleanup_conversation(conversation_id)


# --- Group Chat MCP Tool Endpoints ---

@app.post("/tools/group_join", response_model=GroupJoinResponse, operation_id="group_join")
async def group_join(
    params: GroupJoinRequest,
    client: str = Depends(get_current_client),
) -> GroupJoinResponse:
    """
    Join a group conversation as an MCP client.

    Creates the conversation if it doesn't exist. Returns participant list
    and recent message history for context. Use group_send to send messages
    and group_poll to receive them.
    """
    require_auth(client)

    conv = message_router.get_or_create_conversation(params.conversation_id)
    participant = message_router.add_mcp_client(params.conversation_id, params.name)

    # Build catch-up history (last 50 messages)
    recent = [m.to_dict() for m in conv.message_log[-50:]]

    # Broadcast join to WS participants and other MCP clients
    join_msg = GroupMessage(
        id=make_message_id(),
        conversation_id=params.conversation_id,
        sender_id=participant.participant_id,
        sender_name=params.name,
        content=f"{params.name} joined the conversation",
        message_type=MessageType.JOIN,
    )
    conv.append_message(join_msg)

    join_event = {
        "type": "participant_joined",
        "participant": participant.to_dict(),
        "message": join_msg.to_dict(),
    }
    # Ensure bus is started, then broadcast via bus
    await message_router._ensure_bus_started(params.conversation_id)
    bus = message_router._buses.get(params.conversation_id)
    if bus:
        bus._broadcast_to_outbound(join_event)

    return GroupJoinResponse(
        conversation_id=params.conversation_id,
        participant_id=participant.participant_id,
        participants=[p.to_dict() for p in conv.participants.values()],
        recent_messages=recent,
    )


@app.post("/tools/group_send", response_model=GroupSendResponse, operation_id="group_send")
async def group_send(
    params: GroupSendRequest,
    client: str = Depends(get_current_client),
) -> GroupSendResponse:
    """
    Send a message to a group conversation (multi-participant).

    Use this for conversations involving multiple participants (Claude instances,
    humans, or both). Messages are delivered to ALL participants asynchronously.

    WORKFLOW: group_join → group_send/group_poll (ongoing)
    1. Join a conversation with group_join to get a participant_id.
    2. Send messages with group_send.
    3. Receive messages from others with group_poll.

    For simple request-response with Main Claude (just you asking a question
    and getting an answer), use hub_send/hub_poll instead — it's simpler.
    """
    require_auth(client)

    # Validate participant membership
    conv_id = message_router._participant_index.get(params.participant_id)
    if conv_id is None or conv_id != params.conversation_id:
        raise HTTPException(
            status_code=404,
            detail=f"Participant {params.participant_id} not in conversation {params.conversation_id}",
        )

    # post_message is non-blocking — it puts in inbox and returns immediately.
    # The bus dispatcher delivers to all participants asynchronously.
    await message_router.post_message(
        params.participant_id, params.message, recipient_id=params.recipient_id
    )

    return GroupSendResponse(status="sent", message_id=make_message_id())


@app.post("/tools/group_poll", response_model=GroupPollResponse, operation_id="group_poll")
async def group_poll(
    params: GroupPollRequest,
    client: str = Depends(get_current_client),
) -> GroupPollResponse:
    """
    Receive new messages from a group conversation.

    Returns all pending messages since your last poll — chat messages from
    other participants, Claude responses, and join/leave notifications.
    Call periodically (every 2-3 seconds) to stay up to date.

    This is for multi-participant group conversations (group_join/group_send).
    For simple request-response with Main Claude, use hub_poll instead.
    """
    require_auth(client)

    conv_id = message_router._participant_index.get(params.participant_id)
    if conv_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Participant {params.participant_id} not found",
        )

    conv = message_router.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation {conv_id} not found",
        )

    participant = conv.participants.get(params.participant_id)
    if participant is None or participant.poll_queue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Participant {params.participant_id} has no poll queue",
        )

    # Drain the queue
    messages = []
    while True:
        try:
            msg = participant.poll_queue.get_nowait()
            messages.append(msg)
        except asyncio.QueueEmpty:
            break

    return GroupPollResponse(messages=messages)


@app.post("/tools/group_leave", response_model=GroupLeaveResponse, operation_id="group_leave")
async def group_leave(
    params: GroupLeaveRequest,
    client: str = Depends(get_current_client),
) -> GroupLeaveResponse:
    """
    Leave a group conversation.

    Removes you from the conversation. Other participants will be
    notified of your departure. After leaving, group_poll will no
    longer return messages.
    """
    require_auth(client)

    conv = message_router.get_conversation(params.conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation {params.conversation_id} not found",
        )

    removed = message_router.remove_participant(params.participant_id)
    if removed is None:
        raise HTTPException(
            status_code=404,
            detail=f"Participant {params.participant_id} not found in conversation",
        )

    # Broadcast departure
    leave_msg = GroupMessage(
        id=make_message_id(),
        conversation_id=params.conversation_id,
        sender_id=params.participant_id,
        sender_name=removed.name,
        content=f"{removed.name} left the conversation",
        message_type=MessageType.LEAVE,
    )
    conv.append_message(leave_msg)

    leave_event = {
        "type": "participant_left",
        "participant_id": params.participant_id,
        "message": leave_msg.to_dict(),
    }
    bus = message_router._buses.get(params.conversation_id)
    if bus:
        bus._broadcast_to_outbound(leave_event)

    return GroupLeaveResponse(status="left")


# -----------------------------------------------------------------------------
# Artifact Store Endpoints
# -----------------------------------------------------------------------------


@app.post("/tools/artifact_store", response_model=ArtifactStoreResponse, operation_id="artifact_store")
async def tool_artifact_store(
    request: ArtifactStoreRequest,
    client: str = Depends(get_current_client),
) -> ArtifactStoreResponse:
    """Store a new artifact with content, type, tags, and metadata. Returns artifact ID and embedding status."""
    pool = require_pg_pool()
    try:
        result = await artifact_store_module.store_artifact(
            pool,
            content=request.content,
            artifact_type=request.artifact_type,
            tags=request.tags,
            source_ref=request.source_ref,
            derives_from=request.derives_from,
            sensitive=request.sensitive,
            metadata=request.metadata,
        )
        return ArtifactStoreResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tools/artifact_get", response_model=ArtifactGetResponse, operation_id="artifact_get")
async def tool_artifact_get(
    request: ArtifactGetRequest,
    client: str = Depends(get_current_client),
) -> ArtifactGetResponse:
    """Retrieve an artifact by ID, optionally including version history and feedback."""
    pool = require_pg_pool()
    # Resolve backward-compatible alias: include_outcomes overrides include_feedback if set
    include_feedback = request.include_feedback
    if request.include_outcomes is not None:
        include_feedback = request.include_outcomes
    result = await artifact_store_module.get_artifact(
        pool,
        artifact_id=request.id,
        include_versions=request.include_versions,
        include_feedback=include_feedback,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactGetResponse(**result)


@app.post("/tools/artifact_search", response_model=ArtifactSearchResponse, operation_id="artifact_search")
async def tool_artifact_search(
    request: ArtifactSearchRequest,
    client: str = Depends(get_current_client),
) -> ArtifactSearchResponse:
    """Semantic search across artifacts using natural language. Supports filters by type, tags, date, and confidence."""
    pool = require_pg_pool()
    try:
        results = await artifact_store_module.search_artifacts(
            pool,
            query=request.query,
            artifact_type=request.artifact_type,
            tags=request.tags,
            date_from=request.date_from,
            date_to=request.date_to,
            include_archived=request.include_archived,
            confidence=request.confidence,
            limit=request.limit,
        )
        return ArtifactSearchResponse(results=results)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/artifact_list", response_model=ArtifactListResponse, operation_id="artifact_list")
async def tool_artifact_list(
    request: ArtifactListRequest,
    client: str = Depends(get_current_client),
) -> ArtifactListResponse:
    """List artifacts with optional filters and pagination. No semantic search — use artifact_search for that."""
    pool = require_pg_pool()
    result = await artifact_store_module.list_artifacts(
        pool,
        artifact_type=request.artifact_type,
        tags=request.tags,
        include_archived=request.include_archived,
        limit=request.limit,
        offset=request.offset,
    )
    return ArtifactListResponse(**result)


@app.post("/tools/artifact_archive", response_model=ArtifactArchiveResponse, operation_id="artifact_archive")
async def tool_artifact_archive(
    request: ArtifactArchiveRequest,
    client: str = Depends(get_current_client),
) -> ArtifactArchiveResponse:
    """Archive an artifact — excludes from search but preserves for retrieval by ID."""
    pool = require_pg_pool()
    found = await artifact_store_module.archive_artifact(pool, artifact_id=request.id)
    if not found:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactArchiveResponse(success=True)


@app.post("/tools/artifact_update", response_model=ArtifactUpdateResponse, operation_id="artifact_update")
async def tool_artifact_update(
    request: ArtifactUpdateRequest,
    client: str = Depends(get_current_client),
) -> ArtifactUpdateResponse:
    """Create a new version of an artifact with updated content. Previous versions are preserved."""
    pool = require_pg_pool()
    try:
        result = await artifact_store_module.update_artifact(
            pool,
            artifact_id=request.id,
            content=request.content,
            metadata=request.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactUpdateResponse(**result)


@app.post("/tools/artifact_update_metadata", response_model=ArtifactUpdateMetadataResponse, operation_id="artifact_update_metadata")
async def tool_artifact_update_metadata(
    request: ArtifactUpdateMetadataRequest,
    client: str = Depends(get_current_client),
) -> ArtifactUpdateMetadataResponse:
    """Update an artifact's metadata, tags, or archived status without creating a new version."""
    pool = require_pg_pool()
    found = await artifact_store_module.update_metadata(
        pool,
        artifact_id=request.id,
        metadata=request.metadata,
        tags=request.tags,
        archived=request.archived,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactUpdateMetadataResponse(success=True)


@app.post("/tools/artifact_export", response_model=ArtifactExportResponse, operation_id="artifact_export")
async def tool_artifact_export(
    request: ArtifactExportRequest,
    client: str = Depends(get_current_client),
) -> ArtifactExportResponse:
    """Export artifacts to a backup file (JSON or pg_dump format)."""
    pool = require_pg_pool()
    result = await artifact_store_module.export_artifacts(
        pool,
        format=request.format,
        artifact_type=request.artifact_type,
    )
    return ArtifactExportResponse(**result)


@app.post("/tools/artifact_import", response_model=ArtifactImportResponse, operation_id="artifact_import")
async def tool_artifact_import(
    request: ArtifactImportRequest,
    client: str = Depends(get_current_client),
) -> ArtifactImportResponse:
    """Import artifacts from a JSON export file. Deduplicates by content hash."""
    pool = require_pg_pool()
    try:
        result = await artifact_store_module.import_artifacts(
            pool,
            path=request.path,
            dry_run=request.dry_run,
        )
        return ArtifactImportResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Import file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tools/artifact_feedback", response_model=ArtifactFeedbackResponse, operation_id="artifact_feedback")
async def tool_artifact_feedback(
    request: ArtifactFeedbackRequest,
    client: str = Depends(get_current_client),
) -> ArtifactFeedbackResponse:
    """Record usage feedback on an artifact. Updates the artifact's Bayesian utility score."""
    pool = require_pg_pool()
    try:
        result = await artifact_store_module.record_feedback(
            pool,
            artifact_id=request.artifact_id,
            useful=request.useful,
            note=request.note,
            agent_id=request.agent_id or "main",
        )
        return ArtifactFeedbackResponse(**result)
    except ArtifactNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tools/artifact_set_confidence", response_model=ArtifactSetConfidenceResponse, operation_id="artifact_set_confidence")
async def tool_artifact_set_confidence(
    request: ArtifactSetConfidenceRequest,
    client: str = Depends(get_current_client),
) -> ArtifactSetConfidenceResponse:
    """Set an artifact's confidence level (HIGH, MEDIUM, LOW, or SUPERSEDED)."""
    pool = require_pg_pool()
    try:
        result = await artifact_store_module.set_confidence(
            pool,
            artifact_id=request.artifact_id,
            confidence=request.confidence,
            reason=request.reason,
        )
        return ArtifactSetConfidenceResponse(**result)
    except ArtifactNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tools/artifact_retirement_candidates", response_model=ArtifactRetirementCandidatesResponse, operation_id="artifact_retirement_candidates")
async def tool_artifact_retirement_candidates(
    request: ArtifactRetirementCandidatesRequest,
    client: str = Depends(get_current_client),
) -> ArtifactRetirementCandidatesResponse:
    """Find artifacts that are candidates for retirement based on age, utility score, and retrieval history."""
    pool = require_pg_pool()
    result = await artifact_store_module.get_retirement_candidates(
        pool,
        min_age_days=request.min_age_days,
        max_utility=request.max_utility,
        limit=request.limit,
    )
    return ArtifactRetirementCandidatesResponse(**result)


# -----------------------------------------------------------------------------
# Connector MCP Tools (R7)
# -----------------------------------------------------------------------------


@app.post("/tools/connector_register", response_model=ConnectorRegisterResponse, operation_id="connector_register")
async def tool_connector_register(
    request: ConnectorRegisterRequest,
    client: str = Depends(get_current_client),
) -> ConnectorRegisterResponse:
    """Register a new data source connector. Validates configuration and activates for federated queries."""
    pool = require_pg_pool()
    registry = require_connector_registry()

    # Validate connector type
    if request.connector_type not in CONNECTOR_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown connector type '{request.connector_type}'. Valid types: {list(CONNECTOR_TYPES.keys())}",
        )

    # Check name uniqueness
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM connectors WHERE name = $1", request.name
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Connector with name '{request.name}' already exists",
            )

        # Insert into database
        row = await conn.fetchrow(
            """
            INSERT INTO connectors (name, connector_type, config, status)
            VALUES ($1, $2, $3::jsonb, 'active')
            RETURNING id, status
            """,
            request.name,
            request.connector_type,
            json.dumps(request.config),
        )

    connector_id = str(row["id"])
    status = row["status"]

    # Instantiate and validate
    cls = CONNECTOR_TYPES[request.connector_type]
    config = dict(request.config)
    config["connector_id"] = connector_id
    instance = cls(name=request.name, config=config, pool=pool)

    error_detail = None
    try:
        await instance.validate()
    except (ConnectorError, Exception) as e:
        # Validation failed — update status but do NOT register
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE connectors SET status = 'error' WHERE id = $1::uuid",
                connector_id,
            )
        status = "error"
        error_detail = str(e)
        logger.warning("Connector '%s' validation failed: %s", request.name, e)
    else:
        # Only register after successful validation
        registry.register(instance)

    return ConnectorRegisterResponse(
        connector_id=connector_id,
        name=request.name,
        connector_type=request.connector_type,
        status=status,
        error=error_detail,
    )


@app.post("/tools/connector_index", response_model=ConnectorIndexResponse, operation_id="connector_index")
async def tool_connector_index(
    request: ConnectorIndexRequest,
    client: str = Depends(get_current_client),
) -> ConnectorIndexResponse:
    """Trigger indexing for a registered connector. Walks data source and updates search index."""
    pool = require_pg_pool()
    registry = require_connector_registry()

    # Look up connector in database
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name FROM connectors WHERE id = $1::uuid",
            request.connector_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Connector '{request.connector_id}' not found")

    connector_name = row["name"]

    # Get connector instance from registry
    try:
        instance = registry.get(connector_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not loaded in registry")

    # Update status to indexing
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE connectors SET status = 'indexing' WHERE id = $1::uuid",
            request.connector_id,
        )

    try:
        report = await instance.index(path=request.path)

        # Update status to active and set last_indexed
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE connectors SET status = 'active', last_indexed = NOW() WHERE id = $1::uuid",
                request.connector_id,
            )

        return ConnectorIndexResponse(
            connector_id=request.connector_id,
            items_scanned=report.items_scanned,
            items_indexed=report.items_indexed,
            items_skipped=report.items_skipped,
            items_deleted=report.items_deleted,
            errors=report.errors,
        )
    except Exception as e:
        # Update status to error
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE connectors SET status = 'error' WHERE id = $1::uuid",
                request.connector_id,
            )
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}")


@app.post("/tools/query_federated", response_model=QueryFederatedResponse, operation_id="query_federated")
async def tool_query_federated(
    request: QueryFederatedRequest,
    client: str = Depends(get_current_client),
) -> QueryFederatedResponse:
    """Search across all registered connectors with a natural language query. Returns merged, ranked results."""
    registry = require_connector_registry()

    results = await registry.federated_query(
        query=request.query,
        connector_names=request.connector_names,
        filters=request.filters,
        limit=request.limit,
    )

    federated_results = [
        FederatedSearchResult(
            content=r.content,
            source=r.source,
            score=r.score,
            connector_name=r.connector_name,
            metadata=r.metadata,
        )
        for r in results
    ]

    return QueryFederatedResponse(
        results=federated_results,
        total=len(federated_results),
    )


# -----------------------------------------------------------------------------
# Work Graph Tools
# -----------------------------------------------------------------------------
#
# These endpoints forward to the work-graph service running on localhost
# (see work-graph repo). claude-hub does no work-graph logic itself; it
# applies auth and passes the request through.


async def _forward_to_wg(path: str, body: dict) -> dict:
    """POST to the work-graph service and surface its response unchanged.

    HTTP errors from the service become HTTPExceptions with the same
    status code and detail, so downstream behavior matches the previous
    in-process implementation.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.post(f"{WG_SERVICE_URL}{path}", json=body)
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Work graph service unreachable: {e}")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


@app.post("/tools/wg_session_start", response_model=WgSessionStartResponse, operation_id="wg_session_start")
async def wg_session_start(
    params: Optional[WgSessionStartParams] = Body(default=None),
    client: str = Depends(get_current_client),
) -> WgSessionStartResponse:
    """Begin a new work-graph session. Returns a session_token to pass to subsequent wg_* calls.

    Sessions are independent of each other: each has its own cursor and breadcrumb trail, and
    multiple sessions can be active concurrently without interfering. The graph itself (nodes,
    edges, statuses) is global and shared across sessions. A new session starts cursorless —
    call wg_status to see all roots, or wg_capture (creates a new root) / wg_goto to begin."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_session_start", {})


@app.post("/tools/wg_brief", response_model=WgBriefResponse, operation_id="wg_brief")
async def wg_brief(
    params: Optional[WgBriefParams] = Body(default=None),
    client: str = Depends(get_current_client),
) -> WgBriefResponse:
    """Return a curated prose brief of current work state — the "what's on my plate",
    "status of my work", and "todo overview" view in a single compact response.

    Authoritative for work state: prefer this over remembered or summarized state for any
    what-am-I-working-on question.

    Read-only: performs no writes (no session rows touched, no node/cursor/last_visited
    updates); graph state is byte-identical before/after. The `brief` field is Markdown
    assembled by editorial rules — Workstreams (one line per root, ordered by subtree
    activity, with (stale)/(quiet) markers), In progress, Blocked (each line lists all
    unresolved blockers comma-joined in blocker-id order), and Recently captured (capped
    at max_captured, remainder elided as '…and K more deferred.'). Resolved nodes appear
    nowhere; roots appear only in Workstreams. The `message` field is a single-line count
    summary. An empty graph yields a sentinel sentence in `brief` and zero counts in
    `message`.

    No session or setup needed; call this first. Body is optional — omitted and `{}` are
    equivalent (both apply max_captured=10). When `include_notes` is true, In-progress and
    Blocked sections gain '↳ <first line of node notes>' continuation lines beneath each
    node entry."""
    require_auth(client)
    body = (params or WgBriefParams()).model_dump()
    return await _forward_to_wg("/tools/wg_brief", body)


@app.post("/tools/wg_capture", response_model=WgCaptureResponse, operation_id="wg_capture")
async def wg_capture(
    params: WgCaptureParams,
    client: str = Depends(get_current_client),
) -> WgCaptureResponse:
    """Capture a work item into the graph in a single call. This is the "capture", "todo",
    "note down", and "remember to" tool.

    One-utterance protocol: no handshake needed. `parent_id` is optional, and omitting
    placement creates a new root — a bare {"text": "..."} is a complete call. Placement
    precedence: root=true forces a new root (provenance_parent=null); parent_id places the
    new node under that parent (inheriting its root's ID prefix); otherwise a provided
    session_token uses the session's cursor (a cursorless session creates a new root);
    neither token nor placement hints → new root. root=true and parent_id together are a
    400. Session side effects (cursor move, breadcrumb append, last_active update) happen
    only when a valid session_token is provided, regardless of which placement rule fired.

    Asymmetric capture policy: auto-capture on explicit user cues ("capture: X", "todo: X")
    with a one-line acknowledgment; for merely-inferred open threads, offer instead of
    writing. For cross-cutting relationships (X blocks Y, X relates to Y) where the items
    live in different subtrees, use wg_add_dependency after creation."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_capture", params.model_dump())


@app.post("/tools/wg_goto", response_model=WgGotoResponse, operation_id="wg_goto")
async def wg_goto(
    params: WgGotoParams,
    client: str = Depends(get_current_client),
) -> WgGotoResponse:
    """Move the session cursor to a specific node and return that node's full context.

    Adds the node to the session's breadcrumbs (the per-session navigation history). Returns the
    node itself, its provenance_path (root → ... → node), direct children, and dependency edges
    (blocks + related) in both directions. This is the primary navigation tool — to organize
    captures under a different parent, goto first, then capture there."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_goto", params.model_dump())


@app.post("/tools/wg_status", response_model=WgStatusResponse, operation_id="wg_status")
async def wg_status(
    params: WgStatusParams,
    client: str = Depends(get_current_client),
) -> WgStatusResponse:
    """Show the current session state. Response shape depends on whether the session has a cursor.

    Cursorless (no cursor set; the default for fresh sessions): returns `roots` — every top-level
    workstream in the graph with its child_count, captured_count, and last_activity timestamp.
    This is the cold-start "what's on my plate?" view across all workstreams.

    With cursor set: returns the current `node` (full fields), the `provenance_path` (IDs from
    root to here), `children` (direct descendants as id/text/status summaries), `edges`
    (incoming + outgoing blocks/related edges), and the session's `breadcrumbs` (ordered list
    of every node visited in this session)."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_status", params.model_dump())


@app.post("/tools/wg_query", response_model=WgQueryResponse, operation_id="wg_query")
async def wg_query(
    params: WgQueryParams,
    client: str = Depends(get_current_client),
) -> WgQueryResponse:
    """Run a structural query against the graph. Result shape varies by the `type` parameter —
    see WgQueryParams.type for the five allowed values and their meanings, and WgQueryResponse
    for the per-type result shapes."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_query", params.model_dump())


@app.post("/tools/wg_search", response_model=WgSearchResponse, operation_id="wg_search")
async def wg_search(
    params: WgSearchParams,
    client: str = Depends(get_current_client),
) -> WgSearchResponse:
    """Find nodes by case-insensitive substring match on their text field. Returns each match
    with its provenance_path and root_text so the caller can disambiguate hits across roots."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_search", params.model_dump())


@app.post("/tools/wg_add_dependency", response_model=WgAddDependencyResponse, operation_id="wg_add_dependency")
async def wg_add_dependency(
    params: WgAddDependencyParams,
    client: str = Depends(get_current_client),
) -> WgAddDependencyResponse:
    """Create a dependency edge between two nodes. This is the only tool that creates edges;
    provenance edges (the tree structure) are created automatically by wg_capture and cannot be
    set this way.

    Edge types:
    - 'blocks' is directional: from_id blocks to_id. While from_id's status is unresolved
      (not 'done' or "won't-do"), to_id will appear in `wg_query type=blocked` and will be
      excluded from `wg_query type=ready`. Resolving from_id automatically unblocks to_id —
      no explicit edge removal is needed.
    - 'related' is bidirectional: a generic "these are connected" pointer with no semantics
      beyond cross-tree navigation.

    Edges of either type are visible from both endpoints in wg_status / wg_goto under
    `edges.blocks` / `edges.related` with a `direction` ('outgoing' or 'incoming') for blocks
    edges. Self-edges and duplicate edges are rejected."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_add_dependency", params.model_dump())


@app.post("/tools/wg_update", response_model=WgUpdateResponse, operation_id="wg_update")
async def wg_update(
    params: WgUpdateParams,
    client: str = Depends(get_current_client),
) -> WgUpdateResponse:
    """Update a node's text and/or status. At least one of `text`, `status` must be supplied.

    Status lifecycle: 'captured' (default at creation, deferred work) → 'in-progress' (active work)
    → 'done' (completed) | "won't-do" (decided not to do). Transitions are unconstrained — any
    status can move to any other. Setting status to 'done' or "won't-do" sets the node's `resolved`
    timestamp; moving back to 'captured' or 'in-progress' clears it."""
    require_auth(client)
    return await _forward_to_wg("/tools/wg_update", params.model_dump())


# -----------------------------------------------------------------------------
# Work Graph: Read-only Web UI
# -----------------------------------------------------------------------------
#
# Server-rendered HTML for browsing the graph. Lives behind the existing
# nginx basic_auth (no special location block needed). Spins an ephemeral
# session per request — fine at v0 traffic; revisit if it matters.


async def _wg_ephemeral_session() -> str:
    """Get a fresh session_token for one read-only call. Sessions are cheap."""
    res = await _forward_to_wg("/tools/wg_session_start", {})
    return res["session_token"]


@app.get("/work-graph", response_class=HTMLResponse, operation_id="work_graph_view")
async def work_graph_view(request: Request):
    """Read-only roots overview. The 'what's on my plate?' cold-start view."""
    try:
        token = await _wg_ephemeral_session()
        status = await _forward_to_wg("/tools/wg_status", {"session_token": token})
        roots = status.get("roots", [])
        return templates.TemplateResponse(
            request,
            "work_graph_roots.html",
            context={"roots": roots, "error": None},
        )
    except HTTPException as e:
        return templates.TemplateResponse(
            request,
            "work_graph_roots.html",
            context={"roots": [], "error": f"work-graph service: {e.detail}"},
            status_code=e.status_code if e.status_code >= 500 else 200,
        )


@app.get("/work-graph/{node_id}", response_class=HTMLResponse, operation_id="work_graph_node_view")
async def work_graph_node_view(request: Request, node_id: str):
    """Read-only single node view: text/status, provenance path, children, edges."""
    try:
        token = await _wg_ephemeral_session()
        ctx = await _forward_to_wg(
            "/tools/wg_goto", {"session_token": token, "node_id": node_id}
        )
        # Hydrate provenance_path (list of IDs) into list of {id, text} for breadcrumbs.
        # The cheapest path: read each one. At typical depths (≤5) this is fine.
        crumbs = []
        for nid in ctx.get("provenance_path", []):
            if nid == node_id:
                crumbs.append({"id": nid, "text": ctx["node"]["text"]})
            else:
                # cheap follow-up to get text for the crumb. Could batch if it matters.
                try:
                    parent_ctx = await _forward_to_wg(
                        "/tools/wg_goto", {"session_token": token, "node_id": nid}
                    )
                    crumbs.append({"id": nid, "text": parent_ctx["node"]["text"]})
                except HTTPException:
                    crumbs.append({"id": nid, "text": ""})
        return templates.TemplateResponse(
            request,
            "work_graph_node.html",
            context={
                "node": ctx["node"],
                "provenance_path": crumbs,
                "children": ctx.get("children", []),
                "edges": ctx.get("edges", {"blocks": [], "related": []}),
                "error": None,
            },
        )
    except HTTPException as e:
        return templates.TemplateResponse(
            request,
            "work_graph_node.html",
            context={
                "node": {"id": node_id, "text": "", "status": "", "created": "", "notes": "", "resolved": None},
                "provenance_path": [],
                "children": [],
                "edges": {"blocks": [], "related": []},
                "error": f"{e.detail}" if e.status_code < 500 else f"work-graph service: {e.detail}",
            },
            status_code=e.status_code if e.status_code in (404, 400) else 200,
        )


# -----------------------------------------------------------------------------
# MCP Protocol Wrapper
# -----------------------------------------------------------------------------

# Wrap the FastAPI app with MCP protocol support
# Only expose actual tool endpoints — exclude web UI, terminal, webhooks, etc.
mcp = FastApiMCP(
    app,
    name="claude-hub",
    description=(
        "Hub server exposing several tool families. "
        "hub_*: start a persistent Claude Code backend session and converse with it (Main Claude has full local tooling — just describe what you need). "
        "files_*: read, write, list, search files under /storage. "
        "artifact_*: store, retrieve, search durable knowledge artifacts (semantic + keyword search). "
        "group_*: multi-agent group chat. "
        "wg_*: Work-Graph — a persistent navigable graph of work-in-progress shared across all sessions. "
        "Each session starts cursorless and gets its own cursor on first capture/goto; the graph (nodes + edges) is global. "
        "Nodes have an automatic provenance parent (where the cursor was when captured), forming a forest. "
        "Cross-cutting 'blocks' / 'related' edges are added via wg_add_dependency. "
        "Status lifecycle: captured → in-progress → done | won't-do. "
        "Start with wg_session_start to get a token, then wg_status to see all roots, then wg_capture / wg_goto / wg_query."
    ),
    # Exclude web UI endpoints from MCP tools — they're not meant for Chat Claude.
    # Exclude web UI, OAuth, debug, and infrastructure endpoints from MCP tools.
    # Only actual tool endpoints (hub_*, files_*, group_*, etc.) should be exposed.
    exclude_operations=[
        # Web UI
        "work_graph_view",
        "work_graph_node_view",
        "chat_send_chat_send_post",
        "chat_verify_chat_verify_post",
        "chat_view_chat_get",
        "dashboard_view__get",
        "notifications_view_notifications_view_get",
        "notifications_verify_get_notifications_verify_get",
        "notifications_verify_post_notifications_verify_post",
        "notifications_logout_notifications_logout_post",
        "list_notifications_api_notifications_api_list_get",
        "mark_read_api_notifications_api_mark_read_post",
        "terminal_main_terminal_get",
        "terminal_verify_get_terminal_verify_get",
        "terminal_verify_post_terminal_verify_post",
        "terminal_setup_get_terminal_setup_get",
        "terminal_setup_post_terminal_setup_post",
        "terminal_logout_terminal_logout_post",
        "terminal_ping_terminal_ping_head",
        "group_chat_view",
        "list_conversations",
        "create_conversation",
        "delete_conversation",
        "get_conversation_messages",
        # OAuth endpoints (used by auth flow, not MCP tools)
        "protected_resource_metadata",
        "oauth_metadata__well_known_oauth_authorization_server_get",
        "register_client_register_post",
        "authorize_authorize_get",
        "authorize_consent_authorize_consent_post",
        "token_endpoint_token_post",
        # Debug/health endpoints
        "health_health_get",
        "debug_headers_debug_headers_get",
        "debug_routes_debug_routes_get",
        "debug_sessions_debug_sessions_get",
        "debug_pending_debug_pending_get",
        "debug_memory_debug_memory_get",
        # Webhooks
        "github_webhook_webhooks_github_post",
        # Internal (add_claude is server-side only)
        "add_claude_to_conversation",
    ],
)
# Workaround for fastapi-mcp 0.4.0 bug: its Server() call passes `description`
# into the MCP `version` slot (server.py:144 — `Server(self.name, self.description)`),
# shipping our long description text as serverInfo.version. Strict MCP clients
# (e.g. Claude in Excel) reject the malformed announcement and skip tool registration.
mcp.server.version = "0.2.0"

mcp.mount_http(mount_path="/mcp")  # Streamable HTTP — modern default (claude.ai, Excel, codex)
mcp.mount_sse(mount_path="/mcp-sse")  # SSE compat for legacy clients (deprecated upstream)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "claude_hub.server:app",
        host="0.0.0.0",
        port=8420,
        reload=True,
    )


if __name__ == "__main__":
    main()
