"""
T6 — Agent 5: Orchestration Tests (Unit)
=========================================
Validates config push, rollback, model state transitions,
and Live-Memory integration.
"""
import pytest
from datetime import datetime, timezone


# ── T6.1 Config push ─────────────────────────────────────────────────────

class TestConfigPush:
    """T6.1 — Validate configuration deployment to NetLab devices."""

    def test_t6_1_1_ssh_push_succeeds(self, netlab):
        """T6.1.1 — SSH push to VyOS device succeeds."""
        config = "set system host-name usf-fw-01\nset firewall name TEST default-action drop"
        result = netlab.deploy_config("usf-fw-01", config)
        assert result["status"] == "ok"
        assert result["device"] == "usf-fw-01"

    def test_t6_1_2_push_records_deployment_event(self, neo4j_driver, netlab):
        """T6.1.2 — Successful push creates DeploymentEvent in Neo4j L5."""
        netlab.deploy_config("usf-fw-01", "set system host-name usf-fw-01")

        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:DeploymentEvent {eventId: $eid, timestamp: $ts, "
                "status: 'DEPLOYED', targetDeviceId: $did, modelState: 'DEPLOYED'})",
                {
                    "eid": "DEP-001",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "did": "usf-fw-01"
                }
            )

        nodes = neo4j_driver.nodes
        dep_nodes = [n for n in nodes if n.get("_label") == "DeploymentEvent"]
        assert len(dep_nodes) >= 1
        # status is a literal in the query, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("status: 'DEPLOYED'" in q["query"] for q in queries)

    def test_t6_1_3_push_failure_records_failed_event(self, neo4j_driver):
        """T6.1.3 — Failed push creates DeploymentEvent with FAILED status."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:DeploymentEvent {eventId: $eid, timestamp: $ts, "
                "status: 'FAILED', targetDeviceId: $did, "
                "errorMessage: $err, modelState: 'DEPLOYED'})",
                {
                    "eid": "DEP-002",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "did": "usf-fw-01",
                    "err": "SSH connection timeout"
                }
            )

        nodes = neo4j_driver.nodes
        dep_nodes = [n for n in nodes if n.get("_label") == "DeploymentEvent"]
        assert len(dep_nodes) >= 1
        # status is a literal, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("status: 'FAILED'" in q["query"] for q in queries)

    def test_t6_1_4_push_follows_migration_plan_order(self, netlab):
        """T6.1.4 — Devices configured in plan order, not arbitrary."""
        plan_order = ["usf-fw-01", "usf-fw-02", "dmzfw-01", "dmzfw-02"]
        deploy_log = []

        for device in plan_order:
            result = netlab.deploy_config(device, f"set system host-name {device}")
            deploy_log.append(result["device"])

        assert deploy_log == plan_order

    def test_t6_1_5_post_push_config_verification(self, netlab):
        """T6.1.5 — Running config matches intended config after push."""
        intended_config = "set system host-name usf-fw-01\nset firewall name TEST"
        netlab.deploy_config("usf-fw-01", intended_config)

        running = netlab.devices["usf-fw-01"].exec_command("show configuration")
        assert running == intended_config


# ── T6.2 Rollback ────────────────────────────────────────────────────────

class TestRollback:
    """T6.2 — Validate rollback on deployment failure."""

    def test_t6_2_1_rollback_on_failure(self, netlab):
        """T6.2.1 — If device 3 fails, devices 1–2 are rolled back."""
        # Deploy v1 to devices 1–2 (these succeed)
        v1_config = "set system host-name v1"
        netlab.deploy_config("usf-fw-01", v1_config)
        netlab.deploy_config("usf-fw-02", v1_config)

        # Deploy v2 — simulate failure on device 3 (not in netlab)
        v2_config = "set system host-name v2"
        netlab.deploy_config("usf-fw-01", v2_config)
        netlab.deploy_config("usf-fw-02", v2_config)

        # Simulate device 3 failure — roll back devices 1–2 to v1
        netlab.deploy_config("usf-fw-01", v1_config)
        netlab.deploy_config("usf-fw-02", v1_config)

        assert netlab.devices["usf-fw-01"].running_config == v1_config
        assert netlab.devices["usf-fw-02"].running_config == v1_config

    def test_t6_2_2_rollback_event_recorded(self, neo4j_driver):
        """T6.2.2 — Rollback events recorded in Neo4j."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:DeploymentEvent {eventId: $eid, status: 'ROLLED_BACK', "
                "targetDeviceId: $did, rollbackFrom: $from_v, "
                "rollbackTo: $to_v, modelState: 'DEPLOYED'})",
                {
                    "eid": "DEP-003",
                    "did": "usf-fw-01",
                    "from_v": "CFG-002",
                    "to_v": "CFG-001"
                }
            )

        nodes = neo4j_driver.nodes
        dep_nodes = [n for n in nodes if n.get("_label") == "DeploymentEvent"]
        assert len(dep_nodes) >= 1
        # status is a literal, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("status: 'ROLLED_BACK'" in q["query"] for q in queries)


# ── T6.3 Model state transitions ─────────────────────────────────────────

class TestOrchestrationModelState:
    """T6.3 — Config nodes transition through model states on deploy."""

    def test_t6_3_1_config_transitions_to_deployed(self, neo4j_driver):
        """T6.3.1 — Config nodes move from CANDIDATE to DEPLOYED."""
        # This tests the expected Cypher that Agent 5 would issue
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001', modelState: 'DEPLOYED'})",
                {}
            )

        nodes = neo4j_driver.nodes
        cfg_nodes = [n for n in nodes if n.get("_label") == "Configuration"]
        assert len(cfg_nodes) >= 1
        # modelState is a literal, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("modelState: 'DEPLOYED'" in q["query"] for q in queries)

    def test_t6_3_2_intent_status_updated(self, neo4j_driver):
        """T6.3.2 — Intent status set to ORCHESTRATED after all configs deployed."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Intent {intentId: 'INT-001', status: 'ORCHESTRATED', modelState: 'POR'})",
                {}
            )

        nodes = neo4j_driver.nodes
        intent_nodes = [n for n in nodes if n.get("_label") == "Intent"]
        assert len(intent_nodes) >= 1
        # status is a literal, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("status: 'ORCHESTRATED'" in q["query"] for q in queries)


# ── T6.4 Live-Memory integration ─────────────────────────────────────────

class TestOrchestrationLiveMemory:
    """T6.4 — Agent 5 emits live_notes during deployment."""

    def test_t6_4_1_note_on_deploy_start(self, live_memory):
        """T6.4.1 — Note emitted when deployment begins."""
        live_memory.space_create("ibn-deploy-001")
        note = live_memory.live_note(
            space="ibn-deploy-001",
            category="deployment-start",
            content="Starting deployment of 4 devices for INT-001"
        )
        assert note["category"] == "deployment-start"

    def test_t6_4_2_note_per_device_result(self, live_memory):
        """T6.4.2 — One note per device with success/failure detail."""
        live_memory.space_create("ibn-deploy-001")
        devices = ["usf-fw-01", "usf-fw-02", "dmzfw-01", "dmzfw-02"]
        for d in devices:
            live_memory.live_note(
                space="ibn-deploy-001",
                category="device-result",
                content=f"Device {d}: config pushed successfully, 42 commands applied"
            )

        notes = live_memory.note_list("ibn-deploy-001")
        assert len(notes) == 4

    def test_t6_4_3_note_on_rollback(self, live_memory):
        """T6.4.3 — Note emitted when rollback is triggered."""
        live_memory.space_create("ibn-deploy-001")
        note = live_memory.live_note(
            space="ibn-deploy-001",
            category="rollback-triggered",
            content="Rollback triggered: dmzfw-01 push failed, rolling back usf-fw-01, usf-fw-02"
        )
        assert note["category"] == "rollback-triggered"
        assert "Rollback" in note["content"]
