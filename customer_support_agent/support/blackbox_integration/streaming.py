"""In-process Server-Sent Events broker for Black Box runs."""

import json
import queue
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)


def sse_frame(event_type: str, payload: dict[str, Any]) -> str:
    """Serialize one Server-Sent Events frame."""
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, default=_json_default)}\n\n"
    )


class RunStreamBroker:
    """Bounded, non-blocking fanout for live run events."""

    def __init__(self, queue_size: int = 200):
        self.queue_size = queue_size
        self._subscribers: dict[str, set[queue.Queue]] = defaultdict(set)
        self._latest_subscribers: set[queue.Queue] = set()
        self._lock = Lock()
        self.latest_run_id: str | None = None

    def subscribe(self, run_id: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self.queue_size)
        with self._lock:
            if run_id is None:
                self._latest_subscribers.add(q)
            else:
                self._subscribers[run_id].add(q)
        return q

    def unsubscribe(self, q: queue.Queue, run_id: str | None = None) -> None:
        with self._lock:
            if run_id is None:
                self._latest_subscribers.discard(q)
            else:
                subscribers = self._subscribers.get(run_id)
                if subscribers is not None:
                    subscribers.discard(q)
                    if not subscribers:
                        self._subscribers.pop(run_id, None)

    def publish(self, event_type: str, run_id: str, **payload: Any) -> None:
        envelope = {
            "type": event_type,
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat(),
            **payload,
        }
        if event_type == "run_started":
            self.latest_run_id = run_id

        with self._lock:
            targets = list(self._subscribers.get(run_id, ())) + list(
                self._latest_subscribers
            )

        for target in targets:
            self._put_latest(target, envelope)

    def subscriber_count(self, run_id: str | None = None) -> int:
        with self._lock:
            if run_id is None:
                return len(self._latest_subscribers)
            return len(self._subscribers.get(run_id, ()))

    @staticmethod
    def _put_latest(target: queue.Queue, item: dict[str, Any]) -> None:
        try:
            target.put_nowait(item)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            try:
                target.put_nowait(item)
            except queue.Full:
                pass


broker = RunStreamBroker()
