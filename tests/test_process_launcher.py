"""Tests for ProcessLauncher.

Tests cover:
- ModelProfile creation and validation
- Default profile registry loading
- Command construction for each provider (Claude, Codex, Gemini)
- Output parsing for each provider's format
- run_as_user command wrapping
- ProcessHandle creation
- Profile lookup (by provider, by provider+model_id)
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claude_hub.process_launcher import (
    ModelProfile,
    ProcessHandle,
    ProcessLauncher,
    _default_profiles,
)


# ---------------------------------------------------------------------------
# ModelProfile
# ---------------------------------------------------------------------------


class TestModelProfile:
    def test_basic_creation(self):
        """ModelProfile can be created with required fields."""
        profile = ModelProfile(
            name="Test Model",
            model_id="test-model-1",
            provider="test",
            cli_command=["test-cli", "--model", "test-model-1"],
            output_format="json",
        )
        assert profile.name == "Test Model"
        assert profile.model_id == "test-model-1"
        assert profile.provider == "test"
        assert profile.cli_command == ["test-cli", "--model", "test-model-1"]
        assert profile.output_format == "json"
        assert profile.capabilities == []
        assert profile.max_context is None
        assert profile.cost_tier == "subscription"

    def test_full_creation(self):
        """ModelProfile accepts all optional fields."""
        profile = ModelProfile(
            name="Claude Opus",
            model_id="claude-opus-4-6",
            provider="claude",
            cli_command=["claude", "--model", "claude-opus-4-6"],
            output_format="stream-json",
            capabilities=["code-editing", "architecture"],
            max_context=200_000,
            cost_tier="api-premium",
        )
        assert profile.capabilities == ["code-editing", "architecture"]
        assert profile.max_context == 200_000
        assert profile.cost_tier == "api-premium"

    def test_cli_command_is_list(self):
        """cli_command is a list of strings, not a single string."""
        profile = ModelProfile(
            name="Test",
            model_id="t",
            provider="test",
            cli_command=["cmd", "-a", "-b"],
            output_format="json",
        )
        assert isinstance(profile.cli_command, list)
        assert len(profile.cli_command) == 3


# ---------------------------------------------------------------------------
# Default Profiles
# ---------------------------------------------------------------------------


class TestDefaultProfiles:
    def test_default_profiles_loaded(self):
        """Default profiles include all expected providers."""
        profiles = _default_profiles()
        providers = {p.provider for p in profiles.values()}
        assert "claude" in providers
        assert "codex" in providers
        assert "gemini" in providers

    def test_default_profiles_count(self):
        """Default registry has the expected number of profiles."""
        profiles = _default_profiles()
        # 3 Claude + 2 Codex + 2 Gemini = 7
        assert len(profiles) == 7

    def test_default_profile_keys(self):
        """Profile keys follow the {provider}/{model_id} convention."""
        profiles = _default_profiles()
        for key, profile in profiles.items():
            expected_prefix = f"{profile.provider}/"
            assert key.startswith(expected_prefix), f"Key {key} doesn't match provider {profile.provider}"
            assert key == f"{profile.provider}/{profile.model_id}"

    def test_claude_profiles(self):
        """Claude profiles are correctly configured."""
        profiles = _default_profiles()
        opus = profiles["claude/claude-opus-4-6"]
        assert opus.name == "Claude Opus"
        assert opus.output_format == "stream-json"
        assert opus.cli_command[:2] == ["claude", "--model"]
        assert "claude-opus-4-6" in opus.cli_command

        sonnet = profiles["claude/claude-sonnet-4-6"]
        assert sonnet.name == "Claude Sonnet"
        assert sonnet.output_format == "stream-json"

        haiku = profiles["claude/claude-haiku-4-5-20251001"]
        assert haiku.name == "Claude Haiku"
        assert "fast" in haiku.capabilities

    def test_codex_profiles(self):
        """Codex profiles are correctly configured."""
        profiles = _default_profiles()
        codex = profiles["codex/gpt-5.3-codex"]
        assert codex.name == "Codex"
        assert codex.output_format == "jsonl"
        assert "codex" in codex.cli_command
        assert "exec" in codex.cli_command

        mini = profiles["codex/gpt-5.1-codex-mini"]
        assert mini.name == "Codex Mini"
        assert "fast" in mini.capabilities

    def test_gemini_profiles(self):
        """Gemini profiles are correctly configured."""
        profiles = _default_profiles()
        pro = profiles["gemini/gemini-2.5-pro"]
        assert pro.name == "Gemini Pro"
        assert pro.output_format == "json"
        assert "gemini" in pro.cli_command

        flash = profiles["gemini/gemini-2.5-flash"]
        assert flash.name == "Gemini Flash"
        assert "fast" in flash.capabilities


# ---------------------------------------------------------------------------
# ProcessLauncher: Profile Lookup
# ---------------------------------------------------------------------------


class TestProfileLookup:
    def test_get_profile_by_provider_and_model(self):
        """get_profile returns exact match when both provider and model_id given."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("claude", "claude-opus-4-6")
        assert profile.name == "Claude Opus"
        assert profile.model_id == "claude-opus-4-6"

    def test_get_profile_by_provider_only(self):
        """get_profile returns first (sorted) profile for a provider when no model_id."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("claude")
        assert profile.provider == "claude"
        # Should be deterministic (sorted by key)
        assert profile is not None

    def test_get_profile_unknown_provider(self):
        """get_profile raises ValueError for unknown provider."""
        launcher = ProcessLauncher()
        with pytest.raises(ValueError, match="No profiles registered"):
            launcher.get_profile("unknown-provider")

    def test_get_profile_unknown_model(self):
        """get_profile raises ValueError for unknown model_id."""
        launcher = ProcessLauncher()
        with pytest.raises(ValueError, match="No profile found"):
            launcher.get_profile("claude", "nonexistent-model")

    def test_custom_profiles(self):
        """ProcessLauncher accepts custom profile registry."""
        custom = {
            "custom/my-model": ModelProfile(
                name="My Model",
                model_id="my-model",
                provider="custom",
                cli_command=["my-cli", "run"],
                output_format="json",
            )
        }
        launcher = ProcessLauncher(profiles=custom)
        assert len(launcher.profiles) == 1
        profile = launcher.get_profile("custom", "my-model")
        assert profile.name == "My Model"

    def test_empty_profiles(self):
        """ProcessLauncher with empty registry raises on all lookups."""
        launcher = ProcessLauncher(profiles={})
        with pytest.raises(ValueError):
            launcher.get_profile("claude")


# ---------------------------------------------------------------------------
# Command Construction
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def setup_method(self):
        self.launcher = ProcessLauncher()

    def test_claude_command_with_prompt(self):
        """Claude command includes stream-json flags and -p prompt."""
        profile = self.launcher.get_profile("claude", "claude-opus-4-6")
        cmd = self.launcher.build_command(profile, prompt="Hello world")
        assert cmd[0] == "claude"
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--verbose" in cmd
        assert "-p" in cmd
        assert "Hello world" in cmd

    def test_claude_command_without_prompt(self):
        """Claude command without prompt omits -p flag (interactive mode)."""
        profile = self.launcher.get_profile("claude", "claude-opus-4-6")
        cmd = self.launcher.build_command(profile, prompt=None)
        assert "-p" not in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    def test_codex_command_with_prompt(self):
        """Codex command includes --json and prompt as positional arg."""
        profile = self.launcher.get_profile("codex", "gpt-5.3-codex")
        cmd = self.launcher.build_command(profile, prompt="Fix the bug")
        assert "codex" in cmd
        assert "exec" in cmd
        assert "--json" in cmd
        assert "Fix the bug" in cmd

    def test_codex_command_without_prompt(self):
        """Codex command without prompt omits the positional arg."""
        profile = self.launcher.get_profile("codex", "gpt-5.3-codex")
        cmd = self.launcher.build_command(profile, prompt=None)
        assert "--json" in cmd
        # No prompt string appended
        assert len([c for c in cmd if c == "Fix the bug"]) == 0

    def test_gemini_command_with_prompt(self):
        """Gemini command includes -p, --output-format json, and prompt."""
        profile = self.launcher.get_profile("gemini", "gemini-2.5-pro")
        cmd = self.launcher.build_command(profile, prompt="Analyze this")
        assert "gemini" in cmd
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "Analyze this" in cmd

    def test_gemini_command_without_prompt(self):
        """Gemini command without prompt still has -p and format flags."""
        profile = self.launcher.get_profile("gemini", "gemini-2.5-pro")
        cmd = self.launcher.build_command(profile, prompt=None)
        assert "-p" in cmd
        assert "--output-format" in cmd
        # No prompt string appended
        assert "Analyze this" not in cmd

    def test_unknown_provider_with_prompt(self):
        """Unknown provider just appends prompt as positional arg."""
        profile = ModelProfile(
            name="Unknown",
            model_id="unk-1",
            provider="alien",
            cli_command=["alien-cli"],
            output_format="text",
        )
        cmd = self.launcher.build_command(profile, prompt="Do stuff")
        assert cmd == ["alien-cli", "Do stuff"]

    def test_unknown_provider_without_prompt(self):
        """Unknown provider without prompt returns just the base command."""
        profile = ModelProfile(
            name="Unknown",
            model_id="unk-1",
            provider="alien",
            cli_command=["alien-cli"],
            output_format="text",
        )
        cmd = self.launcher.build_command(profile, prompt=None)
        assert cmd == ["alien-cli"]

    def test_command_does_not_mutate_profile(self):
        """build_command does not modify the profile's cli_command."""
        profile = self.launcher.get_profile("claude", "claude-opus-4-6")
        original_cmd = list(profile.cli_command)
        self.launcher.build_command(profile, prompt="Test")
        assert profile.cli_command == original_cmd


# ---------------------------------------------------------------------------
# run_as_user Wrapping
# ---------------------------------------------------------------------------


class TestRunAsUser:
    def setup_method(self):
        self.launcher = ProcessLauncher()

    def test_wrap_command(self):
        """wrap_command_for_user prepends sudo with correct flags."""
        cmd = ["claude", "--model", "claude-opus-4-6", "-p", "Hello"]
        wrapped = self.launcher.wrap_command_for_user(cmd, "reviewer-agent")
        assert wrapped[:4] == ["sudo", "-u", "reviewer-agent", "--preserve-env"]
        assert wrapped[4:] == cmd

    def test_wrap_preserves_original(self):
        """wrap_command_for_user does not mutate the input list."""
        cmd = ["claude", "-p", "Hi"]
        original = list(cmd)
        self.launcher.wrap_command_for_user(cmd, "agent-user")
        assert cmd == original

    def test_wrap_different_users(self):
        """Different users produce different wrapped commands."""
        cmd = ["gemini", "-p", "Test"]
        wrapped_a = self.launcher.wrap_command_for_user(cmd, "agent-a")
        wrapped_b = self.launcher.wrap_command_for_user(cmd, "agent-b")
        assert wrapped_a[2] == "agent-a"
        assert wrapped_b[2] == "agent-b"
        # Rest of command is the same
        assert wrapped_a[4:] == wrapped_b[4:]


# ---------------------------------------------------------------------------
# Output Parsing: Claude
# ---------------------------------------------------------------------------


class TestParseClaudeOutput:
    def setup_method(self):
        self.launcher = ProcessLauncher()
        self.profile = self.launcher.get_profile("claude", "claude-opus-4-6")

    def test_text_delta(self):
        """Claude text_delta events are parsed as 'text' type."""
        raw = json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "text"
        assert result["content"] == "Hello"
        assert "raw" in result

    def test_tool_use_delta(self):
        """Claude input_json_delta events are parsed as 'tool_use' type."""
        raw = json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "tool_use"
        assert result["content"] == '{"path":'

    def test_assistant_message(self):
        """Claude assistant events extract text from content blocks."""
        raw = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "First paragraph."},
                    {"type": "text", "text": "Second paragraph."},
                ],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "text"
        assert "First paragraph." in result["content"]
        assert "Second paragraph." in result["content"]

    def test_result_event(self):
        """Claude result events are parsed as 'result' type."""
        raw = json.dumps({
            "type": "result",
            "result": "Task completed successfully",
            "duration_ms": 1500,
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "result"
        assert "Task completed successfully" in result["content"]

    def test_error_event(self):
        """Claude error events are parsed as 'error' type."""
        raw = json.dumps({
            "type": "error",
            "error": "Rate limit exceeded",
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "error"
        assert "Rate limit exceeded" in result["content"]

    def test_system_init_ignored(self):
        """Claude system/init events return None (not meaningful for consumers)."""
        raw = json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": "abc-123",
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is None

    def test_empty_line(self):
        """Empty lines return None."""
        assert self.launcher.parse_output(self.profile, "") is None
        assert self.launcher.parse_output(self.profile, "   ") is None

    def test_non_json_line(self):
        """Non-JSON lines return None."""
        assert self.launcher.parse_output(self.profile, "not json at all") is None

    def test_assistant_with_no_text_blocks(self):
        """Assistant message with only non-text blocks returns None."""
        raw = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "read_file"},
                ],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is None


# ---------------------------------------------------------------------------
# Output Parsing: Codex
# ---------------------------------------------------------------------------


class TestParseCodexOutput:
    def setup_method(self):
        self.launcher = ProcessLauncher()
        self.profile = self.launcher.get_profile("codex", "gpt-5.3-codex")

    def test_item_completed_agent_message(self):
        """Codex item.completed with agent_message is parsed as 'result'."""
        raw = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "content": [
                    {"type": "output_text", "text": "Here is the fix."},
                ],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "result"
        assert "Here is the fix." in result["content"]

    def test_item_completed_tool_call(self):
        """Codex item.completed with tool_call is parsed as 'tool_use'."""
        raw = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "tool_call",
                "name": "write_file",
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "tool_use"
        assert result["content"] == "write_file"

    def test_item_streaming(self):
        """Codex item.streaming events are parsed as 'text'."""
        raw = json.dumps({
            "type": "item.streaming",
            "item": {
                "content": [
                    {"type": "output_text", "text": "Partial response..."},
                ],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "text"
        assert "Partial response..." in result["content"]

    def test_item_created_ignored(self):
        """Codex item.created events return None."""
        raw = json.dumps({
            "type": "item.created",
            "item": {"type": "agent_message"},
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is None

    def test_error_event(self):
        """Codex error events are parsed as 'error'."""
        raw = json.dumps({
            "type": "error",
            "message": "Token limit exceeded",
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "error"
        assert "Token limit exceeded" in result["content"]

    def test_item_completed_empty_content(self):
        """Codex item.completed with empty content returns None."""
        raw = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "content": [],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is None

    def test_multiple_output_text_blocks(self):
        """Codex with multiple output_text blocks joins them."""
        raw = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "content": [
                    {"type": "output_text", "text": "Part 1."},
                    {"type": "output_text", "text": "Part 2."},
                ],
            },
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert "Part 1." in result["content"]
        assert "Part 2." in result["content"]


# ---------------------------------------------------------------------------
# Output Parsing: Gemini
# ---------------------------------------------------------------------------


class TestParseGeminiOutput:
    def setup_method(self):
        self.launcher = ProcessLauncher()
        self.profile = self.launcher.get_profile("gemini", "gemini-2.5-pro")

    def test_response_event(self):
        """Gemini response blob is parsed as 'result'."""
        raw = json.dumps({
            "response": "The code has a null pointer dereference on line 42.",
            "stats": {"input_tokens": 100, "output_tokens": 50},
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "result"
        assert "null pointer dereference" in result["content"]

    def test_error_event(self):
        """Gemini error blob is parsed as 'error'."""
        raw = json.dumps({
            "error": "Model not available in your region",
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "error"
        assert "not available" in result["content"]

    def test_unknown_structure(self):
        """Gemini unknown JSON structure is returned as 'text'."""
        raw = json.dumps({"status": "thinking", "progress": 0.5})
        result = self.launcher.parse_output(self.profile, raw)
        assert result is not None
        assert result["type"] == "text"
        # Content should be JSON string of the data
        assert "thinking" in result["content"]

    def test_response_with_stats(self):
        """Gemini response preserves stats in raw field."""
        raw = json.dumps({
            "response": "Answer here",
            "stats": {"input_tokens": 200},
        })
        result = self.launcher.parse_output(self.profile, raw)
        assert result["raw"]["stats"]["input_tokens"] == 200


# ---------------------------------------------------------------------------
# Output Parsing: Unknown Provider
# ---------------------------------------------------------------------------


class TestParseUnknownProvider:
    def test_unknown_provider_returns_text(self):
        """Unknown provider JSON is returned as 'text' with raw preserved."""
        launcher = ProcessLauncher()
        profile = ModelProfile(
            name="Alien",
            model_id="alien-1",
            provider="alien",
            cli_command=["alien-cli"],
            output_format="custom",
        )
        raw = json.dumps({"output": "beep boop"})
        result = launcher.parse_output(profile, raw)
        assert result is not None
        assert result["type"] == "text"
        assert "beep boop" in result["content"]
        assert result["raw"]["output"] == "beep boop"


# ---------------------------------------------------------------------------
# ProcessHandle
# ---------------------------------------------------------------------------


class TestProcessHandle:
    def test_creation(self):
        """ProcessHandle can be created with mock process and profile."""
        mock_process = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()

        profile = ModelProfile(
            name="Test",
            model_id="test-1",
            provider="test",
            cli_command=["test"],
            output_format="json",
        )

        handle = ProcessHandle(
            process=mock_process,
            profile=profile,
            stdin=mock_stdin,
            stdout=mock_stdout,
            working_dir=Path("/tmp/test"),
        )

        assert handle.process is mock_process
        assert handle.profile is profile
        assert handle.stdin is mock_stdin
        assert handle.stdout is mock_stdout
        assert handle.working_dir == Path("/tmp/test")
        assert isinstance(handle.created_at, datetime)

    def test_default_working_dir(self):
        """ProcessHandle defaults working_dir to cwd."""
        mock_process = MagicMock()
        profile = ModelProfile(
            name="Test",
            model_id="test-1",
            provider="test",
            cli_command=["test"],
            output_format="json",
        )
        handle = ProcessHandle(
            process=mock_process,
            profile=profile,
            stdin=MagicMock(),
            stdout=MagicMock(),
        )
        # Should be a Path, default is cwd
        assert isinstance(handle.working_dir, Path)


# ---------------------------------------------------------------------------
# Integration: Full Command Pipeline
# ---------------------------------------------------------------------------


class TestCommandPipeline:
    """End-to-end tests: profile lookup -> command build -> optional user wrap."""

    def test_claude_full_pipeline(self):
        """Full pipeline for Claude: lookup, build, wrap."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("claude", "claude-sonnet-4-6")
        cmd = launcher.build_command(profile, prompt="Review this PR")
        wrapped = launcher.wrap_command_for_user(cmd, "reviewer")

        assert wrapped[0] == "sudo"
        assert wrapped[2] == "reviewer"
        assert "claude" in wrapped
        assert "claude-sonnet-4-6" in wrapped
        assert "Review this PR" in wrapped
        assert "stream-json" in wrapped

    def test_codex_full_pipeline(self):
        """Full pipeline for Codex: lookup, build, wrap."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("codex", "gpt-5.3-codex")
        cmd = launcher.build_command(profile, prompt="Implement feature X")
        wrapped = launcher.wrap_command_for_user(cmd, "builder")

        assert wrapped[0] == "sudo"
        assert wrapped[2] == "builder"
        assert "codex" in wrapped
        assert "exec" in wrapped
        assert "--json" in wrapped
        assert "Implement feature X" in wrapped

    def test_gemini_full_pipeline(self):
        """Full pipeline for Gemini: lookup, build, wrap."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("gemini", "gemini-2.5-flash")
        cmd = launcher.build_command(profile, prompt="Scan for patterns")
        wrapped = launcher.wrap_command_for_user(cmd, "scanner")

        assert wrapped[0] == "sudo"
        assert wrapped[2] == "scanner"
        assert "gemini" in wrapped
        assert "json" in wrapped
        assert "Scan for patterns" in wrapped

    def test_pipeline_without_user_wrap(self):
        """Pipeline without run_as_user produces unwrapped command."""
        launcher = ProcessLauncher()
        profile = launcher.get_profile("claude", "claude-opus-4-6")
        cmd = launcher.build_command(profile, prompt="Hello")

        assert cmd[0] == "claude"
        assert "sudo" not in cmd
