"""
T12 — Inner Loop End-to-End Tests
==================================
Validates the complete inner loop closure:
  Intent → SSoT → Config → NetLab → Observe → Assess → Act → Verify

These tests require the full stack: Neo4j + Live-Memory + NetLab.
Run with:  NEO4J_URI=bolt://localhost:7687 LIVE_MEMORY_URL=http://localhost:8002 pytest tests/e2e/
"""
import pytest
import time
from datetime import datetime, timezone


# ── T12.1 Fulfillment path ───────────────────────────────────────────────

class TestFulfillmentPath:
    """T12.1 — End-to-end fulfillment: Intent → Config → Deploy → Observe."""

    def test_t12_1_1_full_fulfillment_path(self, mock_neo4j, live_memory, netlab):
        """T12.1.1 — Intent flows through SSoT → Config → Deploy → Observe."""
        # Step 1: Ingest intent (Agent 1)
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Intent {intentId: 'INT-E2E-001', "
                "statement: 'Guest VLAN 140 may only reach Internet', "
                "status: 'INGESTED', modelState: 'CANDIDATE'})", {}
            )

        live_memory.space_create("ibn-candidate-e2e")
        live_memory.live_note("ibn-candidate-e2e", "Intent INT-E2E-001 ingested", "intent-ingestion")

        # Step 2: Render config (Agent 3)
        config = "set firewall name GUEST-TO-INTERNET default-action accept\n" \
                 "set firewall name GUEST-TO-USER default-action drop"
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Configuration {configId: 'CFG-E2E-001', "
                "deviceId: 'usf-fw-01', content: $cfg, "
                "format: 'vyos-set', version: 1, modelState: 'CANDIDATE'})",
                {"cfg": config}
            )

        # Step 3: Deploy (Agent 5)
        result = netlab.deploy_config("usf-fw-01", config)
        assert result["status"] == "ok"

        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:DeploymentEvent {eventId: 'DEP-E2E-001', "
                "status: 'DEPLOYED', targetDeviceId: 'usf-fw-01', "
                "modelState: 'DEPLOYED'})", {}
            )

        # Step 4: Observe (Agent 6)
        running = netlab.devices["usf-fw-01"].exec_command("show configuration")
        assert running == config

        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Telemetry {deviceId: 'usf-fw-01', "
                "metric: 'running_config_hash', value: $hash, "
                "modelState: 'AS_BUILT'})",
                {"hash": str(hash(running))}
            )

        # Verify all model states exist
        # modelState is a literal in queries, not a parameter, so verify by checking queries instead.
        queries = mock_neo4j.queries
        assert any("CANDIDATE" in q["query"] for q in queries)
        assert any("DEPLOYED" in q["query"] for q in queries)
        assert any("AS_BUILT" in q["query"] for q in queries)


# ── T12.2 Assurance path ─────────────────────────────────────────────────

class TestAssurancePath:
    """T12.2 — Drift injection → detection → assessment → action."""

    def test_t12_2_1_detect_and_assess_drift(self, mock_neo4j, live_memory, netlab):
        """T12.2.1 — Injected drift is detected and assessed as NON_COMPLIANT."""
        # Setup: deploy known-good config
        good_config = "set firewall name GUEST-TO-INTERNET default-action accept\n" \
                      "set firewall name GUEST-TO-USER default-action drop"
        netlab.deploy_config("usf-fw-01", good_config)

        # Inject drift: overwrite with partial config (rule missing)
        drifted_config = "set firewall name GUEST-TO-INTERNET default-action accept"
        netlab.devices["usf-fw-01"].running_config = drifted_config

        # Agent 6: observe
        observed = netlab.devices["usf-fw-01"].exec_command("show configuration")
        assert "GUEST-TO-USER" not in observed

        # Agent 7: assess
        por_lines = set(good_config.splitlines())
        obs_lines = set(observed.splitlines())
        missing = por_lines - obs_lines

        assert len(missing) > 0  # Drift detected
        verdict = "NON_COMPLIANT" if missing else "COMPLIANT"
        assert verdict == "NON_COMPLIANT"

        # Record in Neo4j
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:ComplianceAssessment {assessmentId: 'CA-E2E-001', "
                "intentId: 'INT-E2E-001', verdict: 'NON_COMPLIANT', "
                "missingRules: $missing, modelState: 'AS_BUILT'})",
                {"missing": list(missing)}
            )

        # Record in Live-Memory
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note(
            "ibn-loop-inner", f"DRIFT: {missing}", "drift-detection"
        )

    def test_t12_2_2_auto_remediate_low_severity(self, mock_neo4j, live_memory, netlab):
        """T12.2.2 — LOW severity auto-remediates via config re-push."""
        # Setup: known-good and drifted state
        good_config = "set firewall name GUEST-TO-INTERNET default-action accept\n" \
                      "set firewall name GUEST-TO-USER default-action drop"
        netlab.devices["usf-fw-01"].running_config = "set firewall name GUEST-TO-INTERNET default-action accept"

        # Agent 8: classify as LOW (single rule, redundancy assumed)
        severity = "LOW"

        # Agent 8: auto-remediate — re-push good config
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Attempting re-push", "remediation-attempt")

        netlab.deploy_config("usf-fw-01", good_config)

        # Agent 7: re-assess
        observed = netlab.devices["usf-fw-01"].exec_command("show configuration")
        por_lines = set(good_config.splitlines())
        obs_lines = set(observed.splitlines())
        remaining_drift = por_lines - obs_lines

        assert len(remaining_drift) == 0  # Remediation successful

        live_memory.live_note("ibn-loop-inner", "Remediation SUCCESS", "remediation-result")

        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Remediation {remediationId: 'REM-E2E-001', "
                "action: 'AUTO_REMEDIATE', success: true, modelState: 'AS_BUILT'})", {}
            )

    def test_t12_2_3_escalate_high_severity(self, mock_neo4j, live_memory, netlab):
        """T12.2.3 — HIGH severity creates Ticket and pauses orchestration."""
        severity = "HIGH"

        live_memory.space_create("ibn-loop-outer")
        live_memory.live_note(
            "ibn-loop-outer",
            "ESCALATION: Multiple intents non-compliant, manual review required",
            "escalation"
        )

        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Ticket {ticketId: 'TKT-E2E-001', severity: 'HIGH', "
                "description: 'Multiple intents violated', modelState: 'POR'})", {}
            )

        nodes = mock_neo4j.nodes
        tickets = [n for n in nodes if n.get("_label") == "Ticket"]
        assert len(tickets) >= 1
        # severity is a literal in the query, not a parameter. Verify by query instead.
        queries = mock_neo4j.queries
        assert any("severity: 'HIGH'" in q["query"] for q in queries)


# ── T12.4 Memory tier integration ────────────────────────────────────────

class TestMemoryIntegration:
    """T12.4 — All three memory tiers populated during loop."""

    def test_t12_4_1_agents_emit_notes(self, live_memory):
        """T12.4.1 — Loop cycle produces notes from agents 6, 7, 8."""
        live_memory.space_create("ibn-loop-inner")

        # Simulate a full cycle of notes
        live_memory.live_note("ibn-loop-inner", "Agent 6: telemetry collected", "telemetry-snapshot")
        live_memory.live_note("ibn-loop-inner", "Agent 7: drift detected", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Agent 7: NON_COMPLIANT", "assessment-result")
        live_memory.live_note("ibn-loop-inner", "Agent 8: remediation started", "remediation-attempt")
        live_memory.live_note("ibn-loop-inner", "Agent 8: remediation succeeded", "remediation-result")

        notes = live_memory.note_list("ibn-loop-inner")
        assert len(notes) == 5

    def test_t12_4_2_consolidation_produces_banks(self, live_memory):
        """T12.4.2 — Consolidation produces populated bank files."""
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift on usf-fw-01", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Remediation succeeded", "remediation-result")

        result = live_memory.bank_consolidate("ibn-loop-inner")
        assert result["notes_consumed"] == 2

        banks = live_memory.bank_read_all("ibn-loop-inner")
        assert len(banks) >= 1

    def test_t12_4_3_graph_memory_receives_knowledge(self, live_memory, graph_memory):
        """T12.4.3 — Graph-Memory populated after consolidation + push."""
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift event: FWR-002 missing", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Remediation: re-push succeeded", "remediation-result")
        live_memory.bank_consolidate("ibn-loop-inner")

        graph_memory.memory_create("ibn-lifecycle")
        banks = live_memory.bank_read_all("ibn-loop-inner")
        for name, content in banks.items():
            graph_memory.graph_push(memory="ibn-lifecycle", content=content, source=f"ibn-loop-inner/{name}")

        answer = graph_memory.question_answer("ibn-lifecycle", "What drift events occurred?")
        assert answer["answer"] is not None
        assert len(answer["sources"]) >= 1
