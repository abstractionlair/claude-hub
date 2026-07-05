"""Route-level tests for the claude-hub work-graph forwarder layer.

This is the first route-level suite for the wg_* forwarders; it establishes the
pattern (mock the `_forward_to_wg` boundary so no live work-graph service is
required) and pins the wg-002 chat-surface contract:

- `WgCaptureParams` accepts the v0 shape and the new tokenless shapes.
- `WgBriefParams` enforces the [0, 100] bound (422 above/below).
- `wg_brief` route accepts omitted body and `{}` equivalently.
- `wg_capture` route forwards the new optional fields as explicit nulls.
- The route docstrings satisfy the spec's description checklist (review-gate AC 22).
- The 401 bodies carry the connector reauthorization guidance.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from claude_hub.auth import require_auth
from claude_hub.server import app
from claude_hub.work_graph_models import WgBriefParams, WgBriefResponse, WgCaptureParams

# The exact reauthorization sentence the spec/brief require in 401 bodies.
REAUTH_SENTENCE = (
    "OAuth token expired or missing — reauthorize Claude Hub "
    "(claude.ai: Settings → Connectors), then retry."
)

# A minimal valid WgCaptureResponse payload the mocked forwarder can return.
_CAP_OK = {
    "node": {
        "id": "tst-0",
        "text": "test item",
        "status": "captured",
        "provenance_parent": None,
        "notes": "",
        "created": "2026-07-04T00:00:00Z",
        "resolved": None,
    },
    "message": "Captured.",
}

_BRIEF_OK = {"brief": "## Workstreams (0)\n", "message": "0 workstreams — 0 in progress, 0 blocked, 0 deferred"}


def _route_description(path: str) -> str:
    """Return the FastAPI route description (the endpoint docstring) for `path`."""
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path:
            return r.description or ""
    raise AssertionError(f"no APIRoute at {path}")


def _route_description_normalized(path: str) -> str:
    """Route description with whitespace collapsed and case lowered.

    The spec's description checklist is about phrase *presence*; line-wrapping
    and sentence-initial capitalization in the docstring are presentation
    details, so the contract checks compare on a normalized token stream.
    """
    return " ".join(_route_description(path).split()).lower()


# ═══════════════════════════════════════════════════════════════════════
# Model acceptance
# ═══════════════════════════════════════════════════════════════════════


class TestWgCaptureParams:
    """WgCaptureParams accepts the v0 shape and the new tokenless shapes, with defaults."""

    def test_v0_shape_token_and_text(self):
        p = WgCaptureParams(session_token="tok-1", text="do thing")
        d = p.model_dump()
        assert d["session_token"] == "tok-1"
        assert d["text"] == "do thing"
        assert d["parent_id"] is None
        assert d["root"] is False
        assert d["notes"] == ""
        assert d["status"] == "captured"

    def test_tokenless_parent_id(self):
        p = WgCaptureParams(text="x", parent_id="pm-0")
        d = p.model_dump()
        assert d["session_token"] is None
        assert d["parent_id"] == "pm-0"
        assert d["root"] is False

    def test_tokenless_root(self):
        p = WgCaptureParams(text="x", root=True)
        d = p.model_dump()
        assert d["session_token"] is None
        assert d["parent_id"] is None
        assert d["root"] is True

    def test_tokenless_bare_text_creates_root_defaults(self):
        p = WgCaptureParams(text="just text")
        d = p.model_dump()
        assert d["session_token"] is None
        assert d["parent_id"] is None
        assert d["root"] is False
        assert d["status"] == "captured"
        assert d["notes"] == ""

    def test_text_is_still_required(self):
        with pytest.raises(ValidationError):
            WgCaptureParams()

    def test_all_fields_together(self):
        p = WgCaptureParams(
            session_token="tok-2", text="x", notes="n", status="in-progress",
            parent_id="pm-1", root=False,
        )
        d = p.model_dump()
        assert d == {
            "session_token": "tok-2", "text": "x", "notes": "n",
            "status": "in-progress", "parent_id": "pm-1", "root": False,
        }

    def test_unknown_field_rejected(self):
        # Regression: the service uses extra='forbid' (src/server.py), so a
        # typo'd field like "parent_idd" must 422 at the hub rather than be
        # silently dropped (which would forward a bare-text payload and create
        # a root instead of placing under the intended parent).
        with pytest.raises(ValidationError):
            WgCaptureParams(text="x", parent_idd="pm-0")

    def test_wrong_type_root_rejected(self):
        # Regression: strict=True means a string "true" must not coerce to bool.
        with pytest.raises(ValidationError):
            WgCaptureParams(text="x", root="true")


class TestWgBriefParams:
    """WgBriefParams bounds: [0, 100] inclusive; defaults to 10."""

    def test_default(self):
        assert WgBriefParams().max_captured == 10

    def test_zero_accepted(self):
        assert WgBriefParams(max_captured=0).max_captured == 0

    def test_one_hundred_accepted(self):
        assert WgBriefParams(max_captured=100).max_captured == 100

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            WgBriefParams(max_captured=-1)

    def test_over_bound_rejected(self):
        with pytest.raises(ValidationError):
            WgBriefParams(max_captured=101)

    def test_wrong_type_max_captured_rejected(self):
        # Regression: strict=True means a string "5" must not coerce to int 5.
        # The spec requires 422 for wrong-type request shapes (§wg_brief Errors).
        with pytest.raises(ValidationError):
            WgBriefParams(max_captured="5")


class TestWgBriefParamsIncludeNotes:
    """WgBriefParams include_notes: defaults to False, accepts bool, rejects wrong type."""

    def test_default(self):
        assert WgBriefParams().include_notes is False

    def test_explicit_true(self):
        assert WgBriefParams(include_notes=True).include_notes is True

    def test_explicit_false(self):
        assert WgBriefParams(include_notes=False).include_notes is False

    def test_wrong_type_rejected(self):
        with pytest.raises(ValidationError):
            WgBriefParams(include_notes="true")


# ═══════════════════════════════════════════════════════════════════════
# wg_brief route
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def client():
    return TestClient(app)


class TestWgBriefRoute:
    """wg_brief route: omitted body and {} both reach the forwarder with the right payload."""

    def test_omitted_body_forwards_default(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief")
        assert r.status_code == 200, r.text
        fw.assert_awaited_once()
        assert fw.call_args.args[0] == "/tools/wg_brief"
        assert fw.call_args.args[1] == {"max_captured": 10, "include_notes": False}

    def test_empty_body_forwards_default(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={})
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 10, "include_notes": False}

    def test_explicit_max_captured_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": 5})
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 5, "include_notes": False}

    def test_zero_max_captured_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": 0})
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 0, "include_notes": False}

    def test_out_of_bounds_negative_returns_422(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": -1})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_out_of_bounds_over_returns_422(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": 101})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_wrong_type_max_captured_returns_422(self, client):
        # Regression: strict=True — string "5" must not coerce to int 5 and
        # reach the forwarder. Spec §wg_brief Errors requires 422 for wrong types.
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": "5"})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_unknown_field_returns_422(self, client):
        # Regression: extra='forbid' — unknown fields must 422, not be dropped.
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": 5, "bogus": 1})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_response_validated_against_brief_response_model(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK):
            r = client.post("/tools/wg_brief")
        body = r.json()
        # Validated by response_model=WgBriefResponse; confirm shape round-trips.
        assert WgBriefResponse(**body).brief == _BRIEF_OK["brief"]


class TestWgBriefRouteIncludeNotes:
    """wg_brief route: include_notes is wired through to the forwarder."""

    def test_include_notes_true_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"include_notes": True})
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 10, "include_notes": True}

    def test_default_false_from_omitted_body(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief")
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 10, "include_notes": False}

    def test_default_false_from_empty_body(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={})
        assert r.status_code == 200, r.text
        assert fw.call_args.args[1] == {"max_captured": 10, "include_notes": False}

    def test_wrong_type_include_notes_returns_422(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"include_notes": "true"})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_unknown_field_still_returns_422_with_include_notes(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_BRIEF_OK) as fw:
            r = client.post("/tools/wg_brief", json={"max_captured": 5, "include_notes": True, "bogus": 1})
        assert r.status_code == 422
        fw.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════
# wg_capture route forwarding
# ═══════════════════════════════════════════════════════════════════════


class TestWgCaptureRoute:
    """wg_capture route forwards the new optional fields as explicit nulls (mocked boundary)."""

    def test_bare_text_forwards_null_optionals(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "do thing"})
        assert r.status_code == 200, r.text
        body = fw.call_args.args[1]
        assert body["text"] == "do thing"
        assert body["session_token"] is None
        assert body["parent_id"] is None
        assert body["root"] is False
        assert body["notes"] == ""
        assert body["status"] == "captured"

    def test_parent_id_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "x", "parent_id": "pm-0"})
        assert r.status_code == 200, r.text
        body = fw.call_args.args[1]
        assert body["parent_id"] == "pm-0"
        assert body["session_token"] is None
        assert body["root"] is False

    def test_root_true_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "x", "root": True})
        assert r.status_code == 200, r.text
        body = fw.call_args.args[1]
        assert body["root"] is True
        assert body["parent_id"] is None
        assert body["session_token"] is None

    def test_v0_shape_forwarded(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"session_token": "tok-1", "text": "x"})
        assert r.status_code == 200, r.text
        body = fw.call_args.args[1]
        assert body["session_token"] == "tok-1"
        assert body["parent_id"] is None
        assert body["root"] is False

    def test_conflicting_hints_forwarded_to_service(self, client):
        # The hub does no placement validation; it forwards and the service
        # returns 400. Verify the conflicting pair is passed through unchanged.
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "x", "parent_id": "pm-0", "root": True})
        assert r.status_code == 200, r.text
        body = fw.call_args.args[1]
        assert body["parent_id"] == "pm-0"
        assert body["root"] is True

    def test_missing_text_returns_422(self, client):
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"parent_id": "pm-0"})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_service_400_surfaces_as_400(self, client):
        # The hub passes domain errors through (status + detail) unchanged.
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock) as fw:
            fw.side_effect = HTTPException(status_code=400, detail="Cannot specify both root=true and parent_id")
            r = client.post("/tools/wg_capture", json={"text": "x", "parent_id": "pm-0", "root": True})
        assert r.status_code == 400
        assert "Cannot specify both" in r.json()["detail"]

    def test_unknown_field_returns_422(self, client):
        # Regression (review round 2): extra='forbid' — a typo'd "parent_idd"
        # must 422 at the hub, not be silently dropped (which would forward a
        # bare-text payload and create a root instead of placing under pm-0).
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "x", "parent_idd": "pm-0"})
        assert r.status_code == 422
        fw.assert_not_awaited()

    def test_wrong_type_root_returns_422(self, client):
        # Regression (review round 2): strict=True — string "true" must not
        # coerce to bool True and reach the forwarder.
        with patch("claude_hub.server._forward_to_wg", new_callable=AsyncMock, return_value=_CAP_OK) as fw:
            r = client.post("/tools/wg_capture", json={"text": "x", "root": "true"})
        assert r.status_code == 422
        fw.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════
# Description contract (spec review-gate AC 22)
# ═══════════════════════════════════════════════════════════════════════


class TestWgDescriptionContract:
    """Route docstrings contain the spec's description checklist phrases."""

    def test_wg_brief_description_contains_discoverability_phrases(self):
        d = _route_description_normalized("/tools/wg_brief")
        assert "what's on my plate" in d
        assert "status of my work" in d
        assert "brief" in d
        assert "todo overview" in d

    def test_wg_brief_description_contains_authority_declaration(self):
        d = _route_description_normalized("/tools/wg_brief")
        assert (
            "authoritative for work state: prefer this over remembered or summarized state "
            "for any what-am-i-working-on question" in d
        )

    def test_wg_brief_description_contains_call_this_first(self):
        d = _route_description_normalized("/tools/wg_brief")
        assert "no session or setup needed; call this first" in d

    def test_wg_capture_description_contains_discoverability_phrases(self):
        d = _route_description_normalized("/tools/wg_capture")
        assert "capture" in d
        assert "todo" in d
        assert "note down" in d
        assert "remember to" in d

    def test_wg_capture_description_contains_one_utterance_protocol(self):
        d = _route_description_normalized("/tools/wg_capture")
        assert "no handshake needed" in d
        assert "parent_id" in d and "optional" in d
        assert "omitting placement creates a new root" in d

    def test_wg_capture_description_contains_asymmetric_capture_policy(self):
        d = _route_description_normalized("/tools/wg_capture")
        assert "auto-capture on explicit user cues" in d
        assert "capture: x" in d
        assert "todo: x" in d
        assert "one-line acknowledgment" in d
        assert "for merely-inferred open threads, offer instead of writing" in d


# ═══════════════════════════════════════════════════════════════════════
# 401 reauthorization guidance
# ═══════════════════════════════════════════════════════════════════════


class TestAuth401Guidance:
    """401 bodies include the connector reauthorization sentence."""

    def test_require_auth_detail_contains_reauthorization(self, monkeypatch):
        monkeypatch.setattr("claude_hub.auth.JWT_SECRET", "test-secret-enables-oauth")
        with pytest.raises(HTTPException) as exc:
            require_auth(None)
        assert exc.value.status_code == 401
        assert REAUTH_SENTENCE in exc.value.detail

    def test_missing_credentials_401_contains_reauthorization(self, monkeypatch, client):
        monkeypatch.setattr("claude_hub.auth.JWT_SECRET", "test-secret-enables-oauth")
        r = client.post("/tools/wg_brief")
        assert r.status_code == 401
        assert REAUTH_SENTENCE in r.json()["detail"]

    def test_invalid_token_401_contains_reauthorization(self, monkeypatch, client):
        monkeypatch.setattr("claude_hub.auth.JWT_SECRET", "test-secret-enables-oauth")
        r = client.post(
            "/tools/wg_brief",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert r.status_code == 401
        assert REAUTH_SENTENCE in r.json()["detail"]
