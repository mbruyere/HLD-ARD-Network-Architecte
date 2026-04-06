"""
T18 — ConsolidationManager Unit Tests
=======================================
Tests the consolidation pipeline orchestrator with MockLiveMemoryClient and
MockGraphMemoryClient from conftest.py.  No real MCP servers required.

Validates:
  - on_model_state_transition: consolidate + conditional graph push
  - on_inner_loop_complete: consolidates ibn-loop-inner
  - check_note_threshold: auto-triggers below / at / above threshold
  - _ensure_memory_exists: creates memory if absent
  - Event bus subscription and dispatch
  - query_knowledge: delegates to GraphMemoryClient
  - ConsolidationResult fields
  - Error handling: consolidation failure, graph push failure
"""

from __future__ import annotations

import pytest

from ibn.core.consolidation_manager import (
    ConsolidationManager,
    ConsolidationResult,
    GRAPH_MEMORY_NAME,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr(live_memory, graph_memory, event_bus):
    """ConsolidationManager with mock dependencies and graph push enabled."""
    return ConsolidationManager(
        live_memory=live_memory,
        graph_memory=graph_memory,
        event_bus=event_bus,
        note_threshold=3,
        sweep_interval=0,   # disable periodic sweep in tests
        push_to_graph=True,
    )


@pytest.fixture
def mgr_no_push(live_memory, graph_memory, event_bus):
    """ConsolidationManager with graph push disabled."""
    return ConsolidationManager(
        live_memory=live_memory,
        graph_memory=graph_memory,
        event_bus=event_bus,
        note_threshold=3,
        sweep_interval=0,
        push_to_graph=False,
    )


def _seed_space(live_memory, space_id: str, note_count: int = 2):
    """Create a space and write *note_count* notes."""
    live_memory.space_create(space_id)
    for i in range(note_count):
        live_memory.live_note(space_id, f"Note {i} in {space_id}", "general")


# ---------------------------------------------------------------------------
# T18.1  ConsolidationResult dataclass
# ---------------------------------------------------------------------------

class TestConsolidationResult:

    def test_t18_1_1_ok_on_no_error(self):
        r = ConsolidationResult(
            space_id="s", notes_consumed=2, banks_updated=1,
            pushed_to_graph=True
        )
        assert r.ok is True

    def test_t18_1_2_not_ok_on_error(self):
        r = ConsolidationResult(
            space_id="s", notes_consumed=0, banks_updated=0,
            pushed_to_graph=False, error="transport failed"
        )
        assert r.ok is False
        assert "transport" in r.error

    def test_t18_1_3_repr_contains_space_and_status(self):
        r = ConsolidationResult(
            space_id="ibn-loop-inner", notes_consumed=4, banks_updated=1,
            pushed_to_graph=True
        )
        s = repr(r)
        assert "ibn-loop-inner" in s
        assert "notes=4" in s


# ---------------------------------------------------------------------------
# T18.2  on_model_state_transition
# ---------------------------------------------------------------------------

class TestModelStateTransition:

    def test_t18_2_1_consolidates_space(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-candidate-001", note_count=2)
        result = mgr.on_model_state_transition("CANDIDATE", "POR", "ibn-candidate-001")
        assert result.notes_consumed == 2
        assert result.ok

    def test_t18_2_2_pushes_to_graph_when_to_state_is_por(self, mgr, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-candidate-001", note_count=2)
        result = mgr.on_model_state_transition("CANDIDATE", "POR", "ibn-candidate-001")
        assert result.pushed_to_graph is True
        assert len(graph_memory.entities) >= 1

    def test_t18_2_3_pushes_to_graph_when_to_state_is_deployed(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-por-v1", note_count=2)
        result = mgr.on_model_state_transition("POR", "DEPLOYED", "ibn-por-v1")
        assert result.pushed_to_graph is True

    def test_t18_2_4_pushes_to_graph_when_to_state_is_as_built(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-deploy-001", note_count=2)
        result = mgr.on_model_state_transition("DEPLOYED", "AS_BUILT", "ibn-deploy-001")
        assert result.pushed_to_graph is True

    def test_t18_2_5_does_not_push_for_what_if_to_candidate(self, mgr, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-whatif-001", note_count=2)
        result = mgr.on_model_state_transition("WHAT_IF", "CANDIDATE", "ibn-whatif-001")
        # CANDIDATE is not in _PUSH_ELIGIBLE_STATES
        assert result.pushed_to_graph is False
        assert len(graph_memory.entities) == 0

    def test_t18_2_6_push_override_true_forces_push(self, mgr, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-whatif-001", note_count=2)
        result = mgr.on_model_state_transition(
            "WHAT_IF", "CANDIDATE", "ibn-whatif-001", push_override=True
        )
        assert result.pushed_to_graph is True

    def test_t18_2_7_push_override_false_prevents_push(self, mgr, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-candidate-001", note_count=2)
        result = mgr.on_model_state_transition(
            "CANDIDATE", "POR", "ibn-candidate-001", push_override=False
        )
        assert result.pushed_to_graph is False

    def test_t18_2_8_no_notes_returns_ok_result(self, mgr, live_memory):
        live_memory.space_create("ibn-candidate-empty")
        result = mgr.on_model_state_transition("CANDIDATE", "POR", "ibn-candidate-empty")
        assert result.ok is True
        assert result.notes_consumed == 0


# ---------------------------------------------------------------------------
# T18.3  on_inner_loop_complete
# ---------------------------------------------------------------------------

class TestInnerLoopComplete:

    def test_t18_3_1_consolidates_ibn_loop_inner(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-loop-inner", note_count=4)
        result = mgr.on_inner_loop_complete()
        assert result.space_id == "ibn-loop-inner"
        assert result.notes_consumed == 4

    def test_t18_3_2_pushes_to_graph(self, mgr, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-loop-inner", note_count=2)
        result = mgr.on_inner_loop_complete()
        assert result.pushed_to_graph is True

    def test_t18_3_3_no_push_when_disabled(self, mgr_no_push, live_memory, graph_memory):
        _seed_space(live_memory, "ibn-loop-inner", note_count=2)
        result = mgr_no_push.on_inner_loop_complete()
        assert result.pushed_to_graph is False
        assert len(graph_memory.entities) == 0


# ---------------------------------------------------------------------------
# T18.4  check_note_threshold
# ---------------------------------------------------------------------------

class TestNoteThreshold:

    def test_t18_4_1_no_trigger_below_threshold(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-asbuilt-001", note_count=2)  # threshold=3
        result = mgr.check_note_threshold("ibn-asbuilt-001")
        assert result is None  # not triggered
        # Notes should remain unconsumed
        assert len(live_memory.note_list("ibn-asbuilt-001")) == 2

    def test_t18_4_2_triggers_at_threshold(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-asbuilt-001", note_count=3)  # exactly threshold
        result = mgr.check_note_threshold("ibn-asbuilt-001")
        assert result is not None
        assert result.notes_consumed == 3

    def test_t18_4_3_triggers_above_threshold(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-asbuilt-001", note_count=10)
        result = mgr.check_note_threshold("ibn-asbuilt-001")
        assert result is not None
        assert result.notes_consumed == 10

    def test_t18_4_4_notes_cleared_after_threshold_trigger(self, mgr, live_memory):
        _seed_space(live_memory, "ibn-asbuilt-001", note_count=5)
        mgr.check_note_threshold("ibn-asbuilt-001")
        assert len(live_memory.note_list("ibn-asbuilt-001")) == 0


# ---------------------------------------------------------------------------
# T18.5  _ensure_memory_exists
# ---------------------------------------------------------------------------

class TestEnsureMemory:

    def test_t18_5_1_creates_memory_when_absent(self, mgr, graph_memory):
        # graph_memory has no memories yet
        mgr._ensure_memory_exists()
        assert GRAPH_MEMORY_NAME in graph_memory.memories

    def test_t18_5_2_does_not_duplicate_existing_memory(self, mgr, graph_memory):
        graph_memory.memory_create(GRAPH_MEMORY_NAME)
        initial_count = len(graph_memory.memories)
        mgr._ensure_memory_exists()
        assert len(graph_memory.memories) == initial_count


# ---------------------------------------------------------------------------
# T18.6  Event bus integration
# ---------------------------------------------------------------------------

class TestEventBus:

    def test_t18_6_1_subscribes_to_state_transition_on_start(self, mgr, event_bus):
        mgr.start()
        assert "model.state.transition" in event_bus.subscriptions
        mgr.stop()

    def test_t18_6_2_subscribes_to_inner_loop_complete_on_start(self, mgr, event_bus):
        mgr.start()
        assert "inner.loop.complete" in event_bus.subscriptions
        mgr.stop()

    def test_t18_6_3_state_transition_event_triggers_consolidation(
        self, mgr, event_bus, live_memory
    ):
        _seed_space(live_memory, "ibn-candidate-001", note_count=2)
        mgr.start()
        event_bus.publish("model.state.transition", {
            "from_state": "CANDIDATE",
            "to_state": "POR",
            "space_id": "ibn-candidate-001",
        })
        mgr.stop()
        # Notes should have been consumed
        assert len(live_memory.note_list("ibn-candidate-001")) == 0

    def test_t18_6_4_inner_loop_event_triggers_ibn_loop_inner(
        self, mgr, event_bus, live_memory
    ):
        _seed_space(live_memory, "ibn-loop-inner", note_count=2)
        mgr.start()
        event_bus.publish("inner.loop.complete", {})
        mgr.stop()
        assert len(live_memory.note_list("ibn-loop-inner")) == 0

    def test_t18_6_5_missing_fields_does_not_raise(self, mgr, event_bus):
        mgr.start()
        # Malformed event — should not raise
        event_bus.publish("model.state.transition", {"incomplete": True})
        mgr.stop()


# ---------------------------------------------------------------------------
# T18.7  query_knowledge
# ---------------------------------------------------------------------------

class TestQueryKnowledge:

    def test_t18_7_1_delegates_to_graph_memory(self, mgr, graph_memory):
        graph_memory.memory_create(GRAPH_MEMORY_NAME)
        graph_memory.graph_push(
            GRAPH_MEMORY_NAME,
            "Drift on usf-fw-01 on 2026-03-15 — rule FWR-002 missing",
            source="ibn-loop-inner/drift",
        )
        answer = mgr.query_knowledge("What caused the last drift?")
        assert answer["answer"] is not None

    def test_t18_7_2_empty_knowledge_returns_gracefully(self, mgr, graph_memory):
        answer = mgr.query_knowledge("What happened?")
        assert "No relevant knowledge" in answer["answer"]


# ---------------------------------------------------------------------------
# T18.8  Full pipeline integration (mock end-to-end)
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_t18_8_1_notes_to_graph_push_full_path(self, mgr, live_memory, graph_memory):
        """
        Full pipeline test (mocked):
        write notes → consolidate → graph push → query
        """
        # 1. Simulate A7/A8 writing notes to ibn-loop-inner
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift on usf-fw-01: FWR-002 missing", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Root cause: manual CLI edit", "assessment")
        live_memory.live_note("ibn-loop-inner", "Action: RE_ORCHESTRATE (MEDIUM)", "remediation")
        live_memory.live_note("ibn-loop-inner", "Result: COMPLIANT after 45s", "remediation-result")

        # 2. Inner loop completes → triggers consolidation + graph push
        result = mgr.on_inner_loop_complete()

        assert result.ok
        assert result.notes_consumed == 4
        assert result.pushed_to_graph is True
        assert len(result.push_results) >= 1

        # 3. Knowledge now queryable
        answer = mgr.query_knowledge("What drift events occurred recently?")
        assert answer["answer"] is not None
        assert len(answer["sources"]) >= 1

    def test_t18_8_2_candidate_to_por_full_path(self, mgr, live_memory, graph_memory):
        """Candidate→POR transition consolidates and pushes approval audit trail."""
        live_memory.space_create("ibn-candidate-001")
        live_memory.live_note(
            "ibn-candidate-001",
            "Decision: zone-based FW policy for Guest VLAN 140 — RFC 9315 §5.1.2",
            "decision",
        )
        live_memory.live_note(
            "ibn-candidate-001",
            "Validation: 4 FW rules generated, no conflicts detected",
            "observation",
        )

        result = mgr.on_model_state_transition("CANDIDATE", "POR", "ibn-candidate-001")

        assert result.ok
        assert result.pushed_to_graph is True
        assert result.notes_consumed == 2
        assert GRAPH_MEMORY_NAME in graph_memory.memories
