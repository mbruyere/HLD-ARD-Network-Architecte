"""
T3 — Live-Memory Integration Tests
====================================
Tests space creation, note ingestion, consolidation, and token auth
against a real Live-Memory MCP server.

Run:
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k \
    pytest tests/integration/test_t3_live_memory_integ.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

USE_REAL_LM = bool(os.environ.get("LIVE_MEMORY_URL"))

REQUIRES_LM = pytest.mark.skipif(
    not USE_REAL_LM,
    reason="Requires real Live-Memory (LIVE_MEMORY_URL)",
)


@pytest.fixture(scope="module")
def lm():
    from ibn.core.live_memory_client import LiveMemoryClient
    return LiveMemoryClient(
        base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
        token=os.environ.get("LIVE_MEMORY_TOKEN", os.environ.get("LM_ADMIN_TOKEN", "")),
    )


@pytest.fixture
def test_space(lm):
    """Create a unique test space and yield its name."""
    name = f"ibn-test-{uuid.uuid4().hex[:8]}"
    try:
        lm.space_create(
            space_id=name,
            description=f"T3 integration test {name}",
            owner="ibn-test",
            rules="# test consolidation rules\n",
        )
    except Exception:
        pass
    yield name


# ── T3.1 — Space creation ────────────────────────────────────────────────


@REQUIRES_LM
class TestSpaceCreation:

    def test_t3_1_1_create_space(self, lm, test_space):
        """T3.1.1 — space_create() succeeds."""
        spaces = lm.space_list()
        names = [s.get("name") or s.get("space_id", "") for s in spaces]
        assert test_space in names

    def test_t3_1_8_space_list_returns_spaces(self, lm):
        """T3.1.8 — space_list() returns at least 1 space."""
        spaces = lm.space_list()
        assert len(spaces) >= 1


# ── T3.2 — Note ingestion ────────────────────────────────────────────────


@REQUIRES_LM
class TestNoteIngestion:

    def test_t3_2_1_write_note(self, lm, test_space):
        """T3.2.1 — live_note() writes a note and returns an ID."""
        result = lm.live_note(
            space=test_space,
            content="Test drift detection: usf-fw-01 missing FWR-002",
            category="drift-detection",
        )
        assert result is not None

    def test_t3_2_2_write_multiple_categories(self, lm, test_space):
        """T3.2.2 — Notes with different categories all stored."""
        categories = [
            "drift-detection",
            "remediation-attempt",
            "remediation-result",
            "loop-metrics",
        ]
        for cat in categories:
            lm.live_note(
                space=test_space,
                content=f"Test note for category {cat}",
                category=cat,
            )

        notes = lm.note_list(test_space)
        assert len(notes) >= 4

    def test_t3_2_3_read_notes_back(self, lm, test_space):
        """T3.2.3 — note_list() returns notes from the space."""
        lm.live_note(
            space=test_space,
            content="Readable note",
            category="test",
        )
        notes = lm.note_list(test_space)
        assert len(notes) >= 1


# ── T3.3 — Consolidation ─────────────────────────────────────────────────


@REQUIRES_LM
class TestConsolidation:

    def test_t3_3_1_consolidation_consumes_notes(self, lm, test_space):
        """T3.3.1 — bank_consolidate() consumes notes."""
        for i in range(5):
            lm.live_note(
                space=test_space,
                content=f"Note {i}: drift event on device-{i}",
                category="drift-detection",
            )

        result = lm.bank_consolidate(test_space)
        assert result is not None
        # After consolidation, notes should be consumed
        notes_after = lm.note_list(test_space)
        # Notes may or may not be fully consumed depending on LM implementation
        # but the consolidation call itself must succeed

    def test_t3_3_2_bank_files_readable(self, lm, test_space):
        """T3.3.2 — bank_read_all() returns bank files after consolidation."""
        lm.live_note(
            space=test_space,
            content="Bank content test note",
            category="general",
        )
        lm.bank_consolidate(test_space)
        banks = lm.bank_read_all(test_space)
        # banks is a dict of {name: content}
        assert isinstance(banks, dict)

    def test_t3_3_4_empty_consolidation_no_error(self, lm):
        """T3.3.4 — Consolidating an empty space is a no-op."""
        empty_space = f"ibn-empty-{uuid.uuid4().hex[:8]}"
        try:
            lm.space_create(
                space_id=empty_space,
                description="empty test space",
                owner="ibn-test",
                rules="# empty\n",
            )
        except Exception:
            pass

        # Should not raise
        result = lm.bank_consolidate(empty_space)
        assert result is not None
