"""
Agent 5 Integration Tests
=========================
Tests Agent 5 (Orchestration) against real Neo4j and Live-Memory.
SSH is always mocked — NetLab is not required.

Run with real infrastructure:
    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_PASSWORD=ibn-closed-loop-2026 \
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k \
    pytest tests/integration/test_agent5_integration.py -v

Run without infrastructure (all tests skip):
    pytest tests/integration/test_agent5_integration.py -v
"""

import os
import uuid
import pytest

# ── Environment detection ──────────────────────────────────────────────────

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))
USE_REAL_LIVE_MEMORY = bool(os.environ.get("LIVE_MEMORY_URL"))
REQUIRES_BOTH = pytest.mark.skipif(
    not (USE_REAL_NEO4J and USE_REAL_LIVE_MEMORY),
    reason="Requires real Neo4j (NEO4J_URI) and Live-Memory (LIVE_MEMORY_URL)",
)

# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_neo4j():
    """Real Neo4j client for integration tests."""
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def real_live_memory():
    """Real Live-Memory client for integration tests."""
    from ibn.core.live_memory_client import LiveMemoryClient
    return LiveMemoryClient(
        base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
        token=os.environ.get("LIVE_MEMORY_TOKEN", os.environ.get("LM_ADMIN_TOKEN", "")),
    )


@pytest.fixture
def mock_ssh():
    """SSH executor that records calls without network access."""
    calls = []

    def executor(device_id: str, config: str) -> dict:
        calls.append({"device": device_id, "config_len": len(config)})
        return {"status": "ok", "device": device_id}

    executor.calls = calls
    return executor


@pytest.fixture
def mock_verifier():
    """SSH verifier that always passes without network access."""
    def verifier(device_id: str, snippets: list) -> dict:
        return {"verified": True, "device": device_id, "checked": len(snippets)}

    return verifier


@pytest.fixture
def deploy_space_id():
    """Unique deploy space ID per test."""
    return f"ibn-deploy-{uuid.uuid4().hex[:8]}"


# ── Tests ──────────────────────────────────────────────────────────────────

@REQUIRES_BOTH
class TestAgent5RealInfra:
    """Full integration: Agent 5 against real Neo4j + Live-Memory, mock SSH."""

    def test_a5_i1_successful_deployment_creates_neo4j_events(
        self, real_neo4j, real_live_memory, mock_ssh, mock_verifier, deploy_space_id
    ):
        """
        A5-I1: Successful deployment creates DeploymentEvent nodes in Neo4j.
        """
        from ibn.agents.agent5_orchestration import Agent5Orchestration
        from ibn.core.models import Intent, ModelState

        # Seed an intent in Neo4j
        intent_id = f"INT-{uuid.uuid4().hex[:8].upper()}"
        real_neo4j.create_intent(Intent(
            intentId=intent_id,
            statement="Allow Employee VLAN to Internet",
            type="access-policy",
            subject="Employee",
            action="permit",
            target="Internet",
            status="INGESTED",
            modelState=ModelState.CANDIDATE,
        ))

        agent = Agent5Orchestration(
            neo4j=real_neo4j,
            live_memory=real_live_memory,
            ssh_executor=mock_ssh,
            ssh_verifier=mock_verifier,
        )

        plan = [
            {
                "deviceId":  "usf-fw-01",
                "configId":  f"CFG-{uuid.uuid4().hex[:8].upper()}",
                "content":   "set system host-name usf-fw-01\nset firewall name EMPLOYEE-INTERNET default-action accept",
            },
            {
                "deviceId":  "usf-fw-02",
                "configId":  f"CFG-{uuid.uuid4().hex[:8].upper()}",
                "content":   "set system host-name usf-fw-02\nset firewall name EMPLOYEE-INTERNET default-action accept",
            },
        ]

        result = agent.run(
            intent_id=intent_id,
            plan=plan,
            deploy_space=deploy_space_id,
            action="deploy",
        )

        # Agent result
        assert result["status"] == "ORCHESTRATED"
        assert len(result["devices"]) == 2
        assert result["verified"] is True

        # SSH was called twice
        assert len(mock_ssh.calls) == 2
        assert {c["device"] for c in mock_ssh.calls} == {"usf-fw-01", "usf-fw-02"}

        # Neo4j: intent status updated
        intents = real_neo4j.run_query(
            "MATCH (i:Intent {intentId: $id}) RETURN i.status AS status",
            id=intent_id,
        )
        assert intents and intents[0]["status"] == "ORCHESTRATED"

        # Neo4j: DeploymentEvent nodes created
        events = real_neo4j.run_query(
            """
            MATCH (e:DeploymentEvent)
            WHERE e.targetDeviceId IN ['usf-fw-01', 'usf-fw-02']
              AND e.status = 'DEPLOYED'
            RETURN e.eventId AS id, e.targetDeviceId AS device, e.status AS status
            ORDER BY e.timestamp DESC
            LIMIT 10
            """
        )
        deployed = [e for e in events if e.get("device") in {"usf-fw-01", "usf-fw-02"}]
        assert len(deployed) >= 2

    def test_a5_i2_failed_deployment_triggers_rollback(
        self, real_neo4j, real_live_memory, deploy_space_id
    ):
        """
        A5-I2: Failure on device 2 triggers rollback of device 1.
        ROLLED_BACK DeploymentEvent is created in Neo4j.
        """
        from ibn.agents.agent5_orchestration import Agent5Orchestration
        from ibn.core.models import Intent, ModelState

        intent_id = f"INT-{uuid.uuid4().hex[:8].upper()}"
        real_neo4j.create_intent(Intent(
            intentId=intent_id,
            statement="Deny IoT VLAN to DMZ",
            type="access-policy",
            subject="IoT",
            action="deny",
            target="DMZ",
            status="INGESTED",
            modelState=ModelState.CANDIDATE,
        ))

        call_count = {"n": 0}

        def failing_ssh(device_id: str, config: str) -> dict:
            call_count["n"] += 1
            if call_count["n"] >= 2:  # Second call fails
                raise RuntimeError(f"Simulated SSH timeout on {device_id}")
            return {"status": "ok", "device": device_id}

        agent = Agent5Orchestration(
            neo4j=real_neo4j,
            live_memory=real_live_memory,
            ssh_executor=failing_ssh,
            ssh_verifier=lambda d, s: {"verified": True, "device": d, "checked": 0},
        )

        plan = [
            {"deviceId": "dmzfw-01", "configId": "CFG-ROLLBACK-01", "content": "set firewall name DENY-IOT"},
            {"deviceId": "dmzfw-02", "configId": "CFG-ROLLBACK-02", "content": "set firewall name DENY-IOT"},
        ]

        result = agent.run(
            intent_id=intent_id,
            plan=plan,
            deploy_space=deploy_space_id,
            action="deploy",
        )

        assert result["status"] == "FAILED"
        assert result["failed"] == "dmzfw-02"
        assert "dmzfw-01" in result["rolled_back"]

        # Verify ROLLED_BACK event in Neo4j
        events = real_neo4j.run_query(
            """
            MATCH (e:DeploymentEvent {status: 'ROLLED_BACK', targetDeviceId: 'dmzfw-01'})
            RETURN e.eventId AS id LIMIT 5
            """
        )
        assert len(events) >= 1

    def test_a5_i3_live_notes_written_to_deploy_space(
        self, real_neo4j, real_live_memory, mock_ssh, mock_verifier, deploy_space_id
    ):
        """
        A5-I3: Live-Memory notes are emitted to the deployment space.
        """
        from ibn.agents.agent5_orchestration import Agent5Orchestration
        from ibn.core.live_memory_client import LiveMemoryClient

        # Create the space first (MCP protocol requires space to exist)
        real_live_memory.space_create(
            space_id=deploy_space_id,
            description=f"Integration test deployment {deploy_space_id}",
            owner="ibn-system",
            rules="# Test deployment space\n",
        )

        intent_id = f"INT-{uuid.uuid4().hex[:8].upper()}"

        from ibn.core.models import Intent, ModelState
        real_neo4j.create_intent(Intent(
            intentId=intent_id,
            statement="Allow Voice VLAN QoS",
            type="qos-policy",
            subject="Voice",
            action="permit",
            target="Internet",
            status="INGESTED",
            modelState=ModelState.CANDIDATE,
        ))

        agent = Agent5Orchestration(
            neo4j=real_neo4j,
            live_memory=real_live_memory,
            ssh_executor=mock_ssh,
            ssh_verifier=mock_verifier,
        )

        plan = [
            {
                "deviceId": "usf-fw-01",
                "configId": "CFG-QOS-01",
                "content": "set traffic-policy shaper VOICE-QOS bandwidth 10mbit",
            },
        ]

        result = agent.run(
            intent_id=intent_id,
            plan=plan,
            deploy_space=deploy_space_id,
            action="deploy",
        )

        assert result["status"] == "ORCHESTRATED"

        # Verify notes exist in the deploy space
        notes = real_live_memory.note_list(deploy_space_id)
        assert len(notes) >= 2  # deployment-start + device-result + verification-result

        # Categories are stored as MCP categories (observation/progress/issue)
        # deployment-start → progress, device-result → observation
        categories = {n.get("category") for n in notes}
        assert "progress" in categories or "observation" in categories


# ── Topology generator integration tests ─────────────────────────────────

@pytest.mark.skipif(not USE_REAL_NEO4J, reason="Requires real Neo4j (NEO4J_URI)")
class TestNetLabTopologyGenerator:
    """Integration: generate topology.yml from real Neo4j POR state."""

    def test_a5_t1_generate_topology_from_neo4j(self, real_neo4j, tmp_path):
        """
        A5-T1: Generate a valid netlab topology from Neo4j POR state.
        """
        from ibn.agents.netlab_topology import NetLabTopologyGenerator

        gen = NetLabTopologyGenerator(real_neo4j)
        topo = gen.generate(site_id="site-hq")

        # Basic structure checks
        assert "provider" in topo
        assert "nodes" in topo
        assert "addressing" in topo

        # Nodes must have device type
        for name, node in topo["nodes"].items():
            assert "device" in node, f"Node {name} missing 'device'"

        # Save and verify YAML is valid
        out = tmp_path / "topology_test.yml"
        gen.save(topo, out)
        assert out.exists()

        import yaml
        with open(out) as f:
            loaded = yaml.safe_load(f)
        assert loaded["provider"] == topo["provider"]

    def test_a5_t2_topology_contains_hld_firewalls(self, real_neo4j):
        """
        A5-T2: Generated topology includes the HLD firewall devices (USF + DMZFW).
        """
        from ibn.agents.netlab_topology import NetLabTopologyGenerator

        gen = NetLabTopologyGenerator(real_neo4j)
        topo = gen.generate(site_id="site-hq")

        node_names = set(topo["nodes"].keys())
        # HLD firewalls must appear in the topology
        fw_devices = {n for n in node_names if "fw" in n.lower() or "usf" in n.lower()}
        assert len(fw_devices) >= 1, f"No firewall devices found in topology nodes: {node_names}"

    def test_a5_t3_topology_vlans_match_hld(self, real_neo4j):
        """
        A5-T3: Population VLANs 100-160 and DMZ VLANs 200-270 are represented.
        """
        from ibn.agents.netlab_topology import NetLabTopologyGenerator

        gen = NetLabTopologyGenerator(real_neo4j)
        topo = gen.generate(site_id="site-hq")

        vlan_ids = {v["id"] for v in topo.get("vlans", {}).values() if isinstance(v, dict) and "id" in v}
        population_vlans = set(range(100, 161))
        dmz_vlans = set(range(200, 271))

        population_present = vlan_ids & population_vlans
        dmz_present = vlan_ids & dmz_vlans

        assert len(population_present) >= 5, f"Too few population VLANs: {population_present}"
        assert len(dmz_present) >= 3, f"Too few DMZ VLANs: {dmz_present}"
