"""In-process WebSocket fan-out for conversations.

Messages are always persisted first (messaging.service) and only then
broadcast, so WebSocket delivery is an optimisation, never the source of
truth: offline clients re-sync over REST. With several API replicas, replace
``ConnectionManager.broadcast`` with Redis pub/sub (docs/deployment.md); the
call sites stay the same.
"""

import asyncio
import logging
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass

from fastapi import WebSocket

logger = logging.getLogger("symbio.realtime")


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    user_id: uuid.UUID
    loop: asyncio.AbstractEventLoop


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[uuid.UUID, set[Client]] = defaultdict(set)
        self._lock = threading.Lock()

    def add(self, conversation_id: uuid.UUID, client: Client) -> None:
        with self._lock:
            self._clients[conversation_id].add(client)

    def remove(self, conversation_id: uuid.UUID, client: Client) -> None:
        with self._lock:
            self._clients[conversation_id].discard(client)
            if not self._clients[conversation_id]:
                self._clients.pop(conversation_id, None)

    def online_user_ids(self, conversation_id: uuid.UUID) -> set[uuid.UUID]:
        with self._lock:
            return {c.user_id for c in self._clients.get(conversation_id, set())}

    def broadcast(self, conversation_id: uuid.UUID, payload: dict, exclude: WebSocket | None = None) -> None:
        """Thread-safe: schedules delivery on each client's own event loop."""
        with self._lock:
            clients = list(self._clients.get(conversation_id, set()))
        for client in clients:
            if client.websocket is exclude:
                continue
            try:
                asyncio.run_coroutine_threadsafe(self._send(conversation_id, client, payload), client.loop)
            except RuntimeError:  # loop closed
                self.remove(conversation_id, client)

    async def _send(self, conversation_id: uuid.UUID, client: Client, payload: dict) -> None:
        try:
            await client.websocket.send_json(payload)
        except Exception:
            self.remove(conversation_id, client)

    def close_conversation(self, conversation_id: uuid.UUID) -> None:
        self.broadcast(conversation_id, {"type": "conversation_closed"})


manager = ConnectionManager()
