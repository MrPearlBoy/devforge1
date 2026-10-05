"""In-process publish/subscribe bus powering real-time agent activity (SSE).

The MVP runs a single API process, so a thread-safe in-memory bus is sufficient
and dependency free.  Multi-worker deployments can replace :class:`EventBus`
with a Redis/Postgres-backed implementation of the same three methods
(``publish``, ``subscribe``, ``unsubscribe``) without touching agent code.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Event:
    """A single real-time workflow/agent event."""

    type: str
    project_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sse(self) -> str:
        body = json.dumps(asdict(self), default=str)
        return f"event: {self.type}\ndata: {body}\n\n"


class EventBus:
    """Fan-out bus with per-project subscriber queues."""

    def __init__(self, max_queue: int = 500) -> None:
        self._subscribers: dict[str, set[queue.Queue]] = defaultdict(set)
        self._lock = threading.Lock()
        self._max_queue = max_queue
        self._history: dict[str, list[Event]] = defaultdict(list)

    def publish(self, event: Event) -> None:
        with self._lock:
            self._history[event.project_id].append(event)
            self._history[event.project_id] = self._history[event.project_id][-100:]
            targets = list(self._subscribers.get(event.project_id, ()))
        for target in targets:
            try:
                target.put_nowait(event)
            except queue.Full:  # slow client: drop the oldest event
                try:
                    target.get_nowait()
                    target.put_nowait(event)
                except queue.Empty:  # pragma: no cover
                    pass

    def emit(self, event_type: str, project_id: str, **payload: Any) -> None:
        """Convenience wrapper used throughout the services/agents."""
        self.publish(Event(type=event_type, project_id=project_id, payload=payload))

    def subscribe(self, project_id: str) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers[project_id].add(subscriber)
        return subscriber

    def unsubscribe(self, project_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.get(project_id, set()).discard(subscriber)

    def recent(self, project_id: str, limit: int = 30) -> list[Event]:
        return self._history.get(project_id, [])[-limit:]

    def stream(self, project_id: str, *, heartbeat_seconds: int = 15,
               max_seconds: int = 1800) -> Iterator[str]:
        """Yield SSE frames for a project until the client disconnects/timeout."""
        subscriber = self.subscribe(project_id)
        started = time.time()
        try:
            yield ": devforge event stream open\n\n"
            while time.time() - started < max_seconds:
                try:
                    event = subscriber.get(timeout=heartbeat_seconds)
                    yield event.to_sse()
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(project_id, subscriber)


bus = EventBus()
