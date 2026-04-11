"""
HLD markdown parser — Slice 1 scope.

Parses the population VLAN table and the DMZ VLAN table from the HLD
document into structured records that Agent 1 can convert into Intent
nodes. Pure functions: no Neo4j, no Live-Memory, no LLM.

Out of scope for Slice 1 (deferred to later slices):
  - Per-population port-configuration sections
  - Firewall zone-pair policy tables
  - Routing / HA / IPsec sections
  - Free-prose sections
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Section markers — used to locate the tables in the HLD markdown
# ---------------------------------------------------------------------------

POPULATION_TABLE_HEADER = "### Population Summary Table"
DMZ_TABLE_HEADER = "### DMZ Summary Table"


# ---------------------------------------------------------------------------
# Parsed records
# ---------------------------------------------------------------------------

@dataclass
class PopulationEntry:
    """One row of the HLD population VLAN table."""
    name:           str        # "Corporate Users"
    vlan:           int        # 100
    large_site:     str        # "500-2000"
    small_site:     str        # "50-400"
    qos_priority:   str        # "Standard"
    dscp:           str        # "AF21, CS0"
    bandwidth:      str        # "2-5 Mbps"
    line_number:    int = 0    # source line in the HLD file (1-based)


@dataclass
class DmzEntry:
    """One row of the HLD DMZ VLAN table."""
    zone:          str         # "DNS"
    vlan:          int         # 200
    purpose:       str         # "Name resolution"
    access_from:   str         # "All Populations"
    device_count:  str         # "2-4"
    line_number:   int = 0


@dataclass
class HldSnapshot:
    """Structured snapshot of the parsed HLD sections.

    A snapshot is the canonical 'desired state' the closed loop reconciles
    against. Diffing two snapshots produces a ChangeSet.
    """
    populations: list[PopulationEntry] = field(default_factory=list)
    dmz:         list[DmzEntry]        = field(default_factory=list)
    source_path: str = ""

    def population_by_vlan(self, vlan: int) -> Optional[PopulationEntry]:
        for p in self.populations:
            if p.vlan == vlan:
                return p
        return None

    def dmz_by_vlan(self, vlan: int) -> Optional[DmzEntry]:
        for d in self.dmz:
            if d.vlan == vlan:
                return d
        return None


@dataclass
class ChangeSet:
    """Delta between two HLD snapshots.

    Each list contains the *new* state of changed/added entries.
    Removed entries hold the previous state for downstream cleanup.
    """
    populations_added:    list[PopulationEntry] = field(default_factory=list)
    populations_modified: list[PopulationEntry] = field(default_factory=list)
    populations_removed:  list[PopulationEntry] = field(default_factory=list)
    dmz_added:            list[DmzEntry]        = field(default_factory=list)
    dmz_modified:         list[DmzEntry]        = field(default_factory=list)
    dmz_removed:          list[DmzEntry]        = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([
            self.populations_added, self.populations_modified, self.populations_removed,
            self.dmz_added, self.dmz_modified, self.dmz_removed,
        ])

    def summary(self) -> str:
        parts = []
        if self.populations_added:
            parts.append(f"+{len(self.populations_added)} populations")
        if self.populations_modified:
            parts.append(f"~{len(self.populations_modified)} populations")
        if self.populations_removed:
            parts.append(f"-{len(self.populations_removed)} populations")
        if self.dmz_added:
            parts.append(f"+{len(self.dmz_added)} dmz")
        if self.dmz_modified:
            parts.append(f"~{len(self.dmz_modified)} dmz")
        if self.dmz_removed:
            parts.append(f"-{len(self.dmz_removed)} dmz")
        return ", ".join(parts) if parts else "no changes"


# ---------------------------------------------------------------------------
# Markdown table parser
# ---------------------------------------------------------------------------

_PIPE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


def _split_row(line: str) -> Optional[list[str]]:
    """Return the cells of a markdown table row, or None if not a table row."""
    m = _PIPE_ROW.match(line)
    if not m:
        return None
    return [cell.strip() for cell in m.group(1).split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    """A table separator row looks like ['---', '---', ...]."""
    return all(re.match(r"^:?-{3,}:?$", c) for c in cells)


def _extract_table(lines: list[str], header_text: str) -> tuple[list[list[str]], int]:
    """Find a markdown table by its preceding ### header.

    Returns (rows, header_line_number_1based) where rows includes the
    header row at index 0 followed by the data rows. Skips the
    separator row.
    """
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header_text:
            header_idx = i
            break
    if header_idx is None:
        return [], 0

    rows: list[list[str]] = []
    in_table = False
    for j in range(header_idx + 1, len(lines)):
        cells = _split_row(lines[j])
        if cells is None:
            if in_table:
                break  # blank line ends the table
            continue
        if _is_separator_row(cells):
            in_table = True
            continue
        if not in_table:
            # First pipe row is the column header
            rows.append(cells)
            in_table = True
        else:
            rows.append(cells)
            # We track absolute line number on the row by attaching it
            # via a closure below — see _parse_population_rows
    # We need to also know each row's line number — recompute below
    return rows, header_idx + 1


def _table_with_lines(lines: list[str], header_text: str) -> list[tuple[list[str], int]]:
    """Like _extract_table but returns (cells, line_number_1based) per data row.

    The header row is skipped here — only data rows are returned.
    """
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header_text:
            header_idx = i
            break
    if header_idx is None:
        return []

    out: list[tuple[list[str], int]] = []
    seen_separator = False
    seen_header_row = False
    for j in range(header_idx + 1, len(lines)):
        cells = _split_row(lines[j])
        if cells is None:
            if seen_separator:
                break  # end of table
            continue
        if _is_separator_row(cells):
            seen_separator = True
            continue
        if not seen_header_row:
            seen_header_row = True
            continue  # skip column header
        out.append((cells, j + 1))  # 1-based line numbers
    return out


# ---------------------------------------------------------------------------
# Population table → PopulationEntry
# ---------------------------------------------------------------------------

def parse_population_table(markdown_text: str) -> list[PopulationEntry]:
    """Parse the HLD population VLAN table into PopulationEntry records.

    Returns an empty list if the table is missing. Skips rows whose VLAN
    column is not parseable as an integer (defensive).
    """
    lines = markdown_text.splitlines()
    rows = _table_with_lines(lines, POPULATION_TABLE_HEADER)
    out: list[PopulationEntry] = []
    for cells, lineno in rows:
        if len(cells) < 7:
            continue
        try:
            vlan = int(cells[1])
        except ValueError:
            continue
        out.append(PopulationEntry(
            name=cells[0],
            vlan=vlan,
            large_site=cells[2],
            small_site=cells[3],
            qos_priority=cells[4],
            dscp=cells[5],
            bandwidth=cells[6],
            line_number=lineno,
        ))
    return out


# ---------------------------------------------------------------------------
# DMZ table → DmzEntry
# ---------------------------------------------------------------------------

def parse_dmz_table(markdown_text: str) -> list[DmzEntry]:
    """Parse the HLD DMZ VLAN table into DmzEntry records."""
    lines = markdown_text.splitlines()
    rows = _table_with_lines(lines, DMZ_TABLE_HEADER)
    out: list[DmzEntry] = []
    for cells, lineno in rows:
        if len(cells) < 5:
            continue
        try:
            vlan = int(cells[1])
        except ValueError:
            continue
        out.append(DmzEntry(
            zone=cells[0],
            vlan=vlan,
            purpose=cells[2],
            access_from=cells[3],
            device_count=cells[4],
            line_number=lineno,
        ))
    return out


# ---------------------------------------------------------------------------
# Snapshot + diff
# ---------------------------------------------------------------------------

def parse_hld(markdown_text: str, source_path: str = "") -> HldSnapshot:
    """Parse a full HLD document into the Slice 1 subset of structured data."""
    return HldSnapshot(
        populations=parse_population_table(markdown_text),
        dmz=parse_dmz_table(markdown_text),
        source_path=source_path,
    )


def parse_hld_file(path: str | Path) -> HldSnapshot:
    """Read an HLD markdown file from disk and parse it."""
    p = Path(path)
    return parse_hld(p.read_text(encoding="utf-8"), source_path=str(p))


def diff_snapshots(old: HldSnapshot, new: HldSnapshot) -> ChangeSet:
    """Compute the delta between two HLD snapshots, keyed by VLAN ID.

    Modification is detected by comparing all fields except line_number
    (line numbers shift on unrelated edits and should not trigger
    a "modified" verdict).
    """
    cs = ChangeSet()

    # Populations
    old_pop = {p.vlan: p for p in old.populations}
    new_pop = {p.vlan: p for p in new.populations}
    for vlan, entry in new_pop.items():
        if vlan not in old_pop:
            cs.populations_added.append(entry)
        elif _population_changed(old_pop[vlan], entry):
            cs.populations_modified.append(entry)
    for vlan, entry in old_pop.items():
        if vlan not in new_pop:
            cs.populations_removed.append(entry)

    # DMZ
    old_dmz = {d.vlan: d for d in old.dmz}
    new_dmz = {d.vlan: d for d in new.dmz}
    for vlan, entry in new_dmz.items():
        if vlan not in old_dmz:
            cs.dmz_added.append(entry)
        elif _dmz_changed(old_dmz[vlan], entry):
            cs.dmz_modified.append(entry)
    for vlan, entry in old_dmz.items():
        if vlan not in new_dmz:
            cs.dmz_removed.append(entry)

    return cs


def _population_changed(a: PopulationEntry, b: PopulationEntry) -> bool:
    return (
        a.name != b.name
        or a.large_site != b.large_site
        or a.small_site != b.small_site
        or a.qos_priority != b.qos_priority
        or a.dscp != b.dscp
        or a.bandwidth != b.bandwidth
    )


def _dmz_changed(a: DmzEntry, b: DmzEntry) -> bool:
    return (
        a.zone != b.zone
        or a.purpose != b.purpose
        or a.access_from != b.access_from
        or a.device_count != b.device_count
    )
