"""Pydantic request/response models for the artifact MCP tools."""

from pydantic import BaseModel, Field


# --- Nested Models ---


class ArtifactVersion(BaseModel):
    """A historical version of an artifact's content."""
    version: int
    content: str
    content_hash: str
    created_at: str


class ArtifactOutcome(BaseModel):
    """An outcome rating attached to an artifact.

    .. deprecated:: Use :class:`ArtifactFeedback` instead.
    """
    rating: str = Field(description="Outcome rating: 'SUCCEEDED', 'PARTIAL_SUCCESS', 'PARTIAL_FAILURE', or 'FAILED'")
    reasoning: str | None = None
    rated_by: str = Field(description="Who rated this outcome (session ID or agent name)")
    rated_at: str


class ArtifactFeedback(BaseModel):
    """A usage-feedback record attached to an artifact."""
    useful: bool = Field(description="Whether the artifact was useful")
    note: str | None = Field(default=None, description="Optional note about the feedback")
    agent_id: str = Field(description="Agent that provided the feedback")
    content_version: int | None = Field(default=None, description="Version of content when feedback was given")
    created_at: str


class ArtifactSearchResult(BaseModel):
    """A single result from a semantic or filtered search."""
    artifact_id: str
    content_preview: str
    artifact_type: str
    tags: list[str]
    score: float = Field(description="Quality-weighted relevance score (base similarity + confidence/utility/age boosts)")
    utility_score: float = Field(description="Utility score from feedback (0.0-1.0)")
    confidence: str = Field(description="Confidence level: HIGH, MEDIUM, LOW, or SUPERSEDED")
    created_at: str


class ArtifactListResult(BaseModel):
    """A single result from a list/browse query."""
    artifact_id: str
    artifact_type: str
    tags: list[str]
    content_preview: str
    created_at: str
    archived: bool


# --- 1. artifact_store ---


class ArtifactStoreRequest(BaseModel):
    """Request to store a new artifact."""
    content: str = Field(description="The artifact content to store")
    artifact_type: str = Field(description="Type of artifact, e.g. 'learning', 'plan', 'snippet'")
    tags: list[str] | None = Field(default=None, description="Optional tags for categorization")
    source_ref: str | None = Field(default=None, description="Source reference, e.g. session ID or file path")
    derives_from: list[str] | None = Field(default=None, description="Artifact IDs this derives from")
    sensitive: bool = Field(default=False, description="Whether this artifact contains sensitive content")
    metadata: dict | None = Field(default=None, description="Arbitrary key-value metadata")


class ArtifactStoreResponse(BaseModel):
    """Response after storing an artifact."""
    artifact_id: str
    version: int
    embedding_status: str = Field(description="Status of embedding generation, e.g. 'pending', 'complete'")


# --- 2. artifact_get ---


class ArtifactGetRequest(BaseModel):
    """Request to retrieve an artifact by ID."""
    id: str = Field(description="The artifact ID to retrieve")
    include_versions: bool = Field(default=False, description="Whether to include version history")
    include_feedback: bool = Field(default=True, description="Whether to include usage feedback")
    # Backward-compatible alias — callers may still pass include_outcomes
    include_outcomes: bool | None = Field(default=None, description="Deprecated alias for include_feedback")


class ArtifactGetResponse(BaseModel):
    """Full artifact record."""
    id: str
    content: str
    content_hash: str
    artifact_type: str
    tags: list[str]
    source_ref: str | None
    derives_from: list[str]
    created_at: str
    sensitive: bool
    archived: bool
    metadata: dict
    confidence: str | None = Field(default=None, description="Quality confidence level: HIGH, MEDIUM, LOW, or SUPERSEDED")
    utility_score: float | None = Field(default=None, description="Bayesian utility score from feedback (0.0-1.0)")
    versions: list[ArtifactVersion] | None = Field(
        default=None, description="Version history, present only if include_versions was True"
    )
    feedback: list[ArtifactFeedback] | None = Field(
        default=None, description="Usage feedback, present only if include_feedback was True"
    )
    # Backward-compatible alias
    outcomes: list[ArtifactOutcome] | None = Field(
        default=None, description="Deprecated — use feedback instead"
    )


# --- 3. artifact_search ---


class ArtifactSearchRequest(BaseModel):
    """Request to search artifacts by query and filters."""
    query: str = Field(description="Semantic search query")
    artifact_type: str | None = Field(default=None, description="Filter by artifact type")
    tags: list[str] | None = Field(default=None, description="Filter by tags (AND logic)")
    date_from: str | None = Field(default=None, description="Filter by creation date (ISO 8601)")
    date_to: str | None = Field(default=None, description="Filter by creation date (ISO 8601)")
    include_archived: bool = Field(default=False, description="Whether to include archived artifacts")
    confidence: str | None = Field(default=None, description="Minimum confidence filter: HIGH, MEDIUM, LOW, or SUPERSEDED")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return (1-50)")


class ArtifactSearchResponse(BaseModel):
    """Search results."""
    results: list[ArtifactSearchResult]


# --- 4. artifact_list ---


class ArtifactListRequest(BaseModel):
    """Request to list/browse artifacts with optional filters."""
    artifact_type: str | None = Field(default=None, description="Filter by artifact type")
    tags: list[str] | None = Field(default=None, description="Filter by tags")
    include_archived: bool = Field(default=False, description="Whether to include archived artifacts")
    limit: int = Field(default=20, ge=1, le=100, description="Max results to return (1-100)")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class ArtifactListResponse(BaseModel):
    """Paginated list results."""
    results: list[ArtifactListResult]
    total_count: int = Field(description="Total number of matching artifacts (for pagination)")


# --- 5. artifact_archive ---


class ArtifactArchiveRequest(BaseModel):
    """Request to archive an artifact."""
    id: str = Field(description="The artifact ID to archive")


class ArtifactArchiveResponse(BaseModel):
    """Response after archiving."""
    success: bool


# --- 6. artifact_update ---


class ArtifactUpdateRequest(BaseModel):
    """Request to update an artifact's content (creates a new version)."""
    id: str = Field(description="The artifact ID to update")
    content: str = Field(description="The new content")
    metadata: dict | None = Field(default=None, description="Optional metadata to merge")


class ArtifactUpdateResponse(BaseModel):
    """Response after updating an artifact."""
    artifact_id: str
    version: int = Field(description="The new version number")
    embedding_status: str = Field(description="Status of embedding generation for the new version")


# --- 7. artifact_update_metadata ---


class ArtifactUpdateMetadataRequest(BaseModel):
    """Request to update only an artifact's metadata, tags, or archived status."""
    id: str = Field(description="The artifact ID to update")
    metadata: dict | None = Field(default=None, description="Metadata fields to merge (does not replace, merges)")
    tags: list[str] | None = Field(default=None, description="Replace tags with this list if provided")
    archived: bool | None = Field(default=None, description="Set archived status if provided")


class ArtifactUpdateMetadataResponse(BaseModel):
    """Response after metadata update."""
    success: bool


# --- 8. artifact_export ---


class ArtifactExportRequest(BaseModel):
    """Request to export artifacts to a file."""
    format: str = Field(default="json", description="Export format, e.g. 'json', 'csv'")
    artifact_type: str | None = Field(default=None, description="Filter export to a specific artifact type")


class ArtifactExportResponse(BaseModel):
    """Response after export."""
    export_path: str = Field(description="Path to the exported file")
    artifact_count: int | None = Field(default=None, description="Number of artifacts exported")


# --- 9. artifact_import ---


class ArtifactImportRequest(BaseModel):
    """Request to import artifacts from a file."""
    path: str = Field(description="Path to the import file")
    dry_run: bool = Field(default=False, description="If True, validate without actually importing")


class ArtifactImportResponse(BaseModel):
    """Response after import."""
    imported: int = Field(description="Number of artifacts successfully imported")
    skipped: int = Field(description="Number of artifacts skipped (duplicates or invalid)")
    errors: list[str] = Field(default_factory=list, description="Error messages for failed imports")


# --- 10. artifact_feedback (record usage feedback) ---


class ArtifactFeedbackRequest(BaseModel):
    """Request to record usage feedback on an artifact."""
    artifact_id: str = Field(description="The artifact ID to provide feedback on")
    useful: bool = Field(description="Whether the artifact was useful")
    note: str | None = Field(default=None, description="Optional note about why it was or wasn't useful")
    agent_id: str | None = Field(default=None, description="Agent providing feedback (defaults to 'main')")


class ArtifactFeedbackResponse(BaseModel):
    """Response after recording feedback."""
    success: bool
    feedback_id: str = Field(description="ID of the newly created feedback record")
    utility_score: float = Field(description="Updated Bayesian utility score for the artifact")


# --- 11. artifact_set_confidence ---


class ArtifactSetConfidenceRequest(BaseModel):
    """Request to set an artifact's confidence level."""
    artifact_id: str = Field(description="The artifact ID to update")
    confidence: str = Field(description="Confidence level: 'HIGH', 'MEDIUM', 'LOW', or 'SUPERSEDED'")
    reason: str | None = Field(default=None, description="Optional reason for the confidence level")


class ArtifactSetConfidenceResponse(BaseModel):
    """Response after setting confidence."""
    success: bool


# --- 12. artifact_retirement_candidates ---


class ArtifactRetirementCandidatesRequest(BaseModel):
    """Request to find artifacts that are candidates for retirement."""
    min_age_days: int = Field(default=30, ge=1, description="Minimum age in days to consider for retirement")
    max_utility: float = Field(default=0.3, ge=0.0, le=1.0, description="Maximum utility score threshold")
    limit: int = Field(default=20, ge=1, le=100, description="Max candidates to return")


class RetirementCandidate(BaseModel):
    """A single artifact that is a candidate for retirement."""
    id: str
    artifact_type: str
    content_preview: str = Field(description="First 200 characters of content")
    utility_score: float
    confidence: str | None
    last_retrieved: str | None
    created_at: str


class ArtifactRetirementCandidatesResponse(BaseModel):
    """Response with retirement candidates."""
    candidates: list[RetirementCandidate]
