"""Pydantic models for the review engine.

Helper/nested models (ModelStatus, ReviewSynthesis, IndividualReview) are used
by the CLI and engine internals.

Request/Response models (ReviewDispatchRequest, etc.) are retained for
documentation but no longer serve HTTP endpoints — the review engine is now
accessed via CLI (python -m claude_hub.review_cli), not MCP/HTTP.
"""

from pydantic import BaseModel, Field


# --- Nested / Helper Models ---


class ModelStatus(BaseModel):
    """Status of a single model within a review job."""
    name: str
    status: str = Field(description="Model status: 'pending', 'running', 'complete', 'failed', or 'timeout'")
    completed_at: str | None = None


class ReviewFinding(BaseModel):
    """A single structured finding from a review."""
    severity: str = Field(description="Finding severity: 'critical', 'important', 'minor', or 'unclassified'")
    finding: str
    model: str | None = Field(default=None, description="Model that produced this finding (set in synthesis context)")


class ReviewSynthesis(BaseModel):
    """Synthesized results across all model reviews."""
    consensus: list[dict] = Field(default_factory=list, description="DEPRECATED: Findings where 2+ models agree — use synthesis_prose")
    unique_findings: dict[str, list] = Field(default_factory=dict, description="DEPRECATED: Model name -> list of unique findings — use synthesis_prose")
    contradictions: list[dict] = Field(default_factory=list, description="DEPRECATED: Findings where models disagree — use synthesis_prose")
    models_requested: list[str]
    models_responded: list[str]
    review_modes: dict[str, str] = Field(default_factory=dict, description="Model name -> invocation mode (agentic/bundled)")
    synthesis_prose: str | None = Field(default=None, description="Prose synthesis from the synthesis model (canonical)")


class IndividualReview(BaseModel):
    """A single model's review output."""
    id: str
    model: str
    status: str = Field(description="Review status: 'pending', 'running', 'complete', 'failed', or 'timeout'")
    findings: list[dict] | None = Field(default=None, description="DEPRECATED: use raw_content — will be None for new reviews")
    raw_content: str | None = Field(default=None, description="Raw model output (canonical)")
    clean_room: bool
    invocation_mode: str = Field(default="agentic", description="How the model was invoked: 'agentic' or 'bundled'")
    started_at: str | None = None
    completed_at: str | None = None


# --- 1. review_dispatch ---


class ReviewDispatchRequest(BaseModel):
    """Request to dispatch a multi-model review."""
    files: list[str] | None = Field(default=None, description="File paths to review (agentic mode)")
    artifact_id: str | None = Field(default=None, description="UUID of artifact to review")
    content: str | None = Field(default=None, description="Raw text to review (bundled fallback)")
    prompt: str = Field(description="Review instructions")
    intent: str | None = Field(default=None, description="What the code should do — spec references, requirements, acceptance criteria")
    intent_ref: str | None = Field(default=None, description="File path or artifact ID referencing spec/requirements for intent context")
    context_files: list[str] | None = Field(default=None, description="Additional files for reviewer to read for conventions and patterns")
    models: list[str] | None = Field(default=None, description="Model names from registry; None = all configured")
    clean_room: bool = Field(default=True, description="Opinion-isolated review (default true, R2.6)")
    exclude_paths: list[str] | None = Field(default=None, description="Paths reviewers should not read (defaults to process docs)")
    include_paths: list[str] | None = Field(default=None, description="Paths to explicitly include even if under an exclude prefix")


class ReviewDispatchResponse(BaseModel):
    """Response after dispatching a review job."""
    job_id: str
    models_dispatched: list[str]
    models_skipped: list[str] | None = Field(default=None, description="Models skipped due to prompt exceeding their input limit")


# --- 2. review_status ---


class ReviewStatusRequest(BaseModel):
    """Request to check the status of a review job."""
    job_id: str = Field(description="The review job ID to check")


class ReviewStatusResponse(BaseModel):
    """Status of a review job and its constituent model reviews."""
    status: str = Field(description="Overall job status: 'pending', 'running', 'complete', or 'failed'")
    models: list[ModelStatus]
    completion_pct: float = Field(description="Percentage of models that have completed (0.0 - 100.0)")


# --- 3. review_get ---


class ReviewGetRequest(BaseModel):
    """Request to retrieve review results."""
    job_id: str = Field(description="The review job ID to retrieve")
    include_individual: bool = Field(default=True, description="Whether to include individual model reviews")


class ReviewGetResponse(BaseModel):
    """Full review results including synthesis and individual reviews."""
    job_id: str
    artifact_id: str | None = None
    synthesis: ReviewSynthesis | None = Field(
        default=None, description="Synthesized results, None if review is still in progress"
    )
    reviews: list[IndividualReview] | None = Field(
        default=None, description="Individual model reviews, None if include_individual was False"
    )
    status: str = Field(description="Overall job status: 'pending', 'running', 'complete', or 'failed'")
