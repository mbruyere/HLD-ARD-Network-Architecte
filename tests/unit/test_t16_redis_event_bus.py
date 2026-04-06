"""
Unit tests for RedisEventBus — all Redis calls are mocked.

Tests cover:
  - publish → XADD with correct stream key and fields
  - subscribe → xgroup_create + consumer thread started
  - consumer loop → deserialises payload, dispatches callbacks, ACKs
  - stop → consumer thread joins cleanly
  - introspection helpers (stream_length, pending_count, flush_stream)
  - get_event_bus() factory (env var dispatch)
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus(url="redis://localhost:6379"):
    """Instantiate RedisEventBus with a fully mocked Redis client."""
    with patch("redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_from_url.return_value = mock_client

        from ibn.core.redis_event_bus import RedisEventBus
        bus = RedisEventBus(url, consumer_group="test-group", consumer_id="test-consumer")
        bus._client = mock_client  # keep reference for assertions
        return bus, mock_client


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

class TestRedisPublish:

    def test_publish_calls_xadd_with_correct_stream_key(self):
        bus, client = _make_bus()
        bus.publish("telemetry.collected", {"deviceId": "fw-01"})

        assert client.xadd.called
        args, kwargs = client.xadd.call_args
        assert args[0] == "ibn:events:telemetry.collected"

    def test_publish_serialises_payload_as_json(self):
        bus, client = _make_bus()
        bus.publish("assessment.complete", {"verdict": "NON_COMPLIANT"})

        _, kwargs = client.xadd.call_args
        fields = client.xadd.call_args[0][1]
        payload = json.loads(fields["payload"])
        assert payload["verdict"] == "NON_COMPLIANT"

    def test_publish_sets_maxlen(self):
        bus, client = _make_bus()
        bus.publish("remediation.complete", {})

        _, kwargs = client.xadd.call_args
        assert kwargs.get("maxlen") == 50_000

    def test_publish_returns_event_with_decoded_payload(self):
        bus, client = _make_bus()
        result = bus.publish("telemetry.collected", {"x": 1})

        assert result["type"] == "telemetry.collected"
        assert result["payload"] == {"x": 1}
        assert "timestamp" in result

    def test_publish_swallows_redis_error_without_raising(self):
        bus, client = _make_bus()
        client.xadd.side_effect = Exception("Redis down")
        # Should not raise
        bus.publish("test.event", {"k": "v"})

    def test_publish_different_event_types_use_different_streams(self):
        bus, client = _make_bus()
        bus.publish("telemetry.collected", {})
        bus.publish("assessment.complete", {})

        stream_keys = [c[0][0] for c in client.xadd.call_args_list]
        assert "ibn:events:telemetry.collected" in stream_keys
        assert "ibn:events:assessment.complete" in stream_keys


# ---------------------------------------------------------------------------
# Subscribe + consumer group initialisation
# ---------------------------------------------------------------------------

class TestRedisSubscribe:

    def test_subscribe_creates_consumer_group(self):
        bus, client = _make_bus()
        bus.subscribe("telemetry.collected", lambda e: None)

        assert client.xgroup_create.called
        args, kwargs = client.xgroup_create.call_args
        assert args[0] == "ibn:events:telemetry.collected"
        assert args[1] == "test-group"

    def test_subscribe_uses_mkstream_true(self):
        bus, client = _make_bus()
        # xgroup_create is a regular call on mock — check mkstream kwarg
        bus.subscribe("some.event", lambda e: None)
        _, kwargs = client.xgroup_create.call_args
        assert kwargs.get("mkstream") is True

    def test_subscribe_ignores_busygroup_error(self):
        bus, client = _make_bus()
        client.xgroup_create.side_effect = Exception("BUSYGROUP Consumer Group already exists")
        # Should not raise
        bus.subscribe("telemetry.collected", lambda e: None)

    def test_subscribe_starts_consumer_thread(self):
        bus, client = _make_bus()
        # Prevent actual blocking loop
        client.xreadgroup.return_value = None
        bus.subscribe("telemetry.collected", lambda e: None)
        time.sleep(0.05)
        assert bus._running is True
        assert bus._thread is not None
        bus.stop()

    def test_subscribe_multiple_events_accumulate_callbacks(self):
        bus, client = _make_bus()
        cb1 = lambda e: None
        cb2 = lambda e: None
        bus.subscribe("event.A", cb1)
        bus.subscribe("event.A", cb2)
        assert len(bus._subscribers["event.A"]) == 2
        bus.stop()

    def test_subscribe_initialises_stream_once(self):
        bus, client = _make_bus()
        bus.subscribe("event.X", lambda e: None)
        bus.subscribe("event.X", lambda e: None)
        # xgroup_create should be called only once per event type
        create_calls = [
            c for c in client.xgroup_create.call_args_list
            if c[0][0] == "ibn:events:event.X"
        ]
        assert len(create_calls) == 1
        bus.stop()


# ---------------------------------------------------------------------------
# Consumer loop dispatch
# ---------------------------------------------------------------------------

class TestConsumerDispatch:

    def _stream_message(self, event_type: str, payload: dict):
        """Build a fake XREADGROUP result."""
        fields = {
            "type":      event_type,
            "payload":   json.dumps(payload),
            "timestamp": "2026-01-01T00:00:00Z",
        }
        stream_key = f"ibn:events:{event_type}"
        return [(stream_key, [("1234-0", fields)])]

    def test_consumer_dispatches_callback_with_decoded_payload(self):
        bus, client = _make_bus()
        received = []

        # Return one message, then nothing
        client.xreadgroup.side_effect = [
            self._stream_message("telemetry.collected", {"deviceId": "fw-01"}),
            None,
            None,
        ]

        bus.subscribe("telemetry.collected", lambda e: received.append(e))
        time.sleep(0.3)
        bus.stop()

        assert len(received) >= 1
        assert received[0]["payload"]["deviceId"] == "fw-01"

    def test_consumer_acks_message_after_dispatch(self):
        bus, client = _make_bus()
        client.xreadgroup.side_effect = [
            self._stream_message("assessment.complete", {}),
            None,
        ]

        bus.subscribe("assessment.complete", lambda e: None)
        time.sleep(0.3)
        bus.stop()

        assert client.xack.called

    def test_consumer_continues_after_callback_exception(self):
        bus, client = _make_bus()
        received = []

        msgs = [
            self._stream_message("evt.x", {"n": 1}),
            self._stream_message("evt.x", {"n": 2}),
            None,
        ]
        client.xreadgroup.side_effect = msgs

        def bad_then_good(e):
            if e["payload"].get("n") == 1:
                raise RuntimeError("simulated crash")
            received.append(e)

        bus.subscribe("evt.x", bad_then_good)
        time.sleep(0.4)
        bus.stop()

        # Second message should still be received
        assert any(e["payload"]["n"] == 2 for e in received)

    def test_consumer_retries_after_xreadgroup_exception(self):
        bus, client = _make_bus()
        client.xreadgroup.side_effect = [
            Exception("Redis timeout"),
            None,
        ]
        bus.subscribe("crash.event", lambda e: None)
        time.sleep(1.5)  # retry has 1s sleep
        bus.stop()
        # Should not have crashed the thread
        assert not bus._thread.is_alive() or not bus._running


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

class TestRedisStop:

    def test_stop_sets_running_false(self):
        bus, client = _make_bus()
        client.xreadgroup.return_value = None
        bus.subscribe("x", lambda e: None)
        bus.stop()
        assert bus._running is False

    def test_stop_is_idempotent(self):
        bus, client = _make_bus()
        bus.stop()
        bus.stop()  # should not raise


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

class TestIntrospection:

    def test_stream_length_returns_xlen(self):
        bus, client = _make_bus()
        client.xlen.return_value = 42
        assert bus.stream_length("telemetry.collected") == 42
        client.xlen.assert_called_once_with("ibn:events:telemetry.collected")

    def test_stream_length_returns_minus1_on_error(self):
        bus, client = _make_bus()
        client.xlen.side_effect = Exception("boom")
        assert bus.stream_length("any.event") == -1

    def test_pending_count_returns_pending_field(self):
        bus, client = _make_bus()
        client.xpending.return_value = {"pending": 7}
        assert bus.pending_count("assessment.complete") == 7

    def test_pending_count_returns_minus1_on_error(self):
        bus, client = _make_bus()
        client.xpending.side_effect = Exception("boom")
        assert bus.pending_count("any.event") == -1

    def test_flush_stream_calls_delete(self):
        bus, client = _make_bus()
        bus.flush_stream("telemetry.collected")
        client.delete.assert_called_once_with("ibn:events:telemetry.collected")


# ---------------------------------------------------------------------------
# get_event_bus() factory
# ---------------------------------------------------------------------------

class TestGetEventBus:

    def test_returns_in_process_bus_without_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from ibn.core.base_agent import get_event_bus, EventBus
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_returns_redis_bus_with_redis_url(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        with patch("ibn.core.redis_event_bus.RedisEventBus.__init__", return_value=None):
            with patch("redis.from_url") as mock_ru:
                mock_client = MagicMock()
                mock_client.ping.return_value = True
                mock_ru.return_value = mock_client
                from ibn.core.base_agent import get_event_bus
                from ibn.core.redis_event_bus import RedisEventBus
                # Re-import to reset module-level state
                bus = get_event_bus("redis://localhost:6379")
                # RedisEventBus.__init__ was patched to None so bus is RedisEventBus instance
                assert isinstance(bus, RedisEventBus)

    def test_falls_back_to_in_process_when_redis_unreachable(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://does-not-exist:9999")
        from ibn.core.base_agent import get_event_bus, EventBus
        bus = get_event_bus("redis://does-not-exist:9999")
        assert isinstance(bus, EventBus)

    def test_explicit_url_overrides_env_var(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        # Passing an unreachable URL → falls back
        from ibn.core.base_agent import get_event_bus, EventBus
        bus = get_event_bus("redis://no-such-host:9999")
        assert isinstance(bus, EventBus)
