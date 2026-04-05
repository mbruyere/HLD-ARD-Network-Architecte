"""
T13 — Event Bus and Agent Communication Tests (Unit)
=====================================================
Validates that agents communicate through the event bus correctly,
events are routed to the right agents, and ordering is maintained.
"""
import pytest


# ── T13.1 Event routing ──────────────────────────────────────────────────

class TestEventRouting:
    """T13.1 — Events routed from producers to correct consumer agents."""

    def test_t13_1_1_intent_creation_triggers_agent2(self, event_bus):
        """T13.1.1 — New Intent node emits intent.created → Agent 2."""
        received = []
        event_bus.subscribe("intent.created", lambda e: received.append(e))

        event_bus.publish("intent.created", {
            "intentId": "INT-001", "status": "INGESTED", "modelState": "CANDIDATE"
        })

        assert len(received) == 1
        assert received[0]["payload"]["intentId"] == "INT-001"

    def test_t13_1_2_policy_creation_triggers_agent3(self, event_bus):
        """T13.1.2 — Policy approved emits policy.approved → Agent 3."""
        received = []
        event_bus.subscribe("policy.approved", lambda e: received.append(e))

        event_bus.publish("policy.approved", {
            "policyId": "POL-001", "intentId": "INT-001"
        })

        assert len(received) == 1

    def test_t13_1_3_config_ready_triggers_agent5(self, event_bus):
        """T13.1.3 — Configuration ready emits config.ready → Agent 5."""
        received = []
        event_bus.subscribe("config.ready", lambda e: received.append(e))

        event_bus.publish("config.ready", {
            "configId": "CFG-001", "deviceId": "usf-fw-01"
        })

        assert len(received) == 1

    def test_t13_1_4_deployment_complete_triggers_agent6(self, event_bus):
        """T13.1.4 — Deployment complete emits deployment.complete → Agent 6."""
        received = []
        event_bus.subscribe("deployment.complete", lambda e: received.append(e))

        event_bus.publish("deployment.complete", {
            "eventId": "DEP-001", "status": "DEPLOYED", "devices": ["usf-fw-01"]
        })

        assert len(received) == 1

    def test_t13_1_5_assessment_noncompliant_triggers_agent8(self, event_bus):
        """T13.1.5 — NON_COMPLIANT assessment emits event → Agent 8."""
        received = []
        event_bus.subscribe("assessment.non_compliant", lambda e: received.append(e))

        event_bus.publish("assessment.non_compliant", {
            "assessmentId": "CA-001", "intentId": "INT-001", "verdict": "NON_COMPLIANT"
        })

        assert len(received) == 1
        assert received[0]["payload"]["verdict"] == "NON_COMPLIANT"

    def test_t13_1_6_remediation_triggers_agent5_repush(self, event_bus):
        """T13.1.6 — Remediation action emits re-orchestrate → Agent 5."""
        received = []
        event_bus.subscribe("remediation.re_orchestrate", lambda e: received.append(e))

        event_bus.publish("remediation.re_orchestrate", {
            "remediationId": "REM-001", "configId": "CFG-002", "deviceId": "usf-fw-01"
        })

        assert len(received) == 1


# ── T13.2 Event ordering ─────────────────────────────────────────────────

class TestEventOrdering:
    """T13.2 — Events are processed in causal order with no duplicates."""

    def test_t13_2_1_causal_order_preserved(self, event_bus):
        """T13.2.1 — Events for same intent processed sequentially."""
        order = []
        event_bus.subscribe("intent.created", lambda e: order.append("created"))
        event_bus.subscribe("policy.approved", lambda e: order.append("approved"))
        event_bus.subscribe("config.ready", lambda e: order.append("ready"))
        event_bus.subscribe("deployment.complete", lambda e: order.append("deployed"))

        # Publish in causal order
        event_bus.publish("intent.created", {"intentId": "INT-001"})
        event_bus.publish("policy.approved", {"policyId": "POL-001"})
        event_bus.publish("config.ready", {"configId": "CFG-001"})
        event_bus.publish("deployment.complete", {"eventId": "DEP-001"})

        assert order == ["created", "approved", "ready", "deployed"]

    def test_t13_2_2_no_duplicate_delivery(self, event_bus):
        """T13.2.2 — Single write produces exactly one event."""
        received = []
        event_bus.subscribe("intent.created", lambda e: received.append(e))

        event_bus.publish("intent.created", {"intentId": "INT-001"})

        assert len(received) == 1
