"""Multi-participant message router for group conversations.

Event-driven message bus architecture. All messages (from humans, Claude
processes, MCP clients) flow through a per-conversation inbox. A dispatcher
task delivers each message to all participants except the sender. Claude
responses flow back through the inbox at depth+1, with depth limiting to
prevent infinite cascading.

Architecture:
    Human (WS) ---- ws_reader ---+
                                 |     +---------+     +------------+
    Claude A -- claude_listener -+---->|  Inbox  |---->| Dispatcher |---> outbound queues
                                 |     | (Queue) |     |  (Task)    |    +-- Human -> WS
    Claude B -- claude_listener -+     +---------+     +------------+    +-- Claude -> stdin
                                 |                                       +-- MCP -> poll_queue
    MCP Client -- group_send ----+
"""

import asyncio
import logging
from typing import Optional

from .chat_process import ChatProcessManager
from .conversation_store import ConversationStore, ConversationStatus
from .conversation import (
    Conversation,
    GroupMessage,
    MessageType,
    Participant,
    ParticipantType,
    make_conversation_id,
    make_message_id,
)

logger = logging.getLogger(__name__)


class ConversationBus:
    """Event-driven message bus for a conversation.

    All messages (from humans, Claude processes, MCP clients) flow through
    the same inbox. A dispatcher task delivers each message to all participants
    except the sender. Claude responses flow back through the inbox at depth+1.
    """

    def __init__(
        self,
        conv: Conversation,
        cpm: ChatProcessManager,
        store: Optional[ConversationStore] = None,
    ):
        self._conv = conv
        self._cpm = cpm
        self._store = store
        self._inbox: asyncio.Queue = asyncio.Queue()  # GroupMessage
        self._outbound: dict[str, asyncio.Queue] = {}  # participant_id -> outbound queue
        self._claude_tasks: dict[str, tuple] = {}  # participant_id -> (writer_task, listener_task)
        self._claude_delivery: dict[str, asyncio.Queue] = {}  # participant_id -> delivery queue
        self._cli_tasks: dict[str, asyncio.Task] = {}  # participant_id -> worker task (CLI_CHAT)
        self._cli_delivery: dict[str, asyncio.Queue] = {}  # participant_id -> delivery queue (CLI_CHAT)
        self._dispatcher_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the dispatcher task."""
        self._dispatcher_task = asyncio.create_task(
            self._dispatch(), name=f"dispatcher-{self._conv.conversation_id}"
        )

    async def stop(self) -> None:
        """Stop dispatcher, all writer/listener tasks, and clean up queues."""
        if self._dispatcher_task and not self._dispatcher_task.done():
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None

        # Cancel all Claude tasks
        for pid, (writer, listener) in list(self._claude_tasks.items()):
            writer.cancel()
            listener.cancel()
            try:
                await writer
            except asyncio.CancelledError:
                pass
            try:
                await listener
            except asyncio.CancelledError:
                pass
        self._claude_tasks.clear()
        self._claude_delivery.clear()

        # Cancel all CLI worker tasks
        for pid, task in list(self._cli_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._cli_tasks.clear()
        self._cli_delivery.clear()

        self._outbound.clear()

    def subscribe(self, participant_id: str) -> asyncio.Queue:
        """Get or create an outbound queue for a participant."""
        if participant_id not in self._outbound:
            self._outbound[participant_id] = asyncio.Queue()
        return self._outbound[participant_id]

    def unsubscribe(self, participant_id: str) -> None:
        """Remove a participant's outbound queue."""
        self._outbound.pop(participant_id, None)

    async def post_message(
        self,
        sender_id: str,
        content: str,
        recipient_id: Optional[str] = None,
    ) -> GroupMessage:
        """Post a message to the inbox.

        Creates a GroupMessage, puts an echo in the sender's outbound queue
        (so the sender sees their own message), then puts the message in the
        inbox for delivery to everyone else.
        """
        sender = self._conv.participants.get(sender_id)
        sender_name = sender.name if sender else sender_id

        msg = GroupMessage(
            id=make_message_id(),
            conversation_id=self._conv.conversation_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            recipient_id=recipient_id,
        )

        # Echo to sender's outbound queue (they see their own message)
        q = self._outbound.get(sender_id)
        if q:
            await q.put({"type": "group_message", **msg.to_dict()})

        # Post to inbox for delivery to everyone else
        await self._inbox.put(msg)
        return msg

    async def _dispatch(self) -> None:
        """Main loop: pull from inbox, append to log, deliver to all except sender."""
        try:
            while True:
                msg = await self._inbox.get()
                self._conv.append_message(msg)
                if self._store:
                    self._store.log_message(msg)

                for pid, participant in self._conv.participants.items():
                    if pid == msg.sender_id:
                        continue  # sender already got echo via post_message
                    if msg.recipient_id and msg.recipient_id != pid:
                        continue  # directed message, skip non-targets

                    if participant.participant_type == ParticipantType.HUMAN_WS:
                        q = self._outbound.get(pid)
                        if q:
                            await q.put({"type": "group_message", **msg.to_dict()})

                    elif participant.participant_type == ParticipantType.MCP_CLIENT:
                        if participant.poll_queue:
                            await participant.poll_queue.put(
                                {"type": "group_message", **msg.to_dict()}
                            )

                    elif participant.participant_type == ParticipantType.CLAUDE_PROCESS:
                        if participant.chat_process_id:
                            formatted = f"[From {msg.sender_name}] {msg.content}"
                            dq = self._claude_delivery.get(pid)
                            if dq:
                                await dq.put(formatted)

                    elif participant.participant_type == ParticipantType.CLI_CHAT:
                        formatted = f"[From {msg.sender_name}] {msg.content}"
                        dq = self._cli_delivery.get(pid)
                        if dq:
                            await dq.put(formatted)

        except asyncio.CancelledError:
            pass

    async def register_claude(self, participant: Participant) -> None:
        """Start writer and listener tasks for a Claude process."""
        chat_id = participant.chat_process_id
        pid = participant.participant_id
        cp = self._cpm._processes.get(chat_id)
        if not cp:
            return

        # Delivery queue: dispatcher puts formatted messages here
        self._claude_delivery[pid] = asyncio.Queue()

        # Subscribe outbound queue
        self.subscribe(pid)

        # Listener subscribes to background reader
        sub_id = f"bus-{self._conv.conversation_id}-{pid}"
        subscriber_queue = cp.subscribe(sub_id)

        writer = asyncio.create_task(
            self._claude_writer(participant),
            name=f"claude-writer-{pid}",
        )
        listener = asyncio.create_task(
            self._claude_listener(participant, subscriber_queue, sub_id),
            name=f"claude-listener-{pid}",
        )
        self._claude_tasks[pid] = (writer, listener)

    async def unregister_claude(self, participant_id: str) -> None:
        """Cancel writer/listener tasks and clean up for a Claude participant."""
        tasks = self._claude_tasks.pop(participant_id, None)
        if tasks:
            writer, listener = tasks
            writer.cancel()
            listener.cancel()
            try:
                await writer
            except asyncio.CancelledError:
                pass
            try:
                await listener
            except asyncio.CancelledError:
                pass

        self._claude_delivery.pop(participant_id, None)
        self.unsubscribe(participant_id)

    async def register_cli(
        self,
        participant: Participant,
        priming_message: Optional[str] = None,
    ) -> None:
        """Start a worker task for a CLI_CHAT participant (codex / gemini).

        If priming_message is provided, sends it as turn 1 and discards the
        reply (priming acknowledgment is not posted to the conversation).
        Best-effort: priming failures are logged but don't block registration.
        """
        pid = participant.participant_id
        chat = participant.cli_chat
        if chat is None:
            return

        self._cli_delivery[pid] = asyncio.Queue()
        self.subscribe(pid)

        if priming_message:
            try:
                await chat.send(priming_message)
            except Exception as e:
                logger.warning(
                    "CLI priming failed for %s: %s", participant.name, e
                )

        task = asyncio.create_task(
            self._cli_worker(participant),
            name=f"cli-worker-{pid}",
        )
        self._cli_tasks[pid] = task

    async def unregister_cli(self, participant_id: str) -> None:
        """Cancel worker task and clean up for a CLI_CHAT participant."""
        task = self._cli_tasks.pop(participant_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._cli_delivery.pop(participant_id, None)
        self.unsubscribe(participant_id)

    async def _cli_worker(self, participant: Participant) -> None:
        """Persistent worker: read delivery queue, call chat.send(), post reply.

        Each iteration is one turn: pull formatted prompt, run chat.send()
        (which spawns a fresh codex/gemini subprocess and resumes the thread),
        post the reply to the inbox. Replies of "PASS" are silently consumed
        to match the Claude norm. Per-turn exceptions are logged but don't
        kill the worker — the next message gets a fresh attempt.
        """
        pid = participant.participant_id
        dq = self._cli_delivery[pid]
        chat = participant.cli_chat
        try:
            while True:
                formatted = await dq.get()
                try:
                    reply = await chat.send(formatted)
                except Exception as e:
                    logger.warning(
                        "CLI chat %s send failed: %s", participant.name, e
                    )
                    continue

                stripped = (reply or "").strip()
                if not stripped or stripped.upper() == "PASS":
                    continue

                msg = GroupMessage(
                    id=make_message_id(),
                    conversation_id=self._conv.conversation_id,
                    sender_id=pid,
                    sender_name=participant.name,
                    content=reply,
                )
                await self._inbox.put(msg)
        except asyncio.CancelledError:
            pass

    async def _claude_writer(self, participant: Participant) -> None:
        """Read from delivery queue, wait for not-busy, write to stdin."""
        pid = participant.participant_id
        chat_id = participant.chat_process_id
        dq = self._claude_delivery[pid]
        try:
            while True:
                formatted = await dq.get()
                # Wait until Claude is not busy
                cp = self._cpm._processes.get(chat_id)
                while cp and cp.busy:
                    await asyncio.sleep(0.1)
                if not cp or cp._dead:
                    break
                try:
                    await self._cpm.write_message(chat_id, formatted)
                except Exception as e:
                    logger.warning("Failed to write to Claude %s: %s", chat_id, e)
                    break
        except asyncio.CancelledError:
            pass

    async def _claude_listener(
        self,
        participant: Participant,
        subscriber_queue: asyncio.Queue,
        sub_id: str,
    ) -> None:
        """Persistent listener: read Claude stdout events, post responses to inbox."""
        current_text = ""
        try:
            while True:
                event = await subscriber_queue.get()
                etype = event.get("type")

                if etype == "stream_event":
                    # Accumulate text silently — no streaming to frontend in group chat
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            if chunk:
                                current_text += chunk

                elif etype == "result":
                    if current_text:
                        stripped = current_text.strip()
                        if stripped.upper() == "PASS":
                            current_text = ""
                            continue  # Silently consume PASS — no message to anyone
                    if current_text:
                        msg = GroupMessage(
                            id=make_message_id(),
                            conversation_id=self._conv.conversation_id,
                            sender_id=participant.participant_id,
                            sender_name=participant.name,
                            content=current_text,
                            metadata={
                                "duration_ms": event.get("duration_ms", 0),
                                "session_id": event.get("session_id", ""),
                            },
                        )
                        await self._inbox.put(msg)
                    current_text = ""

                elif etype == "error":
                    error_str = str(event.get("error", ""))
                    if "closed stdout" in error_str or "dead" in error_str.lower():
                        break

        except asyncio.CancelledError:
            pass
        finally:
            cp = self._cpm._processes.get(participant.chat_process_id)
            if cp:
                cp.unsubscribe(sub_id)

    def _broadcast_to_outbound(self, event: dict) -> None:
        """Push event to all participant outbound queues (streaming + messages)."""
        for q in self._outbound.values():
            q.put_nowait(event)


class MessageRouter:
    """Orchestrates multi-participant group conversations.

    Thin wrapper that manages conversations and delegates message routing
    to per-conversation ConversationBus instances. The existing /ws/chat
    endpoint continues to work unchanged for 1:1 chat sessions.
    """

    def __init__(self, chat_process_manager: ChatProcessManager, store: Optional[ConversationStore] = None):
        self.cpm = chat_process_manager
        self._store = store
        self._conversations: dict[str, Conversation] = {}
        self._buses: dict[str, ConversationBus] = {}  # conv_id -> bus
        self._participant_index: dict[str, str] = {}  # participant_id -> conversation_id

    def create_conversation(self, conversation_id: Optional[str] = None) -> Conversation:
        """Create a new group conversation and start its bus."""
        cid = conversation_id or make_conversation_id()
        conv = Conversation(conversation_id=cid)
        self._conversations[cid] = conv
        bus = ConversationBus(conv, self.cpm, store=self._store)
        self._buses[cid] = bus
        if self._store:
            self._store.log_conversation_start(cid, [])
            self._store.track_conversation_active(cid)
        # Bus start is deferred to an async context — callers that need
        # the bus running should await _ensure_bus_started()
        return conv

    async def _ensure_bus_started(self, conv_id: str) -> None:
        """Ensure the bus for a conversation is running."""
        bus = self._buses.get(conv_id)
        if bus and bus._dispatcher_task is None:
            await bus.start()

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID, or None."""
        return self._conversations.get(conversation_id)

    def get_or_create_conversation(self, conversation_id: str) -> Conversation:
        """Get existing or create new conversation."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            conv = self.create_conversation(conversation_id)
        return conv

    def list_conversations(self) -> list[dict]:
        """List all active conversations."""
        return [conv.to_dict() for conv in self._conversations.values()]

    def add_human(
        self,
        conversation_id: str,
        name: str,
        websocket: object,
        participant_id: Optional[str] = None,
    ) -> Participant:
        """Add a human participant connected via WebSocket."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        pid = participant_id or f"human-{name.lower().replace(' ', '-')}"
        participant = Participant(
            participant_id=pid,
            name=name,
            participant_type=ParticipantType.HUMAN_WS,
            conversation_id=conversation_id,
            websocket=websocket,
        )
        conv.add_participant(participant)
        self._participant_index[pid] = conversation_id
        self._update_lifecycle_participants(conversation_id)

        # Subscribe to the bus outbound queue
        bus = self._buses.get(conversation_id)
        if bus:
            bus.subscribe(pid)

        return participant

    def add_mcp_client(
        self,
        conversation_id: str,
        name: str,
        participant_id: Optional[str] = None,
    ) -> Participant:
        """Add an MCP client participant (e.g., Excel Claude) with a poll queue."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        pid = participant_id or f"mcp-{name.lower().replace(' ', '-')}"
        participant = Participant(
            participant_id=pid,
            name=name,
            participant_type=ParticipantType.MCP_CLIENT,
            conversation_id=conversation_id,
            poll_queue=asyncio.Queue(),
        )
        conv.add_participant(participant)
        self._participant_index[pid] = conversation_id
        self._update_lifecycle_participants(conversation_id)

        # Subscribe to the bus outbound queue
        bus = self._buses.get(conversation_id)
        if bus:
            bus.subscribe(pid)

        return participant

    async def add_claude_process(
        self,
        conversation_id: str,
        name: str,
        participant_id: Optional[str] = None,
        role: str = "chat",
    ) -> Participant:
        """Add a Claude process participant to the conversation.

        Spawns a new Claude Code process via ChatProcessManager with
        group-aware priming that includes participant list and conversation context.

        Args:
            role: "chat" (default) runs in ~/claude-chat/ with Chat Claude identity.
                  "main" runs in the project directory with Main Claude identity,
                  giving full access to CLAUDE.md, window files, and thoughts/.
        """
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        pid = participant_id or f"claude-{name.lower().replace(' ', '-')}"
        chat_id = f"group-{conversation_id}-{pid}"

        # Build group-aware priming message
        priming = self._build_group_priming(conv, name, role=role)

        # Spawn the Claude process -- Main role runs in project_dir for full context
        cwd = self.cpm.project_dir if role == "main" else None
        await self.cpm.get_or_spawn(chat_id, priming_message=priming, cwd=cwd)

        participant = Participant(
            participant_id=pid,
            name=name,
            participant_type=ParticipantType.CLAUDE_PROCESS,
            conversation_id=conversation_id,
            chat_process_id=chat_id,
        )
        conv.add_participant(participant)
        self._participant_index[pid] = conversation_id
        self._update_lifecycle_participants(conversation_id)

        # Ensure bus is started, then register Claude
        await self._ensure_bus_started(conversation_id)
        bus = self._buses.get(conversation_id)
        if bus:
            await bus.register_claude(participant)

        return participant

    async def add_cli_chat(
        self,
        conversation_id: str,
        name: str,
        chat: object,
        participant_id: Optional[str] = None,
    ) -> Participant:
        """Add a CLI-driven participant (codex, gemini) to the conversation.

        `chat` must be any object with `async def send(prompt: str) -> str`
        whose internal state survives across calls (e.g., CodexChat or
        GeminiChat — both maintain a thread/session id and resume per turn).

        Sends a priming message (group context + conversation norms) as the
        first turn, then registers a worker task that handles incoming
        messages by calling chat.send() one at a time.
        """
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        pid = participant_id or f"cli-{name.lower().replace(' ', '-')}"
        participant = Participant(
            participant_id=pid,
            name=name,
            participant_type=ParticipantType.CLI_CHAT,
            conversation_id=conversation_id,
            cli_chat=chat,
        )
        conv.add_participant(participant)
        self._participant_index[pid] = conversation_id
        self._update_lifecycle_participants(conversation_id)

        priming = self._build_cli_priming(conv, name)

        await self._ensure_bus_started(conversation_id)
        bus = self._buses.get(conversation_id)
        if bus:
            await bus.register_cli(participant, priming_message=priming)

        return participant

    def remove_participant(self, participant_id: str) -> Optional[Participant]:
        """Remove a participant from their conversation."""
        conv_id = self._participant_index.pop(participant_id, None)
        if conv_id is None:
            return None

        conv = self._conversations.get(conv_id)
        if conv is None:
            return None

        # Unregister from bus
        bus = self._buses.get(conv_id)
        if bus:
            participant = conv.participants.get(participant_id)
            if participant and participant.participant_type == ParticipantType.CLAUDE_PROCESS:
                # Schedule unregister (async) but don't block
                asyncio.ensure_future(bus.unregister_claude(participant_id))
            elif participant and participant.participant_type == ParticipantType.CLI_CHAT:
                asyncio.ensure_future(bus.unregister_cli(participant_id))
            else:
                bus.unsubscribe(participant_id)

        return conv.remove_participant(participant_id)

    async def post_message(
        self,
        sender_id: str,
        content: str,
        recipient_id: Optional[str] = None,
    ) -> Optional[GroupMessage]:
        """Post a message from any participant. Fire-and-forget."""
        conv_id = self._participant_index.get(sender_id)
        if conv_id is None:
            return None

        await self._ensure_bus_started(conv_id)
        bus = self._buses.get(conv_id)
        if bus is None:
            return None

        return await bus.post_message(sender_id, content, recipient_id)

    def subscribe(self, participant_id: str) -> Optional[asyncio.Queue]:
        """Get outbound queue for a participant."""
        conv_id = self._participant_index.get(participant_id)
        if conv_id is None:
            return None
        bus = self._buses.get(conv_id)
        if bus is None:
            return None
        return bus.subscribe(participant_id)

    def _build_group_priming(self, conv: Conversation, claude_name: str, role: str = "chat") -> str:
        """Build group-aware priming message for a Claude process.

        Includes the standard state injection plus group context:
        - Who's in the conversation
        - Recent message history

        Args:
            role: "chat" or "main". Main role gets identity reinforcement
                since it runs in the project directory with the main CLAUDE.md.
        """
        sections = []

        # Role-specific identity
        if role == "main":
            sections.append(
                "### Role: Main Claude\n"
                "You are Main Claude -- the persistent system Claude with full tooling, "
                "window file access, and infrastructure knowledge. Your CLAUDE.md has loaded. "
                "You are joining a group conversation where you can collaborate with "
                "humans and other Claude instances."
            )

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

        # Conversation norms — prevent acknowledgment loops
        sections.append(
            "### Conversation Norms\n"
            "This is a multi-participant conversation where messages from all participants "
            "(human and AI) are delivered to everyone. Every message you receive appears as "
            "a new turn in your conversation, which creates pressure to respond. However, "
            "if every participant responds to every message, the conversation grows "
            "exponentially and devolves into an acknowledgment loop where everyone is "
            "just confirming what others said.\n\n"
            "**To prevent this:**\n"
            "- If you have nothing substantive to add, respond with just: PASS\n"
            "- Respond fully when: you are addressed by name, you are clearly the "
            "intended target, or a human is speaking\n"
            "- Respond sparingly when: you have significant information, context, or "
            "expertise that the expected responders lack, or you believe errors are "
            "entering the discussion\n"
            "- Do NOT respond just to agree, acknowledge, or summarize what someone "
            "else already said\n"
            "- PASS is always safe. Silence is better than noise."
        )

        # Group context
        participant_names = [p.name for p in conv.participants.values()]
        if participant_names:
            sections.append(
                f"### Group Conversation: {conv.conversation_id}\n"
                f"You are **{claude_name}** in a group conversation.\n"
                f"Current participants: {', '.join(participant_names)}\n"
                f"Messages from other participants will be prefixed with [From name]."
            )

        # Recent message history (last 10 messages)
        if conv.message_log:
            recent = conv.message_log[-10:]
            history_lines = []
            for m in recent:
                if m.message_type == MessageType.CHAT:
                    history_lines.append(f"[{m.sender_name}] {m.content[:200]}")
                elif m.message_type in (MessageType.JOIN, MessageType.LEAVE):
                    history_lines.append(f"* {m.content}")
            if history_lines:
                sections.append(
                    "### Recent Messages\n" + "\n".join(history_lines)
                )

        # Append state injection from ChatProcessManager
        standard_prime = self.cpm._build_priming_message()
        if standard_prime and standard_prime != "Ready. Respond with just: ok":
            parts = standard_prime.split("\n\n", 1)
            if len(parts) > 1:
                sections.append(parts[1])

        if sections:
            header = (
                "You are being initialized into a group conversation. "
                "Absorb this context silently and respond with just: ok\n\n"
            )
            return header + "\n\n".join(sections)
        else:
            return "Ready. Respond with just: ok"

    def _build_cli_priming(self, conv: Conversation, cli_name: str) -> str:
        """Build the first-turn priming message for a CLI_CHAT participant.

        Codex and Gemini have no separate init step — turn 1 of the thread
        is what establishes context for resume-per-turn. This message sets
        up identity, conversation norms (PASS for nothing-to-add), and
        recent history. The reply to this message is silently consumed in
        register_cli — it is not posted to the conversation.
        """
        sections = [
            (
                f"You are joining a multi-participant group conversation as "
                f"**{cli_name}**. Your replies are routed back to the other "
                "participants. Messages from others arrive prefixed with "
                "`[From <name>]`. Each turn, you receive one such message "
                "and reply once."
            ),
            (
                "### Conversation Norms\n"
                "- If you have nothing substantive to add, respond with just: "
                "PASS (uppercase, on its own).\n"
                "- Respond fully when: you are addressed by name, you are "
                "clearly the intended target, or a human is speaking.\n"
                "- Respond sparingly when: you have unique information or "
                "expertise that the expected responders lack.\n"
                "- Do NOT respond just to agree, acknowledge, or summarize "
                "what someone else already said.\n"
                "- PASS is always safe. Silence is better than noise."
            ),
        ]

        participant_names = [p.name for p in conv.participants.values()]
        if participant_names:
            sections.append(
                f"### Group Conversation: {conv.conversation_id}\n"
                f"Current participants: {', '.join(participant_names)}"
            )

        if conv.message_log:
            recent = conv.message_log[-10:]
            history_lines = []
            for m in recent:
                if m.message_type == MessageType.CHAT:
                    history_lines.append(f"[{m.sender_name}] {m.content[:200]}")
                elif m.message_type in (MessageType.JOIN, MessageType.LEAVE):
                    history_lines.append(f"* {m.content}")
            if history_lines:
                sections.append(
                    "### Recent Messages\n" + "\n".join(history_lines)
                )

        sections.append(
            "Acknowledge briefly so I know you have the context, "
            "then wait for the next message."
        )

        return "\n\n".join(sections)

    def _update_lifecycle_participants(self, conversation_id: str) -> None:
        """Update the participant list in the lifecycle table."""
        if not self._store:
            return
        conv = self._conversations.get(conversation_id)
        if conv is None:
            return
        participants = [p.to_dict() for p in conv.participants.values()]
        self._store.update_participants(conversation_id, participants)

    async def cleanup_conversation(self, conversation_id: str) -> None:
        """Remove a conversation and clean up all its participants."""
        if self._store:
            self._store.log_conversation_end(conversation_id)
            self._store.mark_conversation_ended(conversation_id)

        # Stop the bus first
        bus = self._buses.pop(conversation_id, None)
        if bus:
            await bus.stop()

        conv = self._conversations.pop(conversation_id, None)
        if conv is None:
            return

        for pid, participant in list(conv.participants.items()):
            self._participant_index.pop(pid, None)

            # Kill Claude processes associated with this conversation
            if participant.participant_type == ParticipantType.CLAUDE_PROCESS:
                if participant.chat_process_id:
                    await self.cpm.kill_process(participant.chat_process_id)

    async def shutdown(self) -> None:
        """Graceful shutdown: mark all conversations as interrupted, then clean up.

        Called on server shutdown (SIGTERM, lifespan teardown). Marks active
        conversations as interrupted in SQLite before tearing down in-memory state,
        so startup recovery can detect what was running.
        """
        active_ids = list(self._conversations.keys())

        # First: persist interrupted status for all active conversations
        if self._store and active_ids:
            count = self._store.mark_all_active_interrupted(reason="graceful_shutdown")
            logger.info(
                "Graceful shutdown: marked %d conversations as interrupted", count
            )

        # Then: clean up in-memory state (buses, tasks, processes)
        for conv_id in active_ids:
            # Stop the bus
            bus = self._buses.pop(conv_id, None)
            if bus:
                await bus.stop()

            conv = self._conversations.pop(conv_id, None)
            if conv is None:
                continue

            for pid, participant in list(conv.participants.items()):
                self._participant_index.pop(pid, None)

                # Kill Claude processes
                if participant.participant_type == ParticipantType.CLAUDE_PROCESS:
                    if participant.chat_process_id:
                        await self.cpm.kill_process(participant.chat_process_id)

    def startup_recovery(self) -> dict:
        """Run startup recovery. Call before accepting new connections.

        Returns a summary dict of recovery actions taken.
        """
        if not self._store:
            return {"crash_recovered": 0, "total_interrupted": 0, "interrupted_conversation_ids": []}
        return self._store.recover_on_startup()
