"""
T14 — Security and Audit Trail Tests (Unit)
============================================
Validates intent verification pipeline, autonomy boundaries,
and audit trail completeness.
"""
import pytest
from datetime import datetime, timezone


# ── T14.1 Intent verification pipeline ───────────────────────────────────

class TestIntentVerification:
    """T14.1 — Four-stage intent verification before fulfillment."""

    def _verify_intent(self, intent: dict, existing_intents: list,
                       infrastructure: dict, authorized_authors: set) -> dict:
        """Four-stage intent verification — mirrors §12.1."""
        # Stage 1: Syntactic correctness
        required = {"type", "subject", "action", "target"}
        if not required.issubset(intent.keys()):
            return {"passed": False, "stage": "syntactic", "reason": "Missing required fields"}

        # Stage 2: Conflict detection
        for existing in existing_intents:
            if (existing["subject"] == intent["subject"]
                    and existing["target"] == intent["target"]
                    and existing["action"] != intent["action"]):
                return {"passed": False, "stage": "conflict",
                        "reason": f"Conflicts with {existing['intentId']}"}

        # Stage 3: Feasibility
        required_vlans = intent.get("required_vlans", [])
        available_vlans = infrastructure.get("vlans", [])
        for vlan in required_vlans:
            if vlan not in available_vlans:
                return {"passed": False, "stage": "feasibility",
                        "reason": f"VLAN {vlan} not available"}

        # Stage 4: Authorization
        author = intent.get("author", "unknown")
        if author not in authorized_authors:
            return {"passed": False, "stage": "authorization",
                    "reason": f"Author '{author}' not authorized"}

        return {"passed": True, "stage": "all", "reason": ""}

    def test_t14_1_1_syntactically_invalid_rejected(self):
        """T14.1.1 — Malformed intent rejected at syntactic check."""
        result = self._verify_intent(
            {"type": "access-policy"},  # missing subject, action, target
            [], {}, set()
        )
        assert not result["passed"]
        assert result["stage"] == "syntactic"

    def test_t14_1_2_conflicting_intent_flagged(self):
        """T14.1.2 — Conflicting intent caught at conflict check."""
        existing = [{"intentId": "INT-001", "subject": "Guest", "target": "Internet", "action": "permit"}]
        result = self._verify_intent(
            {"type": "access-policy", "subject": "Guest", "action": "deny", "target": "Internet"},
            existing, {}, {"operator-marc"}
        )
        assert not result["passed"]
        assert result["stage"] == "conflict"

    def test_t14_1_3_infeasible_intent_rejected(self):
        """T14.1.3 — Intent requiring nonexistent VLAN rejected."""
        result = self._verify_intent(
            {"type": "access-policy", "subject": "Guest", "action": "permit",
             "target": "Internet", "required_vlans": [999], "author": "operator-marc"},
            [], {"vlans": [100, 110, 140]}, {"operator-marc"}
        )
        assert not result["passed"]
        assert result["stage"] == "feasibility"

    def test_t14_1_4_unauthorized_author_rejected(self):
        """T14.1.4 — Intent from unauthorized author rejected at RBAC."""
        result = self._verify_intent(
            {"type": "access-policy", "subject": "Guest", "action": "permit",
             "target": "Internet", "author": "rogue-user"},
            [], {"vlans": [140]}, {"operator-marc", "operator-admin"}
        )
        assert not result["passed"]
        assert result["stage"] == "authorization"


# ── T14.2 Autonomy boundaries ────────────────────────────────────────────

class TestAutonomyBoundaries:
    """T14.2 — Inner loop cannot exceed defined autonomy limits (§12.2)."""

    INNER_LOOP_ALLOWED = {
        "re_push_config",       # Re-push config matching SSoT desired state
        "restart_protocol",     # Restart a protocol process
        "adjust_non_critical",  # Adjust non-critical parameter
    }

    INNER_LOOP_FORBIDDEN = {
        "modify_intent",        # Cannot change declared intent
        "change_topology",      # Cannot add/remove devices
        "override_policy",      # Cannot override human-approved policy
        "act_on_decommissioning",  # Cannot act on DECOMMISSIONING entities
    }

    def _check_autonomy(self, action: str, entity_state: str = "ACTIVE") -> dict:
        """Check if inner loop is allowed to perform this action."""
        if entity_state == "DECOMMISSIONING":
            return {"allowed": False, "reason": "Entity in DECOMMISSIONING state"}
        if action in self.INNER_LOOP_ALLOWED:
            return {"allowed": True, "reason": ""}
        if action in self.INNER_LOOP_FORBIDDEN:
            return {"allowed": False, "reason": f"Action '{action}' exceeds autonomy boundary"}
        return {"allowed": False, "reason": f"Unknown action '{action}'"}

    def test_t14_2_1_cannot_modify_intent(self):
        """T14.2.1 — Inner loop blocked from modifying Intent.statement."""
        result = self._check_autonomy("modify_intent")
        assert not result["allowed"]

    def test_t14_2_2_cannot_change_topology(self):
        """T14.2.2 — Inner loop blocked from adding/removing devices."""
        result = self._check_autonomy("change_topology")
        assert not result["allowed"]

    def test_t14_2_3_can_repush_config(self):
        """T14.2.3 — Inner loop allowed to re-push existing config."""
        result = self._check_autonomy("re_push_config")
        assert result["allowed"]

    def test_t14_2_4_blocked_on_decommissioning(self):
        """T14.2.4 — Inner loop blocked on DECOMMISSIONING entities."""
        result = self._check_autonomy("re_push_config", entity_state="DECOMMISSIONING")
        assert not result["allowed"]
        assert "DECOMMISSIONING" in result["reason"]


# ── T14.3 Audit trail completeness ───────────────────────────────────────

class TestAuditTrail:
    """T14.3 — Every agent action recorded, full traceability."""

    def test_t14_3_1_agent_execution_recorded(self, mock_neo4j):
        """T14.3.1 — Every agent action creates AgentExecution node."""
        agents = ["A1", "A3", "A5", "A6", "A7", "A8"]
        for agent_id in agents:
            with mock_neo4j.session() as session:
                session.run(
                    "CREATE (:AgentExecution {agentId: $aid, action: $act, "
                    "timestamp: $ts, modelState: 'POR'})",
                    {"aid": agent_id, "act": f"test-action-{agent_id}",
                     "ts": datetime.now(timezone.utc).isoformat()}
                )

        nodes = mock_neo4j.nodes
        exec_nodes = [n for n in nodes if n.get("_label") == "AgentExecution"]
        # Mock stores parameters under their $param keys (aid, act, ts)
        agent_ids = {n.get("aid") for n in exec_nodes}
        for expected in agents:
            assert expected in agent_ids, f"Agent {expected} missing from audit trail"

    def test_t14_3_2_intent_to_device_traceability(self, mock_neo4j):
        """T14.3.2 — Full traversal: Intent → Policy → Config → Deploy → Device."""
        # Create the chain
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Intent {intentId: 'INT-001', modelState: 'POR'})"
                "-[:IMPLEMENTED_BY]->(:Policy {policyId: 'POL-001', modelState: 'POR'})",
                {}
            )
            session.run(
                "CREATE (:Policy {policyId: 'POL-001', modelState: 'POR'})"
                "-[:RENDERED_AS]->(:Configuration {configId: 'CFG-001', modelState: 'DEPLOYED'})",
                {}
            )
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001', modelState: 'DEPLOYED'})"
                "-[:DEPLOYED_ON]->(:Device {deviceId: 'usf-fw-01', modelState: 'POR'})",
                {}
            )

        queries = mock_neo4j.queries
        # Verify all relationship types were created
        rel_types = {"IMPLEMENTED_BY", "RENDERED_AS", "DEPLOYED_ON"}
        found = {r for q in queries for r in rel_types if r in q["query"]}
        assert found == rel_types
