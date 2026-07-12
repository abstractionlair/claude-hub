"""Pydantic models for work-graph MCP tool endpoints.

Field descriptions on parameters and response models become the schemas
visible to MCP agents when they list tools — so they double as the
canonical interface documentation.

Response models mirror the TypedDicts in the work-graph service's
src/models.py. The localhost service emits dicts with these shapes; the
forwarders in claude-hub return them via these Pydantic models so
callers see typed responses in the MCP schema.
"""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ════════════════════════════════════════════════════════════════════
# Request models
# ════════════════════════════════════════════════════════════════════


class WgSessionStartParams(BaseModel):
    """Parameters for wg_session_start (none required)."""

    model_config = ConfigDict(extra="forbid", strict=True)


class WgBriefParams(BaseModel):
    """Parameters for wg_brief — the token-free, read-only work-state brief.

    The body is optional: an omitted body and `{}` are equivalent (both apply
    the max_captured default). max_captured is clamped to [0, 100].
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    max_captured: int = Field(
        default=10,
        ge=0,
        le=100,
        description=(
            "Maximum number of 'Recently captured' items to render in full before eliding the remainder as "
            "'…and K more deferred.'. Default 10; constrained to [0, 100]. max_captured=0 yields only the "
            "remainder line. Raises 422 (not 400) when out of bounds."
        ),
    )

    include_notes: bool = Field(
        default=False,
        description=(
            "When true, In-progress and Blocked lines in the brief gain "
            "'↳ <first line of node notes>' continuation lines beneath each node entry. "
            "Default false (brief renders without notes). "
            "Raises 422 (not 400) when the wrong type is sent."
        ),
    )


class WgCaptureParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_token: Optional[str] = Field(
        default=None,
        description=(
            "Token from wg_session_start. Optional: omit for cursorless capture — no session needed. "
            "When provided, the session's cursor moves to the new node and breadcrumbs append regardless of "
            "which placement rule fired. If neither root nor parent_id is given, a provided token's cursor "
            "decides placement (a cursorless session creates a new root). A provided token is validated even "
            "when parent_id/root decides placement."
        ),
    )
    text: str = Field(
        ...,
        description="One-sentence description of the work item. Plain text. Required, must be non-empty after stripping whitespace.",
    )
    notes: str = Field(
        default="",
        description="Optional freeform context (plain text, no length limit enforced). Use for details that don't belong in the one-line text.",
    )
    status: str = Field(
        default="captured",
        description=(
            "Initial status. Allowed values for capture: 'captured' (default; deferred — not actively being worked) "
            "or 'in-progress' (started). Other lifecycle statuses ('done', \"won't-do\") are reachable via wg_update, not capture."
        ),
    )
    parent_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional. Place the new node under this parent (the new node inherits the parent's root ID prefix). "
            "Mutually exclusive with root=true; giving both is a 400. When omitted along with root and "
            "session_token, the node becomes a new root."
        ),
    )
    root: bool = Field(
        default=False,
        description=(
            "Force the new node to be a new root (provenance_parent=null). Mutually exclusive with parent_id; "
            "giving both is a 400. Default false. Omit all placement hints (no root, no parent_id, no token) to "
            "create a new root."
        ),
    )


class WgGotoParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_token: str = Field(..., description="Token from wg_session_start.")
    node_id: str = Field(
        ...,
        description="Short auto-generated ID like 'wgdv-3'. Format is <prefix>-<n> where prefix is derived from the root node's text and n is sequential within that root.",
    )


class WgStatusParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_token: str = Field(..., description="Token from wg_session_start.")


class WgQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_token: Optional[str] = Field(
        default=None,
        description="Optional token from wg_session_start. Omit for a read-only query that does not touch session state.",
    )
    type: str = Field(
        ...,
        description=(
            "Query type. Allowed values: "
            "'overview' (all roots with child counts and recent-activity timestamps — the dashboard view); "
            "'ready' (captured/in-progress items with no unresolved blockers); "
            "'recent' (nodes with cursor activity in the last `days` days); "
            "'deferred' (all nodes with status 'captured', optionally scoped); "
            "'blocked' (nodes with unresolved 'blocks' edges pointing at them)."
        ),
    )
    scope: Optional[str] = Field(
        default=None,
        description="Optional node ID to scope the query to a subtree. None means whole graph.",
    )
    days: int = Field(
        default=7,
        description="For type='recent', look back this many days. Ignored for other query types.",
    )


class WgSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(
        ...,
        description="Substring to find in node text. Case-insensitive. Empty result is valid (returns []), not an error.",
    )


class WgAddDependencyParams(BaseModel):
    """Parameters for wg_add_dependency.

    This is the only way to create edges. Provenance edges (the tree
    structure) are created automatically by wg_capture; cross-cutting
    edges between nodes in different subtrees use this tool.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    from_id: str = Field(..., description="Source node ID.")
    to_id: str = Field(..., description="Target node ID.")
    type: str = Field(
        ...,
        description=(
            "Edge type. Allowed values: "
            "'blocks' (directional — from_id blocks to_id; to_id will appear in query type='blocked' until from_id is resolved); "
            "'related' (bidirectional — from_id and to_id are connected but neither blocks the other)."
        ),
    )


class WgUpdateParams(BaseModel):
    """Parameters for wg_update.

    At least one of `text`, `status`, or `notes` must be provided. The status
    lifecycle is: 'captured' (default at creation) → 'in-progress' →
    'done' or \"won't-do\". Setting status to 'done' or \"won't-do\"
    sets a `resolved` timestamp on the node; setting it back clears
    the timestamp.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    node_id: str = Field(..., description="ID of the node to update.")
    text: Optional[str] = Field(
        default=None,
        description="New text. Omit or null to leave unchanged. Must be non-empty if provided.",
    )
    status: Optional[str] = Field(
        default=None,
        description=(
            "New status. Allowed values: 'captured', 'in-progress', 'done', \"won't-do\". "
            "Omit or null to leave unchanged."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="New notes/context. Omit or null to leave unchanged; use an empty string to clear notes.",
    )


# ════════════════════════════════════════════════════════════════════
# Response building blocks
# ════════════════════════════════════════════════════════════════════


class WgNode(BaseModel):
    """Full node, returned by capture/goto/update and inside status responses."""
    id: str = Field(..., description="Short auto-generated ID, e.g. 'wgdv-3'.")
    text: str = Field(..., description="One-sentence description.")
    status: str = Field(..., description="One of 'captured', 'in-progress', 'done', \"won't-do\".")
    provenance_parent: Optional[str] = Field(
        ..., description="Parent node ID, or null if this is a root."
    )
    notes: str = Field(..., description="Freeform context; empty string if none.")
    created: str = Field(..., description="ISO 8601 timestamp.")
    resolved: Optional[str] = Field(
        ..., description="ISO 8601 timestamp set when status became 'done' or \"won't-do\"; null otherwise."
    )


class WgNodeSummary(BaseModel):
    """Short node info used in children lists and inside other results."""
    id: str
    text: str
    status: str


class WgRootSummary(BaseModel):
    """Root node with aggregate stats — used in cursorless status and query type='overview'."""
    id: str
    text: str
    status: str
    child_count: int = Field(..., description="Total descendant nodes (whole subtree, not just direct children).")
    captured_count: int = Field(..., description="Descendants whose status is 'captured' (deferred work under this root).")
    last_activity: str = Field(..., description="ISO 8601 timestamp of the most recent activity in this subtree.")


class WgBlocksEdgeRef(BaseModel):
    """A 'blocks' edge as seen from one endpoint."""
    id: str = Field(..., description="The other node's ID.")
    text: str
    direction: str = Field(
        ...,
        description="'outgoing' (this node blocks the referenced node) or 'incoming' (referenced node blocks this node).",
    )


class WgRelatedEdgeRef(BaseModel):
    """A 'related' edge — bidirectional, no direction field."""
    id: str
    text: str


class WgEdgeMap(BaseModel):
    """Dependency edges for one node, grouped by type."""
    blocks: List[WgBlocksEdgeRef]
    related: List[WgRelatedEdgeRef]


class WgEdge(BaseModel):
    """Full edge serialization — returned by add_dependency."""
    type: str = Field(..., description="'blocks' or 'related'.")
    created: str = Field(..., description="ISO 8601 timestamp.")
    # The wire format uses 'from' which is a Python keyword — alias here.
    from_: str = Field(..., alias="from", description="Source node ID.")
    to: str = Field(..., description="Target node ID.")

    model_config = {"populate_by_name": True}


# ════════════════════════════════════════════════════════════════════
# Tool response models
# ════════════════════════════════════════════════════════════════════


class WgSessionStartResponse(BaseModel):
    """Response from wg_session_start."""
    session_token: str = Field(..., description="Pass this to subsequent wg_* calls.")
    cursor: Optional[str] = Field(..., description="Always null on session start (cursorless).")
    message: str = Field(..., description="Plain-English narration of what happened.")


class WgBriefResponse(BaseModel):
    """Response from wg_brief — the curated prose brief of current work state.

    Both fields are non-empty on every 200; `message` contains no newlines and
    its counts agree with the sections rendered in `brief`. The empty-graph
    case yields a sentinel sentence in `brief` and a zero-counts `message`.
    """

    brief: str = Field(
        ...,
        description=(
            "Markdown prose brief of current work state. Sections (omitted when empty): Workstreams (one line "
            "per root, ordered by subtree activity descending, with (stale)/(quiet) markers), In progress, "
            "Blocked (all unresolved blockers, comma-joined in blocker-id order), Recently captured (capped at "
            "max_captured, remainder elided as '…and K more deferred.'). Resolved nodes appear nowhere; roots "
            "appear only in Workstreams. Empty graph yields: 'The graph is empty. Capture your first item with "
            "wg_capture.'"
        ),
    )
    message: str = Field(
        ...,
        description=(
            "Single-line count summary, format: '<R> workstreams — <I> in progress, <B> blocked, <D> deferred' "
            "where D counts captured, unblocked, non-root nodes (shown + elided). No newlines."
        ),
    )


class WgCaptureResponse(BaseModel):
    """Response from wg_capture."""
    node: WgNode
    message: str


class WgGotoResponse(BaseModel):
    """Response from wg_goto. Includes the node, its provenance path, children, and edges."""
    node: WgNode
    provenance_path: List[str] = Field(
        ..., description="Node IDs from root → ... → this node, inclusive of both endpoints."
    )
    children: List[WgNodeSummary]
    edges: WgEdgeMap
    message: str


class WgCursorlessStatusResponse(BaseModel):
    """wg_status when the session has no cursor set — returns all roots."""
    cursor: Optional[str] = Field(..., description="Always null in this response shape.")
    roots: List[WgRootSummary]
    message: str


class WgCursorStatusResponse(BaseModel):
    """wg_status when the session has a cursor — returns the current node's full context."""
    cursor: str
    node: WgNode
    provenance_path: List[str]
    children: List[WgNodeSummary]
    edges: WgEdgeMap
    breadcrumbs: List[str] = Field(
        ..., description="Ordered list of node IDs visited in this session."
    )
    message: str


# wg_status returns one of the two shapes above depending on whether the session has a cursor.
WgStatusResponse = Union[WgCursorlessStatusResponse, WgCursorStatusResponse]


class WgReadyResult(BaseModel):
    id: str
    text: str
    root: str = Field(..., description="ID of the root this item lives under.")
    provenance_path: List[str]


class WgRecentResult(BaseModel):
    id: str
    text: str
    status: str
    last_activity: str = Field(..., description="ISO 8601 timestamp.")


class WgDeferredResult(BaseModel):
    id: str
    text: str
    provenance_path: List[str]
    root_text: str = Field(..., description="Text of the root this item lives under (for context).")


class WgBlockedResult(BaseModel):
    id: str
    text: str
    provenance_path: List[str]
    blocked_by: List[WgNodeSummary] = Field(
        ..., description="Unresolved blockers — nodes with status not 'done' or \"won't-do\" that have a 'blocks' edge into this one."
    )


class WgOverviewQueryResponse(BaseModel):
    results: List[WgRootSummary]
    message: str


class WgReadyQueryResponse(BaseModel):
    results: List[WgReadyResult]
    message: str


class WgRecentQueryResponse(BaseModel):
    results: List[WgRecentResult]
    message: str


class WgDeferredQueryResponse(BaseModel):
    results: List[WgDeferredResult]
    message: str


class WgBlockedQueryResponse(BaseModel):
    results: List[WgBlockedResult]
    message: str


# wg_query returns one of these depending on the `type` parameter.
WgQueryResponse = Union[
    WgOverviewQueryResponse,
    WgReadyQueryResponse,
    WgRecentQueryResponse,
    WgDeferredQueryResponse,
    WgBlockedQueryResponse,
]


class WgSearchResult(BaseModel):
    id: str
    text: str
    status: str
    provenance_path: List[str]
    root_text: str


class WgSearchResponse(BaseModel):
    results: List[WgSearchResult]
    message: str


class WgAddDependencyResponse(BaseModel):
    edge: WgEdge
    message: str


class WgUpdateResponse(BaseModel):
    node: WgNode
    message: str


# Backward-compat: a few callers may still reference WgResponse. Alias to the
# union of all response shapes for permissive validation. New endpoints
# should use the specific response model.
WgResponse = Union[
    WgSessionStartResponse,
    WgBriefResponse,
    WgCaptureResponse,
    WgGotoResponse,
    WgCursorlessStatusResponse,
    WgCursorStatusResponse,
    WgOverviewQueryResponse,
    WgReadyQueryResponse,
    WgRecentQueryResponse,
    WgDeferredQueryResponse,
    WgBlockedQueryResponse,
    WgSearchResponse,
    WgAddDependencyResponse,
    WgUpdateResponse,
]
