"""In-process pub/sub bus feeding the Server-Sent Events endpoint.

The workflow engine publishes every event (agent logs, state transitions,
gate requests, test output, scan findings, git commits); each subscriber
gets its own bounded queue.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def publish(self, project_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(project_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: drop rather than block the engine

    def subscribe(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[project_id].add(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue) -> None:
        self._subs[project_id].discard(q)
        if not self._subs[project_id]:
            self._subs.pop(project_id, None)

    async def stream(self, project_id: str) -> AsyncIterator[str]:
        """Yield SSE frames for one client until it disconnects."""
        q = self.subscribe(project_id)
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.unsubscribe(project_id, q)


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus
