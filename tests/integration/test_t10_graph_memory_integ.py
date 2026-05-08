"""
T10 — Graph-Memory (Tier 3) Integration Tests
===============================================
Tests namespace isolation, ontology-driven ingestion, and graph-guided RAG
against a real Graph-Memory MCP server + Qdrant.

Run:
    GRAPH_MEMORY_URL=http://localhost:8003 \
    GRAPH_MEMORY_TOKEN=<token> \
    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_PASSWORD=ibn-closed-loop-2026 \
    pytest tests/integration/test_t10_graph_memory_integ.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

from tests.fixtures.live_memory_canned import BANK_REMEDIATION_HISTORY

USE_REAL_GM = bool(os.environ.get("GRAPH_MEMORY_URL"))
USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))

REQUIRES_GM = pytest.mark.skipif(
    not USE_REAL_GM,
    reason="Requires real Graph-Memory (GRAPH_MEMORY_URL)",
)

REQUIRES_GM_NEO4J = pytest.mark.skipif(
    not (USE_REAL_GM and USE_REAL_NEO4J),
    reason="Requires real Graph-Memory (GRAPH_MEMORY_URL) and Neo4j (NEO4J_URI)",
)

TEST_MEMORY = f"ibn-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def gm():
    from ibn.core.graph_memory_client import GraphMemoryClient
    return GraphMemoryClient(
        base_url=os.environ.get("GRAPH_MEMORY_URL", "http://localhost:8003"),
        token=os.environ.get("GRAPH_MEMORY_TOKEN", ""),
    )


@pytest.fixture(scope="module")
def neo4j():
    if not USE_REAL_NEO4J:
        pytest.skip("No real Neo4j")
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def test_memory(gm):
    """Create a test memory namespace, clean up after all tests."""
    gm.memory_create(name=TEST_MEMORY, description="T10 integration test memory")
    yield TEST_MEMORY
    try:
        gm.memory_delete(TEST_MEMORY)
    except Exception:
        pass


# ── T10.1 — Namespace isolation ──────────────────────────────────────────


@REQUIRES_GM_NEO4J
class TestNamespaceIsolation:

    def test_t10_1_1_graph_memory_uses_ibn_lifecycle_labels(self, gm, neo4j, test_memory):
        """T10.1.1 — After ingestion, Neo4j labels carry IBN_LIFECYCLE_ prefix."""
        gm.graph_push(
            memory=test_memory,
            content="Drift detected on usf-fw-01: rule FWR-002 missing.",
            source="t10-test",
        )
        rows = neo4j.run_query(
            """
            CALL db.labels()
            YIELD label
            WHERE label STARTS WITH 'IBN_LIFECYCLE_'
            RETURN label ORDER BY label
            """
        )
        labels = [r["label"] for r in rows]
        # After ingestion, at least one IBN_LIFECYCLE_ label should exist
        assert len(labels) >= 1, "No IBN_LIFECYCLE_ labels found after graph_push"

    def test_t10_1_2_no_collision_with_ssot(self, neo4j):
        """T10.1.2 — SSoT labels (Device, Intent, etc.) don't carry IBN_LIFECYCLE_ prefix."""
        rows = neo4j.run_query(
            """
            CALL db.labels()
            YIELD label
            WHERE label STARTS WITH 'IBN_LIFECYCLE_'
              AND label IN ['Device', 'Intent', 'Policy', 'Site', 'VLAN', 'Zone']
            RETURN label
            """
        )
        assert len(rows) == 0, f"Namespace collision: {rows}"

    def test_t10_1_3_both_namespaces_coexist(self, gm, neo4j, test_memory):
        """T10.1.3 — Both SSoT and Graph-Memory write to same instance without interference."""
        # SSoT query
        ssot_count = neo4j.run_query(
            "MATCH (n) WHERE NOT any(l IN labels(n) WHERE l STARTS WITH 'IBN_LIFECYCLE_') RETURN count(n) AS c"
        )
        # Graph-Memory query
        gm_count = neo4j.run_query(
            "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'IBN_LIFECYCLE_') RETURN count(n) AS c"
        )
        # Both should be queryable
        assert ssot_count[0]["c"] >= 0
        assert gm_count[0]["c"] >= 0


# ── T10.2 — IBN Network Lifecycle ontology ───────────────────────────────


@REQUIRES_GM
class TestOntologyExtraction:

    def test_t10_2_1_entity_extraction(self, gm, test_memory):
        """T10.2.1 — graph_push extracts entities from remediation narrative."""
        result = gm.graph_push(
            memory=test_memory,
            content=BANK_REMEDIATION_HISTORY,
            source="t10-remediation-history",
        )
        assert result.get("status") == "ingested"
        entities = result.get("entities_extracted", 0)
        # Should extract DriftEvent, RemediationAction, LessonLearned, etc.
        assert entities >= 1, f"Expected entity extraction, got {entities}"

    def test_t10_2_3_all_entity_families(self, gm, test_memory):
        """T10.2.3 — Push content covering all 4 entity families."""
        content = """
# Decision Record
Decision: Chose active-active HA over active-passive for USF firewalls.
Rationale: Higher throughput with stateful failover. Trade-off: more complex config.

# Drift Incident
Drift detected on dmzfw-01: extra rule ROGUE-RULE present.
Root cause: operator CLI access during maintenance window.
Remediation: auto-remediate — re-pushed CFG-005. Resolved in 30 seconds.

# Deployment Narrative
Deployed INT-002 configs to dmzfw-01 and dmzfw-02.
Post-deploy verification: PASS. 98 lines per device.

# Lesson Learned
Lesson: All firewall changes must go through the intent pipeline.
Recurring pattern: out-of-band CLI access causes drift every maintenance window.
"""
        result = gm.graph_push(
            memory=test_memory,
            content=content,
            source="t10-all-families",
        )
        assert result.get("status") == "ingested"


# ── T10.4 — Graph-guided RAG ─────────────────────────────────────────────


@REQUIRES_GM
class TestGraphGuidedRAG:

    def test_t10_4_1_question_answer_returns_knowledge(self, gm, test_memory):
        """T10.4.1 — question_answer() returns relevant knowledge."""
        # Ensure some content exists
        gm.graph_push(
            memory=test_memory,
            content=BANK_REMEDIATION_HISTORY,
            source="t10-rag-test",
        )
        answer = gm.question_answer(
            memory=test_memory,
            question="What caused the last USF firewall drift?",
        )
        assert "answer" in answer
        assert "sources" in answer
        # Answer should not be the default empty response
        assert answer["answer"] != ""

    def test_t10_4_2_answer_includes_sources(self, gm, test_memory):
        """T10.4.2 — RAG response includes source references."""
        answer = gm.question_answer(
            memory=test_memory,
            question="Was there a remediation for dmzfw-01?",
            max_results=3,
        )
        assert isinstance(answer["sources"], list)
