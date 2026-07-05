"""Tests for Knowledge Quality features -- feedback, confidence, retirement, quality-weighted search, and review grading."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.artifact_store import (
    ArtifactNotFoundError,
    get_retirement_candidates,
    record_feedback,
    search_artifacts,
    set_confidence,
)
from claude_hub.review_engine import (
    _grade_reviewers,
    get_review_quality,
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

    return pool, conn


# ---------------------------------------------------------------------------
# TestRecordFeedback
# ---------------------------------------------------------------------------


class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_successful_positive_feedback(self):
        """Positive feedback: 1 positive -> (1+1)/(1+2) = 0.67 utility_score."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())
        feedback_id = uuid.uuid4()

        conn.fetchval = AsyncMock(
            side_effect=[
                1,            # artifact exists check
                1,            # max version
                feedback_id,  # INSERT RETURNING id
            ]
        )
        conn.fetchrow = AsyncMock(
            return_value={"count_useful": 1, "count_total": 1}
        )
        conn.execute = AsyncMock()

        result = await record_feedback(pool, artifact_id, useful=True)

        assert result["success"] is True
        assert result["feedback_id"] == str(feedback_id)
        assert abs(result["utility_score"] - 2 / 3) < 1e-9  # (1+1)/(1+2)

        # Verify the utility_score UPDATE was called
        conn.execute.assert_awaited_once()
        update_args = conn.execute.call_args[0]
        assert "UPDATE artifacts SET utility_score" in update_args[0]
        assert abs(update_args[1] - 2 / 3) < 1e-9

    @pytest.mark.asyncio
    async def test_successful_negative_feedback(self):
        """Negative feedback: 1 negative -> (0+1)/(1+2) = 0.33 utility_score."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())
        feedback_id = uuid.uuid4()

        conn.fetchval = AsyncMock(
            side_effect=[
                1,            # artifact exists
                1,            # max version
                feedback_id,  # INSERT RETURNING id
            ]
        )
        conn.fetchrow = AsyncMock(
            return_value={"count_useful": 0, "count_total": 1}
        )
        conn.execute = AsyncMock()

        result = await record_feedback(pool, artifact_id, useful=False)

        assert result["success"] is True
        assert abs(result["utility_score"] - 1 / 3) < 1e-9  # (0+1)/(1+2)

    @pytest.mark.asyncio
    async def test_artifact_not_found(self):
        """fetchval returns None for existence check -> raises ArtifactNotFoundError."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        conn.fetchval = AsyncMock(return_value=None)  # artifact does not exist

        with pytest.raises(ArtifactNotFoundError, match="Artifact not found"):
            await record_feedback(pool, artifact_id, useful=True)

    @pytest.mark.asyncio
    async def test_content_version_recorded(self):
        """Max version is looked up and passed to the INSERT."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())
        feedback_id = uuid.uuid4()

        conn.fetchval = AsyncMock(
            side_effect=[
                1,            # artifact exists
                5,            # max version = 5
                feedback_id,  # INSERT RETURNING id
            ]
        )
        conn.fetchrow = AsyncMock(
            return_value={"count_useful": 1, "count_total": 1}
        )
        conn.execute = AsyncMock()

        await record_feedback(pool, artifact_id, useful=True)

        # The third fetchval call is the INSERT; verify content_version = 5
        insert_call = conn.fetchval.call_args_list[2]
        insert_args = insert_call[0]
        # args: (sql, artifact_id, useful, note, agent_id, content_version)
        assert insert_args[5] == 5  # content_version

    @pytest.mark.asyncio
    async def test_multiple_feedback_bayesian(self):
        """Multiple feedbacks: count_useful=3, count_total=4 -> (3+1)/(4+2) = 0.67."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())
        feedback_id = uuid.uuid4()

        conn.fetchval = AsyncMock(
            side_effect=[
                1,            # artifact exists
                2,            # max version
                feedback_id,  # INSERT RETURNING id
            ]
        )
        conn.fetchrow = AsyncMock(
            return_value={"count_useful": 3, "count_total": 4}
        )
        conn.execute = AsyncMock()

        result = await record_feedback(pool, artifact_id, useful=True)

        expected = (3 + 1) / (4 + 2)  # 4/6 = 0.6667
        assert abs(result["utility_score"] - expected) < 1e-9

    @pytest.mark.asyncio
    async def test_agent_id_passed_through(self):
        """agent_id parameter makes it to the INSERT statement."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())
        feedback_id = uuid.uuid4()

        conn.fetchval = AsyncMock(
            side_effect=[
                1,            # artifact exists
                1,            # max version
                feedback_id,  # INSERT RETURNING id
            ]
        )
        conn.fetchrow = AsyncMock(
            return_value={"count_useful": 1, "count_total": 1}
        )
        conn.execute = AsyncMock()

        await record_feedback(
            pool, artifact_id, useful=True, agent_id="sub-agent-42"
        )

        # The third fetchval call is the INSERT
        insert_call = conn.fetchval.call_args_list[2]
        insert_args = insert_call[0]
        # args: (sql, artifact_id, useful, note, agent_id, content_version)
        assert insert_args[4] == "sub-agent-42"


# ---------------------------------------------------------------------------
# TestSetConfidence
# ---------------------------------------------------------------------------


class TestSetConfidence:
    @pytest.mark.asyncio
    async def test_set_high_confidence(self):
        """Setting HIGH confidence executes UPDATE query and returns success."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        conn.fetchval = AsyncMock(return_value=1)  # artifact exists
        conn.execute = AsyncMock()

        result = await set_confidence(pool, artifact_id, "HIGH")

        assert result == {"success": True}

        # Verify the UPDATE was called
        conn.execute.assert_awaited_once()
        update_args = conn.execute.call_args[0]
        assert "UPDATE artifacts SET confidence" in update_args[0]
        assert update_args[1] == "HIGH"

    @pytest.mark.asyncio
    async def test_set_superseded_with_reason(self):
        """Setting SUPERSEDED with reason merges confidence_reason into metadata."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        conn.fetchval = AsyncMock(return_value=1)  # artifact exists
        conn.execute = AsyncMock()

        result = await set_confidence(
            pool, artifact_id, "SUPERSEDED", reason="Replaced by newer learning"
        )

        assert result == {"success": True}

        # Verify the UPDATE uses JSONB merge for the reason
        update_args = conn.execute.call_args[0]
        sql = update_args[0]
        assert "metadata || " in sql or "metadata =" in sql
        # The reason JSON should be in the args
        reason_json = json.loads(update_args[2])
        assert reason_json == {"confidence_reason": "Replaced by newer learning"}

    @pytest.mark.asyncio
    async def test_invalid_confidence_raises(self):
        """confidence='INVALID' raises ValueError before any DB call."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        with pytest.raises(ValueError, match="Invalid confidence value"):
            await set_confidence(pool, artifact_id, "INVALID")

        # No DB calls should have been made
        conn.fetchval.assert_not_awaited()
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_artifact_not_found(self):
        """fetchval returns None for existence check -> raises ArtifactNotFoundError."""
        pool, conn = _mock_pool()
        artifact_id = str(uuid.uuid4())

        conn.fetchval = AsyncMock(return_value=None)  # artifact does not exist

        with pytest.raises(ArtifactNotFoundError, match="Artifact not found"):
            await set_confidence(pool, artifact_id, "HIGH")


# ---------------------------------------------------------------------------
# TestGetRetirementCandidates
# ---------------------------------------------------------------------------


class TestGetRetirementCandidates:
    @pytest.mark.asyncio
    async def test_returns_candidates(self):
        """Mock fetch returns rows; verify result structure."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        created = datetime(2025, 12, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_retrieved = datetime(2026, 1, 15, 8, 0, 0, tzinfo=timezone.utc)

        row = {
            "id": fake_id,
            "artifact_type": "learning",
            "content_preview": "Old artifact content...",
            "utility_score": 0.2,
            "confidence": "LOW",
            "last_retrieved": last_retrieved,
            "created_at": created,
        }
        conn.fetch = AsyncMock(return_value=[row])

        result = await get_retirement_candidates(pool)

        assert len(result["candidates"]) == 1
        candidate = result["candidates"][0]
        assert candidate["id"] == str(fake_id)
        assert candidate["artifact_type"] == "learning"
        assert candidate["content_preview"] == "Old artifact content..."
        assert candidate["utility_score"] == 0.2
        assert candidate["confidence"] == "LOW"
        assert candidate["last_retrieved"] == last_retrieved.isoformat()
        assert candidate["created_at"] == created.isoformat()

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Mock fetch returns empty list -> empty candidates."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        result = await get_retirement_candidates(pool)

        assert result["candidates"] == []

    @pytest.mark.asyncio
    async def test_parameters_passed_through(self):
        """min_age_days, max_utility, and limit are used in the query."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        await get_retirement_candidates(
            pool, min_age_days=60, max_utility=0.15, limit=5
        )

        fetch_call = conn.fetch.call_args
        args = fetch_call[0]
        # args: (sql, min_age_days_str, max_utility, limit)
        assert args[1] == "60"   # min_age_days passed as string
        assert args[2] == 0.15   # max_utility
        assert args[3] == 5      # limit

    @pytest.mark.asyncio
    async def test_query_includes_confidence_filter(self):
        """SQL query includes LOW/SUPERSEDED confidence in retirement conditions."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        await get_retirement_candidates(pool)

        fetch_call = conn.fetch.call_args
        sql = fetch_call[0][0]
        assert "confidence IN ('LOW', 'SUPERSEDED')" in sql

    @pytest.mark.asyncio
    async def test_superseded_artifacts_returned(self):
        """SUPERSEDED confidence artifacts are returned even with high utility_score."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        created = datetime(2025, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

        row = {
            "id": fake_id,
            "artifact_type": "learning",
            "content_preview": "Superseded artifact...",
            "utility_score": 0.9,  # High utility but SUPERSEDED
            "confidence": "SUPERSEDED",
            "last_retrieved": datetime(2026, 2, 1, 8, 0, 0, tzinfo=timezone.utc),
            "created_at": created,
        }
        conn.fetch = AsyncMock(return_value=[row])

        result = await get_retirement_candidates(pool)

        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["confidence"] == "SUPERSEDED"
        assert result["candidates"][0]["utility_score"] == 0.9

    @pytest.mark.asyncio
    async def test_low_confidence_artifacts_returned(self):
        """LOW confidence artifacts are returned as retirement candidates."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        created = datetime(2025, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

        row = {
            "id": fake_id,
            "artifact_type": "plan",
            "content_preview": "Low confidence artifact...",
            "utility_score": 0.8,  # High utility but LOW confidence
            "confidence": "LOW",
            "last_retrieved": datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
            "created_at": created,
        }
        conn.fetch = AsyncMock(return_value=[row])

        result = await get_retirement_candidates(pool)

        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["confidence"] == "LOW"

    @pytest.mark.asyncio
    async def test_null_utility_score_uses_coalesce(self):
        """NULL utility_score should be treated as 0.5 via COALESCE, not excluded."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        await get_retirement_candidates(pool)

        fetch_call = conn.fetch.call_args
        sql = fetch_call[0][0]
        assert "COALESCE(utility_score, 0.5)" in sql

    @pytest.mark.asyncio
    async def test_null_utility_score_in_result(self):
        """Artifacts with NULL utility_score are formatted with 0.5 default."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        created = datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

        row = {
            "id": fake_id,
            "artifact_type": "learning",
            "content_preview": "Never-rated artifact...",
            "utility_score": None,  # NULL utility
            "confidence": "MEDIUM",
            "last_retrieved": None,
            "created_at": created,
        }
        conn.fetch = AsyncMock(return_value=[row])

        result = await get_retirement_candidates(pool)

        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["utility_score"] == 0.5


# ---------------------------------------------------------------------------
# TestSearchQualityWeighted
# ---------------------------------------------------------------------------


class TestSearchQualityWeighted:
    @pytest.mark.asyncio
    async def test_search_includes_quality_fields(self):
        """Search result includes utility_score and confidence fields."""
        pool, conn = _mock_pool()
        fake_embedding = [0.1] * 768
        fake_id = uuid.uuid4()

        result_row = {
            "artifact_id": fake_id,
            "content_preview": "Quality weighted result...",
            "artifact_type": "learning",
            "tags": ["infra"],
            "base_score": 0.80,
            "confidence_boost": 0.1,
            "utility_boost": 0.05,
            "age_boost": -0.02,
            "final_score": 0.93,
            "utility_score": 0.75,
            "confidence": "HIGH",
            "created_at": datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        conn.fetch = AsyncMock(return_value=[result_row])
        conn.execute = AsyncMock()

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            results = await search_artifacts(pool, "find quality artifacts")

        assert len(results) == 1
        r = results[0]
        assert r["utility_score"] == 0.75
        assert r["confidence"] == "HIGH"
        assert r["score"] == 0.93

    @pytest.mark.asyncio
    async def test_last_retrieved_updated(self):
        """After search returns results, UPDATE last_retrieved is called on returned IDs."""
        pool, conn = _mock_pool()
        fake_embedding = [0.1] * 768
        fake_id = uuid.uuid4()

        result_row = {
            "artifact_id": fake_id,
            "content_preview": "Some content...",
            "artifact_type": "plan",
            "tags": [],
            "base_score": 0.70,
            "confidence_boost": 0.0,
            "utility_boost": 0.0,
            "age_boost": 0.0,
            "final_score": 0.70,
            "utility_score": 0.5,
            "confidence": "MEDIUM",
            "created_at": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        conn.fetch = AsyncMock(return_value=[result_row])
        conn.execute = AsyncMock()

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            results = await search_artifacts(pool, "search query")

        assert len(results) == 1

        # Verify UPDATE last_retrieved was called with the returned artifact IDs
        conn.execute.assert_awaited_once()
        update_args = conn.execute.call_args[0]
        assert "UPDATE artifacts SET last_retrieved" in update_args[0]
        assert fake_id in update_args[1]

    @pytest.mark.asyncio
    async def test_superseded_excluded_by_default(self):
        """SUPERSEDED artifacts are excluded unless include_archived=True."""
        pool, conn = _mock_pool()
        fake_embedding = [0.1] * 768
        conn.fetch = AsyncMock(return_value=[])

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            await search_artifacts(pool, "query")

        # Verify the SQL contains SUPERSEDED exclusion
        fetch_call = conn.fetch.call_args
        sql = fetch_call[0][0]
        assert "SUPERSEDED" in sql

    @pytest.mark.asyncio
    async def test_confidence_filter(self):
        """confidence='HIGH' adds a confidence filter to the WHERE clause."""
        pool, conn = _mock_pool()
        fake_embedding = [0.1] * 768
        conn.fetch = AsyncMock(return_value=[])

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            await search_artifacts(pool, "query", confidence="HIGH")

        # Verify the confidence filter was applied
        fetch_call = conn.fetch.call_args
        sql = fetch_call[0][0]
        assert "confidence = ANY" in sql
        # The allowed list should be passed as a parameter
        params = fetch_call[0][1:]
        # Find the list parameter (allowed confidence levels)
        found_confidence_list = False
        for p in params:
            if isinstance(p, list) and "HIGH" in p:
                found_confidence_list = True
                assert p == ["HIGH"]
                break
        assert found_confidence_list, "Expected confidence filter list in params"


# ---------------------------------------------------------------------------
# TestReviewGrading
# ---------------------------------------------------------------------------


class TestReviewGrading:
    @pytest.mark.asyncio
    async def test_grade_reviewers_inserts_grades(self):
        """Mock synthesis model returns valid JSON grades; verify INSERT into review_grades."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review from claude..."},
            {"model": "gemini", "raw_content": "Review from gemini..."},
        ]
        review_modes = {"claude": "agentic", "gemini": "headless"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "EXCELLENT", "note": "Thorough analysis"},
            {"model": "gemini", "grade": "ADEQUATE", "note": "Solid review"},
        ])

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = grades_json
        mock_result.stderr = ""

        synth_model_config = {
            "invoke": ["echo", "{prompt}"],
            "stdin_prompt": False,
            "timeout_seconds": 60,
        }

        mock_registry = {
            "claude": synth_model_config,
            "gemini": {"invoke": ["echo", "{prompt}"], "stdin_prompt": False, "timeout_seconds": 60},
        }

        # fetchval calls: cross_grade_count=0, existing_guard=0
        conn.fetchval = AsyncMock(return_value=0)

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            mock_to_thread.return_value = mock_result
            await _grade_reviewers(
                pool=pool,
                job_id=job_id,
                reviews=reviews,
                review_modes=review_modes,
                synthesis_prose="Consensus findings...",
                synth_model_config=synth_model_config,
                synth_timeout=60,
                review_type="spec",
            )

        # Cross-grading: each reviewer + synthesizer grades all reviews
        # With claude and gemini as reviewers, and claude as synthesizer (already included),
        # we get 2 graders × 2 reviews = 4 INSERT calls
        assert conn.execute.await_count == 4

        # Check that INSERT calls include grader_model
        first_call = conn.execute.call_args_list[0][0]
        assert "INSERT INTO review_grades" in first_call[0]
        assert first_call[1] == job_id  # job_id
        assert first_call[4] in ("EXCELLENT", "ADEQUATE")  # grade

    @pytest.mark.asyncio
    async def test_grade_reviewers_skips_if_grades_exist(self):
        """If grades already exist for job_id, skip insertion to prevent duplicates."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review from claude..."},
        ]
        review_modes = {"claude": "agentic"}

        synth_model_config = {
            "invoke": ["echo", "{prompt}"],
            "stdin_prompt": False,
            "timeout_seconds": 60,
        }

        mock_registry = {"claude": synth_model_config}

        # fetchval calls: cross_grade_count=0, then existing_guard=3 (grades exist)
        conn.fetchval = AsyncMock(side_effect=[0, 3])

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            await _grade_reviewers(
                pool=pool,
                job_id=job_id,
                reviews=reviews,
                review_modes=review_modes,
                synthesis_prose="Consensus findings...",
                synth_model_config=synth_model_config,
                synth_timeout=60,
                review_type="spec",
            )

        # No INSERT calls should have been made -- guard prevented them
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_grade_reviewers_handles_malformed_json(self):
        """Model returns garbage -> should log warning and not crash."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review content"},
        ]
        review_modes = {"claude": "agentic"}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "This is not valid JSON at all {{{garbage"
        mock_result.stderr = ""

        synth_model_config = {
            "invoke": ["echo", "{prompt}"],
            "stdin_prompt": False,
            "timeout_seconds": 60,
        }

        mock_registry = {"claude": synth_model_config}

        # fetchval: cross_grade_count=0, existing_guard=0
        conn.fetchval = AsyncMock(return_value=0)

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            mock_to_thread.return_value = mock_result
            # Should not raise
            await _grade_reviewers(
                pool=pool,
                job_id=job_id,
                reviews=reviews,
                review_modes=review_modes,
                synthesis_prose="Synthesis text...",
                synth_model_config=synth_model_config,
                synth_timeout=60,
                review_type="code",
            )

        # No grades should have been inserted (malformed JSON)
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_review_quality_by_model(self):
        """Query review grades filtered by model_name only."""
        pool, conn = _mock_pool()

        job_id = uuid.uuid4()
        created_at = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
        grade_row = {
            "job_id": job_id,
            "grade": "EXCELLENT",
            "note": "Found critical issues",
            "review_type": "spec",
            "created_at": created_at,
        }
        conn.fetch = AsyncMock(return_value=[grade_row])

        results = await get_review_quality(pool, model_name="gpt-5.4")

        assert len(results) == 1
        assert results[0]["job_id"] == str(job_id)
        assert results[0]["grade"] == "EXCELLENT"
        assert results[0]["note"] == "Found critical issues"
        assert results[0]["review_type"] == "spec"
        assert results[0]["created_at"] == created_at.isoformat()

        # Verify the query filters by model_name only (no review_type filter)
        fetch_call = conn.fetch.call_args[0]
        sql = fetch_call[0]
        assert "model_name = $1" in sql
        assert fetch_call[1] == "gpt-5.4"
        # Only two positional args: sql + model_name
        assert len(fetch_call) == 2

    @pytest.mark.asyncio
    async def test_get_review_quality_by_model_and_type(self):
        """Query review grades filtered by both model_name and review_type."""
        pool, conn = _mock_pool()

        conn.fetch = AsyncMock(return_value=[])

        results = await get_review_quality(
            pool, model_name="kimi-k2.5", review_type="code"
        )

        assert results == []

        # Verify the query filters by both model_name and review_type
        fetch_call = conn.fetch.call_args[0]
        sql = fetch_call[0]
        assert "model_name = $1" in sql
        assert "review_type = $2" in sql
        assert fetch_call[1] == "kimi-k2.5"
        assert fetch_call[2] == "code"
