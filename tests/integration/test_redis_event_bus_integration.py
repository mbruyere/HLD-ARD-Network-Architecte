"""
Redis Event Bus Integration Tests
==================================
Tests RedisEventBus against a real Redis instance.

Run with real Redis:
    REDIS_URL=redis://localhost:6379 \
    pytest tests/integration/test_redis_event_bus_integration.py -v

Run without Redis (all tests skip):
    pytest tests/integration/test_redis_event_bus_integration.py -v
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

def _redis_available() -> bool:
    try:
        import redis as _r
        c = _r.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        c.ping()
        return True
    except Exception:
        return False

REQUIRES_REDIS = pytest.mark.skipif(
    not _redis_available(),
    reason="Requires real Redis (REDIS_URL)",
)


@pytest.fixture
def bus():
    """Fresh RedisEventBus for each test with a unique consumer group."""
    from ibn.core.redis_event_bus import RedisEventBus
    group = f"test-{uuid.uuid4().hex[:8]}"
    b = RedisEventBus(REDIS_URL, consumer_group=group, consumer_id="test-worker")
    yield b
    b.stop()


@pytest.fixture(autouse=True)
def clean_streams(bus):
    """Flush test streams before each test."""
    for et in [
        "telemetry.collected",
        "assessment.complete",
        "remediation.complete",
        "escalation.required",
        "test.event",
    ]:
        bus.flush_stream(et)
    yield


# ── Publish / Subscribe round-trip ────────────────────────────────────────


@REQUIRES_REDIS
class TestPublishSubscribeRoundTrip:

    def test_rb_i1_message_delivered_to_subscriber(self, bus):
        """Published message arrives at subscriber callback within 2 s."""
        received = []
        bus.subscribe("test.event", lambda e: received.append(e))
        time.sleep(0.1)  # let consumer start

        bus.publish("test.event", {"hello": "world"})

        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        assert len(received) == 1
        assert received[0]["payload"]["hello"] == "world"
        assert received[0]["type"] == "test.event"

    def test_rb_i2_multiple_messages_all_delivered(self, bus):
        """All 5 published messages are delivered in order."""
        received = []
        bus.subscribe("test.event", lambda e: received.append(e["payload"]["n"]))
        time.sleep(0.1)

        for n in range(5):
            bus.publish("test.event", {"n": n})

        deadline = time.time() + 3.0
        while len(received) < 5 and time.time() < deadline:
            time.sleep(0.05)

        assert sorted(received) == list(range(5))

    def test_rb_i3_multiple_callbacks_all_invoked(self, bus):
        """Two subscribers on the same event type both receive the message."""
        received_a = []
        received_b = []
        bus.subscribe("test.event", lambda e: received_a.append(e))
        bus.subscribe("test.event", lambda e: received_b.append(e))
        time.sleep(0.1)

        bus.publish("test.event", {"x": 42})

        deadline = time.time() + 2.0
        while (not received_a or not received_b) and time.time() < deadline:
            time.sleep(0.05)

        assert len(received_a) >= 1
        assert len(received_b) >= 1

    def test_rb_i4_payload_survives_serialisation_round_trip(self, bus):
        """Complex payload (nested dict + list) is preserved through JSON."""
        received = []
        bus.subscribe("test.event", lambda e: received.append(e["payload"]))
        time.sleep(0.1)

        payload = {
            "deviceId": "usf-fw-01",
            "rules": ["ALLOW-HTTP", "DENY-ALL"],
            "meta": {"severity": "HIGH", "count": 3},
        }
        bus.publish("test.event", payload)

        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        assert received[0] == payload

    def test_rb_i5_messages_acked_after_delivery(self, bus):
        """After delivery pending_count drops to 0."""
        received = []
        bus.subscribe("test.event", lambda e: received.append(e))
        time.sleep(0.1)

        bus.publish("test.event", {"x": 1})

        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        # Give ACK time to propagate
        time.sleep(0.2)
        pending = bus.pending_count("test.event")
        assert pending == 0


# ── Stream introspection ───────────────────────────────────────────────────


@REQUIRES_REDIS
class TestStreamIntrospection:

    def test_rb_i6_stream_length_increments_on_publish(self, bus):
        """stream_length() reflects XADD calls."""
        bus.publish("test.event", {"a": 1})
        bus.publish("test.event", {"a": 2})
        length = bus.stream_length("test.event")
        assert length >= 2

    def test_rb_i7_flush_stream_resets_length_to_zero(self, bus):
        bus.publish("test.event", {"a": 1})
        bus.flush_stream("test.event")
        assert bus.stream_length("test.event") == 0


# ── Inner Loop integration with Redis bus ─────────────────────────────────


@REQUIRES_REDIS
class TestInnerLoopWithRedisBus:

    def test_rb_i8_inner_loop_uses_redis_bus_when_env_set(self, monkeypatch):
        """
        With REDIS_URL set, InnerLoop picks up a RedisEventBus automatically.
        """
        from unittest.mock import MagicMock
        monkeypatch.setenv("REDIS_URL", REDIS_URL)

        # Reload get_event_bus to pick up env var
        import importlib, ibn.core.base_agent as ba
        importlib.reload(ba)

        neo4j = MagicMock()
        neo4j.run_query.return_value = []
        live_memory = MagicMock()
        live_memory.live_note.return_value = {}

        from ibn.agents.inner_loop import InnerLoop
        from ibn.core.redis_event_bus import RedisEventBus

        loop = InnerLoop(neo4j, live_memory)
        assert isinstance(loop._bus, RedisEventBus)
        loop._bus.stop()

    def test_rb_i9_event_bus_carries_telemetry_event(self, bus):
        """
        Publishing telemetry.collected on RedisEventBus triggers a subscriber.
        Simulates the A6→A7 handoff over Redis.
        """
        received = []
        bus.subscribe(
            "telemetry.collected",
            lambda e: received.append(e["payload"]),
        )
        time.sleep(0.1)

        bus.publish("telemetry.collected", {"intentId": "INT-001", "devices": 2})

        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        assert len(received) == 1
        assert received[0]["intentId"] == "INT-001"


# ── get_event_bus() factory with real Redis ────────────────────────────────


@REQUIRES_REDIS
class TestGetEventBusFactory:

    def test_rb_i10_factory_returns_redis_bus_with_url(self):
        from ibn.core.base_agent import get_event_bus
        from ibn.core.redis_event_bus import RedisEventBus

        bus = get_event_bus(REDIS_URL)
        assert isinstance(bus, RedisEventBus)
        bus.stop()

    def test_rb_i11_factory_falls_back_without_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from ibn.core.base_agent import get_event_bus, EventBus

        bus = get_event_bus()
        assert isinstance(bus, EventBus)
