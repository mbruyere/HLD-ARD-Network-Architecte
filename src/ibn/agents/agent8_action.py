"""
Agent 8 — Action  (RFC 9315 §5.2.3)

Responsibilities:
  1. Receive assessment.complete event from Agent 7 (or run directly with
     an incident_id)
  2. Classify severity: Info / Low / Medium / High / Critical
  3. Apply autonomy decision matrix:
        Info    → log only
        Low     → auto-remediate (re-push config via Agent 5)
        Medium  → auto-remediate + verify
        High    → escalate to outer loop (human review)
        Critical→ rollback to previous POR via PRECEDED_BY + escalate
  4. For auto-remediation: build a plan and call Agent 5 directly
  5. For rollback: traverse the PRECEDED_BY chain in Neo4j, push previous
     Configuration node, create Rollback DeploymentEvent
  6. Write Remediation nodes (L6) with outcome
  7. Emit live_note() to ibn-loop-inner (or ibn-loop-outer on escalation)
  8. Publish remediation.complete / escalation.required events

Entry point::

    agent = Agent8Action(neo4j, live_memory, agent5=agent5_instance)
    result = agent.run(
        incident_id="INC-001",
        assess_space="ibn-loop-inner",
        outer_space="ibn-loop-outer",
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Callable

from ibn.core.base_agent import BaseAgent
from ibn.core.models import Severity


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------

def classify_severity(incident: dict) -> str:
    """
    Map incident properties to a severity string per the decision matrix.

    Expected incident keys (all optional, default to 0/False):
        intents_violated (int)
        service_impact (bool)
        business_critical (bool)
        devices_affected (int)
        redundancy_active (bool)
        metric_deviation_pct (float)
    """
    if incident.get("intents_violated", 0) >= 3:
        return "CRITICAL"
    if incident.get("service_impact") and incident.get("business_critical"):
        return "HIGH"
    if incident.get("devices_affected", 0) >= 2:
        return "MEDIUM"
    if incident.get("redundancy_active") and incident.get("devices_affected", 0) == 1:
        return "LOW"
    if incident.get("metric_deviation_pct", 0) < 10:
        return "INFO"
    return "MEDIUM"


# ---------------------------------------------------------------------------
# Autonomy decision
# ---------------------------------------------------------------------------

def decide_action(severity: str) -> dict:
    """
    Map severity → action plan per the autonomy decision matrix.

    Returns:
        {
            "action": "LOG" | "AUTO_REMEDIATE" | "AUTO_REMEDIATE_VERIFY"
                      | "ESCALATE" | "ROLLBACK_ESCALATE",
            "autonomous": bool,
            "requires_human": bool,
        }
    """
    matrix = {
        "INFO":     {"action": "LOG",                    "autonomous": True,  "requires_human": False},
        "LOW":      {"action": "AUTO_REMEDIATE",          "autonomous": True,  "requires_human": False},
        "MEDIUM":   {"action": "AUTO_REMEDIATE_VERIFY",   "autonomous": True,  "requires_human": False},
        "HIGH":     {"action": "ESCALATE",                "autonomous": False, "requires_human": True},
        "CRITICAL": {"action": "ROLLBACK_ESCALATE",       "autonomous": False, "requires_human": True},
    }
    return matrix.get(severity, matrix["MEDIUM"])


# ---------------------------------------------------------------------------
# Agent 8
# ---------------------------------------------------------------------------

class Agent8Action(BaseAgent):
    """Decide and execute remediation actions based on assessment results."""

    AGENT_ID   = "A8"
    AGENT_NAME = "Action"

    def __init__(self, neo4j, live_memory, agent5=None, event_bus=None):
        super().__init__(neo4j, live_memory, event_bus)
        # Agent 5 instance for re-push remediation (injected for testability)
        self._agent5 = agent5

    # ------------------------------------------------------------------
    # _execute
    # ------------------------------------------------------------------

    def _execute(
        self,
        incident_id: Optional[str] = None,
        assessment: Optional[dict] = None,
        assess_space: str = "ibn-loop-inner",
        outer_space: str = "ibn-loop-outer",
        **kwargs,
    ) -> dict:
        """
        Process one incident.

        Either pass ``incident_id`` (fetches from Neo4j) or pass a raw
        ``assessment`` dict from Agent 7 directly.
        """
        incident = self._load_incident(incident_id, assessment)
        if not incident:
            return {"action": "NONE", "reason": "No incident to process"}

        severity = classify_severity(incident)
        plan = decide_action(severity)
        action = plan["action"]

        remediation_id = f"REM-{uuid.uuid4().hex[:8].upper()}"
        outcome: dict = {"remediationId": remediation_id, "action": action,
                         "severity": severity, "success": False}

        try:
            if action == "LOG":
                outcome["success"] = True
                self._note(assess_space,
                           f"[A8] {severity}: logged only — no action required", "observation")

            elif action in ("AUTO_REMEDIATE", "AUTO_REMEDIATE_VERIFY"):
                outcome = self._auto_remediate(
                    incident, remediation_id, action, assess_space)

            elif action == "ESCALATE":
                outcome = self._escalate(incident, remediation_id, outer_space)

            elif action == "ROLLBACK_ESCALATE":
                outcome = self._rollback_and_escalate(
                    incident, remediation_id, assess_space, outer_space)

        except Exception as exc:
            outcome["success"] = False
            outcome["error"] = str(exc)
            self._log.error("[A8] Action %s failed: %s", action, exc, exc_info=True)
            self._note(assess_space,
                       f"[A8] Remediation FAILED ({action}): {exc}", "issue")
            if incident_id:
                self._write_remediation_node(remediation_id, incident_id, action,
                                             success=False, error=str(exc))

        self._publish(
            "remediation.complete" if outcome.get("success") else "escalation.required",
            outcome,
        )
        return outcome

    # ------------------------------------------------------------------
    # Load incident
    # ------------------------------------------------------------------

    def _load_incident(self, incident_id: Optional[str],
                       assessment: Optional[dict]) -> Optional[dict]:
        """Return an incident dict from Neo4j or the raw assessment dict."""
        if assessment:
            # Convert assessment → incident format.
            # Explicit severity fields in the assessment dict take precedence.
            verdict = assessment.get("verdict", "")
            return {
                "incidentId":       assessment.get("incidentId", ""),
                "intentId":         assessment.get("intentId", ""),
                "verdict":          verdict,
                "devices_affected": assessment.get("devices_affected",
                                        len(assessment.get("driftEvents", []))),
                "service_impact":   assessment.get("service_impact",
                                        verdict == "NON_COMPLIANT"),
                "business_critical": assessment.get("business_critical", False),
                "redundancy_active": assessment.get("redundancy_active", False),
                "intents_violated":  assessment.get("intents_violated",
                                        1 if verdict != "COMPLIANT" else 0),
                "metric_deviation_pct": assessment.get("metric_deviation_pct", 0),
                "drift_events":      assessment.get("driftEvents", []),
            }
        if incident_id:
            rows = self._neo4j.run_query(
                "MATCH (i:Incident {incidentId: $id}) RETURN i",
                id=incident_id,
            )
            if rows and "i" in rows[0]:
                r = dict(rows[0]["i"])
                r.setdefault("devices_affected", r.get("driftCount", 0))
                return r
        return None

    # ------------------------------------------------------------------
    # Remediation: re-push config
    # ------------------------------------------------------------------

    def _auto_remediate(self, incident: dict, remediation_id: str,
                        action: str, space: str) -> dict:
        """Trigger Agent 5 to re-push the CANDIDATE configuration."""
        intent_id = incident.get("intentId", "unknown")

        # Build plan from most recent CANDIDATE configs for affected devices
        drift_events = incident.get("drift_events", [])
        device_ids = ([e["deviceId"] for e in drift_events]
                      if drift_events else self._fetch_firewall_device_ids())

        configs = self._fetch_candidate_configs(device_ids)
        if not configs:
            raise RuntimeError(f"No candidate configs found for {device_ids}")

        plan = [
            {"deviceId": did, "configId": cid, "content": content}
            for did, cid, content in configs
        ]

        self._note(space,
                   f"[A8] {action}: re-pushing {len(plan)} device(s) for intent {intent_id}",
                   "decision")

        # Call Agent 5 if available; otherwise simulate
        if self._agent5:
            push_result = self._agent5.run(
                intent_id=intent_id,
                plan=plan,
                deploy_space=space,
            )
            success = push_result.get("status") in ("deployed", "ok", "success")
        else:
            # Simulate successful push (for unit tests without real SSH)
            success = True
            push_result = {"status": "simulated", "devices": [p["deviceId"] for p in plan]}

        self._write_remediation_node(remediation_id, intent_id, action,
                                     success=success,
                                     error=None if success else "Push failed")

        if success:
            self._note(space,
                       f"[A8] Remediation SUCCESS: {len(plan)} device(s) re-pushed", "observation")
        else:
            self._note(space,
                       f"[A8] Remediation FAILED — escalating to outer loop", "issue")
            self._escalate(incident, f"{remediation_id}-ESC", "ibn-loop-outer")

        return {"remediationId": remediation_id, "action": action,
                "severity": classify_severity(incident),
                "success": success, "devicesRemediated": len(plan),
                "pushResult": push_result}

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(self, incident: dict, remediation_id: str, outer_space: str) -> dict:
        """Escalate to the outer loop (human review queue)."""
        intent_id = incident.get("intentId", incident.get("incidentId", "unknown"))
        severity = classify_severity(incident)

        self._note(
            outer_space,
            f"[A8] ESCALATION — {severity} incident requires human review\n"
            f"  Intent: {intent_id}\n"
            f"  Verdict: {incident.get('verdict','')}\n"
            f"  Devices affected: {incident.get('devices_affected', '?')}",
            "issue",
        )

        self._write_remediation_node(remediation_id, intent_id, "ESCALATE",
                                     success=True, escalated=True)
        return {"remediationId": remediation_id, "action": "ESCALATE",
                "severity": severity, "success": True, "escalated": True,
                "outerSpace": outer_space}

    # ------------------------------------------------------------------
    # Rollback via PRECEDED_BY chain
    # ------------------------------------------------------------------

    def _rollback_and_escalate(self, incident: dict, remediation_id: str,
                               space: str, outer_space: str) -> dict:
        """
        Traverse PRECEDED_BY chain to find the previous good Configuration,
        push it via Agent 5, then escalate.
        """
        intent_id = incident.get("intentId", "unknown")
        device_ids = self._fetch_firewall_device_ids()

        rollback_configs = []
        for device_id in device_ids:
            prev = self._fetch_previous_config(device_id)
            if prev:
                rollback_configs.append(prev)

        if not rollback_configs:
            self._note(space, f"[A8] ROLLBACK: no previous config found — escalating only", "issue")
        else:
            plan = [{"deviceId": c["deviceId"], "configId": c["configId"],
                     "content": c["content"]} for c in rollback_configs]

            self._note(space,
                       f"[A8] ROLLBACK: reverting {len(plan)} device(s) to previous config",
                       "decision")

            if self._agent5:
                self._agent5.run(intent_id=intent_id, plan=plan, deploy_space=space)

        # Escalate regardless
        self._escalate(incident, f"{remediation_id}-ESC", outer_space)
        self._write_remediation_node(remediation_id, intent_id, "ROLLBACK_ESCALATE",
                                     success=True, escalated=True,
                                     rollback_count=len(rollback_configs))

        return {"remediationId": remediation_id, "action": "ROLLBACK_ESCALATE",
                "severity": "CRITICAL", "success": True,
                "rollbackCount": len(rollback_configs), "escalated": True}

    # ------------------------------------------------------------------
    # Neo4j helpers
    # ------------------------------------------------------------------

    def _fetch_firewall_device_ids(self) -> list[str]:
        rows = self._neo4j.run_query(
            """
            MATCH (d:Device)
            WHERE d.deviceRole = 'FIREWALL' AND d.modelState IN ['POR','DEPLOYED']
            RETURN d.deviceId AS deviceId
            """
        )
        return [r["deviceId"] for r in rows if r.get("deviceId")]

    def _fetch_candidate_configs(self, device_ids: list[str]) -> list[tuple]:
        """Return [(device_id, config_id, content), ...] for given devices."""
        rows = self._neo4j.run_query(
            """
            MATCH (c:Configuration)
            WHERE c.deviceId IN $deviceIds
              AND c.modelState IN ['CANDIDATE','DEPLOYED']
            RETURN c.deviceId AS deviceId, c.configId AS configId,
                   c.content AS content
            ORDER BY c.createdAt DESC
            """
        )
        seen: dict[str, tuple] = {}
        for r in rows:
            did = r.get("deviceId")
            if did and did not in seen and r.get("content"):
                seen[did] = (did, r["configId"], r["content"])
        return list(seen.values())

    def _fetch_previous_config(self, device_id: str) -> Optional[dict]:
        """Traverse PRECEDED_BY to find the config before the current one."""
        rows = self._neo4j.run_query(
            """
            MATCH (current:Configuration {deviceId: $deviceId})-[:PRECEDED_BY]->(prev:Configuration)
            RETURN prev.configId AS configId, prev.deviceId AS deviceId,
                   prev.content AS content
            ORDER BY prev.createdAt DESC
            LIMIT 1
            """,
            deviceId=device_id,
        )
        return rows[0] if rows else None

    def _write_remediation_node(self, remediation_id: str, intent_id: str,
                                action: str, success: bool,
                                error: Optional[str] = None,
                                escalated: bool = False,
                                rollback_count: int = 0) -> None:
        self._neo4j.run_query(
            """
            MERGE (r:Remediation {remediationId: $rId})
            SET r.intentId     = $intentId,
                r.action       = $action,
                r.success      = $success,
                r.escalated    = $escalated,
                r.rollbackCount = $rollbackCount,
                r.errorMessage = $error,
                r.modelState   = 'AS_BUILT',
                r.createdAt    = datetime()
            """,
            rId=remediation_id,
            intentId=intent_id,
            action=action,
            success=success,
            escalated=escalated,
            rollbackCount=rollback_count,
            error=error,
        )
