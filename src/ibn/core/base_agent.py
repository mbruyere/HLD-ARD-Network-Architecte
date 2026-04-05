"""
BaseAgent — abstract base class for all 10 IBN agents.

Every agent:
1. Holds references to Neo4jClient and LiveMemoryClient
2. Records every invocation as an AgentExecution node in L9
3. Publishes events to the event bus after significant state changes
4. Provides a standard ``run(**kwargs)`` entry point

Subclasses override ``_execute(**kwargs) → dict`` with their logic.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ibn.core.models import AgentExecution, ModelState
from ibn.core.neo4j_client import Neo4jClient
from ibn.core.live_memory_client import LiveMemoryClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple in-process event bus (swapped out for Kafka/Redis in production)
# ---------------------------------------------------------------------------

class EventBus:
    """Minimal publish/subscribe event bus."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def publish(self, event_type: str, payload: dict) -> dict:
        event = {
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for cb in self._subscribers.get(event_type, []):
            try:
                cb(event)
            except Exception as exc:
                logger.warning("Event handler %s raised: %s", cb, exc)
        return event

    def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)


# Singleton default bus — agents import this unless injected
_default_bus: Optional[EventBus] = None


def get_default_bus() -> EventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base for all IBN agents."""

    #: Override in subclass — e.g. "A1", "A5"
    AGENT_ID: str = "A0"
    #: Human-readable name for logging
    AGENT_NAME: str = "BaseAgent"

    def __init__(
        self,
        neo4j: Neo4jClient,
        live_memory: LiveMemoryClient,
        event_bus: Optional[EventBus] = None,
    ):
        self._neo4j = neo4j
        self._lm = live_memory
        self._bus = event_bus or get_default_bus()
        self._log = logging.getLogger(f"ibn.{self.AGENT_ID}")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, **kwargs) -> dict:
        """Execute the agent, record audit, return result dict."""
        start_ms = int(time.monotonic() * 1000)
        exec_id = f"EXEC-{self.AGENT_ID}-{uuid.uuid4().hex[:8].upper()}"
        self._log.info("[%s] Starting — %s", exec_id, kwargs)

        error_msg: Optional[str] = None
        result: dict = {}

        try:
            result = self._execute(**kwargs)
        except Exception as exc:
            error_msg = str(exc)
            self._log.error("[%s] Failed: %s", exec_id, exc, exc_info=True)
            raise
        finally:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            self._record_execution(
                exec_id    = exec_id,
                action     = kwargs.get("action", "run"),
                input_ref  = kwargs.get("input_ref"),
                output_ref = result.get("id") if isinstance(result, dict) else None,
                duration_ms= duration_ms,
                error_msg  = error_msg,
            )
            self._log.info("[%s] Done in %dms", exec_id, duration_ms)

        return result

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    def _execute(self, **kwargs) -> dict:
        """Agent-specific logic.  Must return a result dict."""

    # ------------------------------------------------------------------
    # Helpers available to all agents
    # ------------------------------------------------------------------

    def _note(self, space: str, content: str, category: str = "general") -> dict:
        """Emit a Live-Memory note, swallowing errors so agents don't crash."""
        try:
            return self._lm.live_note(space=space, content=content, category=category)
        except Exception as exc:
            self._log.warning("live_note failed (space=%s): %s", space, exc)
            return {}

    def _publish(self, event_type: str, payload: dict) -> dict:
        return self._bus.publish(event_type, payload)

    def _record_execution(
        self,
        exec_id:     str,
        action:      str,
        input_ref:   Optional[str],
        output_ref:  Optional[str],
        duration_ms: int,
        error_msg:   Optional[str],
    ) -> None:
        ae = AgentExecution(
            agentId      = self.AGENT_ID,
            action       = action,
            inputRef     = input_ref,
            outputRef    = output_ref,
            modelState   = ModelState.POR,
            durationMs   = duration_ms,
            errorMessage = error_msg,
        )
        try:
            self._neo4j.record_agent_execution(ae)
        except Exception as exc:
            self._log.warning("record_agent_execution failed: %s", exc)
