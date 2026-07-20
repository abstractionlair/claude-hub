"""Generalized process launcher for multiple AI CLI tools.

Abstraction layer that can launch and communicate with any supported CLI tool
(Claude, Codex, Gemini). Handles CLI differences internally: command construction,
output format parsing, and credential routing (which Linux user to run as).

This is the foundation that ChatProcessManager will eventually delegate to for
process spawning, while retaining its own session management, priming, and
subscriber fan-out logic.

Supported providers:
    - claude: Claude Code CLI (stream-json output)
    - codex:  Codex CLI (JSONL output with item events)
    - gemini: Gemini CLI (single JSON blob output)

Usage:
    launcher = ProcessLauncher()
    handle = await launcher.launch("claude", prompt="Explain this code")
    # handle.process, handle.stdin, handle.stdout are ready for I/O
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ModelProfile:
    """Describes a model's identity, invocation pattern, and capabilities.

    Attributes:
        name: Human-readable name (e.g., "Claude Opus").
        model_id: Model identifier passed to the CLI (e.g., "claude-opus-4-6").
        provider: CLI provider key: "claude", "codex", or "gemini".
        cli_command: Base CLI command tokens (e.g., ["claude", "--model", "claude-opus-4-6"]).
        output_format: Expected stdout format: "stream-json", "jsonl", or "json".
        capabilities: Feature tags (e.g., ["code-editing", "large-context"]).
        max_context: Context window size in tokens, if known.
        cost_tier: Billing category: "subscription", "api-cheap", "api-standard", "api-premium".
    """

    name: str
    model_id: str
    provider: str
    cli_command: list[str]
    output_format: str
    capabilities: list[str] = field(default_factory=list)
    max_context: int | None = None
    cost_tier: str = "subscription"


@dataclass
class ProcessHandle:
    """A launched CLI process with its associated metadata.

    Attributes:
        process: The asyncio subprocess.
        profile: The ModelProfile used to launch this process.
        stdin: Writer for sending input to the process.
        stdout: Reader for consuming process output.
        created_at: When this process was launched.
        working_dir: The working directory the process runs in.
    """

    process: asyncio.subprocess.Process
    profile: ModelProfile
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    working_dir: Path = field(default_factory=lambda: Path.cwd())


def _default_profiles() -> dict[str, ModelProfile]:
    """Build the default registry of known model profiles.

    Keys are "{provider}/{model_id}" for unambiguous lookup.
    """
    profiles: dict[str, ModelProfile] = {}

    # --- Claude (Max subscription) ---
    claude_models = [
        ("Claude Opus", "claude-opus-4-6", ["code-editing", "architecture", "executive-function"]),
        ("Claude Sonnet", "claude-sonnet-4-6", ["code-editing", "code-review"]),
        ("Claude Haiku", "claude-haiku-4-5-20251001", ["triage", "classification", "fast"]),
    ]
    for name, model_id, caps in claude_models:
        profiles[f"claude/{model_id}"] = ModelProfile(
            name=name,
            model_id=model_id,
            provider="claude",
            cli_command=["claude", "--model", model_id],
            output_format="stream-json",
            capabilities=caps,
            cost_tier="subscription",
        )

    # --- Codex (ChatGPT Pro subscription) ---
    codex_models = [
        ("Codex", "gpt-5.3-codex", ["code-editing", "deep-debugging"], "subscription"),
        ("Codex Mini", "gpt-5.1-codex-mini", ["triage", "fast"], "subscription"),
    ]
    for name, model_id, caps, tier in codex_models:
        profiles[f"codex/{model_id}"] = ModelProfile(
            name=name,
            model_id=model_id,
            provider="codex",
            cli_command=["codex", "exec", "-m", model_id],
            output_format="jsonl",
            capabilities=caps,
            cost_tier=tier,
        )

    # --- Gemini (Google subscription) ---
    gemini_models = [
        ("Gemini Pro", "gemini-2.5-pro", ["large-context", "reasoning"], "subscription"),
        ("Gemini Flash", "gemini-2.5-flash", ["fast", "locate-scan"], "subscription"),
    ]
    for name, model_id, caps, tier in gemini_models:
        profiles[f"gemini/{model_id}"] = ModelProfile(
            name=name,
            model_id=model_id,
            provider="gemini",
            cli_command=["gemini", "--model", model_id],
            output_format="json",
            capabilities=caps,
            cost_tier=tier,
        )

    return profiles


class ProcessLauncher:
    """Launches and manages CLI processes for any supported AI provider.

    Handles the differences between Claude, Codex, and Gemini CLIs:
    command construction, output format parsing, and user identity (sudo).

    Args:
        profiles: Registry of ModelProfiles keyed by "{provider}/{model_id}".
            If None, uses the built-in default profiles below.
    """

    def __init__(self, profiles: dict[str, ModelProfile] | None = None):
        self.profiles: dict[str, ModelProfile] = (
            profiles if profiles is not None else _default_profiles()
        )

    def get_profile(self, provider: str, model_id: str | None = None) -> ModelProfile:
        """Look up a model profile by provider and optional model_id.

        If model_id is None, returns the first profile for that provider
        (deterministic: sorted by key).

        Raises:
            ValueError: If no matching profile is found.
        """
        if model_id:
            key = f"{provider}/{model_id}"
            if key in self.profiles:
                return self.profiles[key]
            raise ValueError(f"No profile found for {key}")

        # Find first profile for this provider
        for key in sorted(self.profiles):
            profile = self.profiles[key]
            if profile.provider == provider:
                return profile

        raise ValueError(f"No profiles registered for provider '{provider}'")

    def build_command(
        self,
        profile: ModelProfile,
        prompt: str | None = None,
    ) -> list[str]:
        """Construct the full CLI command for a given profile and prompt.

        Each provider has its own invocation pattern:
        - claude: --output-format stream-json --verbose -p "PROMPT"
        - codex: exec --json "PROMPT"
        - gemini: -p --output-format json "PROMPT"

        Args:
            profile: The model profile to build a command for.
            prompt: If provided, append as a one-shot prompt argument.

        Returns:
            The full command as a list of strings suitable for subprocess.
        """
        cmd = list(profile.cli_command)

        if profile.provider == "claude":
            cmd.extend(["--output-format", "stream-json", "--verbose"])
            if prompt:
                cmd.extend(["-p", prompt])

        elif profile.provider == "codex":
            cmd.append("--json")
            if prompt:
                cmd.append(prompt)

        elif profile.provider == "gemini":
            cmd.extend(["-p", "--output-format", "json"])
            if prompt:
                cmd.append(prompt)

        else:
            # Unknown provider: just append prompt as positional arg
            if prompt:
                cmd.append(prompt)

        return cmd

    def wrap_command_for_user(
        self,
        cmd: list[str],
        run_as_user: str,
    ) -> list[str]:
        """Wrap a command with sudo to run as a different Linux user.

        Used in the multi-agent architecture where each agent runs as its
        own Linux user with separate credentials and home directory.

        Args:
            cmd: The base command to wrap.
            run_as_user: The Linux username to run as.

        Returns:
            The wrapped command: ["sudo", "-u", user, "--preserve-env", ...cmd].
        """
        return ["sudo", "-u", run_as_user, "--preserve-env"] + cmd

    def parse_output(self, profile: ModelProfile, raw_line: str) -> dict | None:
        """Parse a line of CLI output into a normalized event dict.

        Each CLI has a different output format. This normalizes to:
            {
                "type": "text" | "tool_use" | "result" | "error",
                "content": str,
                "raw": dict  # Original parsed output
            }

        Args:
            profile: The model profile (determines parsing strategy).
            raw_line: A single line of output from the CLI's stdout.

        Returns:
            Normalized event dict, or None if the line is not parseable
            or not meaningful (e.g., empty lines, debug output).
        """
        line = raw_line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if profile.provider == "claude":
            return self._parse_claude_output(data)
        elif profile.provider == "codex":
            return self._parse_codex_output(data)
        elif profile.provider == "gemini":
            return self._parse_gemini_output(data)
        else:
            # Unknown provider: return raw data as text
            return {
                "type": "text",
                "content": json.dumps(data),
                "raw": data,
            }

    def _parse_claude_output(self, data: dict) -> dict | None:
        """Parse Claude stream-json output.

        Claude emits NDJSON with type fields:
        - "system" (subtype "init") -> ignored (setup)
        - "stream_event" with content_block_delta -> text
        - "assistant" -> text (complete response)
        - "result" -> result
        - tool_use events -> tool_use
        """
        event_type = data.get("type")

        if event_type == "stream_event":
            event = data.get("event", {})
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    return {
                        "type": "text",
                        "content": delta.get("text", ""),
                        "raw": data,
                    }
                elif delta.get("type") == "input_json_delta":
                    return {
                        "type": "tool_use",
                        "content": delta.get("partial_json", ""),
                        "raw": data,
                    }
            return None

        if event_type == "assistant":
            message = data.get("message", {})
            content_blocks = message.get("content", [])
            text_parts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if text_parts:
                return {
                    "type": "text",
                    "content": "\n".join(text_parts),
                    "raw": data,
                }
            return None

        if event_type == "result":
            return {
                "type": "result",
                "content": str(data.get("result", "")),
                "raw": data,
            }

        if event_type == "error":
            return {
                "type": "error",
                "content": str(data.get("error", "Unknown error")),
                "raw": data,
            }

        # system, init, and other types: not meaningful for consumers
        return None

    def _parse_codex_output(self, data: dict) -> dict | None:
        """Parse Codex JSONL output.

        Codex streams JSONL events. The key event is item.completed with
        type "agent_message" containing the response text. Other events
        include item.created, item.streaming, etc.
        """
        event_type = data.get("type")

        if event_type == "item.completed":
            item = data.get("item", {})
            if item.get("type") == "agent_message":
                # Extract text from content blocks
                content_parts = []
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        content_parts.append(block.get("text", ""))
                if content_parts:
                    return {
                        "type": "result",
                        "content": "\n".join(content_parts),
                        "raw": data,
                    }
            elif item.get("type") == "tool_call":
                return {
                    "type": "tool_use",
                    "content": item.get("name", "unknown_tool"),
                    "raw": data,
                }
            return None

        if event_type == "item.streaming":
            item = data.get("item", {})
            # Partial text during streaming
            content_parts = []
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    content_parts.append(block.get("text", ""))
            if content_parts:
                return {
                    "type": "text",
                    "content": "\n".join(content_parts),
                    "raw": data,
                }
            return None

        if event_type == "error":
            return {
                "type": "error",
                "content": str(data.get("message", data.get("error", "Unknown error"))),
                "raw": data,
            }

        # item.created and other events: not meaningful for consumers
        return None

    def _parse_gemini_output(self, data: dict) -> dict | None:
        """Parse Gemini JSON output.

        Gemini in one-shot mode emits a single JSON blob with:
        - "response": the text response
        - "stats": usage statistics
        """
        if "response" in data:
            return {
                "type": "result",
                "content": str(data["response"]),
                "raw": data,
            }

        if "error" in data:
            return {
                "type": "error",
                "content": str(data["error"]),
                "raw": data,
            }

        # Gemini may emit other structures; return as text if non-empty
        if data:
            return {
                "type": "text",
                "content": json.dumps(data),
                "raw": data,
            }

        return None

    async def launch(
        self,
        provider: str,
        model_id: str | None = None,
        prompt: str | None = None,
        working_dir: Path | None = None,
        run_as_user: str | None = None,
    ) -> ProcessHandle:
        """Launch a CLI process for the given provider and model.

        Args:
            provider: CLI provider key ("claude", "codex", "gemini").
            model_id: Specific model identifier. If None, uses provider default.
            prompt: One-shot prompt. If None, starts interactive mode (stdin open).
            working_dir: Working directory for the process. Defaults to cwd.
            run_as_user: If set, wraps command with sudo -u for multi-agent isolation.

        Returns:
            ProcessHandle with the running process and metadata.

        Raises:
            ValueError: If no matching profile exists.
            OSError: If the CLI binary is not found or process fails to start.
        """
        profile = self.get_profile(provider, model_id)
        cmd = self.build_command(profile, prompt)

        if run_as_user:
            cmd = self.wrap_command_for_user(cmd, run_as_user)

        work_dir = working_dir or Path.cwd()

        # Build clean environment. CURRENT_ROLE / ROLE_LAUNCHED_INTERACTIVE are
        # stripped because these are fresh, non-interactive CLI sessions — left
        # inherited they arm the SessionStart continuity hooks and create junk
        # roots in the role's window corpus.
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                             "CURRENT_ROLE", "ROLE_LAUNCHED_INTERACTIVE")}

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(work_dir),
            env=env,
        )

        return ProcessHandle(
            process=process,
            profile=profile,
            stdin=process.stdin,
            stdout=process.stdout,
            created_at=datetime.now(UTC),
            working_dir=work_dir,
        )
