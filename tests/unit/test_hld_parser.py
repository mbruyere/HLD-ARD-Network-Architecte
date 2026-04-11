"""Unit tests for the HLD markdown parser (Slice 1)."""
from __future__ import annotations

import pytest

from ibn.parser.hld_parser import (
    parse_population_table,
    parse_dmz_table,
    parse_hld,
    diff_snapshots,
    PopulationEntry,
    DmzEntry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

POPULATION_DOC = """\
# IBN test fixture

Some preamble text.

### Population Summary Table

| Population | VLAN | Large Site Count | Small Site Count | QoS Priority | DSCP | Bandwidth |
|------------|------|------------------|------------------|--------------|------|-----------|
| Corporate Users | 100 | 500-2000 | 50-400 | Standard | AF21, CS0 | 2-5 Mbps |
| Voice Devices | 110 | 300-1000 | 40-300 | Highest | EF, CS3 | 64-128 Kbps |
| Guest Access | 140 | 50-300 | 10-100 | Scavenger | CS1 | 5-10 Mbps |

Trailing text.
"""

DMZ_DOC = """\
### DMZ Summary Table

| DMZ Zone | VLAN | Purpose | Access From | Device Count |
|----------|------|---------|-------------|--------------|
| DNS | 200 | Name resolution | All Populations | 2-4 |
| Active Directory | 210 | Authentication | Corporate, Admin | 2-8 |
"""


# ---------------------------------------------------------------------------
# Population table parser
# ---------------------------------------------------------------------------

class TestParsePopulationTable:

    def test_extracts_all_rows(self):
        rows = parse_population_table(POPULATION_DOC)
        assert len(rows) == 3
        assert rows[0].vlan == 100
        assert rows[0].name == "Corporate Users"
        assert rows[1].vlan == 110
        assert rows[2].vlan == 140

    def test_captures_qos_dscp_bandwidth(self):
        rows = parse_population_table(POPULATION_DOC)
        guest = rows[2]
        assert guest.qos_priority == "Scavenger"
        assert guest.dscp == "CS1"
        assert guest.bandwidth == "5-10 Mbps"

    def test_line_numbers_are_one_based(self):
        rows = parse_population_table(POPULATION_DOC)
        # The first data row is on line 9 of the fixture (counting from 1)
        assert rows[0].line_number == 9

    def test_returns_empty_when_table_missing(self):
        rows = parse_population_table("# Doc with no table\n\nJust prose.")
        assert rows == []

    def test_skips_non_integer_vlan(self):
        bad = POPULATION_DOC.replace("| 100 |", "| TBD |")
        rows = parse_population_table(bad)
        assert all(r.vlan != 0 for r in rows)
        assert len(rows) == 2  # Corporate Users dropped


# ---------------------------------------------------------------------------
# DMZ table parser
# ---------------------------------------------------------------------------

class TestParseDmzTable:

    def test_extracts_all_rows(self):
        rows = parse_dmz_table(DMZ_DOC)
        assert len(rows) == 2
        assert rows[0].zone == "DNS"
        assert rows[0].vlan == 200
        assert rows[0].access_from == "All Populations"
        assert rows[1].zone == "Active Directory"

    def test_returns_empty_when_table_missing(self):
        assert parse_dmz_table(POPULATION_DOC) == []


# ---------------------------------------------------------------------------
# Snapshot diff
# ---------------------------------------------------------------------------

class TestDiffSnapshots:

    def test_no_op_when_unchanged(self):
        snap = parse_hld(POPULATION_DOC)
        cs = diff_snapshots(snap, snap)
        assert cs.is_empty
        assert cs.summary() == "no changes"

    def test_detects_added_population(self):
        old = parse_hld(POPULATION_DOC)
        new_doc = POPULATION_DOC.replace(
            "| Guest Access | 140 | 50-300 | 10-100 | Scavenger | CS1 | 5-10 Mbps |",
            (
                "| Guest Access | 140 | 50-300 | 10-100 | Scavenger | CS1 | 5-10 Mbps |\n"
                "| Contractor Access | 141 | 20-80 | 5-20 | Standard | AF21 | 2-5 Mbps |"
            ),
        )
        new = parse_hld(new_doc)
        cs = diff_snapshots(old, new)
        assert len(cs.populations_added) == 1
        assert cs.populations_added[0].vlan == 141
        assert cs.populations_added[0].name == "Contractor Access"
        assert not cs.populations_modified
        assert not cs.populations_removed

    def test_detects_modified_population(self):
        old = parse_hld(POPULATION_DOC)
        new_doc = POPULATION_DOC.replace("Guest Access", "Visitor Access")
        new = parse_hld(new_doc)
        cs = diff_snapshots(old, new)
        assert len(cs.populations_modified) == 1
        assert cs.populations_modified[0].vlan == 140
        assert cs.populations_modified[0].name == "Visitor Access"

    def test_detects_removed_population(self):
        old = parse_hld(POPULATION_DOC)
        new_doc = POPULATION_DOC.replace(
            "| Guest Access | 140 | 50-300 | 10-100 | Scavenger | CS1 | 5-10 Mbps |\n", ""
        )
        new = parse_hld(new_doc)
        cs = diff_snapshots(old, new)
        assert len(cs.populations_removed) == 1
        assert cs.populations_removed[0].vlan == 140

    def test_line_number_changes_alone_dont_trigger_modification(self):
        """Adding a blank line above the table shifts line numbers but
        the row content is identical — diff should be empty."""
        old = parse_hld(POPULATION_DOC)
        new = parse_hld("\n\n" + POPULATION_DOC)
        cs = diff_snapshots(old, new)
        assert cs.is_empty
