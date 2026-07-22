"""One-at-a-time conversation with a persistent Codex session.

Resume-per-turn: first turn runs codex in JSON mode, captures the thread_id
from the opening event, and every subsequent turn runs the codex resume
subcommand with that thread_id. State is a single string, so conversations
survive process restarts — serialize chat.thread_id to persist.

Uses asyncio.create_subprocess_exec (argv list, no shell, no injection risk).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from .subprocess_env import scrub_model_subprocess_secrets


FIRST_TURN_ARGV = [
    "codex", "exec",
    "--sandbox", "read-only",
    "--skip-git-repo-check",
    "--json", "-",
]

RESUME_ARGV = ["codex", "exec", "resume", "--json"]


@dataclass
class CodexChat:
    thread_id: str | None = None
    # model=None lets codex pick its configured default (currently the latest
    # model the user has set in ~/.codex/config). Pin a specific id to lock
    # behavior for reproducibility.
    model: str | None = None
    timeout_seconds: int = 900
    # cwd=None inherits the parent process's cwd (right for stdio MCP usage).
    # Set explicitly when you want codex rooted in a specific directory.
    cwd: str | None = None

    async def send(self, prompt: str) -> str:
        argv = self._build_argv()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=scrub_model_subprocess_secrets(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(prompt.encode()),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exited {proc.returncode}: "
                f"{stderr.decode(errors='replace')[:500]}"
            )

        thread_id, text = _parse_codex_jsonl(stdout.decode())
        if self.thread_id is None and thread_id:
            self.thread_id = thread_id
        if not text:
            raise RuntimeError(
                "codex produced no agent_message. stderr: "
                f"{stderr.decode(errors='replace')[:500]}"
            )
        return text

    def _build_argv(self) -> list[str]:
        if self.thread_id is None:
            argv = list(FIRST_TURN_ARGV)
            if self.model:
                argv = ["codex", "exec", "-m", self.model] + argv[2:]
            return argv
        argv = list(RESUME_ARGV)
        if self.model:
            argv += ["-m", self.model]
        argv += [self.thread_id, "-"]
        return argv


def _parse_codex_jsonl(raw: str) -> tuple[str | None, str]:
    thread_id: str | None = None
    parts: list[str] = []
    for line in raw.strip().splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if thread_id is None and obj.get("thread_id"):
            thread_id = obj["thread_id"]
        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            if item.get("type") == "agent_message":
                for block in item.get("content", []):
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(block["text"])
                if not item.get("content") and item.get("text"):
                    parts.append(item["text"])
    return thread_id, "\n\n".join(parts)


async def _smoke_test() -> None:
    chat = CodexChat(model="gpt-5.4")
    print("=== turn 1 ===")
    r1 = await chat.send(
        "I'm going to tell you a number, then ask you about it next turn. "
        "The number is 4173. Just acknowledge briefly."
    )
    print(r1)
    print(f"\n[thread_id={chat.thread_id}]\n")
    print("=== turn 2 ===")
    r2 = await chat.send(
        "What was the number I told you, and what is it times 3? "
        "Show only the answer."
    )
    print(r2)


if __name__ == "__main__":
    asyncio.run(_smoke_test())
