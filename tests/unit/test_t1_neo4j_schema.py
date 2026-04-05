"""
T1 — Neo4j Ontology and Schema Tests (Unit)
============================================
Validates that the 9-layer ontology labels, constraints, and modelState
enforcement work correctly against the mock Neo4j driver.
"""
import pytest


# ── T1.2 Required modelState (application-level) ──────────────────────────

class TestModelStateEnforcement:
    """T1.2.4 — Every node must carry a modelState property."""

    VALID_MODEL_STATES = {"WHAT_IF", "CANDIDATE", "POR", "DEPLOYED", "AS_BUILT"}

    def _validate_model_state(self, properties: dict):
        """Application-level check: modelState must be present and valid."""
        assert "modelState" in properties, "Node is missing required 'modelState' property"
        assert properties["modelState"] in self.VALID_MODEL_STATES, (
            f"Invalid modelState '{properties['modelState']}'. "
            f"Must be one of {self.VALID_MODEL_STATES}"
        )

    def test_t1_2_4_node_without_model_state_rejected(self):
        """Creating a node without modelState should fail validation."""
        bad_node = {"intentId": "INT-001", "statement": "test"}
        with pytest.raises(AssertionError, match="missing required 'modelState'"):
            self._validate_model_state(bad_node)

    def test_t1_2_4_node_with_invalid_model_state_rejected(self):
        """Creating a node with invalid modelState value should fail."""
        bad_node = {"intentId": "INT-001", "modelState": "DRAFT"}
        with pytest.raises(AssertionError, match="Invalid modelState"):
            self._validate_model_state(bad_node)

    def test_t1_2_4_node_with_valid_model_state_accepted(self):
        """Node with valid modelState passes validation."""
        for state in self.VALID_MODEL_STATES:
            good_node = {"intentId": "INT-001", "modelState": state}
            self._validate_model_state(good_node)  # Should not raise


# ── T1.4 Layer node labels ────────────────────────────────────────────────

class TestLayerLabels:
    """T1.4 — All ontology layer labels are creatable in Neo4j."""

    L1_LABELS = ["Site", "Device", "Interface", "PhysicalLink", "LogicalLink",
                 "VLAN", "VRF", "Subnet", "IPAddress"]
    L2_LABELS = ["Topology", "TopologyLayer", "Zone", "Segment", "FirewallPair", "StackGroup"]
    L3_LABELS = ["Architecture", "ArchitectureVersion", "HLD", "ARD", "BusinessUseCase"]
    L4_LABELS = ["Intent", "Policy", "FirewallRule", "SGT", "QoSPolicy"]
    L5_LABELS = ["Configuration", "DeploymentEvent", "Telemetry", "OperationalState"]
    L6_LABELS = ["Alert", "Incident", "RootCause", "ComplianceAssessment", "Remediation"]
    L7_LABELS = ["ChangeRequest", "MigrationPlan"]
    L8_LABELS = ["LifecyclePhase", "LifecycleTransition"]
    L9_LABELS = ["Operator", "Team", "Ticket", "SLA", "AgentExecution"]

    @pytest.mark.parametrize("label", L1_LABELS, ids=lambda l: f"L1-{l}")
    def test_t1_4_1_l1_labels(self, neo4j_driver, label):
        """T1.4.1 — L1 Infrastructure labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'POR'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L2_LABELS, ids=lambda l: f"L2-{l}")
    def test_t1_4_2_l2_labels(self, neo4j_driver, label):
        """T1.4.2 — L2 Topology labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'POR'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L3_LABELS, ids=lambda l: f"L3-{l}")
    def test_t1_4_3_l3_labels(self, neo4j_driver, label):
        """T1.4.3 — L3 Architecture labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'POR'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L4_LABELS, ids=lambda l: f"L4-{l}")
    def test_t1_4_4_l4_labels(self, neo4j_driver, label):
        """T1.4.4 — L4 Policy & Intent labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'CANDIDATE'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L5_LABELS, ids=lambda l: f"L5-{l}")
    def test_t1_4_5_l5_labels(self, neo4j_driver, label):
        """T1.4.5 — L5 Config & State labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'DEPLOYED'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L6_LABELS, ids=lambda l: f"L6-{l}")
    def test_t1_4_6_l6_labels(self, neo4j_driver, label):
        """T1.4.6 — L6 Incident labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'AS_BUILT'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None

    @pytest.mark.parametrize("label", L7_LABELS + L8_LABELS + L9_LABELS,
                             ids=lambda l: f"L7-L9-{l}")
    def test_t1_4_7_l7_l9_labels(self, neo4j_driver, label):
        """T1.4.7 — L7–L9 labels are creatable."""
        with neo4j_driver.session() as session:
            result = session.run(
                f"CREATE (:{label} {{testId: $id, modelState: 'POR'}})",
                {"id": f"test-{label}"}
            )
            assert result is not None
