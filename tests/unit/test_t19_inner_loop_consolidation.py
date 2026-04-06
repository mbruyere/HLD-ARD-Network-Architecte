"""
T19 — Inner Loop + ConsolidationManager + ModelStateController (Unit)
======================================================================
Validates the wired inner loop:
  Agent6 → Agent7 → Agent8 → inner.loop.complete → ConsolidationManager
  → graph_push → Graph-Memory knowledge graph

Also validates ModelStateController:
  legal/illegal transitions, event publication, Neo4j writes,
  full lifecycle: WHAT_IF → CANDIDATE → POR → DEPLOYED → AS_BUILT
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ibn.core.model_state_controller import (
    ModelStateController,
    ModelStateTransitionError,
    ALL_STATES,
)
from ibn.core.consolidation_manager import GRAPH_MEMORY_NAME


# ---------------------------------------------------------------------------
# T19.1  ModelStateController — legal / illegal transitions
# ---------------------------------------------------------------------------

class TestLegalTransitions:

    LEGAL = [
        ("WHAT_IF",   "CANDIDATE"),
        ("CANDIDATE", "POR"),
        ("POR",       "DEPLOYED"),
        ("DEPLOYED",  "AS_BUILT"),
        ("CANDIDATE", "WHAT_IF"),   # rollback
        ("POR",       "CANDIDATE"), # rollback
        ("DEPLOYED",  "POR"),       # rollback
        ("AS_BUILT",  "DEPLOYED"),  # rollback
    ]

    ILLEGAL = [
        ("WHAT_IF",   "POR"),       # skip
        ("WHAT_IF",   "DEPLOYED"),  # skip
        ("CANDIDATE", "AS_BUILT"),  # skip
        ("POR",       "AS_BUILT"),  # skip
        ("AS_BUILT",  "WHAT_IF"),   # too far back
        ("POR",       "WHAT_IF"),   # too far back
    ]

    @pytest.mark.parametrize("from_s,to_s", LEGAL, ids=[f"{f}→{t}" for f, t in LEGAL])
    def test_t19_1_legal_transitions_accepted(self, mock_neo4j, event_bus, from_s, to_s):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.transition("INT-001", from_s, to_s)
        assert result["from_state"] == from_s
        assert result["to_state"] == to_s

    @pytest.mark.parametrize("from_s,to_s", ILLEGAL, ids=[f"{f}→{t}" for f, t in ILLEGAL])
    def test_t19_1_illegal_transitions_rejected(self, mock_neo4j, from_s, to_s):
        ctrl = ModelStateController(mock_neo4j)
        with pytest.raises(ModelStateTransitionError):
            ctrl.transition("INT-001", from_s, to_s)

    def test_t19_1_is_legal_helper(self):
        assert ModelStateController.is_legal("WHAT_IF", "CANDIDATE") is True
        assert ModelStateController.is_legal("WHAT_IF", "POR") is False

    def test_t19_1_case_insensitive(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.transition("INT-001", "what_if", "candidate")
        assert result["from_state"] == "WHAT_IF"
        assert result["to_state"] == "CANDIDATE"


# ---------------------------------------------------------------------------
# T19.2  ModelStateController — event publication
# ---------------------------------------------------------------------------

class TestTransitionEvents:

    def test_t19_2_1_publishes_model_state_transition_event(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.transition("INT-001", "CANDIDATE", "POR")
        events = event_bus.get_events("model.state.transition")
        assert len(events) == 1
        payload = events[0]["payload"]
        assert payload["intent_id"] == "INT-001"
        assert payload["from_state"] == "CANDIDATE"
        assert payload["to_state"] == "POR"

    def test_t19_2_2_event_contains_space_id(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.transition("INT-001", "CANDIDATE", "POR")
        payload = event_bus.get_events("model.state.transition")[0]["payload"]
        assert "ibn-candidate-INT-001" in payload["space_id"]

    def test_t19_2_3_space_override_used_in_event(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.transition("INT-001", "CANDIDATE", "POR", space_id="ibn-candidate-custom")
        payload = event_bus.get_events("model.state.transition")[0]["payload"]
        assert payload["space_id"] == "ibn-candidate-custom"

    def test_t19_2_4_no_event_without_bus(self, mock_neo4j):
        ctrl = ModelStateController(mock_neo4j, event_bus=None)
        # Should not raise even without event bus
        result = ctrl.transition("INT-001", "CANDIDATE", "POR")
        assert result["to_state"] == "POR"

    def test_t19_2_5_transition_id_unique(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        r1 = ctrl.transition("INT-001", "WHAT_IF", "CANDIDATE")
        r2 = ctrl.transition("INT-002", "WHAT_IF", "CANDIDATE")
        assert r1["transition_id"] != r2["transition_id"]


# ---------------------------------------------------------------------------
# T19.3  ModelStateController — convenience helpers
# ---------------------------------------------------------------------------

class TestConvenienceHelpers:

    def test_t19_3_1_approve_transitions_candidate_to_por(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.approve("INT-001")
        assert result["from_state"] == "CANDIDATE"
        assert result["to_state"] == "POR"

    def test_t19_3_2_deploy_transitions_por_to_deployed(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.deploy("INT-001")
        assert result["from_state"] == "POR"
        assert result["to_state"] == "DEPLOYED"

    def test_t19_3_3_verify_transitions_deployed_to_as_built(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.verify("INT-001")
        assert result["from_state"] == "DEPLOYED"
        assert result["to_state"] == "AS_BUILT"

    def test_t19_3_4_rollback_deployed_to_por(self, mock_neo4j, event_bus):
        ctrl = ModelStateController(mock_neo4j, event_bus)
        result = ctrl.rollback("INT-001", from_state="DEPLOYED")
        assert result["to_state"] == "POR"

    def test_t19_3_5_space_for_helper(self):
        assert ModelStateController.space_for("CANDIDATE", "INT-001") == "ibn-candidate-INT-001"
        assert ModelStateController.space_for("POR", "INT-999") == "ibn-por-INT-999"


# ---------------------------------------------------------------------------
# T19.4  ModelStateController → ConsolidationManager integration
# ---------------------------------------------------------------------------

class TestStateTransitionTriggersConsolidation:

    def test_t19_4_1_por_transition_triggers_consolidation_and_push(
        self, mock_neo4j, event_bus, live_memory, graph_memory
    ):
        """CANDIDATE→POR: ConsolidationManager consolidates and pushes to Graph-Memory."""
        from ibn.core.consolidation_manager import ConsolidationManager

        space_id = "ibn-candidate-INT-001"
        live_memory.space_create(space_id)
        live_memory.live_note(space_id, "Policy decision: zone-based FW for VLAN 140", "decision")
        live_memory.live_note(space_id, "Validation: 4 rules, no conflicts", "observation")

        mgr = ConsolidationManager(
            live_memory=live_memory,
            graph_memory=graph_memory,
            event_bus=event_bus,
            sweep_interval=0,
        )
        mgr.start()

        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.transition("INT-001", "CANDIDATE", "POR", space_id=space_id)

        mgr.stop()

        # Notes consumed
        assert len(live_memory.note_list(space_id)) == 0
        # Entities pushed to Graph-Memory
        assert len(graph_memory.entities) >= 1

    def test_t19_4_2_as_built_transition_pushes_to_graph(
        self, mock_neo4j, event_bus, live_memory, graph_memory
    ):
        """DEPLOYED→AS_BUILT triggers push (compliance verified)."""
        from ibn.core.consolidation_manager import ConsolidationManager

        space_id = "ibn-deploy-INT-001"
        live_memory.space_create(space_id)
        live_memory.live_note(space_id, "Deployment narrative: 47 rules pushed", "progress")

        mgr = ConsolidationManager(live_memory, graph_memory, event_bus, sweep_interval=0)
        mgr.start()

        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.verify("INT-001", space_id=space_id)

        mgr.stop()

        assert len(graph_memory.entities) >= 1

    def test_t19_4_3_candidate_transition_no_push(
        self, mock_neo4j, event_bus, live_memory, graph_memory
    ):
        """WHAT_IF→CANDIDATE: consolidates but does NOT push (CANDIDATE not POR-eligible)."""
        from ibn.core.consolidation_manager import ConsolidationManager

        space_id = "ibn-whatif-INT-001"
        live_memory.space_create(space_id)
        live_memory.live_note(space_id, "What-if analysis: adding 200 users to VLAN 100", "observation")

        mgr = ConsolidationManager(live_memory, graph_memory, event_bus, sweep_interval=0)
        mgr.start()

        ctrl = ModelStateController(mock_neo4j, event_bus)
        ctrl.transition("INT-001", "WHAT_IF", "CANDIDATE", space_id=space_id)

        mgr.stop()

        # Consolidated
        assert len(live_memory.note_list(space_id)) == 0
        # NOT pushed (CANDIDATE ∉ push-eligible)
        assert len(graph_memory.entities) == 0


# ---------------------------------------------------------------------------
# T19.5  InnerLoop wiring
# ---------------------------------------------------------------------------

class TestInnerLoopWiring:

    def test_t19_5_1_inner_loop_has_consolidation_manager(self):
        """InnerLoop creates a ConsolidationManager on init."""
        from ibn.agents.inner_loop import InnerLoop
        from ibn.core.consolidation_manager import ConsolidationManager

        neo4j = MagicMock()
        neo4j.run_query.return_value = []
        lm = MagicMock()
        lm.live_note.return_value = {}
        gm = MagicMock()
        gm.memory_list.return_value = []
        gm.memory_create.return_value = {}

        loop = InnerLoop(neo4j, lm, graph_memory=gm)
        assert hasattr(loop, "consolidation")
        assert isinstance(loop.consolidation, ConsolidationManager)

    def test_t19_5_2_start_starts_consolidation(self):
        """InnerLoop.start() starts the ConsolidationManager."""
        from ibn.agents.inner_loop import InnerLoop

        neo4j = MagicMock()
        neo4j.run_query.return_value = []
        lm = MagicMock()
        lm.live_note.return_value = {}
        gm = MagicMock()
        gm.memory_list.return_value = []
        gm.memory_create.return_value = {}

        loop = InnerLoop(neo4j, lm, graph_memory=gm)
        loop.consolidation.start = MagicMock()
        loop.consolidation.stop = MagicMock()

        loop.start()
        loop.consolidation.start.assert_called_once()

        loop.stop()
        loop.consolidation.stop.assert_called_once()

    def test_t19_5_3_run_cycle_emits_inner_loop_complete(self, event_bus):
        """run_cycle() emits inner.loop.complete event after completing."""
        from ibn.agents.inner_loop import InnerLoop

        neo4j = MagicMock()
        neo4j.run_query.return_value = []
        lm = MagicMock()
        lm.live_note.return_value = {}
        gm = MagicMock()
        gm.memory_list.return_value = []

        loop = InnerLoop(neo4j, lm, event_bus=event_bus, graph_memory=gm)
        loop.run_cycle(site_id="SITE-HQ-01")

        events = event_bus.get_events("inner.loop.complete")
        assert len(events) == 1
        assert events[0]["payload"]["site_id"] == "SITE-HQ-01"

    def test_t19_5_4_inner_loop_complete_triggers_consolidation(
        self, event_bus, live_memory, graph_memory
    ):
        """inner.loop.complete event triggers ConsolidationManager."""
        from ibn.core.consolidation_manager import ConsolidationManager

        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift: FWR-002 missing", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Remediation: re-push CFG-002", "remediation")

        mgr = ConsolidationManager(live_memory, graph_memory, event_bus, sweep_interval=0)
        mgr.start()

        # Simulate inner loop completion
        event_bus.publish("inner.loop.complete", {"site_id": "SITE-HQ-01"})

        mgr.stop()

        # Notes consumed, entities pushed
        assert len(live_memory.note_list("ibn-loop-inner")) == 0
        assert len(graph_memory.entities) >= 1


# ---------------------------------------------------------------------------
# T19.6  Full Phase 2 lifecycle (mocked end-to-end)
# ---------------------------------------------------------------------------

class TestFullPhase2Lifecycle:

    def test_t19_6_1_intent_lifecycle_what_if_to_as_built(
        self, mock_neo4j, event_bus, live_memory, graph_memory
    ):
        """
        Mocked end-to-end: WHAT_IF → CANDIDATE → POR → DEPLOYED → AS_BUILT
        At each eligible transition (POR, DEPLOYED, AS_BUILT),
        bank files are pushed to Graph-Memory.
        """
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(live_memory, graph_memory, event_bus, sweep_interval=0)
        mgr.start()

        ctrl = ModelStateController(mock_neo4j, event_bus)

        def seed_and_transition(from_s: str, to_s: str, intent_id: str, notes: list[str]):
            space_id = ModelStateController.space_for(from_s, intent_id)
            live_memory.space_create(space_id)
            for n in notes:
                live_memory.live_note(space_id, n, "general")
            ctrl.transition(intent_id, from_s, to_s, space_id=space_id)
            return space_id

        # WHAT_IF → CANDIDATE  (no graph push)
        entities_before = len(graph_memory.entities)
        seed_and_transition("WHAT_IF", "CANDIDATE", "INT-001", [
            "What-if: add 200 users to VLAN 100. Blast radius: 3 devices."
        ])
        assert len(graph_memory.entities) == entities_before  # no push

        # CANDIDATE → POR  (push triggered)
        seed_and_transition("CANDIDATE", "POR", "INT-001", [
            "Decision: zone-based FW for VLAN 140.",
            "Validation: 4 rules, no conflicts.",
        ])
        assert len(graph_memory.entities) > entities_before  # pushed

        entities_after_por = len(graph_memory.entities)

        # POR → DEPLOYED  (push triggered)
        seed_and_transition("POR", "DEPLOYED", "INT-001", [
            "Deployment: 47 rules pushed to usf-fw-01. Verified.",
        ])
        assert len(graph_memory.entities) > entities_after_por

        entities_after_deploy = len(graph_memory.entities)

        # DEPLOYED → AS_BUILT  (push triggered)
        seed_and_transition("DEPLOYED", "AS_BUILT", "INT-001", [
            "As-built: compliance 100%. No drift detected.",
        ])
        assert len(graph_memory.entities) > entities_after_deploy

        mgr.stop()

        # Knowledge queryable
        answer = mgr.query_knowledge("What deployment was done for INT-001?")
        assert answer["answer"] is not None

    def test_t19_6_2_inner_loop_remediation_builds_knowledge(
        self, event_bus, live_memory, graph_memory
    ):
        """
        Inner loop remediation cycles accumulate knowledge in Graph-Memory.
        Each inner.loop.complete event pushes drift/remediation narratives.
        """
        from ibn.core.consolidation_manager import ConsolidationManager

        mgr = ConsolidationManager(live_memory, graph_memory, event_bus, sweep_interval=0)
        mgr.start()

        # Simulate 3 inner loop cycles
        live_memory.space_create("ibn-loop-inner")
        for i in range(3):
            live_memory.live_note(
                "ibn-loop-inner",
                f"Cycle {i}: drift FWR-{100+i} missing on usf-fw-01. Remediated.",
                "drift-detection",
            )
            event_bus.publish("inner.loop.complete", {"cycle": i})

        mgr.stop()

        # All notes consumed across 3 consolidations
        assert len(live_memory.note_list("ibn-loop-inner")) == 0
        # Entities built up
        assert len(graph_memory.entities) >= 1

        answer = mgr.query_knowledge("What drift events occurred in the inner loop?")
        assert answer["answer"] is not None
        assert len(answer["sources"]) >= 1
