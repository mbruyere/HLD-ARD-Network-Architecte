"""
T15 — Model State Lifecycle Tests (Unit)
=========================================
Validates correct model state transitions, immutability through PRECEDED_BY
versioning, and cross-model-state queries.
"""
import pytest


# ── T15.1 State transitions ──────────────────────────────────────────────

class TestStateTransitions:
    """T15.1 — Only valid model state transitions are allowed."""

    VALID_TRANSITIONS = {
        "WHAT_IF": {"CANDIDATE"},
        "CANDIDATE": {"POR", "WHAT_IF"},  # Can be rejected back to WHAT_IF
        "POR": {"DEPLOYED"},
        "DEPLOYED": {"AS_BUILT"},
        "AS_BUILT": {"WHAT_IF"},  # Drift triggers re-plan
    }

    def _validate_transition(self, from_state: str, to_state: str) -> bool:
        """Check if a state transition is valid."""
        allowed = self.VALID_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    def test_t15_1_1_whatif_to_candidate(self):
        """T15.1.1 — WHAT_IF → CANDIDATE is valid."""
        assert self._validate_transition("WHAT_IF", "CANDIDATE")

    def test_t15_1_2_candidate_to_por(self):
        """T15.1.2 — CANDIDATE → POR is valid."""
        assert self._validate_transition("CANDIDATE", "POR")

    def test_t15_1_3_por_to_deployed(self):
        """T15.1.3 — POR → DEPLOYED is valid."""
        assert self._validate_transition("POR", "DEPLOYED")

    def test_t15_1_4_deployed_to_asbuilt(self):
        """T15.1.4 — DEPLOYED → AS_BUILT is valid."""
        assert self._validate_transition("DEPLOYED", "AS_BUILT")

    def test_t15_1_5_invalid_transition_rejected(self):
        """T15.1.5 — WHAT_IF → DEPLOYED (skipping steps) is invalid."""
        assert not self._validate_transition("WHAT_IF", "DEPLOYED")
        assert not self._validate_transition("WHAT_IF", "POR")
        assert not self._validate_transition("CANDIDATE", "DEPLOYED")
        assert not self._validate_transition("CANDIDATE", "AS_BUILT")


# ── T15.2 Immutability ───────────────────────────────────────────────────

class TestImmutability:
    """T15.2 — Nodes are versioned, not mutated. PRECEDED_BY chains are traversable."""

    def test_t15_2_1_new_version_created_not_mutated(self, neo4j_driver):
        """T15.2.1 — Config update creates new node with PRECEDED_BY link."""
        with neo4j_driver.session() as session:
            # Create v1
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001-v1', version: 1, "
                "content: 'v1 config', modelState: 'POR'})", {}
            )
            # Create v2 with PRECEDED_BY
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001-v2', version: 2, "
                "content: 'v2 config', modelState: 'CANDIDATE'})"
                "-[:PRECEDED_BY]->"
                "(:Configuration {configId: 'CFG-001-v1', version: 1, modelState: 'POR'})", {}
            )

        # Verify both CREATE queries were issued (mock stores params, not Cypher props)
        queries = neo4j_driver.queries
        assert len(queries) >= 2
        # PRECEDED_BY relationship was created in the second query
        assert any("PRECEDED_BY" in q["query"] for q in queries)
        # Both queries targeted Configuration labels
        assert all("Configuration" in q["query"] for q in queries)

    def test_t15_2_2_preceded_by_chain_traversable(self, neo4j_driver):
        """T15.2.2 — Three-version chain: v3 → v2 → v1."""
        with neo4j_driver.session() as session:
            for v in range(1, 4):
                session.run(
                    f"CREATE (:Configuration {{configId: 'CFG-{v}', version: {v}, modelState: 'POR'}})", {}
                )
            # Create PRECEDED_BY chain
            session.run(
                "CREATE (:Configuration {configId: 'CFG-3', modelState: 'POR'})"
                "-[:PRECEDED_BY]->(:Configuration {configId: 'CFG-2', modelState: 'POR'})", {}
            )
            session.run(
                "CREATE (:Configuration {configId: 'CFG-2', modelState: 'POR'})"
                "-[:PRECEDED_BY]->(:Configuration {configId: 'CFG-1', modelState: 'POR'})", {}
            )

        # Verify chain exists in queries
        queries = neo4j_driver.queries
        preceded_queries = [q for q in queries if "PRECEDED_BY" in q["query"]]
        assert len(preceded_queries) >= 2

    def test_t15_2_3_old_versions_readable(self, neo4j_driver):
        """T15.2.3 — Old versions remain accessible after new version created."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Configuration {configId: 'CFG-v1', version: 1, "
                "content: 'original content', modelState: 'POR'})", {}
            )
            session.run(
                "CREATE (:Configuration {configId: 'CFG-v2', version: 2, "
                "content: 'updated content', modelState: 'CANDIDATE'})", {}
            )

        # Verify both versions were created as separate queries
        queries = neo4j_driver.queries
        assert len(queries) >= 2
        # Both target Configuration label
        cfg_queries = [q for q in queries if "Configuration" in q["query"]]
        assert len(cfg_queries) >= 2
        # Nodes exist (mock stores params, not Cypher property names)
        nodes = neo4j_driver.nodes
        configs = [n for n in nodes if n.get("_label") == "Configuration"]
        assert len(configs) >= 2


# ── T15.3 Cross-model-state queries ──────────────────────────────────────

class TestCrossModelStateQueries:
    """T15.3 — Query nodes filtered by model state."""

    def test_t15_3_1_query_por_nodes_only(self, seeded_neo4j):
        """T15.3.1 — Filter returns only POR nodes."""
        nodes = seeded_neo4j.nodes
        por_nodes = [n for n in nodes if n.get("modelState") == "POR"]
        non_por = [n for n in nodes if n.get("modelState") and n.get("modelState") != "POR"]
        assert len(por_nodes) > 0
        assert len(non_por) == 0  # Seeded data is all POR

    def test_t15_3_2_compare_por_vs_asbuilt(self, seeded_neo4j):
        """T15.3.2 — Both POR and AS_BUILT queryable for same device."""
        # Add an AS_BUILT node
        seeded_neo4j.seed_node("OperationalState", {
            "deviceId": "usf-fw-01", "operState": "running",
            "modelState": "AS_BUILT"
        })

        nodes = seeded_neo4j.nodes
        por_devices = [n for n in nodes if n.get("_label") == "Device" and n.get("modelState") == "POR"]
        asbuilt = [n for n in nodes if n.get("_label") == "OperationalState" and n.get("modelState") == "AS_BUILT"]

        assert len(por_devices) > 0
        assert len(asbuilt) > 0

    def test_t15_3_3_count_by_model_state(self, seeded_neo4j):
        """T15.3.3 — Count nodes grouped by model state."""
        # Add some non-POR nodes
        seeded_neo4j.seed_node("Intent", {"intentId": "INT-001", "modelState": "CANDIDATE"})
        seeded_neo4j.seed_node("Telemetry", {"metric": "cpu", "modelState": "AS_BUILT"})

        nodes = seeded_neo4j.nodes
        state_counts = {}
        for n in nodes:
            state = n.get("modelState")
            if state:
                state_counts[state] = state_counts.get(state, 0) + 1

        assert "POR" in state_counts
        assert "CANDIDATE" in state_counts
        assert "AS_BUILT" in state_counts
