"""Pydantic request/response models for the connector MCP tools (R7)."""

from pydantic import BaseModel, Field


# --- connector_register (R7.1) ---


class ConnectorRegisterRequest(BaseModel):
    """Request to register a new data source connector."""

    name: str = Field(description="Unique connector name")
    connector_type: str = Field(
        description="Type identifier (artifact_store, filesystem, etc.)"
    )
    config: dict = Field(
        default_factory=dict, description="Connector-specific configuration"
    )


class ConnectorRegisterResponse(BaseModel):
    """Response after registering a connector."""

    connector_id: str = Field(description="UUID of the registered connector")
    name: str = Field(description="Connector name")
    connector_type: str = Field(description="Connector type identifier")
    status: str = Field(description="Initial status (active)")
    error: str | None = Field(default=None, description="Error detail if validation failed")


# --- connector_index (R7.3) ---


class ConnectorIndexRequest(BaseModel):
    """Request to trigger indexing for a connector."""

    connector_id: str = Field(description="Connector UUID to index")
    path: str | None = Field(
        default=None, description="Specific path/scope to index (default: full scan)"
    )


class ConnectorIndexResponse(BaseModel):
    """Response after indexing completes."""

    connector_id: str = Field(description="Connector UUID that was indexed")
    items_scanned: int = Field(description="Total items scanned")
    items_indexed: int = Field(description="Items newly indexed or updated")
    items_skipped: int = Field(description="Items skipped (unchanged)")
    items_deleted: int = Field(default=0, description="Stale items removed from index")
    errors: list[str] = Field(
        default_factory=list, description="Error messages for failed items"
    )


# --- query_federated (R7.4) ---


class QueryFederatedRequest(BaseModel):
    """Request to search across all registered connectors."""

    query: str = Field(description="Natural-language search query")
    connector_names: list[str] | None = Field(
        default=None,
        description="Connector names to query (default: all active connectors)",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Max total results")
    filters: dict | None = Field(
        default=None, description="Connector-specific filters"
    )


class FederatedSearchResult(BaseModel):
    """A single result from a federated search."""

    content: str = Field(description="Content or content preview")
    source: str = Field(description="Source path/URI within the connector")
    score: float = Field(description="Relevance score (0-1)")
    connector_name: str = Field(description="Name of the connector that produced this result")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class QueryFederatedResponse(BaseModel):
    """Response from a federated search."""

    results: list[FederatedSearchResult] = Field(description="Ranked search results")
    total: int = Field(description="Total number of results returned")
