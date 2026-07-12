import asyncio
from types import SimpleNamespace

import pytest

import claude_hub.server as server
from claude_hub.models import GroupPollRequest


def _install_poll_queue(monkeypatch, participant_id: str = "mcp-a") -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    participant = SimpleNamespace(poll_queue=queue)
    conversation = SimpleNamespace(participants={participant_id: participant})
    router = SimpleNamespace(
        _participant_index={participant_id: "conv-a"},
        get_conversation=lambda conv_id: conversation if conv_id == "conv-a" else None,
    )
    monkeypatch.setattr(server, "message_router", router, raising=False)
    return queue


@pytest.mark.asyncio
async def test_group_poll_drains_existing_messages_without_waiting(monkeypatch):
    queue = _install_poll_queue(monkeypatch)
    await queue.put({"type": "group_message", "content": "ready"})

    response = await server.group_poll(
        GroupPollRequest(participant_id="mcp-a", wait_seconds=30),
        client=None,
    )

    assert response.messages == [{"type": "group_message", "content": "ready"}]


@pytest.mark.asyncio
async def test_group_poll_waits_for_first_message_then_drains(monkeypatch):
    queue = _install_poll_queue(monkeypatch)

    async def delayed_messages() -> None:
        await asyncio.sleep(0.01)
        await queue.put({"type": "group_message", "content": "first"})
        await queue.put({"type": "group_message", "content": "second"})

    producer = asyncio.create_task(delayed_messages())

    response = await server.group_poll(
        GroupPollRequest(participant_id="mcp-a", wait_seconds=0.2),
        client=None,
    )
    await producer

    assert [m["content"] for m in response.messages] == ["first", "second"]


@pytest.mark.asyncio
async def test_group_poll_wait_timeout_returns_empty(monkeypatch):
    _install_poll_queue(monkeypatch)

    response = await server.group_poll(
        GroupPollRequest(participant_id="mcp-a", wait_seconds=0.01),
        client=None,
    )

    assert response.messages == []
