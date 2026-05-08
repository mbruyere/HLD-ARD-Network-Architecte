"""
T1 — Neo4j Ontology and Schema Integration Tests
==================================================
Tests schema DDL loading, constraint enforcement, and index verification
against a real Neo4j instance.

Run:
    NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=ibn-closed-loop-2026 \
    pytest tests/integration/test_t1_neo4j_schema_integ.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))

REQUIRES_NEO4J = pytest.mark.skipif(
    not USE_REAL_NEO4J,
    reason="Requires real Neo4j (NEO4J_URI)",
)


@pytest.fixture(scope="module")
def neo4j():
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


# ── T1.1 — Schema DDL loads ──────────────────────────────────────────────


@REQUIRES_NEO4J
class TestSchemaDDL:

    def test_t1_1_1_schema_file_loads_without_error(self, neo4j):
        """T1.1.1 — Load Neo4j_Schema_Cypher.cypher succeeds."""
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "Neo4j_Schema_Cypher.cypher"
        )
        if not os.path.exists(schema_path):
            pytest.skip("Neo4j_Schema_Cypher.cypher not found")

        with open(schema_path) as f:
            cypher = f.read()

        # Split on semicolons and run each statement
        statements = [s.strip() for s in cypher.split(";") if s.strip()]
        errors = []
        for stmt in statements:
            if not stmt or stmt.startswith("//"):
                continue
            try:
                neo4j.run_query(stmt)
            except Exception as exc:
                errors.append(f"{stmt[:80]}... → {exc}")

        assert len(errors) == 0, f"Schema load errors:\n" + "\n".join(errors)

    def test_t1_1_2_idempotent_reload(self, neo4j):
        """T1.1.2 — Loading DDL twice produces no errors (IF NOT EXISTS guards)."""
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "Neo4j_Schema_Cypher.cypher"
        )
        if not os.path.exists(schema_path):
            pytest.skip("Neo4j_Schema_Cypher.cypher not found")

        with open(schema_path) as f:
            cypher = f.read()

        statements = [s.strip() for s in cypher.split(";") if s.strip()]
        errors = []
        for stmt in statements:
            if not stmt or stmt.startswith("//"):
                continue
            try:
                neo4j.run_query(stmt)
            except Exception as exc:
                errors.append(f"{stmt[:80]}... → {exc}")

        assert len(errors) == 0, f"Idempotent reload errors:\n" + "\n".join(errors)


# ── T1.2 — Constraint enforcement ────────────────────────────────────────


@REQUIRES_NEO4J
class TestConstraintEnforcement:

    def test_t1_2_1_duplicate_intent_id_rejected(self, neo4j):
        """T1.2.1 — Unique intentId constraint prevents duplicates."""
        uid = f"INT-DUP-{uuid.uuid4().hex[:8]}"
        neo4j.run_query(
            "CREATE (:Intent {intentId: $id, modelState: 'CANDIDATE'})",
            id=uid,
        )
        with pytest.raises(Exception):
            neo4j.run_query(
                "CREATE (:Intent {intentId: $id, modelState: 'CANDIDATE'})",
                id=uid,
            )
        # Cleanup
        neo4j.run_query("MATCH (i:Intent {intentId: $id}) DELETE i", id=uid)

    def test_t1_2_2_duplicate_device_id_rejected(self, neo4j):
        """T1.2.2 — Unique deviceId constraint prevents duplicates."""
        uid = f"DEV-DUP-{uuid.uuid4().hex[:8]}"
        neo4j.run_query(
            "CREATE (:Device {deviceId: $id, modelState: 'POR'})",
            id=uid,
        )
        with pytest.raises(Exception):
            neo4j.run_query(
                "CREATE (:Device {deviceId: $id, modelState: 'POR'})",
                id=uid,
            )
        neo4j.run_query("MATCH (d:Device {deviceId: $id}) DELETE d", id=uid)


# ── T1.3 — Index verification ────────────────────────────────────────────


@REQUIRES_NEO4J
class TestIndexes:

    def _get_indexes(self, neo4j):
        rows = neo4j.run_query("SHOW INDEXES")
        return rows

    def test_t1_3_1_device_id_index_exists(self, neo4j):
        """T1.3.1 — Index exists on Device.deviceId."""
        indexes = self._get_indexes(neo4j)
        device_indexes = [
            idx for idx in indexes
            if "Device" in str(idx.get("labelsOrTypes", []))
            and "deviceId" in str(idx.get("properties", []))
        ]
        assert len(device_indexes) >= 1, "No index found on Device.deviceId"

    def test_t1_3_2_intent_id_index_exists(self, neo4j):
        """T1.3.2 — Index exists on Intent.intentId."""
        indexes = self._get_indexes(neo4j)
        intent_indexes = [
            idx for idx in indexes
            if "Intent" in str(idx.get("labelsOrTypes", []))
            and "intentId" in str(idx.get("properties", []))
        ]
        assert len(intent_indexes) >= 1, "No index found on Intent.intentId"


# ── T1.4 — Layer labels creatable ────────────────────────────────────────


ALL_LABELS = [
    "Site", "Device", "Interface", "PhysicalLink", "LogicalLink",
    "VLAN", "VRF", "Subnet", "IPAddress",
    "Topology", "TopologyLayer", "Zone", "Segment", "FirewallPair", "StackGroup",
    "Architecture", "ArchitectureVersion", "HLD", "ARD", "BusinessUseCase",
    "Intent", "Policy", "FirewallRule", "SGT", "QoSPolicy",
    "Configuration", "DeploymentEvent", "Telemetry", "OperationalState",
    "Alert", "Incident", "RootCause", "ComplianceAssessment", "Remediation",
    "ChangeRequest", "MigrationPlan",
    "LifecyclePhase", "LifecycleTransition",
    "Operator", "Team", "Ticket", "SLA", "AgentExecution",
]


@REQUIRES_NEO4J
class TestLayerLabelsInteg:

    @pytest.mark.parametrize("label", ALL_LABELS)
    def test_t1_4_label_creatable(self, neo4j, label):
        """T1.4 — All ontology labels are creatable in real Neo4j."""
        uid = f"test-{label}-{uuid.uuid4().hex[:8]}"
        neo4j.run_query(
            f"CREATE (n:{label} {{testId: $id, modelState: 'POR'}}) RETURN n",
            id=uid,
        )
        # Verify and cleanup
        rows = neo4j.run_query(
            f"MATCH (n:{label} {{testId: $id}}) RETURN n",
            id=uid,
        )
        assert len(rows) == 1
        neo4j.run_query(
            f"MATCH (n:{label} {{testId: $id}}) DELETE n",
            id=uid,
        )
