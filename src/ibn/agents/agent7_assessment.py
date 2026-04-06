"""
Agent 7 — Assessment  (RFC 9315 §5.2.2)

Responsibilities:
  1. For each active intent, fetch the desired state (POR Configuration) and
     the observed state (AS_BUILT Telemetry / OperationalState from Neo4j)
  2. Compare line-by-line: produce COMPLIANT | DEGRADED | NON_COMPLIANT verdict
  3. Detect specific drift types: firewall_rule, interface_state, vrrp_role
  4. Trace root cause via Neo4j dependency traversal (CONTAINS, AGGREGATES chains)
  5. Write ComplianceAssessment nodes (L6) and Incident nodes on drift
  6. Update Intent.complianceStatus
  7. Emit live_note() with verdict + drift summary to ibn-loop-inner space
  8. Publish assessment.complete event consumed by Agent 8

Entry point::

    agent = Agent7Assessment(neo4j, live_memory)
    result = agent.run(
        intent_id="INT-001",
        assess_space="ibn-loop-inner",
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import Severity


# ---------------------------------------------------------------------------
# Drift detection helpers
# ---------------------------------------------------------------------------

_DRIFT_DETECTORS: dict[str, callable] = {}


def _drift_detector(name: str):
    def decorator(fn):
        _DRIFT_DETECTORS[name] = fn
        return fn
    return decorator


@_drift_detector("firewall_rule")
def _detect_firewall_rule_drift(por_state: dict, asbuilt_state: dict) -> Optional[dict]:
    """Detect missing or changed firewall rules."""
    por_rules = set(por_state.get("rules", []))
    asbuilt_rules = set(asbuilt_state.get("rules", []))
    missing = por_rules - asbuilt_rules
    extra = asbuilt_rules - por_rules
    if missing or extra:
        return {
            "drift_type": "firewall_rule",
            "missing": sorted(missing),
            "extra": sorted(extra),
            "severity_hint": "HIGH" if len(missing) >= 3 else "MEDIUM" if missing else "LOW",
        }
    return None


@_drift_detector("interface_state")
def _detect_interface_state_drift(por_state: dict, asbuilt_state: dict) -> Optional[dict]:
    """Detect interface operational state mismatches."""
    por_ifaces = por_state.get("interfaces", {})
    asbuilt_ifaces = asbuilt_state.get("interfaces", {})
    drifted = {
        iface: {"expected": por_ifaces[iface], "observed": asbuilt_ifaces.get(iface)}
        for iface in por_ifaces
        if asbuilt_ifaces.get(iface) != por_ifaces[iface]
    }
    if drifted:
        return {
            "drift_type": "interface_state",
            "drifted_interfaces": drifted,
            "severity_hint": "MEDIUM",
        }
    return None


@_drift_detector("vrrp_role")
def _detect_vrrp_role_drift(por_state: dict, asbuilt_state: dict) -> Optional[dict]:
    """Detect VRRP/HA role mismatches (both nodes claiming master, etc.)."""
    por_role = por_state.get("vrrp_role")
    asbuilt_role = asbuilt_state.get("vrrp_role")
    if por_role and asbuilt_role and por_role != asbuilt_role:
        return {
            "drift_type": "vrrp_role",
            "expected": por_role,
            "observed": asbuilt_role,
            "severity_hint": "HIGH",
        }
    return None


# ---------------------------------------------------------------------------
# Compliance comparison
# ---------------------------------------------------------------------------

def assess_compliance(por_config: str, asbuilt_config: str) -> dict:
    """
    Compare POR (desired) config lines against As-Built (observed).

    Returns:
        {
            "verdict": "COMPLIANT" | "DEGRADED" | "NON_COMPLIANT",
            "missing": [...],
            "extra": [...],
            "compliance_pct": float,
        }
    """
    por_lines = set(por_config.strip().splitlines()) if por_config.strip() else set()
    asbuilt_lines = set(asbuilt_config.strip().splitlines()) if asbuilt_config.strip() else set()

    if not por_lines:
        return {"verdict": "UNKNOWN", "missing": [], "extra": [], "compliance_pct": 0.0}

    missing = sorted(por_lines - asbuilt_lines)
    extra = sorted(asbuilt_lines - por_lines)
    compliance_pct = round(100.0 * (len(por_lines) - len(missing)) / len(por_lines), 1)

    if not missing:
        verdict = "COMPLIANT"
    elif len(missing) < len(por_lines):
        verdict = "DEGRADED"
    else:
        verdict = "NON_COMPLIANT"

    return {
        "verdict": verdict,
        "missing": missing,
        "extra": extra,
        "compliance_pct": compliance_pct,
    }


def detect_drift(drift_type: str, por_state: dict, asbuilt_state: dict) -> Optional[dict]:
    """Run a named drift detector. Returns None if no drift."""
    detector = _DRIFT_DETECTORS.get(drift_type)
    if not detector:
        return None
    return detector(por_state, asbuilt_state)


def trace_root_cause(drift_event: dict, dependency_graph: dict) -> dict:
    """
    Trace root cause via dependency traversal.

    dependency_graph: {node_id: [upstream_node_ids...]}
    Returns the deepest upstream node causing the drift.
    """
    affected = drift_event.get("affected_node", drift_event.get("drift_type", "unknown"))
    chain = [affected]
    visited = {affected}

    current = affected
    depth = 0
    while depth < 10:
        parents = dependency_graph.get(current, [])
        if not parents:
            break
        # Follow first unvisited parent
        next_node = next((p for p in parents if p not in visited), None)
        if next_node is None:
            break
        chain.append(next_node)
        visited.add(next_node)
        current = next_node
        depth += 1

    root = chain[-1]
    return {
        "root_cause": root,
        "causal_chain": chain,
        "depth": len(chain) - 1,
        "confidence": "HIGH" if len(chain) > 1 else "LOW",
    }


# ---------------------------------------------------------------------------
# Agent 7
# ---------------------------------------------------------------------------

class Agent7Assessment(BaseAgent):
    """Compare POR vs As-Built, detect drift, write compliance results."""

    AGENT_ID   = "A7"
    AGENT_NAME = "Assessment"

    def _execute(
        self,
        intent_id: Optional[str] = None,
        assess_space: str = "ibn-loop-inner",
        **kwargs,
    ) -> dict:
        """
        Assess compliance for one intent (or all active intents if none given).

        Returns a list of assessment results.
        """
        intents = self._fetch_intents(intent_id)
        if not intents:
            self._note(assess_space, "No active intents to assess", "observation")
            return {"assessments": []}

        assessments = []
        for intent in intents:
            result = self._assess_intent(intent, assess_space)
            assessments.append(result)

        self._publish("assessment.complete", {
            "assessments": assessments,
            "total": len(assessments),
            "non_compliant": sum(1 for a in assessments if a["verdict"] != "COMPLIANT"),
        })
        return {"assessments": assessments}

    # ------------------------------------------------------------------
    # Intent loading
    # ------------------------------------------------------------------

    def _fetch_intents(self, intent_id: Optional[str]) -> list[dict]:
        if intent_id:
            rows = self._neo4j.run_query(
                "MATCH (i:Intent {intentId: $id}) RETURN i",
                id=intent_id,
            )
            return [dict(r["i"]) for r in rows if "i" in r]
        # All active intents
        rows = self._neo4j.run_query(
            """
            MATCH (i:Intent)
            WHERE i.status IN ['ORCHESTRATED','ACTIVE','INGESTED','TRANSLATED']
            RETURN i
            ORDER BY i.intentId
            LIMIT 50
            """
        )
        return [dict(r["i"]) for r in rows if "i" in r]

    # ------------------------------------------------------------------
    # Per-intent assessment
    # ------------------------------------------------------------------

    def _assess_intent(self, intent: dict, space: str) -> dict:
        intent_id = intent.get("intentId", "unknown")

        # Fetch most recent POR config for each firewall
        por_configs = self._fetch_por_configs(intent_id)
        # Fetch current telemetry
        asbuilt_configs = self._fetch_asbuilt_configs()

        all_verdicts = []
        drift_events = []

        for device_id, por_content in por_configs.items():
            asbuilt_content = asbuilt_configs.get(device_id, "")
            result = assess_compliance(por_content, asbuilt_content)
            result["deviceId"] = device_id
            all_verdicts.append(result)

            if result["verdict"] != "COMPLIANT" and result["missing"]:
                drift_events.append({
                    "deviceId": device_id,
                    "verdict": result["verdict"],
                    "missing_count": len(result["missing"]),
                    "missing_sample": result["missing"][:3],
                })

        # Aggregate verdict
        if not all_verdicts:
            verdict = "UNKNOWN"
            compliance_pct = 0.0
        elif all(v["verdict"] == "COMPLIANT" for v in all_verdicts):
            verdict = "COMPLIANT"
            compliance_pct = 100.0
        elif any(v["verdict"] == "NON_COMPLIANT" for v in all_verdicts):
            verdict = "NON_COMPLIANT"
            compliance_pct = sum(v.get("compliance_pct", 0) for v in all_verdicts) / len(all_verdicts)
        else:
            verdict = "DEGRADED"
            compliance_pct = sum(v.get("compliance_pct", 0) for v in all_verdicts) / len(all_verdicts)

        # Write ComplianceAssessment to L6
        assessment_id = self._write_assessment(intent_id, verdict, compliance_pct, drift_events)

        # Create Incident if non-compliant
        incident_id = None
        if verdict != "COMPLIANT":
            incident_id = self._write_incident(intent_id, assessment_id, verdict, drift_events)
            self._update_intent_status(intent_id, "NON_COMPLIANT")

        # Live-Memory note
        self._note(
            space,
            f"[A7] {intent_id} → {verdict} ({compliance_pct:.0f}% compliant) "
            f"| drift on {len(drift_events)} device(s)"
            + (f" | incident: {incident_id}" if incident_id else ""),
            "observation" if verdict == "COMPLIANT" else "issue",
        )

        return {
            "intentId": intent_id,
            "verdict": verdict,
            "compliancePct": compliance_pct,
            "assessmentId": assessment_id,
            "incidentId": incident_id,
            "driftEvents": drift_events,
        }

    # ------------------------------------------------------------------
    # Neo4j reads
    # ------------------------------------------------------------------

    def _fetch_por_configs(self, intent_id: str) -> dict[str, str]:
        """Return {deviceId: content} for the latest CANDIDATE/POR configs."""
        rows = self._neo4j.run_query(
            """
            MATCH (c:Configuration)
            WHERE c.modelState IN ['CANDIDATE','POR','DEPLOYED']
            RETURN c.deviceId AS deviceId, c.content AS content, c.createdAt AS ts
            ORDER BY c.createdAt DESC
            """
        )
        # Keep most recent per device
        seen: dict[str, str] = {}
        for r in rows:
            did = r.get("deviceId")
            if did and did not in seen and r.get("content"):
                seen[did] = r["content"]
        return seen

    def _fetch_asbuilt_configs(self) -> dict[str, str]:
        """Return {deviceId: running_config} from AS_BUILT Telemetry nodes."""
        rows = self._neo4j.run_query(
            """
            MATCH (t:Telemetry {metric: 'running_config'})
            WHERE t.modelState = 'AS_BUILT'
            RETURN t.deviceId AS deviceId, t.value AS content
            ORDER BY t.timestamp DESC
            """
        )
        seen: dict[str, str] = {}
        for r in rows:
            did = r.get("deviceId")
            if did and did not in seen:
                seen[did] = r.get("content", "")
        return seen

    # ------------------------------------------------------------------
    # Neo4j writes
    # ------------------------------------------------------------------

    def _write_assessment(self, intent_id: str, verdict: str,
                          compliance_pct: float, drift_events: list) -> str:
        assessment_id = f"CA-{uuid.uuid4().hex[:8].upper()}"
        self._neo4j.run_query(
            """
            MERGE (ca:ComplianceAssessment {assessmentId: $aId})
            SET ca.intentId      = $intentId,
                ca.verdict       = $verdict,
                ca.compliancePct = $pct,
                ca.driftCount    = $driftCount,
                ca.modelState    = 'AS_BUILT',
                ca.assessedAt    = datetime()
            WITH ca
            OPTIONAL MATCH (i:Intent {intentId: $intentId})
            FOREACH (_ IN CASE WHEN i IS NOT NULL THEN [1] ELSE [] END |
                MERGE (ca)-[:ASSESSES]->(i)
            )
            """,
            aId=assessment_id,
            intentId=intent_id,
            verdict=verdict,
            pct=compliance_pct,
            driftCount=len(drift_events),
        )
        return assessment_id

    def _write_incident(self, intent_id: str, assessment_id: str,
                        verdict: str, drift_events: list) -> str:
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        severity = (
            "CRITICAL" if len(drift_events) >= 3 else
            "HIGH"     if verdict == "NON_COMPLIANT" else
            "MEDIUM"
        )
        self._neo4j.run_query(
            """
            MERGE (inc:Incident {incidentId: $incId})
            SET inc.intentId     = $intentId,
                inc.assessmentId = $aId,
                inc.severity     = $severity,
                inc.driftCount   = $driftCount,
                inc.modelState   = 'AS_BUILT',
                inc.createdAt    = datetime()
            """,
            incId=incident_id,
            intentId=intent_id,
            aId=assessment_id,
            severity=severity,
            driftCount=len(drift_events),
        )
        return incident_id

    def _update_intent_status(self, intent_id: str, status: str) -> None:
        self._neo4j.run_query(
            """
            MATCH (i:Intent {intentId: $id})
            SET i.complianceStatus = $status
            """,
            id=intent_id,
            status=status,
        )
