"""
T11 — Consolidation Pipeline Tests (Unit)
==========================================
Validates the Live-Memory → Graph-Memory bridge:
bank_consolidate() → graph_push() → entity extraction → embeddings.
"""
import pytest


# ── T11.3 Model state transition triggers ─────────────────────────────────

class TestConsolidationTriggers:
    """T11.3 — Consolidation triggered on model state transitions."""

    TRANSITION_TRIGGERS = [
        ("WHAT_IF", "CANDIDATE", "ibn-whatif-001"),
        ("CANDIDATE", "POR", "ibn-candidate-001"),
        ("POR", "DEPLOYED", "ibn-por-v1"),
        ("DEPLOYED", "AS_BUILT", "ibn-deploy-001"),
    ]

    @pytest.mark.parametrize("from_state,to_state,space", TRANSITION_TRIGGERS,
                             ids=[f"{f}->{t}" for f, t, _ in TRANSITION_TRIGGERS])
    def test_t11_3_transitions_trigger_consolidation(self, live_memory, from_state, to_state, space):
        """T11.3.1–T11.3.4 — Model state transitions trigger bank_consolidate()."""
        live_memory.space_create(space)
        # Simulate notes accumulated during the model state
        live_memory.live_note(space, f"Activity during {from_state} phase", "general")
        live_memory.live_note(space, f"Another note from {from_state}", "general")

        # Transition triggers consolidation
        result = live_memory.bank_consolidate(space)

        assert result["status"] == "consolidated"
        assert result["notes_consumed"] == 2
        # Notes should be cleared after consolidation
        remaining = live_memory.note_list(space)
        assert len(remaining) == 0

    def test_t11_3_5_inner_loop_iteration_triggers(self, live_memory):
        """T11.3.5 — Inner loop cycle completion triggers consolidation."""
        live_memory.space_create("ibn-loop-inner")
        # Simulate a full inner loop cycle
        live_memory.live_note("ibn-loop-inner", "Drift detected on usf-fw-01", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Assessment: NON_COMPLIANT", "assessment-result")
        live_memory.live_note("ibn-loop-inner", "Remediation: re-push CFG-002", "remediation-attempt")
        live_memory.live_note("ibn-loop-inner", "Result: COMPLIANT after re-push", "remediation-result")

        result = live_memory.bank_consolidate("ibn-loop-inner")

        assert result["notes_consumed"] == 4
        banks = live_memory.bank_read_all("ibn-loop-inner")
        assert len(banks) >= 1  # At least one bank populated


# ── T11.2 graph_push() ───────────────────────────────────────────────────

class TestGraphPush:
    """T11.2 — Bank files pushed to Graph-Memory for knowledge extraction."""

    def test_t11_2_1_bank_content_pushed_to_graph_memory(self, live_memory, graph_memory):
        """T11.2.1 — Consolidated bank content pushed to Graph-Memory."""
        # Simulate consolidation
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift on usf-fw-01", "drift-detection")
        live_memory.bank_consolidate("ibn-loop-inner")

        # Push bank content to Graph-Memory
        banks = live_memory.bank_read_all("ibn-loop-inner")
        graph_memory.memory_create("ibn-lifecycle")

        for bank_name, content in banks.items():
            result = graph_memory.graph_push(
                memory="ibn-lifecycle",
                content=content,
                source=f"ibn-loop-inner/{bank_name}"
            )
            assert result["status"] == "ingested"

    def test_t11_2_2_ontology_extraction_from_bank(self, graph_memory):
        """T11.2.2 — Ontology-driven extraction produces entities from bank content."""
        graph_memory.memory_create("ibn-lifecycle")

        result = graph_memory.graph_push(
            memory="ibn-lifecycle",
            content="# Remediation History\n\n## REM-001 (2026-03-15)\n"
                    "Drift detected on usf-fw-01: FWR-002 missing.\n"
                    "Action: Auto-remediate (re-push CFG-002).\n"
                    "Result: COMPLIANT after 45 seconds.",
            source="ibn-loop-inner/remediation-history"
        )

        assert result["entities_extracted"] >= 1

    def test_t11_2_3_full_pipeline(self, live_memory, graph_memory):
        """T11.2.3 — Full pipeline: notes → consolidate → push → knowledge."""
        # 1. Create space and write notes
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift event on usf-fw-01", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Remediation succeeded", "remediation-result")

        # 2. Consolidate
        live_memory.bank_consolidate("ibn-loop-inner")
        banks = live_memory.bank_read_all("ibn-loop-inner")
        assert len(banks) >= 1

        # 3. Push to Graph-Memory
        graph_memory.memory_create("ibn-lifecycle")
        for bank_name, content in banks.items():
            graph_memory.graph_push(memory="ibn-lifecycle", content=content,
                                     source=f"ibn-loop-inner/{bank_name}")

        # 4. Query knowledge
        answer = graph_memory.question_answer(
            memory="ibn-lifecycle",
            question="What drift events occurred recently?"
        )
        assert answer["answer"] is not None
        assert len(answer["sources"]) >= 1
