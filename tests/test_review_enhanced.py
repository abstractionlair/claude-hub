"""Tests for enhanced review engine features: session capture, peer-disagreement, cross-grading."""

import json
import subprocess
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.review_engine import (
    _extract_session_and_text,
    _grade_reviewers,
    _peer_followup,
    _run_single_grading,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool():
    """Create a mock asyncpg pool with acquire() context manager."""
    pool = MagicMock()
    conn = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="UPDATE 1")

    conn.fetchval = AsyncMock(return_value=None)

    return pool, conn


MOCK_SYNTH_CONFIG = {
    "invoke": ["echo", "{prompt}"],
    "stdin_prompt": False,
    "timeout_seconds": 60,
}


# ---------------------------------------------------------------------------
# TestExtractSessionAndText
# ---------------------------------------------------------------------------


class TestExtractSessionAndText:
    def test_none_format_returns_unchanged(self):
        raw = "some raw output"
        session_id, text = _extract_session_and_text(raw, None)
        assert session_id is None
        assert text == raw

    def test_claude_json_extracts_session_and_result(self):
        raw = json.dumps({
            "type": "result",
            "result": "The code looks good overall.",
            "session_id": "abc-123-def",
            "cost_usd": 0.05,
        })
        session_id, text = _extract_session_and_text(raw, "claude")
        assert session_id == "abc-123-def"
        assert text == "The code looks good overall."

    def test_claude_json_missing_session_id(self):
        raw = json.dumps({"type": "result", "result": "Review text"})
        session_id, text = _extract_session_and_text(raw, "claude")
        assert session_id is None
        assert text == "Review text"

    def test_claude_json_missing_result_falls_back(self):
        raw = json.dumps({"session_id": "sid-1"})
        session_id, text = _extract_session_and_text(raw, "claude")
        assert session_id == "sid-1"
        assert text == raw  # falls back to raw_output

    def test_gemini_json_extracts_session_and_response(self):
        raw = json.dumps({
            "session_id": "gem-session-456",
            "response": "Found 3 issues in the codebase.",
        })
        session_id, text = _extract_session_and_text(raw, "gemini")
        assert session_id == "gem-session-456"
        assert text == "Found 3 issues in the codebase."

    def test_gemini_json_uses_text_field(self):
        raw = json.dumps({
            "session_id": "gem-2",
            "text": "Alternative text field.",
        })
        session_id, text = _extract_session_and_text(raw, "gemini")
        assert session_id == "gem-2"
        assert text == "Alternative text field."

    def test_gemini_json_uses_content_field(self):
        raw = json.dumps({
            "session_id": "gem-3",
            "content": "Content field fallback.",
        })
        session_id, text = _extract_session_and_text(raw, "gemini")
        assert session_id == "gem-3"
        assert text == "Content field fallback."

    def test_codex_jsonl_extracts_thread_id_and_messages(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "019d-abcd-1234"}),
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message",
                "content": [{"type": "text", "text": "First part of review."}],
            }}),
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message",
                "content": [{"type": "text", "text": "Second part."}],
            }}),
        ]
        raw = "\n".join(lines)
        session_id, text = _extract_session_and_text(raw, "codex")
        assert session_id == "019d-abcd-1234"
        assert "First part of review." in text
        assert "Second part." in text

    def test_codex_jsonl_no_agent_messages(self):
        """Thread started but no agent messages — falls back to raw."""
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "tid-1"}),
            json.dumps({"type": "something_else"}),
        ]
        raw = "\n".join(lines)
        session_id, text = _extract_session_and_text(raw, "codex")
        assert session_id == "tid-1"
        assert text == raw  # no text_parts, falls back

    def test_codex_jsonl_with_non_json_lines(self):
        """Gracefully skips non-JSON lines in JSONL."""
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "tid-2"}),
            "this is not json",
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message",
                "content": [{"type": "text", "text": "Review text."}],
            }}),
        ]
        raw = "\n".join(lines)
        session_id, text = _extract_session_and_text(raw, "codex")
        assert session_id == "tid-2"
        assert text == "Review text."

    def test_malformed_json_returns_raw(self):
        raw = "not json at all"
        session_id, text = _extract_session_and_text(raw, "claude")
        assert session_id is None
        assert text == raw

    def test_empty_string(self):
        session_id, text = _extract_session_and_text("", "claude")
        assert session_id is None
        assert text == ""


# ---------------------------------------------------------------------------
# TestPeerFollowup
# ---------------------------------------------------------------------------


class TestPeerFollowup:
    @pytest.mark.asyncio
    async def test_no_contradictions_returns_empty(self):
        """When synthesis model finds no contradictions, return empty list."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        mock_result.stderr = ""

        reviews = [
            {"model": "claude", "raw_content": "Review A", "session_id": "s1"},
            {"model": "gemini", "raw_content": "Review B", "session_id": "s2"},
        ]

        mock_registry = {
            "claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None, "resume_cmd": ["claude", "--session-id", "{session_id}", "-p", "-"]},
            "gemini": {**MOCK_SYNTH_CONFIG, "session_id_format": None, "resume_cmd": ["gemini", "--session", "{session_id}"]},
        }

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            result = await _peer_followup(pool, job_id, reviews, "Synthesis text")

        assert result == []

    @pytest.mark.asyncio
    async def test_contradiction_triggers_followup(self):
        """When contradictions found, resumes reviewer sessions."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        contradiction_json = json.dumps([{
            "topic": "race condition at db.py:47",
            "location": "db.py:47",
            "positions": [
                {"reviewer": "claude", "assessment": "No race condition"},
                {"reviewer": "gemini", "assessment": "Critical race condition"},
            ],
        }])

        followup_response = json.dumps({"stance": "conceded", "evidence": "You're right, I missed the lock ordering."})

        # First call: contradiction detection. Subsequent calls: followup resumes.
        mock_results = [
            MagicMock(returncode=0, stdout=contradiction_json, stderr=""),
            MagicMock(returncode=0, stdout=followup_response, stderr=""),
            MagicMock(returncode=0, stdout=followup_response, stderr=""),
        ]

        reviews = [
            {"model": "claude", "raw_content": "Review A", "session_id": "claude-sid"},
            {"model": "gemini", "raw_content": "Review B", "session_id": "gemini-sid"},
        ]

        mock_registry = {
            "claude": {
                **MOCK_SYNTH_CONFIG,
                "session_id_format": None,
                "resume_cmd": ["claude", "--session-id", "{session_id}", "-p", "-"],
            },
            "gemini": {
                **MOCK_SYNTH_CONFIG,
                "session_id_format": None,
                "resume_cmd": ["gemini", "--session", "{session_id}"],
            },
        }

        call_count = 0

        async def mock_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            result = mock_results[min(call_count, len(mock_results) - 1)]
            call_count += 1
            return result

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            result = await _peer_followup(pool, job_id, reviews, "Synthesis text")

        assert len(result) == 1
        assert result[0]["topic"] == "race condition at db.py:47"
        assert "resolutions" in result[0]
        assert len(result[0]["resolutions"]) == 2

    @pytest.mark.asyncio
    async def test_missing_session_id_marks_unresolved(self):
        """Reviewer without session_id gets unresolved stance."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        contradiction_json = json.dumps([{
            "topic": "error handling",
            "location": None,
            "positions": [
                {"reviewer": "claude", "assessment": "Handled correctly"},
                {"reviewer": "gpt-5.4", "assessment": "Missing error handling"},
            ],
        }])

        followup_response = json.dumps({"stance": "defended", "evidence": "The error is caught at line 50."})

        call_count = 0
        mock_results = [
            MagicMock(returncode=0, stdout=contradiction_json, stderr=""),
            MagicMock(returncode=0, stdout=followup_response, stderr=""),
        ]

        async def mock_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            result = mock_results[min(call_count, len(mock_results) - 1)]
            call_count += 1
            return result

        reviews = [
            {"model": "claude", "raw_content": "Review A", "session_id": "claude-sid"},
            {"model": "gpt-5.4", "raw_content": "Review B", "session_id": None},  # no session
        ]

        mock_registry = {
            "claude": {
                **MOCK_SYNTH_CONFIG,
                "session_id_format": None,
                "resume_cmd": ["claude", "--session-id", "{session_id}", "-p", "-"],
            },
            "gpt-5.4": {
                **MOCK_SYNTH_CONFIG,
                "session_id_format": None,
                "resume_cmd": ["codex", "exec", "resume", "{session_id}"],
            },
        }

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            result = await _peer_followup(pool, job_id, reviews, "Synthesis text")

        assert len(result) == 1
        resolutions = result[0]["resolutions"]
        gpt_resolution = [r for r in resolutions if r["reviewer"] == "gpt-5.4"]
        assert len(gpt_resolution) == 1
        assert gpt_resolution[0]["stance"] == "unresolved"

    @pytest.mark.asyncio
    async def test_contradiction_detection_failure_returns_empty(self):
        """If synthesis model fails to detect contradictions, return empty list."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        reviews = [{"model": "claude", "raw_content": "Review", "session_id": "s1"}]

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value={"claude": MOCK_SYNTH_CONFIG}),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            result = await _peer_followup(pool, job_id, reviews, "Synthesis")

        assert result == []

    @pytest.mark.asyncio
    async def test_session_resume_timeout_marks_unresolved(self):
        """If session resume times out, mark as unresolved."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        contradiction_json = json.dumps([{
            "topic": "memory leak",
            "location": "cache.py:12",
            "positions": [
                {"reviewer": "claude", "assessment": "Leak exists"},
                {"reviewer": "gemini", "assessment": "No leak"},
            ],
        }])

        call_count = 0

        async def mock_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(returncode=0, stdout=contradiction_json, stderr="")
            raise subprocess.TimeoutExpired(cmd="resume", timeout=60)

        reviews = [
            {"model": "claude", "raw_content": "A", "session_id": "s1"},
            {"model": "gemini", "raw_content": "B", "session_id": "s2"},
        ]

        mock_registry = {
            "claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None, "resume_cmd": ["claude", "{session_id}"]},
            "gemini": {**MOCK_SYNTH_CONFIG, "session_id_format": None, "resume_cmd": ["gemini", "{session_id}"]},
        }

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", side_effect=mock_to_thread),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            result = await _peer_followup(pool, job_id, reviews, "Synthesis")

        assert len(result) == 1
        # At least one resolution should be unresolved due to timeout
        stances = [r["stance"] for r in result[0]["resolutions"]]
        assert "unresolved" in stances


# ---------------------------------------------------------------------------
# TestCrossGradingPolicy
# ---------------------------------------------------------------------------


class TestCrossGradingPolicy:
    @pytest.mark.asyncio
    async def test_full_cross_grading_under_20_cycles(self):
        """Under 20 completed cycles, all reviewer models grade all reviews."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review from claude"},
            {"model": "gpt-5.4", "raw_content": "Review from gpt"},
        ]
        review_modes = {"claude": "agentic", "gpt-5.4": "agentic"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "EXCELLENT", "note": "Good"},
            {"model": "gpt-5.4", "grade": "ADEQUATE", "note": "OK"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        mock_registry = {
            "claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
            "gpt-5.4": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
        }

        # fetchval calls: cross_grade_count=5 (<20), existing_guard=0
        conn.fetchval = AsyncMock(side_effect=[5, 0])

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            await _grade_reviewers(
                pool=pool, job_id=job_id, reviews=reviews,
                review_modes=review_modes, synthesis_prose="Synthesis",
                synth_model_config=MOCK_SYNTH_CONFIG, synth_timeout=60,
                review_type="code",
            )

        # 2 graders (claude + gpt-5.4) × 2 reviews each = 4 grades
        assert conn.execute.await_count == 4

    @pytest.mark.asyncio
    async def test_synthesizer_only_grading_after_20_no_contradictions(self):
        """After 20 cycles with no contradictions, only synthesizer grades."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review A"},
            {"model": "gpt-5.4", "raw_content": "Review B"},
        ]
        review_modes = {"claude": "agentic", "gpt-5.4": "agentic"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "ADEQUATE", "note": "OK"},
            {"model": "gpt-5.4", "grade": "ADEQUATE", "note": "OK"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        mock_registry = {
            "claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
            "gpt-5.4": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
        }

        # cross_grade_count=21 (>20, not mod 5), no contradictions, existing_guard=0
        conn.fetchval = AsyncMock(side_effect=[21, 0])

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            await _grade_reviewers(
                pool=pool, job_id=job_id, reviews=reviews,
                review_modes=review_modes, synthesis_prose="Synthesis",
                synth_model_config=MOCK_SYNTH_CONFIG, synth_timeout=60,
                review_type="code",
            )

        # Only synthesizer (claude) grades: 1 grader × 2 reviews = 2 grades
        assert conn.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_full_cross_grading_on_contradictions(self):
        """After 20 cycles, contradictions trigger full cross-grading."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review A"},
            {"model": "gemini", "raw_content": "Review B"},
        ]
        review_modes = {"claude": "agentic", "gemini": "agentic"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "ADEQUATE", "note": "OK"},
            {"model": "gemini", "grade": "INADEQUATE", "failure_mode": "false_positive", "note": "Bad"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        mock_registry = {
            "claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
            "gemini": {**MOCK_SYNTH_CONFIG, "session_id_format": None},
        }

        # cross_grade_count=21 (>20), but contradictions present
        conn.fetchval = AsyncMock(side_effect=[21, 0])

        peer_disagreements = [{"topic": "race condition", "positions": []}]

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            await _grade_reviewers(
                pool=pool, job_id=job_id, reviews=reviews,
                review_modes=review_modes, synthesis_prose="Synthesis",
                synth_model_config=MOCK_SYNTH_CONFIG, synth_timeout=60,
                review_type="code",
                peer_disagreements=peer_disagreements,
            )

        # Full cross-grading: 2 graders × 2 reviews = 4 grades
        assert conn.execute.await_count == 4

    @pytest.mark.asyncio
    async def test_full_cross_grading_on_5th_cycle(self):
        """Every 5th cycle triggers full cross-grading."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [{"model": "claude", "raw_content": "Review A"}]
        review_modes = {"claude": "agentic"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "ADEQUATE", "note": "OK"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")
        mock_registry = {"claude": {**MOCK_SYNTH_CONFIG, "session_id_format": None}}

        # cross_grade_count=25 (>20, but 25 % 5 == 0)
        conn.fetchval = AsyncMock(side_effect=[25, 0])

        with (
            patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result),
            patch("claude_hub.review_engine.get_registry", return_value=mock_registry),
            patch("claude_hub.review_engine.get_synthesis_config", return_value={"model": "claude", "timeout_seconds": 60}),
        ):
            await _grade_reviewers(
                pool=pool, job_id=job_id, reviews=reviews,
                review_modes=review_modes, synthesis_prose="Synthesis",
                synth_model_config=MOCK_SYNTH_CONFIG, synth_timeout=60,
                review_type="code",
            )

        # Full cross-grading: 1 grader (claude is both reviewer and synthesizer) × 1 review = 1 grade
        assert conn.execute.await_count == 1


# ---------------------------------------------------------------------------
# TestRunSingleGrading
# ---------------------------------------------------------------------------


class TestRunSingleGrading:
    @pytest.mark.asyncio
    async def test_populates_new_columns(self):
        """Verify grader_model, failure_mode, review_target, peer_disagreement are populated."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        reviews = [
            {"model": "claude", "raw_content": "Review from claude"},
        ]
        review_modes = {"claude": "agentic"}

        grades_json = json.dumps([
            {"model": "claude", "grade": "INADEQUATE", "failure_mode": "false_positive", "note": "Flagged non-issue"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        peer_json = json.dumps([{"topic": "test"}])

        with patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
            await _run_single_grading(
                pool=pool, job_id=job_id, reviews=reviews,
                review_modes=review_modes, synthesis_prose="Synthesis",
                grader_name="gemini", grader_config=MOCK_SYNTH_CONFIG,
                grader_timeout=60, review_type="spec",
                peer_json=peer_json,
            )

        assert conn.execute.await_count == 1
        call_args = conn.execute.call_args_list[0][0]
        sql = call_args[0]
        assert "grader_model" in sql
        assert "failure_mode" in sql
        assert "peer_disagreement" in sql
        # Positional args: job_id, model_name, review_type, grade, note, grader_model, failure_mode, review_target, peer_json
        assert call_args[1] == job_id
        assert call_args[2] == "claude"  # model_name (model being graded)
        assert call_args[4] == "INADEQUATE"  # grade
        assert call_args[6] == "gemini"  # grader_model
        assert call_args[7] == "false_positive"  # failure_mode

    @pytest.mark.asyncio
    async def test_clears_failure_mode_for_good_grades(self):
        """EXCELLENT and ADEQUATE grades should have failure_mode = None."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        grades_json = json.dumps([
            {"model": "claude", "grade": "EXCELLENT", "failure_mode": "false_positive", "note": "Great"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        with patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
            await _run_single_grading(
                pool=pool, job_id=job_id,
                reviews=[{"model": "claude", "raw_content": "Review"}],
                review_modes={"claude": "agentic"},
                synthesis_prose="Synthesis",
                grader_name="gemini", grader_config=MOCK_SYNTH_CONFIG,
                grader_timeout=60, review_type="code",
            )

        call_args = conn.execute.call_args_list[0][0]
        assert call_args[4] == "EXCELLENT"
        assert call_args[7] is None  # failure_mode cleared for EXCELLENT

    @pytest.mark.asyncio
    async def test_invalid_failure_mode_set_to_none(self):
        """Invalid failure_mode values are silently set to None."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        grades_json = json.dumps([
            {"model": "claude", "grade": "INADEQUATE", "failure_mode": "bad_value", "note": "Bad"},
        ])

        mock_result = MagicMock(returncode=0, stdout=grades_json, stderr="")

        with patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
            await _run_single_grading(
                pool=pool, job_id=job_id,
                reviews=[{"model": "claude", "raw_content": "Review"}],
                review_modes={"claude": "agentic"},
                synthesis_prose="Synthesis",
                grader_name="gemini", grader_config=MOCK_SYNTH_CONFIG,
                grader_timeout=60, review_type="code",
            )

        call_args = conn.execute.call_args_list[0][0]
        assert call_args[7] is None  # invalid failure_mode cleared

    @pytest.mark.asyncio
    async def test_extracts_text_from_json_output(self):
        """Grader using JSON output mode — text extracted before parsing."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        inner_grades = json.dumps([
            {"model": "claude", "grade": "ADEQUATE", "note": "Solid"},
        ])
        # Claude JSON wrapper
        raw = json.dumps({"result": inner_grades, "session_id": "grading-session"})

        mock_result = MagicMock(returncode=0, stdout=raw, stderr="")

        grader_config = {**MOCK_SYNTH_CONFIG, "session_id_format": "claude"}

        with patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
            await _run_single_grading(
                pool=pool, job_id=job_id,
                reviews=[{"model": "claude", "raw_content": "Review"}],
                review_modes={"claude": "agentic"},
                synthesis_prose="Synthesis",
                grader_name="claude", grader_config=grader_config,
                grader_timeout=60, review_type="code",
            )

        assert conn.execute.await_count == 1
        call_args = conn.execute.call_args_list[0][0]
        assert call_args[4] == "ADEQUATE"

    @pytest.mark.asyncio
    async def test_grading_timeout_does_not_raise(self):
        """Grading timeout is logged but does not crash."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        async def timeout_side_effect(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="grade", timeout=60)

        with patch("claude_hub.review_engine.asyncio.to_thread", side_effect=timeout_side_effect):
            # Should not raise
            await _run_single_grading(
                pool=pool, job_id=job_id,
                reviews=[{"model": "claude", "raw_content": "Review"}],
                review_modes={"claude": "agentic"},
                synthesis_prose="Synthesis",
                grader_name="gemini", grader_config=MOCK_SYNTH_CONFIG,
                grader_timeout=60, review_type="code",
            )

        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_crash(self):
        """Grader returns garbage — no grades inserted, no crash."""
        pool, conn = _mock_pool()
        job_id = uuid.uuid4()

        mock_result = MagicMock(returncode=0, stdout="not json {{{", stderr="")

        with patch("claude_hub.review_engine.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
            await _run_single_grading(
                pool=pool, job_id=job_id,
                reviews=[{"model": "claude", "raw_content": "Review"}],
                review_modes={"claude": "agentic"},
                synthesis_prose="Synthesis",
                grader_name="gemini", grader_config=MOCK_SYNTH_CONFIG,
                grader_timeout=60, review_type="code",
            )

        conn.execute.assert_not_awaited()
