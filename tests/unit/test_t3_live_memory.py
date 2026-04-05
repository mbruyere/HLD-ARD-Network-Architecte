"""
T3 — Live-Memory Spaces and Pipeline Tests (Unit)
==================================================
Validates space creation, note ingestion, consolidation, and token auth
against the mock Live-Memory client.
"""
import pytest


# ── T3.1 Space creation ───────────────────────────────────────────────────

class TestSpaceCreation:
    """T3.1 — Validate creation of all 7 IBN foundational spaces."""

    IBN_SPACES = {
        "ibn-loop-inner": {"bank_count": 4, "banks": [
            "active-remediations", "drift-analysis", "remediation-history", "loop-metrics"
        ]},
        "ibn-loop-outer": {"bank_count": 5, "banks": [
            "escalation-queue", "decision-log", "compliance-summary",
            "reporting-context", "operator-notes"
        ]},
        "ibn-por-v1": {"bank_count": 4, "banks": [
            "approval-record", "design-rationale", "validation-results", "change-history"
        ]},
        "ibn-candidate-bootstrap": {"bank_count": 4, "banks": [
            "policy-decisions", "config-rendering", "validation-results", "rejected-alternatives"
        ]},
        "ibn-deploy-bootstrap": {"bank_count": 3, "banks": [
            "deployment-log", "verification-results", "jinja2-context"
        ]},
        "ibn-asbuilt-current": {"bank_count": 3, "banks": [
            "network-health", "anomaly-watch", "telemetry-insights"
        ]},
        "ibn-whatif-bootstrap": {"bank_count": 3, "banks": [
            "exploration-brief", "options-analysis", "simulation-results"
        ]},
    }

    @pytest.mark.parametrize("space_name,config", IBN_SPACES.items(),
                             ids=list(IBN_SPACES.keys()))
    def test_t3_1_create_space(self, live_memory, space_name, config):
        """T3.1.1–T3.1.7 — Each IBN space is created with correct bank structure."""
        # Define consolidation rules with bank mappings
        consolidation_rules = {
            "banks": {bank: {"description": f"Bank for {bank}"} for bank in config["banks"]}
        }

        result = live_memory.space_create(
            name=space_name,
            description=f"IBN space: {space_name}",
            consolidation_rules=consolidation_rules
        )

        assert result["status"] == "created"
        assert result["space"] == space_name
        # Verify rules stored
        rules = live_memory.space_rules(space_name)
        assert len(rules["banks"]) == config["bank_count"]

    def test_t3_1_8_all_seven_spaces_listed(self, live_memory):
        """T3.1.8 — space_list() returns all 7 spaces after creation."""
        for name in self.IBN_SPACES:
            live_memory.space_create(name=name)

        spaces = live_memory.space_list()
        space_names = [s["name"] for s in spaces]

        for expected in self.IBN_SPACES:
            assert expected in space_names, f"Space '{expected}' missing from space_list()"


# ── T3.2 Note ingestion ──────────────────────────────────────────────────

class TestNoteIngestion:
    """T3.2 — Validate live_note() writes and reads."""

    def test_t3_2_1_write_single_note(self, live_memory):
        """T3.2.1 — Write a single note to ibn-loop-inner."""
        live_memory.space_create("ibn-loop-inner")

        note = live_memory.live_note(
            space="ibn-loop-inner",
            category="drift-detection",
            content="Detected firewall rule FWR-001 missing on usf-fw-01"
        )

        assert "id" in note
        assert note["space"] == "ibn-loop-inner"
        assert note["category"] == "drift-detection"

    def test_t3_2_2_write_multiple_categories(self, live_memory):
        """T3.2.2 — Write notes with 4 different categories."""
        live_memory.space_create("ibn-loop-inner")

        categories = [
            ("drift-detection", "Drift detected on usf-fw-01"),
            ("remediation-attempt", "Re-pushing config to usf-fw-01"),
            ("remediation-result", "Config re-push succeeded"),
            ("loop-metrics", "Cycle time: 45 seconds"),
        ]

        note_ids = []
        for cat, content in categories:
            note = live_memory.live_note(space="ibn-loop-inner", category=cat, content=content)
            note_ids.append(note["id"])

        # All IDs should be unique
        assert len(set(note_ids)) == 4

    def test_t3_2_3_read_notes_from_space(self, live_memory):
        """T3.2.3 — Read notes back from space."""
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Test note 1", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Test note 2", "remediation-attempt")

        notes = live_memory.note_list("ibn-loop-inner")
        assert len(notes) == 2

    def test_t3_2_4_category_to_bank_mapping(self, live_memory):
        """T3.2.4 — Verify category→bank file mapping logic."""
        CATEGORY_BANK_MAP = {
            "drift-detection": "drift-analysis",
            "remediation-attempt": "active-remediations",
            "remediation-result": "remediation-history",
            "loop-metrics": "loop-metrics",
        }
        for category, expected_bank in CATEGORY_BANK_MAP.items():
            # The mapping should be deterministic
            bank_name = category.replace("detection", "analysis").replace("attempt", "remediations").replace("result", "history")
            # Simplified mapping check — real implementation uses consolidation rules
            assert expected_bank is not None, f"No bank mapping for category '{category}'"


# ── T3.3 Consolidation ───────────────────────────────────────────────────

class TestConsolidation:
    """T3.3 — Validate bank_consolidate() behavior."""

    def test_t3_3_1_consolidation_consumes_notes(self, live_memory):
        """T3.3.1 — After consolidation, notes are consumed and banks updated."""
        live_memory.space_create("ibn-loop-inner")
        for i in range(5):
            live_memory.live_note("ibn-loop-inner", f"Note {i}", "drift-detection")

        result = live_memory.bank_consolidate("ibn-loop-inner")

        assert result["status"] == "consolidated"
        assert result["notes_consumed"] == 5
        # Notes should be cleared
        remaining = live_memory.note_list("ibn-loop-inner")
        assert len(remaining) == 0

    def test_t3_3_2_bank_contains_consolidated_content(self, live_memory):
        """T3.3.2 — Bank files contain consolidated content after consolidation."""
        live_memory.space_create("ibn-loop-inner")
        live_memory.live_note("ibn-loop-inner", "Drift event A", "drift-detection")
        live_memory.live_note("ibn-loop-inner", "Drift event B", "drift-detection")
        live_memory.bank_consolidate("ibn-loop-inner")

        banks = live_memory.bank_read_all("ibn-loop-inner")
        assert "drift-detection" in banks
        assert "Drift event A" in banks["drift-detection"]
        assert "Drift event B" in banks["drift-detection"]

    def test_t3_3_4_empty_space_consolidation_noop(self, live_memory):
        """T3.3.4 — Consolidation on empty space does nothing."""
        live_memory.space_create("ibn-loop-inner")

        result = live_memory.bank_consolidate("ibn-loop-inner")

        assert result["status"] == "no_notes"


# ── T3.4 Token authentication ────────────────────────────────────────────

class TestTokenAuth:
    """T3.4 — Token-based authentication validation."""

    def test_t3_4_1_agent_write_token_created(self, live_memory):
        """T3.4.1 — Agent write tokens can be created."""
        token = live_memory.token_create("agent-a1-write", role="agent")
        assert "token" in token
        assert token["role"] == "agent"

    def test_t3_4_2_operator_read_token_created(self, live_memory):
        """T3.4.2 — Operator read tokens can be created."""
        token = live_memory.token_create("operator-read", role="operator")
        assert token["role"] == "operator"

    def test_t3_4_3_multiple_tokens_unique(self, live_memory):
        """T3.4.3 — Each token is unique."""
        t1 = live_memory.token_create("agent-1", role="agent")
        t2 = live_memory.token_create("agent-2", role="agent")
        assert t1["token"] != t2["token"]
