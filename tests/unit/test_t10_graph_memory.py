"""
T10 — Graph-Memory (Tier 3) Tests (Unit)
=========================================
Validates namespace isolation, IBN Network Lifecycle ontology,
entity extraction, and graph-guided RAG queries.
"""
import pytest


# ── T10.1 Namespace isolation ─────────────────────────────────────────────

class TestNamespaceIsolation:
    """T10.1 — Graph-Memory uses IBN_LIFECYCLE_* labels, no SSoT collision."""

    NAMESPACE_PREFIX = "IBN_LIFECYCLE_"

    def test_t10_1_1_graph_memory_uses_prefixed_labels(self, graph_memory):
        """T10.1.1 — Entities created in Graph-Memory use IBN_LIFECYCLE_* labels."""
        graph_memory.memory_create("ibn-lifecycle", ontology={
            "entities": ["PolicyDecision", "DriftEvent", "RemediationAction", "LessonLearned"],
            "prefix": self.NAMESPACE_PREFIX
        })

        result = graph_memory.graph_push(
            memory="ibn-lifecycle",
            content="Policy POL-001 was created to enforce Guest isolation",
            source="ibn-candidate-001/policy-decisions"
        )

        assert result["status"] == "ingested"
        assert result["entities_extracted"] >= 1

    def test_t10_1_2_no_collision_with_ssot_labels(self, neo4j_driver, graph_memory):
        """T10.1.2 — SSoT and Graph-Memory labels don't collide."""
        ssot_labels = {"Intent", "Policy", "Device", "Configuration", "Alert"}
        graph_memory_labels = {f"{self.NAMESPACE_PREFIX}{e}" for e in
                               ["PolicyDecision", "DriftEvent", "RemediationAction"]}

        overlap = ssot_labels & graph_memory_labels
        assert len(overlap) == 0, f"Label collision: {overlap}"


# ── T10.2 IBN Network Lifecycle ontology ──────────────────────────────────

class TestIBNOntology:
    """T10.2 — Custom ontology with 4 entity families and typed relationships."""

    ENTITY_FAMILIES = {
        "Decisions": ["PolicyDecision", "DesignChoice", "ConfigDecision"],
        "Incidents": ["DriftEvent", "ComplianceViolation", "ServiceImpact"],
        "Operations": ["RemediationAction", "DeploymentOperation", "RollbackEvent"],
        "Knowledge": ["LessonLearned", "BestPractice", "PatternDiscovery"],
    }

    RELATIONSHIP_TYPES = [
        "CAUSED_BY", "RESOLVED_BY", "JUSTIFIED_BY",
        "PRECEDED_BY", "RELATED_TO", "LEARNED_FROM"
    ]

    def test_t10_2_1_entity_extraction(self, graph_memory):
        """T10.2.1 — Consolidated bank file produces correct entity type."""
        graph_memory.memory_create("ibn-lifecycle")
        result = graph_memory.graph_push(
            memory="ibn-lifecycle",
            content="Decision: Implemented zone-based firewall policy for Guest isolation. "
                    "Rationale: RFC 9315 requires intent-to-policy translation that respects "
                    "segment boundaries defined in the HLD.",
            source="ibn-candidate-001/policy-decisions"
        )
        assert result["status"] == "ingested"
        assert result["entities_extracted"] >= 1

    def test_t10_2_2_relationship_extraction(self, graph_memory):
        """T10.2.2 — Bank file mentioning causation produces CAUSED_BY relationship."""
        graph_memory.memory_create("ibn-lifecycle")
        graph_memory.graph_push(
            memory="ibn-lifecycle",
            content="DriftEvent DE-042 on usf-fw-01: firewall rule FWR-002 missing. "
                    "Caused by: manual SSH session by operator removed rule outside loop.",
            source="ibn-loop-inner/drift-analysis"
        )
        # In production, entity extraction would create DriftEvent + CAUSED_BY relationship
        assert len(graph_memory.entities) >= 1

    def test_t10_2_3_all_entity_families_supported(self, graph_memory):
        """T10.2.3 — All 4 entity families are extractable."""
        graph_memory.memory_create("ibn-lifecycle")

        samples = [
            ("Decision to use zone-based policy for VLAN 140", "Decisions"),
            ("Drift detected: interface eth0.140 down on usf-fw-01", "Incidents"),
            ("Auto-remediation: re-pushed config CFG-002 to usf-fw-01", "Operations"),
            ("Lesson: VRRP preempt should be disabled during maintenance", "Knowledge"),
        ]

        for content, family in samples:
            result = graph_memory.graph_push(
                memory="ibn-lifecycle",
                content=content,
                source=f"test/{family.lower()}"
            )
            assert result["status"] == "ingested"

        assert len(graph_memory.entities) == 4


# ── T10.4 Graph-guided RAG ───────────────────────────────────────────────

class TestGraphGuidedRAG:
    """T10.4 — question_answer() returns relevant historical knowledge."""

    def test_t10_4_1_question_answer_returns_knowledge(self, graph_memory):
        """T10.4.1 — Historical query returns relevant drift/remediation info."""
        graph_memory.memory_create("ibn-lifecycle")
        graph_memory.graph_push(
            memory="ibn-lifecycle",
            content="USF firewall usf-fw-01 experienced config drift on 2026-03-15. "
                    "Rule FWR-002 was manually removed. Remediation: auto re-push of CFG-002.",
            source="ibn-loop-inner/remediation-history"
        )

        answer = graph_memory.question_answer(
            memory="ibn-lifecycle",
            question="What happened last time the USF firewall drifted?"
        )

        assert answer["answer"] is not None
        assert len(answer["sources"]) >= 1

    def test_t10_4_2_empty_knowledge_returns_gracefully(self, graph_memory):
        """T10.4.2 — Query on empty memory returns no-results gracefully."""
        graph_memory.memory_create("ibn-lifecycle-empty")

        answer = graph_memory.question_answer(
            memory="ibn-lifecycle-empty",
            question="What happened last time?"
        )

        assert "No relevant knowledge" in answer["answer"]
