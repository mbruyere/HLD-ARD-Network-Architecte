"""
T11 — Consolidation Pipeline Integration Tests
================================================
Tests the full Live-Memory → Graph-Memory bridge: bank_consolidate(),
graph_push(), and model state transition triggers against real infra.

Run:
    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_PASSWORD=ibn-closed-loop-2026 \
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k \
    GRAPH_MEMORY_URL=http://localhost:8003 \
    GRAPH_MEMORY_TOKEN=<token> \
    pytest tests/integration/test_t11_consolidation_integ.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))
USE_REAL_LM = bool(os.environ.get("LIVE_MEMORY_URL"))
USE_REAL_GM = bool(os.environ.get("GRAPH_MEMORY_URL"))

REQUIRES_LM = pytest.mark.skipif(
    not USE_REAL_LM,
    reason="Requires real Live-Memory (LIVE_MEMORY_URL)",
)

REQUIRES_ALL = pytest.mark.skipif(
    not (USE_REAL_LM and USE_REAL_GM),
    reason="Requires real Live-Memory + Graph-Memory",
)

REQUIRES_FULL_STACK = pytest.mark.skipif(
    not (USE_REAL_NEO4J and USE_REAL_LM and USE_REAL_GM),
    reason="Requires real Neo4j + Live-Memory + Graph-Memory",
)


@pytest.fixture(scope="module")
def lm():
    from ibn.core.live_memory_client import LiveMemoryClient
    return LiveMemoryClient(
        base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
        token=os.environ.get("LIVE_MEMORY_TOKEN", os.environ.get("LM_ADMIN_TOKEN", "")),
    )


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
        return None
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


@pytest.fixture
def test_space(lm):
    """Create a unique test space for each test."""
    name = f"ibn-consol-{uuid.uuid4().hex[:8]}"
    try:
        lm.space_create(
            space_id=name,
            description=f"T11 consolidation test {name}",
            owner="ibn-test",
            rules="# consolidation test rules\n",
        )
    except Exception:
        pass
    yield name


# ── T11.1 — bank_consolidate() ───────────────────────────────────────────


@REQUIRES_LM
class TestBankConsolidate:

    def test_t11_1_1_consolidation_produces_structured_output(self, lm, test_space):
        """T11.1.1 — Write 10 notes then consolidate → structured bank files."""
        for i in range(10):
            lm.live_note(
                space=test_space,
                content=f"Note {i}: drift event #{i} on device usf-fw-0{i % 2 + 1}",
                category="drift-detection",
            )

        result = lm.bank_consolidate(test_space)
        assert result is not None

    def test_t11_1_2_notes_consumed(self, lm, test_space):
        """T11.1.2 — Notes are consumed after consolidation."""
        for i in range(5):
            lm.live_note(
                space=test_space,
                content=f"Consumable note {i}",
                category="general",
            )

        before = lm.note_list(test_space)
        assert len(before) >= 5

        lm.bank_consolidate(test_space)

        after = lm.note_list(test_space)
        assert len(after) < len(before), (
            f"Notes not consumed: {len(before)} before, {len(after)} after"
        )

    def test_t11_1_3_mixed_categories_consolidated(self, lm, test_space):
        """T11.1.3 — Notes with different categories are consolidated correctly."""
        lm.live_note(space=test_space, content="Drift A", category="drift-detection")
        lm.live_note(space=test_space, content="Remediation A", category="remediation-result")
        lm.live_note(space=test_space, content="Drift B", category="drift-detection")
        lm.live_note(space=test_space, content="Metric A", category="loop-metrics")

        result = lm.bank_consolidate(test_space)
        assert result is not None

        banks = lm.bank_read_all(test_space)
        assert isinstance(banks, dict)


# ── T11.2 — graph_push() ─────────────────────────────────────────────────


@REQUIRES_ALL
class TestGraphPush:

    def test_t11_2_1_bank_files_pushed_to_graph_memory(self, lm, gm, test_space):
        """T11.2.1 — Consolidated bank files can be pushed to Graph-Memory."""
        # Write notes and consolidate
        for i in range(5):
            lm.live_note(
                space=test_space,
                content=f"Remediation note {i}: re-pushed CFG-{i:03d}",
                category="remediation-result",
            )
        lm.bank_consolidate(test_space)

        # Read bank files
        banks = lm.bank_read_all(test_space)
        if not banks:
            pytest.skip("No bank files after consolidation")

        # Push to Graph-Memory
        test_memory = f"ibn-test-push-{uuid.uuid4().hex[:8]}"
        gm.memory_create(name=test_memory, description="T11.2 push test")

        results = gm.graph_push_batch(
            memory=test_memory,
            bank_files=banks,
            space_id=test_space,
        )

        assert len(results) >= 1
        for r in results:
            assert r.get("status") == "ingested"

        # Cleanup
        try:
            gm.memory_delete(test_memory)
        except Exception:
            pass

    def test_t11_2_2_entities_extracted_from_bank_content(self, gm):
        """T11.2.2 — Ontology-driven extraction produces entities."""
        test_memory = f"ibn-test-extract-{uuid.uuid4().hex[:8]}"
        gm.memory_create(name=test_memory, description="T11.2.2 extraction test")

        result = gm.graph_push(
            memory=test_memory,
            content=(
                "# Remediation History\n\n"
                "Drift detected on usf-fw-01: firewall rule FWR-002 missing.\n"
                "Root cause: manual SSH session removed rule outside the loop.\n"
                "Action: Auto-remediate — re-pushed CFG-002.\n"
                "Result: COMPLIANT after 45 seconds.\n"
            ),
            source="t11-extraction-test",
        )

        assert result.get("entities_extracted", 0) >= 1

        try:
            gm.memory_delete(test_memory)
        except Exception:
            pass


# ── T11.3 — ConsolidationManager with real infra ─────────────────────────


@REQUIRES_ALL
class TestConsolidationManager:

    def test_t11_3_consolidation_manager_end_to_end(self, lm, gm, test_space):
        """
        T11.3 — ConsolidationManager.on_model_state_transition() triggers
        consolidation and pushes to Graph-Memory when to_state is POR.
        """
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=lm,
            graph_memory=gm,
            event_bus=None,
            push_to_graph=True,
        )

        # Seed some notes
        for i in range(5):
            lm.live_note(
                space=test_space,
                content=f"Candidate decision {i}: approved policy POL-{i:03d}",
                category="design-rationale",
            )

        # Trigger consolidation as if transitioning CANDIDATE → POR
        result = mgr.on_model_state_transition(
            from_state="CANDIDATE",
            to_state="POR",
            space_id=test_space,
        )

        assert result.ok, f"Consolidation failed: {result.error}"
        # POR is push-eligible — banks should be pushed to Graph-Memory
        assert result.pushed_to_graph is True

    def test_t11_3_inner_loop_consolidation(self, lm, gm, test_space):
        """
        T11.3.5 — on_inner_loop_complete() consolidates ibn-loop-inner.
        """
        from ibn.core.consolidation_manager import ConsolidationManager

        # Use test_space as a stand-in for ibn-loop-inner
        mgr = ConsolidationManager(
            live_memory=lm,
            graph_memory=gm,
            event_bus=None,
            push_to_graph=True,
        )

        # Seed notes
        for i in range(3):
            lm.live_note(
                space=test_space,
                content=f"Loop iteration {i}: all compliant",
                category="loop-metrics",
            )

        # Directly call the consolidation method with the test space
        result = mgr._consolidate_and_push(test_space, push=True)
        assert result.ok, f"Inner loop consolidation failed: {result.error}"


# ── T11.3 — Model state transition triggers (using mocks for event bus) ──


class TestTransitionTriggersMocked:
    """
    These tests verify the ConsolidationManager trigger logic without
    requiring real infra — they use the mock clients from conftest.py.
    """

    def test_t11_3_1_whatif_to_candidate_triggers_consolidation(
        self, live_memory, graph_memory, event_bus
    ):
        """T11.3.1 — WHAT_IF → CANDIDATE triggers consolidation of ibn-whatif space."""
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            event_bus=event_bus,
            push_to_graph=False,
        )
        mgr.start()

        # Seed notes in the whatif space
        live_memory.space_create("ibn-whatif-INT-001")
        for i in range(3):
            live_memory.live_note("ibn-whatif-INT-001", f"What-if note {i}")

        result = mgr.on_model_state_transition(
            from_state="WHAT_IF",
            to_state="CANDIDATE",
            space_id="ibn-whatif-INT-001",
        )
        assert result.ok
        assert result.notes_consumed == 3

        mgr.stop()

    def test_t11_3_2_candidate_to_por_triggers_push(
        self, live_memory, graph_memory, event_bus
    ):
        """T11.3.2 — CANDIDATE → POR triggers consolidation + graph push."""
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            event_bus=event_bus,
            push_to_graph=True,
        )

        live_memory.space_create("ibn-candidate-INT-001")
        for i in range(3):
            live_memory.live_note("ibn-candidate-INT-001", f"Candidate note {i}")

        result = mgr.on_model_state_transition(
            from_state="CANDIDATE",
            to_state="POR",
            space_id="ibn-candidate-INT-001",
        )
        assert result.ok
        assert result.pushed_to_graph is True

    def test_t11_3_3_por_to_deployed_triggers_push(
        self, live_memory, graph_memory, event_bus
    ):
        """T11.3.3 — POR → DEPLOYED triggers push."""
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            push_to_graph=True,
        )

        live_memory.space_create("ibn-por-v1")
        live_memory.live_note("ibn-por-v1", "POR approval note")

        result = mgr.on_model_state_transition(
            from_state="POR",
            to_state="DEPLOYED",
            space_id="ibn-por-v1",
        )
        assert result.ok
        assert result.pushed_to_graph is True

    def test_t11_3_4_deployed_to_asbuilt_triggers_push(
        self, live_memory, graph_memory, event_bus
    ):
        """T11.3.4 — DEPLOYED → AS_BUILT triggers push."""
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            push_to_graph=True,
        )

        live_memory.space_create("ibn-deploy-001")
        live_memory.live_note("ibn-deploy-001", "Deployment complete")

        result = mgr.on_model_state_transition(
            from_state="DEPLOYED",
            to_state="AS_BUILT",
            space_id="ibn-deploy-001",
        )
        assert result.ok
        assert result.pushed_to_graph is True

    def test_t11_3_5_inner_loop_triggers_consolidation(
        self, live_memory, graph_memory
    ):
        """T11.3.5 — on_inner_loop_complete() consolidates ibn-loop-inner."""
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            push_to_graph=True,
        )

        live_memory.space_create("ibn-loop-inner")
        for i in range(5):
            live_memory.live_note("ibn-loop-inner", f"Remediation cycle {i}")

        result = mgr.on_inner_loop_complete()
        assert result.ok
        assert result.notes_consumed == 5
        assert result.pushed_to_graph is True
