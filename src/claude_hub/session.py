"""Session lifecycle management for Claude Code processes."""

import subprocess
import json
import uuid
import os
import re
import signal
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from .observations import (
    ObservationStore,
    parse_observation_markers,
    extract_keywords,
)


# Sentinel: main session uses --continue (most recent session) instead of a fixed UUID
MAIN_SESSION_UUID = None

# Context monitoring prompt - instructs Main Claude to self-report token usage
CONTEXT_MONITOR_PROMPT = """
Monitor your context window usage. After each response, check your token usage
from system warnings. Include this marker at the end of your response:
[TOKENS: X/Y/PCT] where X=tokens used, Y=total tokens, PCT=percentage used.

If usage is ≥95%, also include [CONTEXT_CRITICAL] marker.
""".strip()

# Threshold constants for context window management
CONTEXT_CRITICAL_THRESHOLD = 95  # Percent - force restart at this point

# Observation retrieval settings
OBSERVATION_LOAD_LIMIT = 15  # Max observations to load at session start
OBSERVATION_TOPIC_LIMIT = 5  # Additional observations for topic-triggered retrieval
OBSERVATION_MIN_CONFIDENCE = 0.3  # Minimum effective confidence to load

# Response size limits for MCP clients
MAX_RESPONSE_CHARS = 12000  # ~3000 tokens - safe for chat clients
TRUNCATION_MESSAGE = "\n\n[Response truncated due to size limit. Full output available in Claude Code session.]"


@dataclass
class SessionInfo:
    """Information about a Claude Code session."""
    session_id: str
    claude_session_id: str  # UUID for --resume
    message_count: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    tokens_used: int = 0
    tokens_total: int = 200000  # Default budget
    usage_percent: float = 0.0


class SessionManager:
    """
    Manages Claude Code session lifecycle.

    Uses Claude Code's --resume feature for session continuity.
    The main session persists across messages, maintaining context
    through Claude Code's built-in session management and
    continuous-claude hooks.
    """

    def __init__(
        self,
        claude_binary: str = "claude",
        project_dir: Optional[Path] = None
    ):
        self.claude_binary = claude_binary
        # Project dir for running claude (enables continuous-claude hooks)
        self.project_dir = project_dir or Path.home() / "claude-hub"
        self._sessions: dict[str, SessionInfo] = {}
        self._claude_process: Optional[subprocess.Popen] = None

        # Initialize observation store
        self.observation_store = ObservationStore(dsn=os.environ.get("CLAUDE_HUB_PG_DSN", ""))
        self._session_observations_loaded: set[str] = set()  # Track which sessions have loaded initial observations

    def get_or_create_main(self) -> SessionInfo:
        """Get the main Claude session, creating if needed."""
        if "main" not in self._sessions:
            self._sessions["main"] = SessionInfo(
                session_id="main",
                claude_session_id=MAIN_SESSION_UUID,
            )
        return self._sessions["main"]

    def create_subagent(self, agent_id: str) -> SessionInfo:
        """Create a new sub-agent session."""
        if agent_id in self._sessions:
            return self._sessions[agent_id]
        self._sessions[agent_id] = SessionInfo(
            session_id=agent_id,
            claude_session_id=str(uuid.uuid4()),
        )
        return self._sessions[agent_id]

    def _extract_token_usage(self, response: str) -> tuple[int, int, float]:
        """Extract token usage from Main Claude's self-reported markers."""
        match = re.search(r'\[TOKENS: (\d+)/(\d+)/([\d.]+)\]', response)
        if match:
            used = int(match.group(1))
            total = int(match.group(2))
            pct = float(match.group(3))
            return used, total, pct
        return 0, 0, 0.0

    def _is_context_critical(self, response: str) -> bool:
        """Check if Main Claude signaled critical context usage."""
        return '[CONTEXT_CRITICAL]' in response

    def _truncate_response(self, response: str, max_chars: int = MAX_RESPONSE_CHARS) -> str:
        """
        Truncate response if it exceeds size limits.

        Preserves beginning and end of response, truncating the middle.
        This ensures Chat Claude sees the context and conclusion even if
        the middle details are cut.
        """
        if len(response) <= max_chars:
            return response

        # Reserve space for truncation message
        available = max_chars - len(TRUNCATION_MESSAGE)

        # Keep 60% at start, 40% at end
        start_chars = int(available * 0.6)
        end_chars = available - start_chars

        start = response[:start_chars]
        end = response[-end_chars:]

        return start + TRUNCATION_MESSAGE + end

    def _update_session_tokens(self, session_id: str, tokens_used: int, tokens_total: int, usage_percent: float):
        """Update token usage for a session."""
        session = self._sessions.get(session_id)
        if session:
            session.tokens_used = tokens_used
            session.tokens_total = tokens_total
            session.usage_percent = usage_percent

    def _get_observations_for_message(self, session_id: str, message: str) -> str:
        """
        Get relevant observations to include in context.

        On first message to a session, loads recent high-confidence observations.
        For all messages, does topic-triggered retrieval based on keywords.
        """
        observations = []

        # Session start: load recent high-confidence observations
        if session_id not in self._session_observations_loaded:
            recent = self.observation_store.get_recent(
                days=30,
                limit=OBSERVATION_LOAD_LIMIT,
                min_confidence=OBSERVATION_MIN_CONFIDENCE
            )
            observations.extend(recent)
            self._session_observations_loaded.add(session_id)
            print(f"[Observations] Loaded {len(recent)} recent observations for session {session_id}")

        # Topic-triggered: extract keywords and find relevant observations
        keywords = extract_keywords(message)
        if keywords:
            relevant = self.observation_store.get_relevant(
                tags=keywords,
                limit=OBSERVATION_TOPIC_LIMIT,
                min_confidence=OBSERVATION_MIN_CONFIDENCE
            )
            # Avoid duplicates
            existing_ids = {o.id for o in observations}
            new_relevant = [o for o in relevant if o.id not in existing_ids]
            if new_relevant:
                observations.extend(new_relevant)
                print(f"[Observations] Loaded {len(new_relevant)} topic-relevant observations for keywords: {keywords[:5]}")

        if not observations:
            return ""

        return self.observation_store.format_for_context(observations)

    def _process_observation_markers(self, response: str, session_id: str) -> list:
        """Parse and record any observation markers in the response."""
        recorded = parse_observation_markers(
            response,
            self.observation_store,
            session_id=session_id
        )
        if recorded:
            print(f"[Observations] Recorded {len(recorded)} new observations from response")
        return recorded

    def _run_claude(
        self,
        session: "SessionInfo",
        message: str,
        observations_context: str = "",
        use_resume: bool = True
    ) -> subprocess.CompletedProcess:
        """Run claude command and return the result."""
        cmd = [self.claude_binary, "--print", "--dangerously-skip-permissions"]

        if session.claude_session_id is None:
            # Main session: use --continue to pick up the most recent session
            if use_resume:
                cmd.append("--continue")
            # If use_resume=False, no session flag — starts a fresh session
        elif use_resume:
            cmd.extend(["--resume", session.claude_session_id])
        else:
            cmd.extend(["--session-id", session.claude_session_id])

        # Add context monitoring prompt to instruct Main Claude to self-report token usage
        cmd.extend(["--append-system-prompt", CONTEXT_MONITOR_PROMPT])

        # If we have observations to inject, prepend them to the message as a system reminder
        if observations_context:
            full_message = f"<system-reminder>\n{observations_context}</system-reminder>\n\n{message}"
        else:
            full_message = message

        cmd.append(full_message)

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(self.project_dir),  # Run from project dir for hooks
            env={
                **os.environ,
                "HOME": str(Path.home()),
                "CURRENT_ROLE": "mcp-server",
            }
        )

    def send_message(self, session_id: str, message: str) -> str:
        """
        Send a message to a Claude session and get response.

        Strategy: Always try --resume first since the session likely exists
        (from previous server runs or persistent Claude processes). Only fall
        back to --session-id if the session doesn't exist yet.

        Runs from project directory to enable continuous-claude hooks.
        Injects relevant observations into context automatically.
        """
        session = self._sessions.get(session_id)
        if session is None:
            if session_id == "main":
                session = self.get_or_create_main()
            else:
                raise ValueError(f"Unknown session: {session_id}")

        # Update activity timestamp
        session.last_activity = datetime.utcnow()
        session.message_count += 1

        # Get relevant observations for this message
        observations_context = self._get_observations_for_message(session_id, message)

        try:
            # Try --continue first (main) or --resume (subagents)
            result = self._run_claude(session, message, observations_context, use_resume=True)

            # No session to continue - start fresh
            if result.stderr and "No session found" in result.stderr:
                print(f"[Session {session_id}] No session to continue, starting fresh")
                result = self._run_claude(session, message, observations_context, use_resume=False)

            # Session locked by interactive use - start fresh instead
            if result.stderr and "already in use" in result.stderr:
                print(f"[Session {session_id}] Session in use, starting fresh session")
                result = self._run_claude(session, message, observations_context, use_resume=False)

            response = result.stdout.strip()

            # Process any observation markers in the response
            self._process_observation_markers(response, session_id)

            # Extract token usage from Main Claude's self-report
            tokens_used, tokens_total, usage_pct = self._extract_token_usage(response)
            if tokens_used > 0:
                self._update_session_tokens(session_id, tokens_used, tokens_total, usage_pct)
                print(f"[Session {session_id}] Token usage: {tokens_used}/{tokens_total} ({usage_pct}%)")

                # Check thresholds and handle accordingly
                if usage_pct >= CONTEXT_CRITICAL_THRESHOLD:
                    # CRITICAL: Must restart now (blocking)
                    self._handle_critical_context(session_id)

            # Log any stderr (hook errors, etc.) but don't fail
            if result.stderr:
                # Filter out common hook noise
                stderr_lines = [
                    line for line in result.stderr.split('\n')
                    if line and not line.startswith('SessionEnd hook')
                ]
                if stderr_lines:
                    print(f"[Session {session_id}] stderr: {stderr_lines[:3]}")

                # If no response but there's an error, return the error
                if not response and stderr_lines:
                    return f"[Error: {stderr_lines[0]}]"

            # Truncate response if needed for MCP client size limits
            final_response = response if response else "[No response from Claude]"
            return self._truncate_response(final_response)

        except subprocess.TimeoutExpired:
            return "[Error: Claude session timed out after 300s. Operation may still be running in background. Consider using async operations for long-running tasks.]"
        except FileNotFoundError:
            return "[Error: Claude CLI not found. Is claude-code installed?]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    def terminate_session(self, session_id: str) -> None:
        """Terminate/forget a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def list_sessions(self) -> list[str]:
        """List active session IDs."""
        return list(self._sessions.keys())

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get info about a session."""
        return self._sessions.get(session_id)

    def get_token_usage(self, session_id: str) -> int:
        """Get tokens used for a session."""
        session = self._sessions.get(session_id)
        return session.tokens_used if session else 0

    def get_token_total(self, session_id: str) -> int:
        """Get total token capacity for a session."""
        session = self._sessions.get(session_id)
        return session.tokens_total if session else 200000

    def calculate_usage_percentage(self, session_id: str) -> float:
        """Calculate token usage percentage for a session."""
        session = self._sessions.get(session_id)
        return session.usage_percent if session else 0.0

    def get_tokens_remaining(self, session_id: str) -> int:
        """Get remaining token capacity for a session."""
        session = self._sessions.get(session_id)
        if session and session.tokens_total > 0:
            return session.tokens_total - session.tokens_used
        return 0

    def get_observation_stats(self) -> dict:
        """Get statistics about the observation store."""
        return self.observation_store.get_stats()

    def _handle_critical_context(self, session_id: str):
        """
        Graceful restart at 95% threshold (blocking).

        Kills Claude process and resets session state so next message
        starts fresh (SessionStart hook loads window file context).
        """
        try:
            print(f"[Context Critical] Initiating graceful restart for {session_id}")

            # 1. Kill Claude process
            # We use pkill to kill any running claude processes with our session ID
            # This is safer than trying to track the process ourselves
            try:
                subprocess.run(
                    ["pkill", "-f", f"--resume {session_id}"],
                    timeout=5
                )
                print(f"[Context Critical] Killed Claude process for {session_id}")
            except Exception as e:
                print(f"[Context Critical] Failed to kill Claude process: {e}")

            # 2. Reset session state (next message will create fresh session)
            session = self._sessions.get(session_id)
            if session:
                session.tokens_used = 0
                session.tokens_total = 200000
                session.usage_percent = 0.0
                print(f"[Context Critical] Reset session state. Next message will resume with fresh context.")

        except Exception as e:
            print(f"[Context Critical] Error during graceful restart: {e}")
