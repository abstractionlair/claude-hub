"""Routing table management."""

import uuid
from typing import Optional

from .models import RouteEntry


class RoutingTable:
    """
    Manages routing of conversations to Claude sessions.

    Default: all conversations route to main Claude.
    Main Claude (or sub-agents) can modify routing via control commands.
    """

    def __init__(self):
        self._routes: dict[str, RouteEntry] = {}
        self._message_counts: dict[str, int] = {}

    def generate_conversation_id(self) -> str:
        """Generate a unique conversation ID for a new chat."""
        return f"chat-{uuid.uuid4().hex[:8]}"

    def get_target(self, conversation_id: str) -> str:
        """Get the target session for a conversation."""
        entry = self._routes.get(conversation_id)
        if entry is None:
            return "main"

        # Check if we've exceeded message count limit
        if entry.expires_after_messages is not None:
            count = self._message_counts.get(conversation_id, 0)
            if count >= entry.expires_after_messages:
                # Revert to main
                del self._routes[conversation_id]
                return "main"

        return entry.target

    def record_message(self, conversation_id: str) -> None:
        """Record that a message was sent in a conversation."""
        self._message_counts[conversation_id] = self._message_counts.get(conversation_id, 0) + 1

    def route_to(
        self,
        conversation_id: str,
        target: str,
        message_count: Optional[int] = None
    ) -> None:
        """Route a conversation to a specific target."""
        self._routes[conversation_id] = RouteEntry(
            conversation_id=conversation_id,
            target=target,
            expires_after_messages=message_count,
        )
        # Reset message count when re-routing
        self._message_counts[conversation_id] = 0

    def release(self, conversation_id: str) -> None:
        """Release a conversation back to main."""
        if conversation_id in self._routes:
            del self._routes[conversation_id]

    def get_all_routes(self) -> dict[str, RouteEntry]:
        """Get all active routes (for debugging/inspection)."""
        return self._routes.copy()
