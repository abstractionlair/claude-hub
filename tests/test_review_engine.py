"""Tests for review_engine module -- model registry, dispatch, status, and results."""

import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from claude_hub import review_engine
from claude_hub.review_engine import (
    DEFAULT_EXCLUDE_PATHS,
    _check_and_synthesize,
    _review_semaphore,
    _run_single_review,
    _synthesize_reviews,
    build_review_prompt,
    check_review_status,
    dispatch_review,
    get_registry,
    get_review_results,
    get_synthesis_config,
    load_model_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool():
    """Create a mock asyncpg pool with acquire() context manager.

    Returns both the pool and the connection object so tests can
    configure return values on conn.fetchval / conn.fetchrow / etc.
    """
    pool = MagicMock()
    conn = AsyncMock()

    # Make pool.acquire() work as async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    # Also support pool.fetch(), pool.fetchrow(), pool.execute() directly
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="UPDATE 1")

    # Default fetchval to None (used for artifact content lookups)
    conn.fetchval = AsyncMock(return_value=None)

    return pool, conn


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset module-level registry before each test to prevent pollution."""
    review_engine._model_registry = None
    review_engine._synthesis_config = None
    yield
    review_engine._model_registry = None
    review_engine._synthesis_config = None


@pytest.fixture
def sample_registry():
    """A minimal valid model registry dict."""
    return {
        "claude": {
            "invoke": ["claude", "-p", "{prompt_file}", "--file", "{file}"],
            "mode": "agentic",
            "timeout_seconds": 300,
            "clean_room_flags": ["--no-context"],
        },
        "gemini": {
            "invoke": ["gemini", "-p", "review {file}"],
            "mode": "agentic",
            "timeout_seconds": 120,
        },
    }


@pytest.fixture
def registry_yaml(tmp_path, sample_registry):
    """Write a valid YAML config to a temp file and return its path."""
    import yaml

    config = {"models": sample_registry}
    p = tmp_path / "review_models.yaml"
    p.write_text(yaml.dump(config), encoding="utf-8")
    return p


@pytest.fixture
def loaded_registry(registry_yaml):
    """Load the sample registry and return the dict (also sets module state)."""
    return load_model_registry(registry_yaml)


# ---------------------------------------------------------------------------
# 1. Model Registry Tests
# ---------------------------------------------------------------------------


class TestLoadModelRegistry:
    def test_load_model_registry_success(self, registry_yaml, sample_registry):
        """Loads YAML, returns dict with expected models."""
        result = load_model_registry(registry_yaml)

        assert isinstance(result, dict)
        assert "claude" in result
        assert "gemini" in result
        assert result["claude"]["invoke"] == sample_registry["claude"]["invoke"]
        assert result["claude"]["timeout_seconds"] == 300
        assert result["gemini"]["timeout_seconds"] == 120

    def test_load_model_registry_missing_file(self, tmp_path):
        """Raises FileNotFoundError when config file doesn't exist."""
        missing = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError, match="not found"):
            load_model_registry(missing)

    def test_load_model_registry_missing_required_fields(self, tmp_path):
        """Raises ValueError if a model entry is missing invoke or timeout_seconds."""
        import yaml

        config = {
            "models": {
                "broken_model": {
                    "invoke": ["echo", "hi"],
                    # missing timeout_seconds
                }
            }
        }
        p = tmp_path / "bad_models.yaml"
        p.write_text(yaml.dump(config), encoding="utf-8")

        with pytest.raises(ValueError, match="missing required fields"):
            load_model_registry(p)

    def test_load_model_registry_empty_models(self, tmp_path):
        """Raises ValueError if no models are defined."""
        import yaml

        config = {"models": {}}
        p = tmp_path / "empty.yaml"
        p.write_text(yaml.dump(config), encoding="utf-8")

        with pytest.raises(ValueError, match="No models defined"):
            load_model_registry(p)

    def test_get_registry_before_load(self):
        """Raises RuntimeError when registry hasn't been loaded."""
        with pytest.raises(RuntimeError, match="not loaded"):
            get_registry()

    def test_get_registry_after_load(self, loaded_registry):
        """Returns the loaded registry after successful load."""
        result = get_registry()

        assert result is loaded_registry
        assert "claude" in result


# ---------------------------------------------------------------------------
# 2. Parse Output Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3-4. Parse tests removed (model-forward: _parse_review_output,
#       _parse_synthesis_json, _extract_files_accessed deleted)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. Dispatch Tests
# ---------------------------------------------------------------------------


class TestDispatchReview:
    @pytest.mark.asyncio
    async def test_dispatch_review_creates_rows(self, loaded_registry):
        """Creates review rows for each model and returns job_id."""
        pool, conn = _mock_pool()

        # Each call to conn.fetchval returns a review_id
        review_id_1 = uuid.uuid4()
        review_id_2 = uuid.uuid4()
        conn.fetchval = AsyncMock(side_effect=[review_id_1, review_id_2])

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                content="Review this code",
                prompt="Find security issues",
            )

        assert "job_id" in result
        assert uuid.UUID(result["job_id"])  # valid UUID
        assert set(result["models_dispatched"]) == {"claude", "gemini"}

        # Two INSERT calls (one per model)
        assert conn.fetchval.call_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_review_validates_no_source(self, loaded_registry):
        """Raises ValueError if no content source is provided."""
        pool, conn = _mock_pool()

        with pytest.raises(ValueError, match="At least one"):
            await dispatch_review(pool, prompt="review this")

    @pytest.mark.asyncio
    async def test_dispatch_review_allows_files_and_content(self, loaded_registry):
        """Allows both files and content to be provided (not mutually exclusive)."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                files=["src/foo.py"],
                content="some text",
                prompt="review",
                models=["claude"],
            )

        assert "job_id" in result

    @pytest.mark.asyncio
    async def test_dispatch_review_unknown_model(self, loaded_registry):
        """Raises ValueError for an unknown model name."""
        pool, conn = _mock_pool()

        with pytest.raises(ValueError, match="Unknown model"):
            await dispatch_review(
                pool,
                content="some code",
                prompt="review",
                models=["nonexistent_model"],
            )

    @pytest.mark.asyncio
    async def test_dispatch_review_artifact_not_found(self, loaded_registry):
        """Raises ValueError if artifact_id doesn't exist in the store."""
        pool, conn = _mock_pool()
        fake_id = str(uuid.uuid4())

        with patch.object(
            review_engine.artifact_store_module,
            "get_artifact",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(ValueError, match="Artifact not found"):
                await dispatch_review(
                    pool,
                    artifact_id=fake_id,
                    prompt="review this artifact",
                )

    @pytest.mark.asyncio
    async def test_dispatch_review_with_files_list(self, loaded_registry):
        """Accepts files list for agentic review (paths not validated by dispatch)."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                files=["src/foo.py", "src/bar.py"],
                prompt="review these files",
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]

    @pytest.mark.asyncio
    async def test_dispatch_review_selected_models(self, loaded_registry):
        """Only dispatches to specified models when models list is given."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                content="Some code to review",
                prompt="review",
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]
        # Only one INSERT (just the claude model)
        assert conn.fetchval.call_count == 1

    @pytest.mark.asyncio
    async def test_dispatch_review_with_intent(self, loaded_registry):
        """Passes intent text through to prompt construction."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                files=["src/review_engine.py"],
                prompt="review this",
                intent="This module should dispatch reviews to multiple models",
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]

    @pytest.mark.asyncio
    async def test_dispatch_review_with_artifact_id(self, loaded_registry):
        """Resolves content from artifact store when artifact_id is provided."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        artifact_id = str(uuid.uuid4())
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch.object(
            review_engine.artifact_store_module,
            "get_artifact",
            new_callable=AsyncMock,
            return_value={"content": "artifact content here"},
        ), patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                artifact_id=artifact_id,
                prompt="review this artifact",
                models=["gemini"],
            )

        assert result["models_dispatched"] == ["gemini"]


# ---------------------------------------------------------------------------
# 5. Status Tests
# ---------------------------------------------------------------------------


class TestCheckReviewStatus:
    @pytest.mark.asyncio
    async def test_check_status_all_complete(self):
        """Returns status='complete' when synthesis exists."""
        pool, conn = _mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "model": "claude", "status": "complete", "completed_at": now},
            {"id": uuid.uuid4(), "model": "gemini", "status": "complete", "completed_at": now},
        ])
        conn.fetchval = AsyncMock(return_value=1)  # synthesis_exists = truthy

        result = await check_review_status(pool, str(uuid.uuid4()))

        assert result["status"] == "complete"
        assert result["completion_pct"] == 100.0
        assert len(result["models"]) == 2

    @pytest.mark.asyncio
    async def test_check_status_running(self):
        """Returns status='running' when some reviews are still pending."""
        pool, conn = _mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "model": "claude", "status": "complete", "completed_at": now},
            {"id": uuid.uuid4(), "model": "gemini", "status": "pending", "completed_at": None},
        ])
        conn.fetchval = AsyncMock(return_value=None)  # no synthesis

        result = await check_review_status(pool, str(uuid.uuid4()))

        assert result["status"] == "running"
        assert result["completion_pct"] == 50.0

    @pytest.mark.asyncio
    async def test_check_status_all_failed(self):
        """Returns status='failed' when all reviews failed."""
        pool, conn = _mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "model": "claude", "status": "failed", "completed_at": now},
            {"id": uuid.uuid4(), "model": "gemini", "status": "failed", "completed_at": now},
        ])
        conn.fetchval = AsyncMock(return_value=None)  # no synthesis

        result = await check_review_status(pool, str(uuid.uuid4()))

        assert result["status"] == "failed"
        assert result["completion_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_check_status_not_found(self):
        """Returns status='not_found' for unknown job_id."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchval = AsyncMock(return_value=None)

        result = await check_review_status(pool, str(uuid.uuid4()))

        assert result["status"] == "not_found"
        assert result["models"] == []
        assert result["completion_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_check_status_mixed_complete_and_timeout(self):
        """Timeout counts as done for completion percentage calculation."""
        pool, conn = _mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "model": "claude", "status": "complete", "completed_at": now},
            {"id": uuid.uuid4(), "model": "gemini", "status": "timeout", "completed_at": now},
        ])
        conn.fetchval = AsyncMock(return_value=None)

        result = await check_review_status(pool, str(uuid.uuid4()))

        # All done (complete + timeout), but no synthesis yet => running
        assert result["status"] == "running"
        assert result["completion_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_check_status_model_statuses_populated(self):
        """Individual model statuses include name, status, and completed_at."""
        pool, conn = _mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "model": "claude", "status": "running", "completed_at": None},
        ])
        conn.fetchval = AsyncMock(return_value=None)

        result = await check_review_status(pool, str(uuid.uuid4()))

        assert len(result["models"]) == 1
        assert result["models"][0]["name"] == "claude"
        assert result["models"][0]["status"] == "running"
        assert result["models"][0]["completed_at"] is None


# ---------------------------------------------------------------------------
# 6. Get Results Tests
# ---------------------------------------------------------------------------


class TestGetReviewResults:
    @pytest.mark.asyncio
    async def test_get_results_with_synthesis(self):
        """Returns full synthesis + individual reviews when complete."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        artifact_id = uuid.uuid4()
        synth_artifact_id = uuid.uuid4()
        review_id_1 = uuid.uuid4()
        review_id_2 = uuid.uuid4()
        now = datetime.now(timezone.utc)

        synth_row = {
            "artifact_id": artifact_id,
            "synthesis_artifact_id": synth_artifact_id,
            "review_ids": [review_id_1, review_id_2],
            "consensus": json.dumps([{"severity": "critical", "finding": "XSS"}]),
            "unique_findings": json.dumps({"claude": [{"finding": "style"}]}),
            "contradictions": json.dumps([]),
            "models_requested": ["claude", "gemini"],
            "models_responded": ["claude", "gemini"],
            "review_modes": json.dumps({"claude": "agentic", "gemini": "agentic"}),
        }
        conn.fetchrow = AsyncMock(return_value=synth_row)

        review_rows = [
            {
                "id": review_id_1,
                "model": "claude",
                "status": "complete",
                "findings": json.dumps([{"severity": "critical", "finding": "XSS"}]),
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
            {
                "id": review_id_2,
                "model": "gemini",
                "status": "complete",
                "findings": json.dumps([{"severity": "minor", "finding": "naming"}]),
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id, include_individual=True)

        assert result["status"] == "complete"
        assert result["job_id"] == job_id
        assert result["artifact_id"] == str(artifact_id)
        assert result["synthesis"] is not None
        assert len(result["synthesis"]["consensus"]) == 1
        assert result["synthesis"]["consensus"][0]["severity"] == "critical"
        assert "claude" in result["synthesis"]["unique_findings"]
        assert result["synthesis"]["contradictions"] == []
        assert result["synthesis"]["models_requested"] == ["claude", "gemini"]
        assert result["synthesis"]["models_responded"] == ["claude", "gemini"]
        assert result["reviews"] is not None
        assert len(result["reviews"]) == 2
        assert result["reviews"][0]["model"] == "claude"
        assert result["reviews"][1]["model"] == "gemini"

    @pytest.mark.asyncio
    async def test_get_results_without_individual(self):
        """Returns synthesis only when include_individual=False."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        synth_row = {
            "artifact_id": uuid.uuid4(),
            "synthesis_artifact_id": uuid.uuid4(),
            "review_ids": [uuid.uuid4()],
            "consensus": json.dumps([]),
            "unique_findings": json.dumps({}),
            "contradictions": json.dumps([]),
            "models_requested": ["claude"],
            "models_responded": ["claude"],
            "review_modes": json.dumps({"claude": "agentic"}),
        }
        conn.fetchrow = AsyncMock(return_value=synth_row)

        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "complete",
                "findings": json.dumps([]),
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id, include_individual=False)

        assert result["status"] == "complete"
        assert result["synthesis"] is not None
        assert result["reviews"] is None

    @pytest.mark.asyncio
    async def test_get_results_not_found(self):
        """Returns status='not_found' for unknown job_id."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())

        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])

        result = await get_review_results(pool, job_id)

        assert result["status"] == "not_found"
        assert result["job_id"] == job_id
        assert result["artifact_id"] is None
        assert result["synthesis"] is None
        assert result["reviews"] is None

    @pytest.mark.asyncio
    async def test_get_results_in_progress(self):
        """Returns status='running' and synthesis=None when still in progress."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        conn.fetchrow = AsyncMock(return_value=None)  # no synthesis yet
        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "complete",
                "findings": json.dumps([{"finding": "issue"}]),
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
            {
                "id": uuid.uuid4(),
                "model": "gemini",
                "status": "running",
                "findings": None,
                "clean_room": True,
                "started_at": now,
                "completed_at": None,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id)

        assert result["status"] == "running"
        assert result["synthesis"] is None
        assert result["reviews"] is not None
        assert len(result["reviews"]) == 2

    @pytest.mark.asyncio
    async def test_get_results_all_failed(self):
        """Returns status='failed' when all reviews have failed and no synthesis."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        conn.fetchrow = AsyncMock(return_value=None)  # no synthesis
        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "failed",
                "findings": None,
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
            {
                "id": uuid.uuid4(),
                "model": "gemini",
                "status": "failed",
                "findings": None,
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id)

        assert result["status"] == "failed"
        assert result["synthesis"] is None

    @pytest.mark.asyncio
    async def test_get_results_findings_deserialization(self):
        """Findings stored as JSON strings are deserialized into dicts."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        conn.fetchrow = AsyncMock(return_value=None)
        findings_data = [
            {"severity": "important", "finding": "Missing auth check"},
            {"severity": "minor", "finding": "Long function"},
        ]
        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "complete",
                "findings": json.dumps(findings_data),
                "clean_room": False,
                "started_at": now,
                "completed_at": now,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id)

        assert result["reviews"] is not None
        assert len(result["reviews"][0]["findings"]) == 2
        assert result["reviews"][0]["findings"][0]["severity"] == "important"
        assert result["reviews"][0]["clean_room"] is False

    @pytest.mark.asyncio
    async def test_get_results_synthesis_fields_as_dicts(self):
        """Synthesis fields already returned as dicts (not strings) are handled."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Simulate DB driver returning pre-parsed JSONB as dicts
        synth_row = {
            "artifact_id": uuid.uuid4(),
            "synthesis_artifact_id": uuid.uuid4(),
            "review_ids": [uuid.uuid4()],
            "consensus": [{"finding": "agreed issue"}],  # already a list, not a string
            "unique_findings": {"claude": [{"finding": "solo"}]},  # already a dict
            "contradictions": [],
            "models_requested": ["claude"],
            "models_responded": ["claude"],
            "review_modes": {"claude": "agentic"},  # already a dict
        }
        conn.fetchrow = AsyncMock(return_value=synth_row)

        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "complete",
                "findings": [{"finding": "issue"}],  # already a list
                "clean_room": True,
                "started_at": now,
                "completed_at": now,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id)

        assert result["status"] == "complete"
        assert result["synthesis"]["consensus"] == [{"finding": "agreed issue"}]
        assert result["synthesis"]["unique_findings"] == {"claude": [{"finding": "solo"}]}
        assert result["reviews"][0]["findings"] == [{"finding": "issue"}]

    @pytest.mark.asyncio
    async def test_get_results_timestamps_iso_format(self):
        """started_at and completed_at are converted to ISO format strings."""
        pool, conn = _mock_pool()
        job_id = str(uuid.uuid4())
        ts = datetime(2026, 3, 5, 14, 30, 0, tzinfo=timezone.utc)

        conn.fetchrow = AsyncMock(return_value=None)
        review_rows = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "status": "complete",
                "findings": json.dumps([]),
                "clean_room": True,
                "started_at": ts,
                "completed_at": ts,
            },
        ]
        conn.fetch = AsyncMock(return_value=review_rows)

        result = await get_review_results(pool, job_id)

        review = result["reviews"][0]
        assert review["started_at"] == ts.isoformat()
        assert review["completed_at"] == ts.isoformat()


# ---------------------------------------------------------------------------
# 7. Prompt Construction Tests
# ---------------------------------------------------------------------------


class TestBuildReviewPrompt:
    def test_build_prompt_with_files(self):
        """Includes file list in the prompt."""
        result = build_review_prompt(files=["src/foo.py", "src/bar.py"])
        assert "## Files to Review" in result
        assert "- src/foo.py" in result
        assert "- src/bar.py" in result

    def test_build_prompt_with_intent(self):
        """Includes intent section in the prompt."""
        result = build_review_prompt(
            files=["src/foo.py"],
            intent="This module implements user authentication via JWT tokens",
        )
        assert "## Intent" in result
        assert "JWT tokens" in result

    def test_build_prompt_with_context_files(self):
        """Includes suggested context files."""
        result = build_review_prompt(
            files=["src/new.py"],
            context_files=["src/existing.py", "tests/test_existing.py"],
        )
        assert "## Suggested Context" in result
        assert "- src/existing.py" in result
        assert "- tests/test_existing.py" in result

    def test_build_prompt_default_excludes(self):
        """Default exclude paths are included in boundaries."""
        result = build_review_prompt(files=["src/foo.py"])
        assert "## Boundaries" in result
        for path in DEFAULT_EXCLUDE_PATHS:
            assert path in result

    def test_build_prompt_custom_excludes(self):
        """Custom exclude paths override defaults."""
        result = build_review_prompt(
            files=["src/foo.py"],
            exclude_paths=["vendor/", "generated/"],
        )
        assert "vendor/" in result
        assert "generated/" in result
        # Default excludes should NOT appear
        assert "CLAUDE.md" not in result

    def test_build_prompt_include_overrides_exclude(self):
        """Include paths remove matching excludes."""
        result = build_review_prompt(
            files=["src/foo.py"],
            include_paths=["docs/design/spec.md"],
        )
        # thoughts/ledgers/ and thoughts/history/ are default excludes
        # but docs/design/spec.md shouldn't trigger removal of those
        assert "## Boundaries" in result
        assert "Exception" in result
        assert "docs/design/spec.md" in result

    def test_build_prompt_review_approach(self):
        """Includes prose review approach instructions (model-forward)."""
        result = build_review_prompt(files=["src/foo.py"])
        assert "## Review Approach" in result
        assert "Write your review as prose" in result
        assert "no required format" in result
        # Old structured format should be gone
        assert "## Output Format" not in result

    def test_build_prompt_empty_files(self):
        """No files section when files is None or empty."""
        result = build_review_prompt(prompt="General review")
        assert "## Files to Review" not in result


# ---------------------------------------------------------------------------
# 8. Agentic Dispatch Tests
# ---------------------------------------------------------------------------


class TestAgenticDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_sensitive_artifact_rejected(self, loaded_registry):
        """Raises ValueError when trying to review a sensitive artifact."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        with patch.object(
            review_engine.artifact_store_module,
            "get_artifact",
            new_callable=AsyncMock,
            return_value={"content": "secret stuff", "sensitive": True},
        ):
            with pytest.raises(ValueError, match="sensitive"):
                await dispatch_review(
                    pool,
                    artifact_id=artifact_id,
                    prompt="review this",
                )

    @pytest.mark.asyncio
    async def test_dispatch_max_input_chars_skips_model(self, loaded_registry):
        """Models with exceeded max_input_chars are skipped, not errored."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        # Override registry to have a model with very low max_input_chars
        review_engine._model_registry["tiny"] = {
            "invoke": ["echo", "{prompt}"],
            "timeout_seconds": 10,
            "mode": "agentic",
            "max_input_chars": 10,  # Very low -- will be skipped
        }

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                content="A" * 100,  # Exceeds tiny's limit
                prompt="review",
                models=["claude", "tiny"],
            )

        assert "claude" in result["models_dispatched"]
        assert "tiny" not in result["models_dispatched"]
        assert "tiny" in result.get("models_skipped", [])

    @pytest.mark.asyncio
    async def test_dispatch_intent_ref_file(self, loaded_registry, tmp_path, monkeypatch):
        """Resolves intent_ref from a relative file path."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        # Write intent file inside tmp_path and use it as CWD
        intent_file = tmp_path / "spec.md"
        intent_file.write_text("R2.1: Reviews must be agentic", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                files=["src/review_engine.py"],
                prompt="review against spec",
                intent_ref="spec.md",  # relative path
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]

    @pytest.mark.asyncio
    async def test_dispatch_intent_ref_rejects_absolute_path(self, loaded_registry):
        """Raises ValueError if intent_ref is an absolute path."""
        pool, conn = _mock_pool()

        with pytest.raises(ValueError, match="must be a relative path"):
            await dispatch_review(
                pool,
                files=["src/foo.py"],
                prompt="review",
                intent_ref="/etc/passwd",
                models=["claude"],
            )

    @pytest.mark.asyncio
    async def test_dispatch_intent_ref_rejects_traversal(self, loaded_registry, tmp_path, monkeypatch):
        """Raises ValueError if intent_ref contains path traversal."""
        pool, conn = _mock_pool()
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="path traversal"):
            await dispatch_review(
                pool,
                files=["src/foo.py"],
                prompt="review",
                intent_ref="../../../etc/passwd",
                models=["claude"],
            )

    @pytest.mark.asyncio
    async def test_dispatch_intent_ref_artifact(self, loaded_registry):
        """Resolves intent_ref from an artifact UUID."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        intent_artifact_id = str(uuid.uuid4())
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch.object(
            review_engine.artifact_store_module,
            "get_artifact",
            new_callable=AsyncMock,
            return_value={"content": "R2.1: Reviews must be agentic"},
        ), patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                files=["src/review_engine.py"],
                prompt="review against spec",
                intent_ref=intent_artifact_id,
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]

    @pytest.mark.asyncio
    async def test_dispatch_stores_invocation_mode(self, loaded_registry):
        """INSERT query includes invocation_mode from model config."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            await dispatch_review(
                pool,
                content="some code",
                prompt="review",
                models=["claude"],
            )

        # Check the INSERT call included invocation_mode
        insert_call = conn.fetchval.call_args
        # Args: query, job_id, artifact_id, model_name, prompt, clean_room, mode
        # The 7th positional arg (index 6) should be the mode
        assert insert_call[0][6] == "agentic"


# ---------------------------------------------------------------------------
# 9. Synthesis Tests
# ---------------------------------------------------------------------------


class TestSynthesis:
    @pytest.mark.asyncio
    async def test_check_and_synthesize_race_condition(self):
        """UNIQUE constraint prevents duplicate synthesis on concurrent calls."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        # Support conn.transaction() as async context manager
        txn_ctx = AsyncMock()
        txn_ctx.__aenter__ = AsyncMock(return_value=None)
        txn_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_ctx)

        # All reviews done (inside transaction: pending_count, already_synthesized, completed_rows)
        conn.fetchval = AsyncMock(
            side_effect=[
                0,     # pending_count = 0
                None,  # already_synthesized = None
            ]
        )
        # completed_rows (inside transaction), then all_models (in empty synth path)
        conn.fetch = AsyncMock(
            side_effect=[
                [],  # completed_rows = empty
                [{"model": "claude"}, {"model": "gemini"}],  # all_models
            ]
        )

        # Simulate UniqueViolationError on INSERT (race -- another task got there first)
        async def mock_execute(query, *args):
            if "INSERT INTO review_syntheses" in query:
                raise asyncpg.UniqueViolationError("duplicate key")
            return "UPDATE 1"

        conn.execute = mock_execute

        # Should NOT raise -- catches UniqueViolationError gracefully
        await _check_and_synthesize(pool, job_id)

    @pytest.mark.asyncio
    async def test_synthesis_uses_configured_model(self):
        """Synthesis uses the model specified in synthesis config."""
        # After loading a registry with synthesis config, verify it's accessible
        assert get_synthesis_config()["model"] == "claude"
        assert get_synthesis_config()["timeout_seconds"] == 120


# ---------------------------------------------------------------------------
# 10. Files Accessed Extraction Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. Backward Compatibility Tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_dispatch_with_content_only(self, loaded_registry):
        """Content-only dispatch works (bundled fallback for doc reviews)."""
        pool, conn = _mock_pool()
        review_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=review_id)

        with patch("asyncio.create_task"):
            result = await dispatch_review(
                pool,
                content="Review this document content",
                prompt="Check for clarity",
                models=["claude"],
            )

        assert result["models_dispatched"] == ["claude"]


# ---------------------------------------------------------------------------
# 12. Bundled Mode Execution Path Tests
# ---------------------------------------------------------------------------


class TestBundledModeExecution:
    """Test that bundled mode writes content+prompt to temp files and substitutes placeholders."""

    @pytest.mark.asyncio
    async def test_bundled_mode_writes_temp_files_and_substitutes(self, loaded_registry):
        """When mode='bundled' and content is provided, writes both content and prompt to
        temp files and substitutes {file} and {prompt_file} in the invoke template."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        model_config = {
            "invoke": ["cat", "{file}", "{prompt_file}"],
            "timeout_seconds": 60,
            "mode": "bundled",
        }

        captured_cmd = []
        captured_kwargs = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            captured_kwargs.update(kwargs)
            # Verify temp files exist at call time
            assert os.path.isfile(cmd[1]), f"content file {cmd[1]} should exist"
            assert os.path.isfile(cmd[2]), f"prompt file {cmd[2]} should exist"
            # Verify content of the temp files
            with open(cmd[1]) as f:
                assert f.read() == "bundled content here"
            with open(cmd[2]) as f:
                assert "Find bugs" in f.read()
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="test-bundled",
                        model_config=model_config,
                        task_prompt="Find bugs",
                        content="bundled content here",
                        clean_room=False,
                    )

        # Verify that the cmd used substituted paths (not raw {file}/{prompt_file})
        assert len(captured_cmd) == 3
        assert "{file}" not in captured_cmd[1]
        assert "{prompt_file}" not in captured_cmd[2]
        assert captured_cmd[1].endswith("content.md")
        assert captured_cmd[2].endswith("prompt.md")

    @pytest.mark.asyncio
    async def test_bundled_mode_no_content_uses_agentic_path(self, loaded_registry):
        """When mode='bundled' but content is None, falls through to agentic path."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        model_config = {
            "invoke": ["echo", "{prompt_file}"],
            "timeout_seconds": 60,
            "mode": "bundled",
        }

        captured_cmd = []

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="test-bundled-no-content",
                        model_config=model_config,
                        task_prompt="Review this",
                        content=None,
                        clean_room=False,
                    )

        # Should still have substituted prompt_file but NOT written content.md
        assert len(captured_cmd) == 2
        assert "{prompt_file}" not in captured_cmd[1]
        assert captured_cmd[1].endswith("prompt.md")


# ---------------------------------------------------------------------------
# 13. Semaphore Concurrency Limit Tests
# ---------------------------------------------------------------------------


class TestSemaphoreConcurrencyLimit:
    """Test that _review_semaphore limits concurrent reviews to 3."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency_to_3(self, loaded_registry):
        """Verifies at most 3 reviews run concurrently under the semaphore."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def slow_to_thread(fn, *args, **kwargs):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            # Simulate work
            await asyncio.sleep(0.05)
            async with lock:
                current_concurrent -= 1
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        model_config = {
            "invoke": ["echo", "{prompt}"],
            "timeout_seconds": 60,
            "mode": "agentic",
        }

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=slow_to_thread):
            with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                # Launch 6 reviews concurrently
                tasks = []
                for i in range(6):
                    task = asyncio.create_task(
                        _run_single_review(
                            pool=pool,
                            review_id=uuid.uuid4(),
                            job_id=uuid.uuid4(),
                            model_name=f"model-{i}",
                            model_config=model_config,
                            task_prompt="review",
                            content=None,
                            clean_room=False,
                        )
                    )
                    tasks.append(task)

                await asyncio.gather(*tasks)

        # The semaphore should have limited concurrency to 3
        assert max_concurrent <= 3, f"Expected max 3 concurrent, got {max_concurrent}"
        # Also verify that at least 2 ran concurrently (sanity check that
        # parallelism actually happened)
        assert max_concurrent >= 2, f"Expected at least 2 concurrent, got {max_concurrent}"


# ---------------------------------------------------------------------------
# 14. Non-Zero Exit Code -> Failed Status Tests
# ---------------------------------------------------------------------------


class TestNonZeroExitCodeFailedStatus:
    """Test that non-zero exit code from subprocess.run results in status='failed'."""

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_sets_failed_status(self, loaded_registry):
        """When subprocess.run returns a non-zero exit code, the DB is updated with status='failed'."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        model_config = {
            "invoke": ["false"],
            "timeout_seconds": 60,
            "mode": "agentic",
        }

        def fake_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = "partial output"
            result.stderr = "something went wrong"
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="failing-model",
                        model_config=model_config,
                        task_prompt="review",
                        content=None,
                        clean_room=False,
                    )

        # Find the UPDATE call that sets status='failed'
        failed_update_found = False
        for call in conn.execute.call_args_list:
            args = call[0]
            if len(args) >= 1 and isinstance(args[0], str) and "status = 'failed'" in args[0]:
                failed_update_found = True
                break

        assert failed_update_found, (
            "Expected an UPDATE query setting status='failed' for non-zero exit code. "
            f"Calls were: {[c[0][0][:80] for c in conn.execute.call_args_list if c[0]]}"
        )

    @pytest.mark.asyncio
    async def test_zero_exit_code_sets_complete_status(self, loaded_registry):
        """When subprocess.run returns exit code 0, the DB is updated with status='complete'."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        model_config = {
            "invoke": ["echo", "{prompt}"],
            "timeout_seconds": 60,
            "mode": "agentic",
        }

        def fake_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": [{"severity": "minor", "finding": "test"}]}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="success-model",
                        model_config=model_config,
                        task_prompt="review",
                        content=None,
                        clean_room=False,
                    )

        # Find the UPDATE call that sets status='complete'
        complete_update_found = False
        for call in conn.execute.call_args_list:
            args = call[0]
            if len(args) >= 1 and isinstance(args[0], str) and "status = 'complete'" in args[0]:
                complete_update_found = True
                break

        assert complete_update_found, (
            "Expected an UPDATE query setting status='complete' for zero exit code."
        )


# ---------------------------------------------------------------------------
# 15. stdin_prompt Support Tests
# ---------------------------------------------------------------------------


class TestStdinPromptSupport:
    """Test that stdin_prompt: true passes input to subprocess.run."""

    @pytest.mark.asyncio
    async def test_stdin_prompt_passes_input_kwarg(self, loaded_registry):
        """When model_config has stdin_prompt=True, subprocess.run receives input=task_prompt."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        task_prompt = "Please review this code carefully"
        model_config = {
            "invoke": ["cat"],
            "timeout_seconds": 60,
            "mode": "agentic",
            "stdin_prompt": True,
        }

        captured_kwargs = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="stdin-model",
                        model_config=model_config,
                        task_prompt=task_prompt,
                        content=None,
                        clean_room=False,
                    )

        assert "input" in captured_kwargs, "Expected 'input' kwarg when stdin_prompt=True"
        assert captured_kwargs["input"] == task_prompt

    @pytest.mark.asyncio
    async def test_no_stdin_prompt_omits_input_kwarg(self, loaded_registry):
        """When stdin_prompt is not set, subprocess.run does NOT receive input kwarg."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        model_config = {
            "invoke": ["echo", "{prompt}"],
            "timeout_seconds": 60,
            "mode": "agentic",
            # stdin_prompt is absent (defaults to False)
        }

        captured_kwargs = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="no-stdin-model",
                        model_config=model_config,
                        task_prompt="review",
                        content=None,
                        clean_room=False,
                    )

        assert "input" not in captured_kwargs, "Expected no 'input' kwarg when stdin_prompt is absent"


# ---------------------------------------------------------------------------
# 16. intent_ref Path Validation Tests (verify existing)
# ---------------------------------------------------------------------------


class TestIntentRefPathValidation:
    """Verify intent_ref rejects absolute paths and path traversal.

    These tests were added by the engine agent during C5 fixes. We confirm
    they exist (tests 5a, 5b in the coverage requirements).
    """

    @pytest.mark.asyncio
    async def test_intent_ref_absolute_path_rejected(self, loaded_registry):
        """intent_ref with an absolute path raises ValueError."""
        pool, conn = _mock_pool()

        with pytest.raises(ValueError, match="must be a relative path"):
            await dispatch_review(
                pool,
                files=["src/foo.py"],
                prompt="review",
                intent_ref="/etc/shadow",
                models=["claude"],
            )

    @pytest.mark.asyncio
    async def test_intent_ref_traversal_rejected(self, loaded_registry, tmp_path, monkeypatch):
        """intent_ref with ../ traversal outside repo raises ValueError."""
        pool, conn = _mock_pool()
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="path traversal"):
            await dispatch_review(
                pool,
                files=["src/foo.py"],
                prompt="review",
                intent_ref="../../etc/passwd",
                models=["claude"],
            )


# ---------------------------------------------------------------------------
# 17. Synthesis Fallback Removed -> RuntimeError Tests
# ---------------------------------------------------------------------------


class TestSynthesisRuntimeError:
    """Test that _synthesize_reviews raises RuntimeError when synthesis model is not in registry."""

    @pytest.mark.asyncio
    async def test_synthesis_raises_when_model_not_in_registry(self, loaded_registry):
        """When synth_model is not in the registry, _synthesize_reviews logs RuntimeError."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        conn.fetch = AsyncMock(return_value=[
            {"model": "claude"},
            {"model": "gemini"},
        ])

        # Override the synthesis config to point to a model not in registry
        review_engine._synthesis_config = {
            "model": "nonexistent-synth-model",
            "timeout_seconds": 60,
        }

        job_id = uuid.uuid4()
        reviews = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "findings": json.dumps([{"severity": "minor", "finding": "test"}]),
                "raw_content": "raw output",
                "artifact_id": None,
                "invocation_mode": "agentic",
            },
        ]

        # The RuntimeError is caught by the broad except Exception clause
        # Verify the error is logged and empty synthesis data is stored
        with patch("claude_hub.review_engine.artifact_store_module.store_artifact",
                    new_callable=AsyncMock, return_value={"artifact_id": str(uuid.uuid4())}):
            await _synthesize_reviews(pool, job_id, reviews)

        # Verify the synthesis row was still inserted (with empty consensus)
        insert_found = False
        for call in conn.execute.call_args_list:
            args = call[0]
            if len(args) >= 1 and isinstance(args[0], str) and "INSERT INTO review_syntheses" in args[0]:
                insert_found = True
                # The consensus should be empty (since synthesis failed)
                consensus_arg = args[5]  # $5 = consensus
                parsed = json.loads(consensus_arg)
                assert parsed == [], f"Expected empty consensus after RuntimeError, got {parsed}"
                break

        assert insert_found, "Expected review_syntheses INSERT even when synthesis model is missing"

    @pytest.mark.asyncio
    async def test_synthesis_runtime_error_is_logged(self, loaded_registry):
        """Verify the RuntimeError is caught and logged when synth model config is None."""
        review_engine._synthesis_config = {
            "model": "phantom-model",
            "timeout_seconds": 60,
        }

        registry = get_registry()
        assert "phantom-model" not in registry

        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        conn.fetch = AsyncMock(return_value=[{"model": "claude"}])

        reviews = [
            {
                "id": uuid.uuid4(),
                "model": "claude",
                "findings": "[]",
                "raw_content": "",
                "artifact_id": None,
                "invocation_mode": "agentic",
            },
        ]

        with patch("claude_hub.review_engine.artifact_store_module.store_artifact",
                    new_callable=AsyncMock, return_value={"artifact_id": str(uuid.uuid4())}):
            with patch("claude_hub.review_engine.logger") as mock_logger:
                await _synthesize_reviews(pool, job_id=uuid.uuid4(), reviews=reviews)
                # The RuntimeError should have been caught and logged
                mock_logger.exception.assert_called()
                logged_msg = mock_logger.exception.call_args[0][0]
                assert "Synthesis failed" in logged_msg


# ---------------------------------------------------------------------------
# 18. Content Written to File for Agentic Models Tests
# ---------------------------------------------------------------------------


class TestAgenticContentWrittenToFile:
    """Test that agentic mode writes content to review_subject.md and prepends NOTE."""

    @pytest.mark.asyncio
    async def test_agentic_mode_writes_content_file(self, loaded_registry):
        """When mode=agentic and content is not None, a review_subject.md file is written."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        original_prompt = "Review for security issues"
        content = "def vulnerable_func():\n    return input()"
        model_config = {
            "invoke": ["echo", "{prompt_file}"],
            "timeout_seconds": 60,
            "mode": "agentic",
        }

        captured_prompt_content = None

        def fake_subprocess_run(cmd, **kwargs):
            nonlocal captured_prompt_content
            # Read the prompt file to check its contents
            prompt_file = cmd[1]  # second arg is the prompt_file path
            with open(prompt_file) as f:
                captured_prompt_content = f.read()
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="agentic-model",
                        model_config=model_config,
                        task_prompt=original_prompt,
                        content=content,
                        clean_room=False,
                    )

        # The prompt should contain the NOTE about the content file path
        assert captured_prompt_content is not None
        assert "NOTE: The content to review has been written to:" in captured_prompt_content
        assert "review_subject.md" in captured_prompt_content
        # The original prompt should follow the NOTE
        assert original_prompt in captured_prompt_content

    @pytest.mark.asyncio
    async def test_agentic_mode_no_content_no_note(self, loaded_registry):
        """When mode=agentic and content is None, no NOTE is prepended."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        review_id = uuid.uuid4()
        job_id = uuid.uuid4()
        original_prompt = "Review for security issues"
        model_config = {
            "invoke": ["echo", "{prompt_file}"],
            "timeout_seconds": 60,
            "mode": "agentic",
        }

        captured_prompt_content = None

        def fake_subprocess_run(cmd, **kwargs):
            nonlocal captured_prompt_content
            prompt_file = cmd[1]
            with open(prompt_file) as f:
                captured_prompt_content = f.read()
            result = MagicMock()
            result.returncode = 0
            result.stdout = '{"findings": []}'
            result.stderr = ""
            return result

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with patch("claude_hub.review_engine._check_and_synthesize", new_callable=AsyncMock):
                    await _run_single_review(
                        pool=pool,
                        review_id=review_id,
                        job_id=job_id,
                        model_name="agentic-model",
                        model_config=model_config,
                        task_prompt=original_prompt,
                        content=None,
                        clean_room=False,
                    )

        # The prompt should NOT contain the NOTE
        assert captured_prompt_content is not None
        assert "NOTE:" not in captured_prompt_content
        assert captured_prompt_content == original_prompt
