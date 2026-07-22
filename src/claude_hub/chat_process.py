"""Persistent Claude Code process manager for streaming web chat.

Manages long-lived Claude Code processes that communicate via stream-json
stdin/stdout. Each process stays alive across multiple messages, preserving
session context. Processes are keyed by chat_id, supporting multiple
concurrent conversations.

Architecture:
    Browser <-> WebSocket <-> FastAPI <-> stdin/stdout <-> claude (persistent)

    Each process has a background asyncio task that continuously reads stdout,
    preventing pipe buffer overflow and desync. Callers subscribe to receive
    events via asyncio.Queue, then write to stdin. The reader fans events to
    all subscribers.

Process command:
    claude -p --input-format stream-json --output-format stream-json
           --verbose --dangerously-skip-permissions --include-partial-messages

Input format (one JSON line per message):
    {"type":"user","message":{"role":"user","content":[{"type":"text","text":"..."}]}}

Output format (NDJSON on stdout, when process stdin is kept open):
    {"type":"system","subtype":"init",...}                    — process ready
    {"type":"stream_event","event":{"type":"content_block_delta",...}} — streaming token
    {"type":"assistant","message":{...},...}                  — complete response
    {"type":"result","result":"...","duration_ms":...,...}    — turn complete
"""

import asyncio
import json
import os
import shutil
import subprocess
import uuid

from .subprocess_env import scrub_model_subprocess_secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional


@dataclass
class ChatProcess:
    """A managed Claude Code process with a background stdout reader."""
    chat_id: str
    process: asyncio.subprocess.Process
    session_id: Optional[str] = None  # Claude session UUID (from init event)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    message_count: int = 0
    busy: bool = False  # True while processing a message

    # Background reader infrastructure
    _reader_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _subscribers: dict[str, asyncio.Queue] = field(default_factory=dict, repr=False)
    _dead: bool = field(default=False, repr=False)  # Set when reader detects EOF/exit

    def subscribe(self, subscriber_id: str) -> asyncio.Queue:
        """Register a subscriber queue for stdout events."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[subscriber_id] = q
        return q

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber queue."""
        self._subscribers.pop(subscriber_id, None)


class ChatProcessManager:
    """Manages persistent Claude Code processes for web chat.

    Processes are keyed by chat_id. Each process is a long-lived Claude Code
    instance communicating via stream-json over stdin/stdout.

    Each process has a background asyncio task that continuously reads stdout,
    preventing pipe buffer overflow and stdout desync after timeouts. Callers
    use send_message() which subscribes a queue, writes to stdin, and yields
    events from the queue.

    Chat processes run from /home/claude/claude-chat/ (Chat identity) with
    --add-dir access to /home/claude/claude-hub/ (shared project state).
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        claude_binary: Optional[str] = None,
        observations_dsn: Optional[str] = None,
    ):
        self.project_dir = project_dir or Path.home() / "claude-hub"
        self.chat_dir = Path.home() / "claude-chat"
        self.claude_binary = claude_binary or shutil.which("claude") or "claude"
        self.observations_dsn = observations_dsn or os.environ.get("CLAUDE_HUB_PG_DSN", "")
        self._processes: dict[str, ChatProcess] = {}
        self._lock = asyncio.Lock()

    async def get_or_spawn(
        self, chat_id: str, priming_message: Optional[str] = None, cwd: Optional[Path] = None
    ) -> ChatProcess:
        """Get an existing process or spawn a new one for this chat_id.

        Args:
            chat_id: Unique identifier for this chat session.
            priming_message: If provided, use instead of _build_priming_message()
                when spawning a new process. Used by MessageRouter for group-aware priming.
            cwd: Working directory override. Defaults to self.chat_dir.
                Use self.project_dir for Main Claude role (gets main CLAUDE.md + full context access).
        """
        async with self._lock:
            cp = self._processes.get(chat_id)
            if cp and cp.process.returncode is None and not cp._dead:
                return cp
            # Process dead or doesn't exist — spawn fresh
            if cp:
                # Cancel reader task before removing
                if cp._reader_task and not cp._reader_task.done():
                    cp._reader_task.cancel()
                    try:
                        await cp._reader_task
                    except asyncio.CancelledError:
                        pass
                del self._processes[chat_id]
            return await self._spawn(chat_id, priming_message=priming_message, cwd=cwd)

    async def _spawn(
        self, chat_id: str, priming_message: Optional[str] = None, cwd: Optional[Path] = None
    ) -> ChatProcess:
        """Spawn a new Claude Code process. Must be called under self._lock.

        Args:
            cwd: Working directory override. Defaults to self.chat_dir.
        """
        work_dir = cwd or self.chat_dir
        cmd = [
            self.claude_binary,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--include-partial-messages",
        ]
        # Only add --add-dir if cwd is different from project_dir
        # (when running in project_dir, the CLAUDE.md is already available)
        if work_dir != self.project_dir:
            cmd.extend(["--add-dir", str(self.project_dir)])

        # Build clean environment: strip the service's secrets (the model child
        # never needs them) and unset CLAUDECODE to allow nested spawning.
        env = {k: v for k, v in scrub_model_subprocess_secrets().items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        env["HOME"] = str(Path.home())
        env["CURRENT_ROLE"] = "mcp-server"

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(work_dir),
            env=env,
            limit=1_048_576,  # 1MB — default 64KB is too small for large JSON responses
        )

        cp = ChatProcess(chat_id=chat_id, process=process)
        self._processes[chat_id] = cp

        # Build and send priming message with state injection
        priming_text = priming_message or self._build_priming_message()
        init_msg = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": priming_text}],
            },
        })
        process.stdin.write((init_msg + "\n").encode())
        await process.stdin.drain()

        # Read the init event, then drain the priming message's response
        # (everything up to and including the "result" event)
        try:
            while True:
                line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=30.0
                )
                if not line:
                    break
                data = json.loads(line.decode().strip())
                etype = data.get("type")
                if etype == "system" and data.get("subtype") == "init":
                    cp.session_id = data.get("session_id")
                elif etype == "result":
                    # Priming message complete — process is ready
                    break
        except (asyncio.TimeoutError, json.JSONDecodeError) as e:
            print(f"[ChatProcess] Warning: init/prime failed for {chat_id}: {e}")

        # Start the background stdout reader (takes over stdout from here)
        cp._reader_task = asyncio.create_task(
            self._stdout_reader(cp),
            name=f"stdout-reader-{chat_id}",
        )

        return cp

    async def _stdout_reader(self, cp: ChatProcess) -> None:
        """Background task: continuously read stdout and fan out to subscribers.

        Runs until the process exits or stdout closes. On exit, notifies all
        subscribers with an error event and marks the ChatProcess as dead.
        Never times out — the pipe is always drained.
        """
        try:
            while True:
                line = await cp.process.stdout.readline()
                if not line:
                    # EOF — process closed stdout
                    error_event = {"type": "error", "error": "Process closed stdout"}
                    for q in list(cp._subscribers.values()):
                        await q.put(error_event)
                    cp._dead = True
                    break

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                # Fan out to all current subscribers
                for q in list(cp._subscribers.values()):
                    await q.put(event)

                # "result" marks end of a turn — clear busy flag
                if event.get("type") == "result":
                    cp.busy = False

        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_event = {"type": "error", "error": f"Reader error: {e}"}
            for q in list(cp._subscribers.values()):
                await q.put(error_event)
            cp._dead = True

    async def write_message(self, chat_id: str, text: str) -> ChatProcess:
        """Write a message to a chat process's stdin. Does not read stdout.

        Returns the ChatProcess for subscription. Raises ValueError if
        the process is dead.
        """
        cp = await self.get_or_spawn(chat_id)

        if cp._dead:
            raise ValueError(f"Process {chat_id} is dead")

        cp.busy = True
        cp.last_activity = datetime.utcnow()
        cp.message_count += 1

        input_msg = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        })
        cp.process.stdin.write((input_msg + "\n").encode())
        await cp.process.stdin.drain()

        return cp

    async def send_message(
        self,
        chat_id: str,
        text: str,
        cwd: Optional[Path] = None,
    ) -> AsyncIterator[dict]:
        """Send a message to a chat process and yield streaming events.

        Yields NDJSON event dicts as they arrive. The final event will have
        type="result". If the process dies mid-stream, yields an error event.

        Internally: subscribes a queue to the background reader, writes to
        stdin, yields events from the queue, then unsubscribes. The background
        reader continuously drains stdout regardless of subscriber timeouts.
        """
        cp = await self.get_or_spawn(chat_id, cwd=cwd)

        if cp.busy:
            yield {"type": "error", "error": "Process is busy with another message"}
            return

        sub_id = f"send-{uuid.uuid4().hex[:8]}"
        queue = cp.subscribe(sub_id)  # Subscribe BEFORE write — no missed events

        try:
            await self.write_message(chat_id, text)

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield {"type": "error", "error": "Response timed out (300s)"}
                    break

                yield event

                # "result" or "error" marks end of this turn
                if event.get("type") in ("result", "error"):
                    break
        finally:
            cp.unsubscribe(sub_id)

    async def kill_process(self, chat_id: str, skip_busy: bool = False) -> bool:
        """Kill a specific chat process.

        Args:
            chat_id: Process key to kill.
            skip_busy: If True, skip processes currently marked busy (for idle reaping).
        """
        # Pop under lock, but do the slow wait/kill outside to avoid blocking
        cp = None
        async with self._lock:
            candidate = self._processes.get(chat_id)
            if candidate is None or candidate.process.returncode is not None:
                return False
            if skip_busy and candidate.busy:
                return False  # Became busy since we identified it — don't kill
            cp = self._processes.pop(chat_id)

        # Cancel reader and terminate outside the lock
        if cp._reader_task and not cp._reader_task.done():
            cp._reader_task.cancel()
            try:
                await cp._reader_task
            except asyncio.CancelledError:
                pass
        cp.process.terminate()
        try:
            await asyncio.wait_for(cp.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            cp.process.kill()
        return True

    async def reap_idle(self, max_idle_seconds: float = 1800) -> int:
        """Kill processes that have been idle longer than max_idle_seconds.

        Skips processes with chat_id starting with "group-" since those are
        managed by MessageRouter and cannot be respawned after reaping.

        Returns the number of processes reaped.
        """
        now = datetime.utcnow()
        to_reap = []
        async with self._lock:
            for chat_id, cp in self._processes.items():
                # Don't reap group-chat participants — they can't be respawned
                if chat_id.startswith("group-"):
                    continue
                if cp.busy:
                    continue
                idle = (now - cp.last_activity).total_seconds()
                if idle > max_idle_seconds:
                    to_reap.append(chat_id)

        reaped = 0
        for chat_id in to_reap:
            # skip_busy=True re-checks busy flag inside lock to close TOCTOU gap
            if await self.kill_process(chat_id, skip_busy=True):
                reaped += 1
        return reaped

    async def shutdown(self):
        """Kill all managed processes. Call on server shutdown."""
        async with self._lock:
            for chat_id, cp in list(self._processes.items()):
                if cp._reader_task and not cp._reader_task.done():
                    cp._reader_task.cancel()
                    try:
                        await cp._reader_task
                    except asyncio.CancelledError:
                        pass
                if cp.process.returncode is None:
                    cp.process.terminate()
                    try:
                        await asyncio.wait_for(cp.process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        cp.process.kill()
            self._processes.clear()

    def _build_priming_message(self) -> str:
        """Build the priming message with injected state.

        Includes:
        - Latest window-file context (continuity across sessions)
        - Recent observations
        - System snapshot

        Best-effort: any failure falls back to minimal prime.
        """
        sections = []

        # Role instructions from role files (reads CURRENT_ROLE from env)
        role_name = os.environ.get("CURRENT_ROLE", "mcp-server")
        role_dir = Path.home() / "roles" / role_name
        manifest_file = Path.home() / "shared" / "infrastructure-manifest.md"

        # Load role shared.md
        role_shared = role_dir / "shared.md"
        if role_shared.exists():
            sections.append(role_shared.read_text())
        else:
            # Fallback if role file missing
            sections.append(
                f"## Role: {role_name}\n\n"
                f"Role file not found at {role_shared}. "
                "Read it manually if needed."
            )

        # Load infrastructure manifest
        if manifest_file.exists():
            sections.append(manifest_file.read_text())

        # Load global user context
        user_context = Path.home() / "shared" / "user-context.md"
        if user_context.exists():
            sections.append(user_context.read_text())

        # Path restrictions — prevent FUSE mount crawling
        sections.append(
            "### Path Restrictions\n"
            "The following paths contain FUSE mounts (remote filesystems) that are extremely slow to traverse. "
            "NEVER use `find`, `ls -R`, `tree`, or any recursive command on these paths:\n"
            "- /storage/google/ — Google Drive (FUSE mount, will hang for 25+ min)\n"
            "- /storage/onedrive/ — OneDrive (FUSE mount, will hang for 25+ min)\n"
            "- /storage/pcloud/ — pCloud (FUSE mount, will hang for 25+ min)\n"
            "- /mnt/ — system mount points (contains FUSE bind mounts)\n"
            "- /storage/ — use only specific known subdirectories, never recursive search\n\n"
            "If you need to find files on remote storage, ask the user for the specific path "
            "rather than searching broadly."
        )

        # Window-file context (replaces legacy ledger summary)
        try:
            window_summary = self._get_window_context()
            if window_summary:
                sections.append(window_summary)
        except Exception as e:
            print(f"[ChatProcess] Warning: window context failed: {e}")

        # Recent observations
        try:
            obs_summary = self._get_observations_summary()
            if obs_summary:
                sections.append(obs_summary)
        except Exception as e:
            print(f"[ChatProcess] Warning: observations summary failed: {e}")

        # System snapshot
        try:
            sys_snapshot = self._get_system_snapshot()
            if sys_snapshot:
                sections.append(sys_snapshot)
        except Exception as e:
            print(f"[ChatProcess] Warning: system snapshot failed: {e}")

        if sections:
            header = (
                "Here is your current state and recent context. "
                "Take a moment to orient, then respond with \"ready\" "
                "to indicate you're prepared for incoming requests.\n\n"
            )
            return header + "\n\n".join(sections)
        else:
            return (
                "You are Main Claude, starting up with minimal context. "
                "Respond with \"ready\" when you're prepared for requests."
            )

    def _get_window_context(self) -> Optional[str]:
        """Load the latest window file for continuity context.

        Checks role-scoped windows first (~/roles/$CURRENT_ROLE/windows/),
        falls back to project-local windows.
        """
        try:
            role = os.environ.get("CURRENT_ROLE")
            window_path = None

            # Try role-scoped windows first
            if role:
                role_windows = Path.home() / "roles" / role / "windows"
                if role_windows.is_dir():
                    # Find most recent .md file
                    candidates = sorted(role_windows.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if candidates:
                        window_path = candidates[0]

            # Fallback to project-local
            if window_path is None:
                from .continuity import find_latest_window
                window_path = find_latest_window(harness="claude-code")

            if window_path is None:
                return None

            content = window_path.read_text(encoding="utf-8")
            if not content.strip():
                return None

            # Truncate if very large (keep first ~2000 chars)
            if len(content) > 2000:
                content = content[:2000] + "\n\n[... truncated ...]"

            return (
                f"### Window Context: {window_path.name}\n\n"
                f"{content}"
            )
        except Exception:
            return None

    def _get_observations_summary(self) -> Optional[str]:
        """Get recent observations formatted for context."""
        if not self.observations_dsn:
            return None

        try:
            from .observations import ObservationStore
            store = ObservationStore(dsn=self.observations_dsn)
            recent = store.get_recent(limit=10)
            if not recent:
                return None
            return store.format_for_context(recent)
        except Exception:
            return None

    def _get_system_snapshot(self) -> Optional[str]:
        """Get brief system snapshot (uptime, disk, key services)."""
        lines = ["### System Snapshot"]

        try:
            uptime = subprocess.run(
                ["uptime", "-p"], capture_output=True, text=True, timeout=5
            )
            if uptime.returncode == 0:
                lines.append(f"- Uptime: {uptime.stdout.strip()}")
        except Exception:
            pass

        try:
            df = subprocess.run(
                ["df", "-h", "--output=avail,pcent", "/", "/storage"],
                capture_output=True, text=True, timeout=5,
            )
            if df.returncode == 0:
                lines.append(f"- Disk:\n```\n{df.stdout.strip()}\n```")
        except Exception:
            pass

        # Check key services
        services = ["claude-hub", "nginx"]
        for svc in services:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=5,
                )
                status = result.stdout.strip()
                lines.append(f"- {svc}: {status}")
            except Exception:
                pass

        return "\n".join(lines) if len(lines) > 1 else None

    def get_chat_summary(self, chat_id: str) -> Optional[dict]:
        """Get summary of a chat session for history logging."""
        cp = self._processes.get(chat_id)
        if not cp:
            return None
        now = datetime.utcnow()
        duration = now - cp.created_at
        return {
            "chat_id": chat_id,
            "session_id": cp.session_id,
            "message_count": cp.message_count,
            "duration_seconds": int(duration.total_seconds()),
            "created_at": cp.created_at.isoformat(),
            "ended_at": now.isoformat(),
        }

    def list_chats(self) -> list[dict]:
        """List all active chat processes with metadata."""
        result = []
        for chat_id, cp in self._processes.items():
            alive = cp.process.returncode is None
            result.append({
                "chat_id": chat_id,
                "session_id": cp.session_id,
                "alive": alive,
                "busy": cp.busy,
                "message_count": cp.message_count,
                "created_at": cp.created_at.isoformat(),
                "last_activity": cp.last_activity.isoformat(),
            })
        return result
