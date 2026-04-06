"""
Redis Streams Event Bus  (RFC 9315 §6 — CDC/event-driven inner loop)

Drop-in replacement for the in-process ``EventBus``.  Events are written
to Redis Streams (``XADD``) so agents running in separate processes or
containers can consume them via consumer groups (``XREADGROUP``).

Key design decisions
--------------------
* **Same interface** as the in-process ``EventBus`` (``publish`` / ``subscribe``).
* **Consumer groups** — each logical subscriber set shares a group so a
  message is delivered once even with multiple worker replicas.
* **Background thread** — ``subscribe()`` automatically starts a daemon
  thread that blocks on ``XREADGROUP`` and dispatches to registered callbacks.
* **Graceful fallback** — ``RedisEventBus.__init__`` raises ``ConnectionError``
  if Redis is unreachable; callers should catch and fall back to the
  in-process bus (see ``get_event_bus()`` in ``base_agent.py``).
* **AOF persistence** — the docker-compose redis service uses
  ``appendonly yes / appendfsync everysec`` so events survive restarts.

Stream naming convention
------------------------
  ``ibn:events:{event_type}``  e.g. ``ibn:events:telemetry.collected``

Consumer group naming convention
---------------------------------
  ``ibn-{consumer_group}``  default: ``ibn-agents``

Usage
-----
::

    bus = RedisEventBus("redis://localhost:6379")
    bus.subscribe("telemetry.collected", my_handler)
    bus.publish("telemetry.collected", {"deviceId": "usf-fw-01"})
    bus.stop()
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("ibn.redis_bus")

STREAM_PREFIX   = "ibn:events:"
DEFAULT_GROUP   = "ibn-agents"
BLOCK_MS        = 200    # block time per XREADGROUP call
BATCH_SIZE      = 10     # messages per read
MAX_STREAM_LEN  = 50_000 # approximate cap per stream


class RedisEventBus:
    """
    Redis Streams-backed event bus.

    Parameters
    ----------
    redis_url:
        Redis connection URL, e.g. ``redis://localhost:6379`` or
        ``redis://:password@host:port/db``.
    consumer_group:
        Name of the Redis consumer group.  All agent processes sharing the
        same group name compete for messages (each message delivered once).
    consumer_id:
        Unique ID for this consumer within the group.  Defaults to a random
        hex suffix so multiple processes don't clash.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        consumer_group: str = DEFAULT_GROUP,
        consumer_id: Optional[str] = None,
    ):
        import redis as _redis  # lazy import — optional dependency

        self._client = _redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        # Verify connection immediately
        self._client.ping()

        self._group      = consumer_group
        self._consumer   = consumer_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._subscribers: dict[str, list[Callable]] = {}
        self._streams_initialised: set[str] = set()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        logger.info(
            "RedisEventBus connected: %s | group=%s | consumer=%s",
            redis_url, self._group, self._consumer,
        )

    # ------------------------------------------------------------------
    # Public interface (same as in-process EventBus)
    # ------------------------------------------------------------------

    def publish(self, event_type: str, payload: dict) -> dict:
        """
        Write an event to the Redis Stream for *event_type*.

        Returns the canonical event dict (same structure as in-process bus).
        """
        event = {
            "type":      event_type,
            "payload":   json.dumps(payload),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        stream_key = self._stream_key(event_type)
        try:
            self._client.xadd(
                stream_key,
                event,
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )
            logger.debug("Published %s → %s", event_type, stream_key)
        except Exception as exc:
            logger.error("Redis publish failed (%s): %s", stream_key, exc)

        return {**event, "payload": payload}  # return decoded payload

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Register *callback* to be invoked when events of *event_type* arrive.

        Idempotent: calling subscribe() multiple times with different callbacks
        accumulates them.  The first subscribe() call starts the consumer thread.
        """
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)
            self._ensure_stream_and_group(event_type)
            if not self._running:
                self._start_consumer()

    def stop(self) -> None:
        """Stop the background consumer thread gracefully."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("RedisEventBus stopped")

    # ------------------------------------------------------------------
    # Stream / group initialisation
    # ------------------------------------------------------------------

    def _stream_key(self, event_type: str) -> str:
        return f"{STREAM_PREFIX}{event_type}"

    def _ensure_stream_and_group(self, event_type: str) -> None:
        """Create the stream (if needed) and the consumer group."""
        if event_type in self._streams_initialised:
            return
        stream_key = self._stream_key(event_type)
        try:
            # mkstream=True creates the stream atomically if absent
            self._client.xgroup_create(
                stream_key, self._group, id="$", mkstream=True
            )
            logger.debug("Created consumer group %s on %s", self._group, stream_key)
        except Exception as exc:
            # BUSYGROUP = group already exists — ignore
            if "BUSYGROUP" not in str(exc):
                logger.warning("xgroup_create %s: %s", stream_key, exc)
        self._streams_initialised.add(event_type)

    # ------------------------------------------------------------------
    # Consumer loop (runs in daemon thread)
    # ------------------------------------------------------------------

    def _start_consumer(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._consume_loop,
            name=f"redis-bus-{self._consumer}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Consumer thread started: %s", self._thread.name)

    def _consume_loop(self) -> None:
        """
        Continuously read from all subscribed streams using XREADGROUP.
        Dispatches each message to the registered callbacks, then ACKs.
        """
        while self._running:
            with self._lock:
                subscribed = dict(self._subscribers)

            if not subscribed:
                time.sleep(0.1)
                continue

            streams = {self._stream_key(et): ">" for et in subscribed}
            try:
                results = self._client.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams=streams,
                    count=BATCH_SIZE,
                    block=BLOCK_MS,
                )
            except Exception as exc:
                logger.error("xreadgroup failed: %s — retrying in 1 s", exc)
                time.sleep(1)
                continue

            if not results:
                continue

            for stream_key, messages in results:
                # Derive event_type from stream key
                event_type = stream_key.removeprefix(STREAM_PREFIX)
                callbacks = subscribed.get(event_type, [])

                for msg_id, fields in messages:
                    payload_raw = fields.get("payload", "{}")
                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_raw}

                    event = {
                        "type":      fields.get("type", event_type),
                        "payload":   payload,
                        "timestamp": fields.get("timestamp", ""),
                    }

                    for cb in callbacks:
                        try:
                            cb(event)
                        except Exception as exc:
                            logger.warning(
                                "Callback %s raised for %s: %s", cb, event_type, exc
                            )

                    # ACK so message isn't re-delivered
                    try:
                        self._client.xack(stream_key, self._group, msg_id)
                    except Exception as exc:
                        logger.warning("xack failed %s: %s", msg_id, exc)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def stream_length(self, event_type: str) -> int:
        """Return number of entries in the stream for *event_type*."""
        try:
            return self._client.xlen(self._stream_key(event_type))
        except Exception:
            return -1

    def pending_count(self, event_type: str) -> int:
        """Return number of pending (delivered but not ACKed) messages."""
        try:
            info = self._client.xpending(self._stream_key(event_type), self._group)
            return info.get("pending", 0)
        except Exception:
            return -1

    def flush_stream(self, event_type: str) -> None:
        """Delete the stream for *event_type* (useful in tests)."""
        try:
            self._client.delete(self._stream_key(event_type))
        except Exception as exc:
            logger.warning("flush_stream %s: %s", event_type, exc)
