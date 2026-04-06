"""
IBN Inner Loop Controller

Wires Agent 6 → Agent 7 → Agent 8 via the EventBus.

The inner loop operates autonomously (RFC 9315 §6):
  1. Agent 6 publishes ``telemetry.collected`` after each polling cycle
  2. Agent 7 subscribes → runs compliance assessment → publishes ``assessment.complete``
  3. Agent 8 subscribes → decides and executes action → publishes ``remediation.complete``
     or ``escalation.required``

Usage::

    from ibn.agents.inner_loop import InnerLoop

    loop = InnerLoop(neo4j, live_memory, agent5=agent5)
    loop.start()          # subscribe all agents to the event bus
    loop.run_cycle()      # trigger one manual assessment cycle (for testing)
    loop.stop()           # unsubscribe
"""

from __future__ import annotations

import logging
from typing import Optional

from ibn.core.base_agent import EventBus, get_default_bus, get_event_bus
from ibn.core.live_memory_client import LiveMemoryClient
from ibn.core.graph_memory_client import GraphMemoryClient
from ibn.core.neo4j_client import Neo4jClient
from ibn.core.consolidation_manager import ConsolidationManager
from ibn.agents.agent6_monitoring import Agent6Monitoring
from ibn.agents.agent7_assessment import Agent7Assessment
from ibn.agents.agent8_action import Agent8Action

logger = logging.getLogger("ibn.inner_loop")


class InnerLoop:
    """Wires and manages the autonomous inner loop."""

    def __init__(
        self,
        neo4j: Neo4jClient,
        live_memory: LiveMemoryClient,
        agent5=None,
        event_bus: Optional[EventBus] = None,
        assess_space: str = "ibn-loop-inner",
        outer_space: str = "ibn-loop-outer",
        graph_memory: Optional[GraphMemoryClient] = None,
    ):
        self._bus = event_bus or get_event_bus()
        self._assess_space = assess_space
        self._outer_space = outer_space

        self._neo4j = neo4j
        self.agent6 = Agent6Monitoring(neo4j, live_memory, self._bus)
        self.agent7 = Agent7Assessment(neo4j, live_memory, self._bus)
        self.agent8 = Agent8Action(neo4j, live_memory, agent5=agent5, event_bus=self._bus)

        # Tier 3 consolidation — wires Live-Memory → Graph-Memory bridge
        _gm = graph_memory or GraphMemoryClient.from_env()
        self.consolidation = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=_gm,
            event_bus=self._bus,
            note_threshold=20,
            sweep_interval=3600,
            push_to_graph=True,
        )

        self._subscribed = False

    def start(self) -> None:
        """Subscribe agents to the event bus — starts the autonomous loop."""
        if self._subscribed:
            return

        # A6 telemetry → A7 assessment
        self._bus.subscribe("telemetry.collected", self._on_telemetry)
        # A7 assessment.complete → A8 action
        self._bus.subscribe("assessment.complete", self._on_assessment)
        # A8 remediation.complete → consolidation trigger
        self._bus.subscribe("remediation.complete", self._on_remediation)
        self._bus.subscribe("escalation.required", self._on_escalation)

        # Start consolidation manager (subscribes to model.state.transition
        # and inner.loop.complete on the same bus)
        self.consolidation.start()

        self._subscribed = True
        logger.info("Inner loop started — subscribed to event bus")

    def stop(self) -> None:
        """Unsubscribe and stop the loop."""
        self.consolidation.stop()
        self._subscribed = False
        logger.info("Inner loop stopped")

    def _fetch_device_ids(self, site_id: str) -> list[str]:
        """Return FIREWALL device IDs for the given site from Neo4j."""
        rows = self._neo4j.run_query(
            """
            MATCH (d:Device)-[:LOCATED_AT]->(s:Site {siteId: $siteId})
            WHERE d.deviceRole = 'FIREWALL' AND d.modelState IN ['POR','DEPLOYED']
            RETURN d.deviceId AS deviceId
            UNION
            MATCH (d:Device)
            WHERE d.deviceRole = 'FIREWALL' AND d.modelState IN ['POR','DEPLOYED']
            RETURN d.deviceId AS deviceId
            """,
            siteId=site_id,
        )
        ids = list({r["deviceId"] for r in rows if r.get("deviceId")})
        return ids or []

    def run_cycle(self, site_id: str = "SITE-HQ-01") -> dict:
        """
        Run one complete inner loop cycle manually.
        Useful for testing and for cron-driven operation before CDC is wired.

        Returns a summary of the cycle.
        """
        # Step 1: collect telemetry (A6) — auto-discover firewall devices
        device_ids = self._fetch_device_ids(site_id)
        if not device_ids:
            logger.warning("No firewall devices found for site %s — skipping A6 collection", site_id)
            telemetry_result = {"devices": 0, "anomalies": 0}
        else:
            telemetry_result = self.agent6.run(
                devices=device_ids,
                asbuilt_space=self._assess_space,
            )

        # Step 2: assess all active intents (A7)
        assessment_result = self.agent7.run(assess_space=self._assess_space)

        # Step 3: act on any non-compliant assessments (A8)
        action_results = []
        for a in assessment_result.get("assessments", []):
            if a.get("verdict") != "COMPLIANT":
                action_result = self.agent8.run(
                    assessment=a,
                    assess_space=self._assess_space,
                    outer_space=self._outer_space,
                )
                action_results.append(action_result)

        cycle_result = {
            "telemetry": telemetry_result,
            "assessments": assessment_result,
            "actions": action_results,
            "cycle_complete": True,
        }

        # Emit inner loop complete — triggers ConsolidationManager to
        # consolidate ibn-loop-inner and push to Graph-Memory
        self._bus.publish("inner.loop.complete", {
            "site_id": site_id,
            "actions_taken": len(action_results),
        })

        return cycle_result

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_telemetry(self, event: dict) -> None:
        """A6 published telemetry.collected → trigger A7."""
        if not self._subscribed:
            return
        payload = event.get("payload", {})
        intent_id = payload.get("intentId")
        try:
            self.agent7.run(
                intent_id=intent_id,
                assess_space=self._assess_space,
            )
        except Exception as exc:
            logger.error("A7 failed after telemetry event: %s", exc)

    def _on_assessment(self, event: dict) -> None:
        """A7 published assessment.complete → trigger A8 for non-compliant ones."""
        if not self._subscribed:
            return
        payload = event.get("payload", {})
        for assessment in payload.get("assessments", []):
            if assessment.get("verdict") != "COMPLIANT":
                try:
                    self.agent8.run(
                        assessment=assessment,
                        assess_space=self._assess_space,
                        outer_space=self._outer_space,
                    )
                except Exception as exc:
                    logger.error("A8 failed for assessment %s: %s",
                                 assessment.get("assessmentId"), exc)

    def _on_remediation(self, event: dict) -> None:
        payload = event.get("payload", {})
        logger.info("Remediation complete: %s", payload)
        # Emit inner.loop.complete so ConsolidationManager consolidates
        # ibn-loop-inner after each event-driven remediation cycle
        self._bus.publish("inner.loop.complete", {
            "trigger": "remediation",
            "intent_id": payload.get("intentId"),
        })

    def _on_escalation(self, event: dict) -> None:
        logger.warning("Escalation required: %s", event.get("payload", {}))
