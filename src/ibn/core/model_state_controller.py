"""
ModelStateController — manages model state transitions for the IBN lifecycle.

Implements the 5 concurrent model states (§3.3 of IBN_Closed_Loop_Architecture):
  WHAT_IF → CANDIDATE → POR → DEPLOYED → AS_BUILT

Each state transition:
  1. Validates the transition is legal (e.g., cannot skip from WHAT_IF to POR).
  2. Writes a LifecycleTransition node to Neo4j.
  3. Publishes a ``model.state.transition`` event on the event bus, which
     triggers ConsolidationManager to consolidate the departing space and
     push bank files to Graph-Memory when the arriving state is POR or above.

The controller also tracks the Live-Memory space associated with each active
intent/model-state pair so downstream consumers know which space to consolidate.

Usage::

    from ibn.core.model_state_controller import ModelStateController

    ctrl = ModelStateController(neo4j, event_bus)

    # Promote an intent from CANDIDATE to POR (human approval)
    ctrl.transition(
        intent_id="INT-001",
        from_state="CANDIDATE",
        to_state="POR",
        reason="Approved by network architect",
        operator="operator-01",
    )
    # → publishes model.state.transition on event bus
    # → ConsolidationManager consolidates ibn-candidate-{intent_id}
    # → bank files pushed to Graph-Memory (POR ∈ push-eligible states)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("ibn.model_state_controller")


# Legal forward transitions only (no skipping, no going backwards)
_LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("WHAT_IF",   "CANDIDATE"),
    ("CANDIDATE", "POR"),
    ("POR",       "DEPLOYED"),
    ("DEPLOYED",  "AS_BUILT"),
    # Rollback paths (backwards transitions)
    ("CANDIDATE", "WHAT_IF"),
    ("POR",       "CANDIDATE"),
    ("DEPLOYED",  "POR"),
    ("AS_BUILT",  "DEPLOYED"),
})

# Default Live-Memory space prefix per source state
_SPACE_PREFIXES: dict[str, str] = {
    "WHAT_IF":   "ibn-whatif",
    "CANDIDATE": "ibn-candidate",
    "POR":       "ibn-por",
    "DEPLOYED":  "ibn-deploy",
    "AS_BUILT":  "ibn-asbuilt",
}

ALL_STATES = frozenset({"WHAT_IF", "CANDIDATE", "POR", "DEPLOYED", "AS_BUILT"})


class ModelStateTransitionError(ValueError):
    """Raised when an illegal model state transition is attempted."""


class ModelStateController:
    """
    Manages model state transitions for IBN intents.

    Parameters
    ----------
    neo4j:
        Neo4j client for writing LifecycleTransition nodes.
    event_bus:
        Event bus to publish ``model.state.transition`` events on.
    """

    def __init__(self, neo4j, event_bus=None):
        self._neo4j = neo4j
        self._bus = event_bus

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    def transition(
        self,
        intent_id: str,
        from_state: str,
        to_state: str,
        reason: str = "",
        operator: str = "system",
        space_id: Optional[str] = None,
    ) -> dict:
        """
        Execute a model state transition for an intent.

        Parameters
        ----------
        intent_id:
            The intent being transitioned.
        from_state / to_state:
            Source and target model states.
        reason:
            Human-readable rationale for the transition.
        operator:
            Who/what triggered the transition (agent ID or operator name).
        space_id:
            Override the Live-Memory space to consolidate.
            Defaults to ``{prefix}-{intent_id}`` based on the from_state.

        Returns
        -------
        dict with: ``transition_id``, ``intent_id``, ``from_state``,
                   ``to_state``, ``space_id``, ``timestamp``.

        Raises
        ------
        ModelStateTransitionError:
            If the (from_state, to_state) pair is not a legal transition.
        """
        from_state = from_state.upper()
        to_state = to_state.upper()

        if (from_state, to_state) not in _LEGAL_TRANSITIONS:
            raise ModelStateTransitionError(
                f"Illegal transition {from_state} → {to_state} for intent {intent_id}. "
                f"Legal transitions: {sorted(_LEGAL_TRANSITIONS)}"
            )

        transition_id = f"TRN-{uuid.uuid4().hex[:8].upper()}"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Derive Live-Memory space if not overridden
        if space_id is None:
            prefix = _SPACE_PREFIXES.get(from_state, "ibn-unknown")
            space_id = f"{prefix}-{intent_id}"

        # Write LifecycleTransition node to Neo4j
        self._write_transition(
            transition_id=transition_id,
            intent_id=intent_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            operator=operator,
            timestamp=timestamp,
        )

        # Publish event to trigger ConsolidationManager
        if self._bus is not None:
            self._bus.publish("model.state.transition", {
                "transition_id": transition_id,
                "intent_id":     intent_id,
                "from_state":    from_state,
                "to_state":      to_state,
                "space_id":      space_id,
                "reason":        reason,
                "operator":      operator,
                "timestamp":     timestamp,
            })

        logger.info(
            "Transition %s: intent=%s %s → %s space=%s",
            transition_id, intent_id, from_state, to_state, space_id,
        )

        return {
            "transition_id": transition_id,
            "intent_id":     intent_id,
            "from_state":    from_state,
            "to_state":      to_state,
            "space_id":      space_id,
            "timestamp":     timestamp,
        }

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def approve(self, intent_id: str, operator: str = "operator", space_id: Optional[str] = None) -> dict:
        """Promote CANDIDATE → POR (human approval gate)."""
        return self.transition(
            intent_id=intent_id,
            from_state="CANDIDATE",
            to_state="POR",
            reason="Approved by operator",
            operator=operator,
            space_id=space_id,
        )

    def deploy(self, intent_id: str, operator: str = "system", space_id: Optional[str] = None) -> dict:
        """Promote POR → DEPLOYED (orchestration complete)."""
        return self.transition(
            intent_id=intent_id,
            from_state="POR",
            to_state="DEPLOYED",
            reason="Deployment completed",
            operator=operator,
            space_id=space_id,
        )

    def verify(self, intent_id: str, operator: str = "system", space_id: Optional[str] = None) -> dict:
        """Promote DEPLOYED → AS_BUILT (compliance verified)."""
        return self.transition(
            intent_id=intent_id,
            from_state="DEPLOYED",
            to_state="AS_BUILT",
            reason="Compliance verified — all assessments COMPLIANT",
            operator=operator,
            space_id=space_id,
        )

    def rollback(self, intent_id: str, from_state: str, reason: str = "", space_id: Optional[str] = None) -> dict:
        """Roll back one state (e.g. DEPLOYED → POR)."""
        rollback_map = {
            "DEPLOYED":  "POR",
            "POR":       "CANDIDATE",
            "CANDIDATE": "WHAT_IF",
            "AS_BUILT":  "DEPLOYED",
        }
        to_state = rollback_map.get(from_state.upper())
        if not to_state:
            raise ModelStateTransitionError(f"Cannot roll back from {from_state}")
        return self.transition(
            intent_id=intent_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason or f"Rollback from {from_state}",
            operator="system",
            space_id=space_id,
        )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_legal(from_state: str, to_state: str) -> bool:
        """Return True if the transition is legal."""
        return (from_state.upper(), to_state.upper()) in _LEGAL_TRANSITIONS

    @staticmethod
    def space_for(state: str, intent_id: str) -> str:
        """Return the default Live-Memory space for a given state + intent."""
        prefix = _SPACE_PREFIXES.get(state.upper(), "ibn-unknown")
        return f"{prefix}-{intent_id}"

    # ------------------------------------------------------------------
    # Neo4j write
    # ------------------------------------------------------------------

    def _write_transition(
        self,
        transition_id: str,
        intent_id: str,
        from_state: str,
        to_state: str,
        reason: str,
        operator: str,
        timestamp: str,
    ) -> None:
        """Write a LifecycleTransition node to Neo4j (L8 Lifecycle layer)."""
        try:
            self._neo4j.run_query(
                """
                MERGE (i:Intent {intentId: $intentId})
                CREATE (t:LifecycleTransition {
                    transitionId: $transitionId,
                    intentId:     $intentId,
                    fromState:    $fromState,
                    toState:      $toState,
                    reason:       $reason,
                    operator:     $operator,
                    timestamp:    $timestamp,
                    modelState:   $toState
                })
                CREATE (i)-[:HAS_TRANSITION]->(t)
                """,
                transitionId=transition_id,
                intentId=intent_id,
                fromState=from_state,
                toState=to_state,
                reason=reason,
                operator=operator,
                timestamp=timestamp,
            )
        except Exception as exc:
            logger.warning("Could not write LifecycleTransition to Neo4j: %s", exc)
