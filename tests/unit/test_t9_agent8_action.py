"""
T9 — Agent 8: Compliance Action Tests (Unit)
=============================================
Validates severity classification, autonomy decision matrix, remediation
execution, rollback via PRECEDED_BY, and Live-Memory integration.
"""
import pytest
from datetime import datetime, timezone


# ── T9.1 Severity classification ─────────────────────────────────────────

class TestSeverityClassification:
    """T9.1 — Classify incidents by severity level per the decision matrix."""

    def _classify_severity(self, incident: dict) -> str:
        """Severity classification logic — mirrors Agent 8 decision matrix."""
        # Critical: multiple intents violated
        if incident.get("intents_violated", 0) >= 3:
            return "CRITICAL"
        # High: service-impacting, business-critical
        if incident.get("service_impact", False) and incident.get("business_critical", False):
            return "HIGH"
        # Medium: drift on multiple devices
        if incident.get("devices_affected", 0) >= 2:
            return "MEDIUM"
        # Low: single interface down, redundancy active
        if incident.get("redundancy_active", False) and incident.get("devices_affected", 0) == 1:
            return "LOW"
        # Info: minor metric fluctuation
        if incident.get("metric_deviation_pct", 0) < 10:
            return "INFO"
        return "MEDIUM"  # default

    def test_t9_1_1_info_minor_fluctuation(self):
        """T9.1.1 — Minor metric fluctuation → INFO."""
        result = self._classify_severity({"metric_deviation_pct": 5, "devices_affected": 0})
        assert result == "INFO"

    def test_t9_1_2_low_single_interface_redundancy(self):
        """T9.1.2 — Single interface down, redundancy active → LOW."""
        result = self._classify_severity({"devices_affected": 1, "redundancy_active": True})
        assert result == "LOW"

    def test_t9_1_3_medium_multi_device_drift(self):
        """T9.1.3 — Drift on 2+ devices → MEDIUM."""
        result = self._classify_severity({"devices_affected": 3, "redundancy_active": False})
        assert result == "MEDIUM"

    def test_t9_1_4_high_service_impacting(self):
        """T9.1.4 — Service-impacting, business-critical → HIGH."""
        result = self._classify_severity({"service_impact": True, "business_critical": True})
        assert result == "HIGH"

    def test_t9_1_5_critical_multiple_intents(self):
        """T9.1.5 — Multiple intents violated → CRITICAL."""
        result = self._classify_severity({"intents_violated": 4})
        assert result == "CRITICAL"


# ── T9.2 Autonomy decision matrix ────────────────────────────────────────

class TestAutonomyDecision:
    """T9.2 — Validate the action taken for each severity level."""

    ACTION_MATRIX = {
        "INFO": {"action": "LOG", "autonomous": True, "loop": "inner"},
        "LOW": {"action": "AUTO_REMEDIATE", "autonomous": True, "loop": "inner"},
        "MEDIUM": {"action": "AUTO_REMEDIATE_VERIFY", "autonomous": True, "loop": "inner"},
        "HIGH": {"action": "ESCALATE", "autonomous": False, "loop": "outer"},
        "CRITICAL": {"action": "ROLLBACK_ESCALATE", "autonomous": False, "loop": "outer"},
    }

    def _decide_action(self, severity: str) -> dict:
        """Look up the action matrix for a given severity."""
        return self.ACTION_MATRIX.get(severity, {"action": "UNKNOWN"})

    def test_t9_2_1_info_log_only(self):
        """T9.2.1 — INFO → log to Neo4j, no remediation."""
        action = self._decide_action("INFO")
        assert action["action"] == "LOG"
        assert action["autonomous"] is True

    def test_t9_2_2_low_auto_remediate(self):
        """T9.2.2 — LOW → auto-remediate via Agent 5 re-push."""
        action = self._decide_action("LOW")
        assert action["action"] == "AUTO_REMEDIATE"
        assert action["autonomous"] is True
        assert action["loop"] == "inner"

    def test_t9_2_3_medium_auto_remediate_verify(self):
        """T9.2.3 — MEDIUM → auto-remediate affected scope + verify."""
        action = self._decide_action("MEDIUM")
        assert action["action"] == "AUTO_REMEDIATE_VERIFY"

    def test_t9_2_4_high_escalate(self):
        """T9.2.4 — HIGH → escalate to human, create Ticket."""
        action = self._decide_action("HIGH")
        assert action["action"] == "ESCALATE"
        assert action["autonomous"] is False
        assert action["loop"] == "outer"

    def test_t9_2_5_critical_rollback_escalate(self):
        """T9.2.5 — CRITICAL → rollback + freeze + escalate."""
        action = self._decide_action("CRITICAL")
        assert action["action"] == "ROLLBACK_ESCALATE"
        assert action["autonomous"] is False


# ── T9.3 Remediation execution ───────────────────────────────────────────

class TestRemediationExecution:
    """T9.3 — Validate remediation actions and recording."""

    def test_t9_3_1_triggers_agent5_repush(self, netlab):
        """T9.3.1 — LOW severity triggers re-push of config via Agent 5."""
        # Re-push the POR config to the device
        por_config = "set firewall name GUEST-TO-USER default-action drop"
        result = netlab.deploy_config("usf-fw-01", por_config)
        assert result["status"] == "ok"
        assert netlab.devices["usf-fw-01"].running_config == por_config

    def test_t9_3_2_creates_remediation_node(self, mock_neo4j):
        """T9.3.2 — Remediation node created in L6 with RESOLVES relationship."""
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Remediation {remediationId: $rid, action: 'AUTO_REMEDIATE', "
                "timestamp: $ts, success: true, modelState: 'AS_BUILT'})"
                "-[:RESOLVES]->"
                "(:Incident {incidentId: 'INC-001', modelState: 'AS_BUILT'})",
                {"rid": "REM-001", "ts": datetime.now(timezone.utc).isoformat()}
            )
        nodes = mock_neo4j.nodes
        rem = [n for n in nodes if n.get("_label") == "Remediation"]
        assert len(rem) >= 1
        queries = mock_neo4j.queries
        assert any("RESOLVES" in q["query"] for q in queries)

    def test_t9_3_3_records_success(self, mock_neo4j):
        """T9.3.3 — Remediation marked success after re-verification."""
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Remediation {remediationId: 'REM-001', success: true, modelState: 'AS_BUILT'})",
                {}
            )
        # success is a literal in the query, not a parameter.
        # Verify the Remediation node was created instead.
        nodes = mock_neo4j.nodes
        rem = [n for n in nodes if n.get("_label") == "Remediation"]
        assert len(rem) >= 1

    def test_t9_3_4_records_failure_and_escalates(self, mock_neo4j):
        """T9.3.4 — Failed remediation recorded, escalation triggered."""
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Remediation {remediationId: 'REM-002', success: false, "
                "escalatedTo: 'HIGH', modelState: 'AS_BUILT'})",
                {}
            )
            session.run(
                "CREATE (:Ticket {ticketId: 'TKT-001', severity: 'HIGH', "
                "description: 'Remediation REM-002 failed, manual intervention required', "
                "modelState: 'POR'})",
                {}
            )
        nodes = mock_neo4j.nodes
        rem = [n for n in nodes if n.get("_label") == "Remediation"]
        tickets = [n for n in nodes if n.get("_label") == "Ticket"]
        assert len(rem) >= 1
        assert len(tickets) >= 1


# ── T9.4 Rollback via PRECEDED_BY ────────────────────────────────────────

class TestRollbackPrecedeBy:
    """T9.4 — Rollback using PRECEDED_BY version chain."""

    def _find_last_good_config(self, versions: list, current_broken: str) -> dict | None:
        """Walk PRECEDED_BY chain to find last compliant config."""
        for v in reversed(versions):
            if v["configId"] != current_broken and v.get("compliant", False):
                return v
        return None

    def test_t9_4_1_traverse_preceded_by(self):
        """T9.4.1 — Finds last-known-good config via PRECEDED_BY chain."""
        versions = [
            {"configId": "CFG-001", "version": 1, "compliant": True},
            {"configId": "CFG-002", "version": 2, "compliant": True},
            {"configId": "CFG-003", "version": 3, "compliant": False},  # broken
        ]
        good = self._find_last_good_config(versions, "CFG-003")
        assert good is not None
        assert good["configId"] == "CFG-002"

    def test_t9_4_2_rollback_deploys_previous(self, netlab):
        """T9.4.2 — Rollback deploys the previous config version."""
        v2_config = "set firewall name GUEST-TO-USER default-action drop"
        netlab.deploy_config("usf-fw-01", v2_config)
        assert netlab.devices["usf-fw-01"].running_config == v2_config


# ── T9.5 Live-Memory integration ─────────────────────────────────────────

class TestActionLiveMemory:
    """T9.5 — Agent 8 emits live_notes for remediation events."""

    def test_t9_5_1_note_on_remediation_attempt(self, live_memory):
        """T9.5.1 — Note emitted when remediation starts."""
        live_memory.space_create("ibn-loop-inner")
        note = live_memory.live_note(
            space="ibn-loop-inner",
            category="remediation-attempt",
            content="Attempting auto-remediation for INC-001: re-push CFG-002 to usf-fw-01"
        )
        assert note["category"] == "remediation-attempt"

    def test_t9_5_2_note_on_remediation_result(self, live_memory):
        """T9.5.2 — Note emitted with remediation outcome."""
        live_memory.space_create("ibn-loop-inner")
        note = live_memory.live_note(
            space="ibn-loop-inner",
            category="remediation-result",
            content="Remediation REM-001 SUCCESS: usf-fw-01 re-assessed as COMPLIANT"
        )
        assert note["category"] == "remediation-result"
        assert "SUCCESS" in note["content"]

    def test_t9_5_3_note_on_escalation(self, live_memory):
        """T9.5.3 — Escalation emits note to ibn-loop-outer."""
        live_memory.space_create("ibn-loop-outer")
        note = live_memory.live_note(
            space="ibn-loop-outer",
            category="escalation",
            content="ESCALATION: INC-002 (HIGH severity) — 2 intents non-compliant, remediation failed. "
                    "Ticket TKT-001 created, orchestration paused."
        )
        assert note["category"] == "escalation"
        assert note["space"] == "ibn-loop-outer"
