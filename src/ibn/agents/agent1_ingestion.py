"""
Agent 1 — Intent Ingestion  (RFC 9315 §5.1.1)

Responsibilities:
  1. Parse and validate structured intent templates (Phase 1) or NL (Phase 3)
  2. Conflict detection against active POR intents in Neo4j
  3. Create Intent node (L4) in CANDIDATE modelState
  4. Emit live_note() to the appropriate Live-Memory candidate space
  5. Publish intent.ingested event on the event bus
  6. Record AgentExecution audit node (L9)

Entry point::

    agent = Agent1Ingestion(neo4j, live_memory)
    result = agent.run(
        intent_data={
            "type": "access-policy",
            "subject": "Guest",
            "action": "permit",
            "target": "Internet",
            "statement": "Guest users must only access the internet",
        },
        candidate_space="ibn-candidate-001",
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import Intent, ModelState, VALID_INTENT_ACTIONS


class ConflictError(ValueError):
    """Raised when a new intent conflicts with an existing active intent."""


class Agent1Ingestion(BaseAgent):

    AGENT_ID   = "A1"
    AGENT_NAME = "Ingestion"

    # ------------------------------------------------------------------
    # Required fields for structured template ingestion
    # ------------------------------------------------------------------
    _REQUIRED_FIELDS = {"type", "subject", "action", "target"}

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        intent_data:      dict = kwargs["intent_data"]
        candidate_space:  str  = kwargs.get("candidate_space", "ibn-candidate-001")
        author_id:        Optional[str] = kwargs.get("author_id")

        # 1. Validate
        intent = self._validate(intent_data, author_id)

        # 2. Conflict detection
        conflict = self._detect_conflict(intent)
        if conflict:
            self._note(
                candidate_space,
                f"CONFLICT: {intent.intentId} conflicts with {conflict['existing_intent']} "
                f"— {conflict['detail']}",
                category="conflict-detection",
            )
            raise ConflictError(
                f"Intent {intent.intentId} conflicts with {conflict['existing_intent']}: "
                f"{conflict['detail']}"
            )

        # 3. Persist to Neo4j (L4)
        self._neo4j.create_intent(intent)

        # 4. Live-Memory note
        self._note(
            candidate_space,
            f"Intent {intent.intentId} ingested: "
            f"{intent.subject} → {intent.action} → {intent.target}",
            category="intent-ingestion",
        )

        # 5. Publish event
        self._publish("intent.ingested", {
            "intentId":   intent.intentId,
            "subject":    intent.subject,
            "action":     intent.action,
            "target":     intent.target,
            "modelState": intent.modelState.value,
        })

        return {
            "id":          intent.intentId,
            "intentId":    intent.intentId,
            "status":      intent.status,
            "modelState":  intent.modelState.value,
            "conflict":    None,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, data: dict, author_id: Optional[str]) -> Intent:
        missing = self._REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        statement = data.get("statement", "").strip()
        if not statement:
            # Auto-generate from subject/action/target
            statement = (
                f"{data['subject']} {data['action']} {data['target']}"
            ).strip()
        if not statement:
            raise ValueError("Intent statement cannot be empty")

        action = data["action"]
        if action not in VALID_INTENT_ACTIONS:
            raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_INTENT_ACTIONS}")

        intent_id = data.get(
            "intentId",
            f"INT-{uuid.uuid4().hex[:8].upper()}",
        )

        return Intent(
            intentId   = intent_id,
            statement  = statement,
            type       = data["type"],
            subject    = data["subject"],
            action     = action,
            target     = data["target"],
            status     = "INGESTED",
            modelState = ModelState.CANDIDATE,
            authorId   = author_id,
            priority   = data.get("priority", 100),
        )

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _detect_conflict(self, new_intent: Intent) -> Optional[dict]:
        """
        Query Neo4j for active POR intents that overlap with the new one.
        Returns a conflict dict or None.
        """
        try:
            active = self._neo4j.get_active_intents()
        except Exception:
            # If we can't reach Neo4j for conflict check, log and proceed
            self._log.warning("Could not query active intents for conflict check")
            return None

        for existing in active:
            if (
                existing.get("subject") == new_intent.subject
                and existing.get("target") == new_intent.target
            ):
                if existing.get("action") != new_intent.action:
                    return {
                        "type":            "CONFLICTING_ACTION",
                        "existing_intent": existing["intentId"],
                        "new_intent":      new_intent.intentId,
                        "detail": (
                            f"Same subject/target but "
                            f"{existing['action']} vs {new_intent.action}"
                        ),
                    }
                else:
                    return {
                        "type":            "DUPLICATE",
                        "existing_intent": existing["intentId"],
                        "detail":          "Identical intent already active",
                    }

        return None
