"""Tests for review_cli module — argument parsing, file resolution, output formatting."""

import asyncio
import json
import uuid
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.review_cli import (
    _cmd_get,
    _cmd_review,
    _default_output_path,
    _detect_git_changes,
    _resolve_files,
    _write_results,
    parse_args,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**overrides):
    """Build a Namespace with sensible defaults for the review command."""
    defaults = dict(
        command=None,
        files=None,
        content=None,
        prompt="Test review",
        intent=None,
        intent_ref=None,
        context_files=None,
        models=None,
        clean_room=True,
        exclude_paths=None,
        include_paths=None,
        artifact_id=None,
        output=None,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def _make_review_result(status="complete", with_synthesis=True, with_reviews=True):
    """Build a mock review result dict."""
    result = {
        "job_id": str(uuid.uuid4()),
        "artifact_id": None,
        "status": status,
        "synthesis": None,
        "reviews": None,
    }
    if with_synthesis:
        result["synthesis"] = {
            "synthesis_prose": "This is the synthesis.",
            "models_requested": ["claude", "gemini"],
            "models_responded": ["claude", "gemini"],
            "review_modes": {"claude": "agentic", "gemini": "agentic"},
            "consensus": [],
            "unique_findings": {},
            "contradictions": [],
        }
    if with_reviews:
        result["reviews"] = [
            {
                "id": str(uuid.uuid4()),
                "model": "claude",
                "status": "complete",
                "raw_content": "Claude's review output.",
                "clean_room": True,
                "invocation_mode": "agentic",
                "started_at": None,
                "completed_at": None,
                "findings": None,
            },
            {
                "id": str(uuid.uuid4()),
                "model": "gemini",
                "status": "complete",
                "raw_content": "Gemini's review output.",
                "clean_room": True,
                "invocation_mode": "agentic",
                "started_at": None,
                "completed_at": None,
                "findings": None,
            },
        ]
    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_default_mode_with_files_and_prompt(self):
        args = parse_args(["--files", "src/a.py", "src/b.py", "--prompt", "Review"])
        assert args.command is None
        assert args.files == ["src/a.py", "src/b.py"]
        assert args.prompt == "Review"

    def test_default_mode_prompt_only(self):
        args = parse_args(["--prompt", "Review changes"])
        assert args.command is None
        assert args.files is None
        assert args.prompt == "Review changes"

    def test_default_mode_with_models(self):
        args = parse_args(["--prompt", "Review", "--models", "claude", "gemini"])
        assert args.models == ["claude", "gemini"]

    def test_default_mode_with_output(self):
        args = parse_args(["--prompt", "Review", "-o", "/tmp/review.md"])
        assert args.output == "/tmp/review.md"

    def test_no_clean_room_flag(self):
        args = parse_args(["--prompt", "Review", "--no-clean-room"])
        assert args.clean_room is False

    def test_default_mode_requires_prompt(self):
        with pytest.raises(SystemExit):
            parse_args(["--files", "src/foo.py"])

    def test_get_subcommand(self):
        args = parse_args(["get", "abc-123"])
        assert args.command == "get"
        assert args.job_id == "abc-123"

    def test_get_subcommand_with_output(self):
        args = parse_args(["get", "abc-123", "-o", "/tmp/out.md"])
        assert args.command == "get"
        assert args.output == "/tmp/out.md"

    def test_content_and_artifact_id(self):
        args = parse_args(["--prompt", "Review", "--content", "some code"])
        assert args.content == "some code"

        args2 = parse_args(["--prompt", "Review", "--artifact-id", "abc"])
        assert args2.artifact_id == "abc"

    def test_intent_ref(self):
        args = parse_args(["--prompt", "Review", "--intent-ref", "docs/spec.md"])
        assert args.intent_ref == "docs/spec.md"

    def test_get_subcommand_does_not_require_prompt(self):
        """The get subcommand should work without --prompt."""
        args = parse_args(["get", "abc-123"])
        assert args.command == "get"


# ---------------------------------------------------------------------------
# Git change detection
# ---------------------------------------------------------------------------

class TestDetectGitChanges:
    @patch("claude_hub.review_cli.subprocess.run")
    def test_detects_unstaged_and_staged(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="src/a.py\nsrc/b.py\n"),
            MagicMock(returncode=0, stdout="src/b.py\nsrc/c.py\n"),
        ]
        files = _detect_git_changes()
        assert files == ["src/a.py", "src/b.py", "src/c.py"]

    @patch("claude_hub.review_cli.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert _detect_git_changes() == []

    @patch("claude_hub.review_cli.subprocess.run")
    def test_failed_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _detect_git_changes() == []

    @patch("claude_hub.review_cli.subprocess.run")
    def test_results_sorted(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="z.py\na.py\n"),
            MagicMock(returncode=0, stdout=""),
        ]
        assert _detect_git_changes() == ["a.py", "z.py"]


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------

class TestResolveFiles:
    def test_returns_files_when_provided(self):
        args = _make_args(files=["src/a.py"])
        assert _resolve_files(args) == ["src/a.py"]

    def test_returns_none_when_content_provided(self):
        args = _make_args(content="some code")
        assert _resolve_files(args) is None

    def test_returns_none_when_artifact_id_provided(self):
        args = _make_args(artifact_id="abc-123")
        assert _resolve_files(args) is None

    @patch("claude_hub.review_cli._detect_git_changes")
    def test_auto_detect_from_git(self, mock_detect, capsys):
        mock_detect.return_value = ["src/foo.py"]
        args = _make_args()
        result = _resolve_files(args)
        assert result == ["src/foo.py"]
        assert "Auto-detected" in capsys.readouterr().err

    @patch("claude_hub.review_cli._detect_git_changes")
    def test_exits_when_no_files_and_no_git_changes(self, mock_detect):
        mock_detect.return_value = []
        args = _make_args()
        with pytest.raises(SystemExit) as exc_info:
            _resolve_files(args)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------

class TestDefaultOutputPath:
    def test_generates_dated_path(self, tmp_path):
        with patch.dict("os.environ", {"CLAUDE_HUB_PROJECT_DIR": str(tmp_path)}):
            path = _default_output_path()
            assert "review-" in path.name
            assert path.suffix == ".md"
            assert path.parent.name == "reviews"

    def test_avoids_collision(self, tmp_path):
        with patch.dict("os.environ", {"CLAUDE_HUB_PROJECT_DIR": str(tmp_path)}):
            path1 = _default_output_path()
            path1.parent.mkdir(parents=True, exist_ok=True)
            path1.write_text("existing")
            path2 = _default_output_path()
            assert path2 != path1
            assert "-2" in path2.name

    def test_slug_included(self, tmp_path):
        with patch.dict("os.environ", {"CLAUDE_HUB_PROJECT_DIR": str(tmp_path)}):
            path = _default_output_path(slug="security")
            assert "security" in path.name


# ---------------------------------------------------------------------------
# Write results
# ---------------------------------------------------------------------------

class TestWriteResults:
    def test_writes_synthesis_and_reviews(self, tmp_path):
        path = tmp_path / "review.md"
        result = _make_review_result()
        _write_results(path, result, "Test prompt", ["src/a.py"])
        content = path.read_text()
        assert "# Review:" in content
        assert "Test prompt" in content
        assert "src/a.py" in content
        assert "This is the synthesis." in content
        assert "## Individual Reviews" in content
        assert "Claude's review output." in content
        assert "Gemini's review output." in content

    def test_writes_without_synthesis(self, tmp_path):
        path = tmp_path / "review.md"
        result = _make_review_result(with_synthesis=False)
        _write_results(path, result, "Test", None)
        content = path.read_text()
        assert "## Synthesis" not in content

    def test_writes_without_reviews(self, tmp_path):
        path = tmp_path / "review.md"
        result = _make_review_result(with_reviews=False)
        _write_results(path, result, "Test", None)
        content = path.read_text()
        assert "## Individual Reviews" not in content

    def test_handles_failed_model(self, tmp_path):
        path = tmp_path / "review.md"
        result = _make_review_result()
        result["reviews"][1]["status"] = "failed"
        result["reviews"][1]["raw_content"] = None
        _write_results(path, result, "Test", None)
        content = path.read_text()
        assert "*No output (status: failed)*" in content

    def test_skipped_models_shown(self, tmp_path):
        path = tmp_path / "review.md"
        result = _make_review_result()
        result["synthesis"]["models_requested"] = ["claude", "gemini", "gpt-5.4"]
        _write_results(path, result, "Test", None)
        content = path.read_text()
        assert "gpt-5.4" in content


# ---------------------------------------------------------------------------
# Review command flow
# ---------------------------------------------------------------------------

class TestCmdReview:
    @pytest.mark.asyncio
    @patch("claude_hub.review_cli._resolve_files")
    @patch("claude_hub.review_cli.review_engine")
    @patch("claude_hub.review_cli._default_output_path")
    async def test_dispatch_await_write(self, mock_output, mock_engine, mock_resolve, tmp_path, capsys):
        output_file = tmp_path / "review.md"
        mock_output.return_value = output_file
        mock_resolve.return_value = ["src/a.py"]

        done_task = asyncio.Future()
        done_task.set_result(None)
        mock_engine.dispatch_review = AsyncMock(return_value={
            "job_id": "test-job",
            "models_dispatched": ["claude"],
            "tasks": [done_task],
        })

        result = _make_review_result()
        mock_engine.get_review_results = AsyncMock(return_value=result)

        pool = MagicMock()
        args = _make_args(prompt="Review this")
        await _cmd_review(pool, args)

        assert output_file.exists()
        content = output_file.read_text()
        assert "This is the synthesis." in content

        err = capsys.readouterr().err
        assert str(output_file) in err

    @pytest.mark.asyncio
    @patch("claude_hub.review_cli._resolve_files")
    @patch("claude_hub.review_cli.review_engine")
    async def test_custom_output_path(self, mock_engine, mock_resolve, tmp_path):
        output_file = tmp_path / "custom.md"
        mock_resolve.return_value = ["src/a.py"]

        done_task = asyncio.Future()
        done_task.set_result(None)
        mock_engine.dispatch_review = AsyncMock(return_value={
            "job_id": "test-job",
            "models_dispatched": ["claude"],
            "tasks": [done_task],
        })
        mock_engine.get_review_results = AsyncMock(return_value=_make_review_result())

        pool = MagicMock()
        args = _make_args(prompt="Review", output=str(output_file))
        await _cmd_review(pool, args)

        assert output_file.exists()

    @pytest.mark.asyncio
    @patch("claude_hub.review_cli._resolve_files")
    @patch("claude_hub.review_cli.review_engine")
    @patch("claude_hub.review_cli._default_output_path")
    async def test_skipped_models_reported(self, mock_output, mock_engine, mock_resolve, tmp_path, capsys):
        mock_output.return_value = tmp_path / "review.md"
        mock_resolve.return_value = ["src/a.py"]

        done_task = asyncio.Future()
        done_task.set_result(None)
        mock_engine.dispatch_review = AsyncMock(return_value={
            "job_id": "test-job",
            "models_dispatched": ["claude"],
            "models_skipped": ["gpt-5.4"],
            "tasks": [done_task],
        })
        mock_engine.get_review_results = AsyncMock(return_value=_make_review_result())

        pool = MagicMock()
        args = _make_args(prompt="Review")
        await _cmd_review(pool, args)

        err = capsys.readouterr().err
        assert "gpt-5.4" in err


# ---------------------------------------------------------------------------
# Get command
# ---------------------------------------------------------------------------

class TestCmdGet:
    @pytest.mark.asyncio
    @patch("claude_hub.review_cli.review_engine")
    @patch("claude_hub.review_cli._default_output_path")
    async def test_get_writes_results(self, mock_output, mock_engine, tmp_path, capsys):
        output_file = tmp_path / "review.md"
        mock_output.return_value = output_file
        mock_engine.get_review_results = AsyncMock(return_value=_make_review_result())

        pool = MagicMock()
        args = Namespace(command="get", job_id="abc-123", output=None)
        await _cmd_get(pool, args)

        assert output_file.exists()
        assert "This is the synthesis." in output_file.read_text()

    @pytest.mark.asyncio
    @patch("claude_hub.review_cli.review_engine")
    async def test_get_not_found(self, mock_engine, capsys):
        mock_engine.get_review_results = AsyncMock(return_value={
            "job_id": "abc-123",
            "status": "not_found",
            "synthesis": None,
            "reviews": None,
            "artifact_id": None,
        })

        pool = MagicMock()
        args = Namespace(command="get", job_id="abc-123", output=None)
        with pytest.raises(SystemExit) as exc_info:
            await _cmd_get(pool, args)
        assert exc_info.value.code == 1
