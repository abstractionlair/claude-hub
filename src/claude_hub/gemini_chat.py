"""One-at-a-time conversation with a persistent Gemini session.

Resume-per-turn: first turn runs gemini in JSON mode, captures session_id
from the response. Every subsequent turn runs gemini with --resume
<session_id>. State is a single UUID string — serialize chat.session_id to
persist across restarts.

Note: --resume <UUID> is undocumented (gemini --help says --resume takes
"latest" or an index number) but works correctly and is stable across
concurrent sessions. Verified against gemini CLI 0.37.0.

Uses asyncio.create_subprocess_exec (argv list, no shell, no injection risk).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from .subprocess_env import scrub_model_subprocess_secrets


@dataclass
class GeminiChat:
    session_id: str | None = None
    # model=None lets gemini pick its configured default. Pin a specific id
    # to lock behavior for reproducibility.
    model: str | None = None
    timeout_seconds: int = 600
    # cwd=None inherits parent cwd. Set explicitly when you want gemini
    # rooted in a specific directory (also affects gemini's session storage
    # alias and its workspace-root sandbox).
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
                f"gemini exited {proc.returncode}: "
                f"{stderr.decode(errors='replace')[:500]}"
            )

        session_id, text = _parse_gemini_json(stdout.decode())
        if session_id:
            self.session_id = session_id
        if not text:
            raise RuntimeError(
                "gemini produced no response. stderr: "
                f"{stderr.decode(errors='replace')[:500]}"
            )
        return text

    def _build_argv(self) -> list[str]:
        argv = ["gemini", "-o", "json"]
        if self.model:
            argv += ["-m", self.model]
        if self.session_id is not None:
            argv += ["--resume", self.session_id]
        argv += ["-p", "-"]
        return argv


def _parse_gemini_json(raw: str) -> tuple[str | None, str]:
    """Parse gemini's single-JSON-blob output.

    Shape: {"session_id": "<uuid>", "response": "<text>", "stats": {...}}
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    session_id = data.get("session_id")
    response = (
        data.get("response")
        or data.get("text")
        or data.get("content")
        or ""
    )
    return session_id, response


async def _smoke_test() -> None:
    chat = GeminiChat(model="gemini-3-flash-preview")
    print("=== turn 1 ===")
    r1 = await chat.send(
        "I'm going to tell you a number, then ask you about it next turn. "
        "The number is 7306. Just acknowledge briefly."
    )
    print(r1)
    print(f"\n[session_id={chat.session_id}]\n")
    print("=== turn 2 ===")
    r2 = await chat.send(
        "What was the number I told you, and what is it times 4? "
        "Show only the answer."
    )
    print(r2)


if __name__ == "__main__":
    asyncio.run(_smoke_test())
