"""
T2 — Neo4j HLD Data Seed Tests (Unit)
======================================
Validates that the HLD seed data produces the correct graph structure
when loaded into the mock Neo4j driver.

Uses canned seed data from ``tests/fixtures/neo4j_canned.py`` to verify
node counts, relationship integrity, campus profile constraints, and
modelState enforcement — all against the in-memory mock driver.
"""

import pytest

from tests.fixtures.neo4j_canned import (
    SEED_SITES,
    SEED_DEVICES,
    SEED_VLANS,
    SEED_ZONES,
    SEED_SEGMENTS,
    SEED_FIREWALL_PAIRS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_graph(driver):
    """Load all HLD seed data into the mock Neo4j driver."""
    for site in SEED_SITES:
        driver.seed_node("Site", {**site})
    for device in SEED_DEVICES:
        driver.seed_node("Device", {**device})
    for vlan in SEED_VLANS:
        driver.seed_node("VLAN", {**vlan})
    for zone in SEED_ZONES:
        driver.seed_node("Zone", {**zone})
    for segment in SEED_SEGMENTS:
        driver.seed_node("Segment", {**segment})
    for pair in SEED_FIREWALL_PAIRS:
        driver.seed_node("FirewallPair", {**pair})


def _count_by_label(driver, label):
    """Count nodes with a given label in the mock store."""
    return sum(1 for n in driver.nodes if n.get("_label") == label)


def _nodes_by_label(driver, label):
    """Return all nodes with a given label."""
    return [n for n in driver.nodes if n.get("_label") == label]


# ── T2.1 — Node counts after seed ────────────────────────────────────────


class TestNodeCounts:
    """T2.1 — Validate correct node counts after HLD seed."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_neo4j):
        self.driver = mock_neo4j
        _seed_graph(self.driver)

    def test_t2_1_1_site_count(self):
        """T2.1.1 — 3 Sites (HQ, Branch-A, Branch-B)."""
        assert _count_by_label(self.driver, "Site") == 3

    def test_t2_1_2_device_count(self):
        """T2.1.2 — 8 Devices (4 FW + 2 access + 2 aggregation)."""
        assert _count_by_label(self.driver, "Device") == len(SEED_DEVICES)

    def test_t2_1_3_vlan_count(self):
        """T2.1.3 — 16 VLANs (7 population + 8 DMZ + 1 transit)."""
        assert _count_by_label(self.driver, "VLAN") == 16

    def test_t2_1_4_zone_count(self):
        """T2.1.4 — 6 Zones (USER, GUEST, IOT, DMZ_INFRA, INTERNET, MGMT)."""
        assert _count_by_label(self.driver, "Zone") == 6

    def test_t2_1_5_segment_count(self):
        """T2.1.5 — 7 Segments (Employee, Voice, Printer, Video, Guest, IoT, Management)."""
        assert _count_by_label(self.driver, "Segment") == 7

    def test_t2_1_6_firewall_pair_count(self):
        """T2.1.6 — 2 FirewallPairs (USF, DMZFW)."""
        assert _count_by_label(self.driver, "FirewallPair") == 2


# ── T2.2 — Relationship integrity (property-based) ───────────────────────


class TestRelationshipIntegrity:
    """T2.2 — Validate referential integrity via properties.

    Since the mock driver stores flat nodes (no real Neo4j relationships),
    we verify referential integrity through foreign-key properties:
    device.siteId → site.siteId, segment.zoneId → zone.zoneId, etc.
    """

    @pytest.fixture(autouse=True)
    def setup(self, mock_neo4j):
        self.driver = mock_neo4j
        _seed_graph(self.driver)

    def test_t2_2_1_all_devices_reference_valid_site(self):
        """T2.2.1 — Every device's siteId matches an existing Site."""
        site_ids = {s["siteId"] for s in _nodes_by_label(self.driver, "Site")}
        for device in _nodes_by_label(self.driver, "Device"):
            assert device["siteId"] in site_ids, (
                f"Device {device['deviceId']} references unknown site {device['siteId']}"
            )

    def test_t2_2_2_firewall_pair_members_exist(self):
        """T2.2.2 — Every FirewallPair member device exists in the Device set."""
        device_ids = {d["deviceId"] for d in _nodes_by_label(self.driver, "Device")}
        for pair in _nodes_by_label(self.driver, "FirewallPair"):
            for member in pair["members"]:
                assert member in device_ids, (
                    f"FirewallPair {pair['pairId']} references unknown device {member}"
                )

    def test_t2_2_3_firewall_pair_has_two_members(self):
        """T2.2.2 — Each FirewallPair aggregates exactly 2 devices."""
        for pair in _nodes_by_label(self.driver, "FirewallPair"):
            assert len(pair["members"]) == 2, (
                f"FirewallPair {pair['pairId']} has {len(pair['members'])} members, expected 2"
            )

    def test_t2_2_4_segments_reference_valid_zones(self):
        """T2.2.3 — Every segment's zoneId matches an existing Zone."""
        zone_ids = {z["zoneId"] for z in _nodes_by_label(self.driver, "Zone")}
        for seg in _nodes_by_label(self.driver, "Segment"):
            assert seg["zoneId"] in zone_ids, (
                f"Segment {seg['segmentId']} references unknown zone {seg['zoneId']}"
            )

    def test_t2_2_5_vlans_reference_valid_sites(self):
        """T2.2.4 — Every VLAN's siteId matches an existing Site."""
        site_ids = {s["siteId"] for s in _nodes_by_label(self.driver, "Site")}
        for vlan in _nodes_by_label(self.driver, "VLAN"):
            assert vlan["siteId"] in site_ids, (
                f"VLAN {vlan['vlanId']} references unknown site {vlan['siteId']}"
            )

    def test_t2_2_6_segments_reference_valid_vlans(self):
        """Each segment's vlanId matches an existing VLAN."""
        vlan_ids = {v["vlanId"] for v in _nodes_by_label(self.driver, "VLAN")}
        for seg in _nodes_by_label(self.driver, "Segment"):
            assert seg["vlanId"] in vlan_ids, (
                f"Segment {seg['segmentId']} references unknown VLAN {seg['vlanId']}"
            )

    def test_t2_2_7_hq_has_all_devices(self):
        """All seed devices belong to HQ site."""
        hq_devices = [d for d in _nodes_by_label(self.driver, "Device")
                       if d["siteId"] == "SITE-HQ-01"]
        assert len(hq_devices) == len(SEED_DEVICES)


# ── T2.3 — Campus profile constraints ────────────────────────────────────


class TestCampusProfileConstraints:
    """T2.3 — HLD-specific invariants for the Campus profile."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_neo4j):
        self.driver = mock_neo4j
        _seed_graph(self.driver)

    def test_t2_3_1_hq_has_firewall_pairs(self):
        """T2.3.1 — HQ site has at least 1 FirewallPair."""
        pairs = [p for p in _nodes_by_label(self.driver, "FirewallPair")
                 if p["siteId"] == "SITE-HQ-01"]
        assert len(pairs) >= 1

    def test_t2_3_2_population_vlans_in_range(self):
        """T2.3.2 — Population VLANs are in the 100-160 range."""
        population_vlans = [v for v in _nodes_by_label(self.driver, "VLAN")
                           if 100 <= v["vlanId"] <= 160]
        expected = {100, 110, 120, 130, 140, 150, 160}
        actual = {v["vlanId"] for v in population_vlans}
        assert actual == expected

    def test_t2_3_3_dmz_vlans_in_range(self):
        """DMZ VLANs are in the 200-270 range."""
        dmz_vlans = [v for v in _nodes_by_label(self.driver, "VLAN")
                     if 200 <= v["vlanId"] <= 270]
        expected = {200, 210, 220, 230, 240, 250, 260, 270}
        actual = {v["vlanId"] for v in dmz_vlans}
        assert actual == expected

    def test_t2_3_4_transit_vlan_300_exists(self):
        """T2.3.3 — Transit VLAN 300 exists."""
        transit = [v for v in _nodes_by_label(self.driver, "VLAN")
                   if v["vlanId"] == 300]
        assert len(transit) == 1
        assert transit[0]["name"] == "Transit"

    def test_t2_3_5_usf_and_dmzfw_pairs_exist(self):
        """T2.3.4 — Both USF and DMZFW firewall pairs exist."""
        pairs = _nodes_by_label(self.driver, "FirewallPair")
        functions = {p["function"] for p in pairs}
        assert "USF" in functions
        assert "DMZFW" in functions

    def test_t2_3_6_all_nodes_have_por_model_state(self):
        """T2.3.5 — All seeded nodes have modelState='POR'."""
        for node in self.driver.nodes:
            assert node.get("modelState") == "POR", (
                f"Node {node.get('_label')} {node.get('_id')} has "
                f"modelState={node.get('modelState')!r}, expected 'POR'"
            )

    def test_t2_3_7_firewall_devices_are_vyos(self):
        """All firewall devices use the VyOS platform."""
        fw_devices = [d for d in _nodes_by_label(self.driver, "Device")
                      if d["deviceRole"] == "FIREWALL"]
        for d in fw_devices:
            assert d["vendor"] == "vyos", (
                f"Firewall {d['deviceId']} vendor is {d['vendor']!r}, expected 'vyos'"
            )

    def test_t2_3_8_each_zone_has_segments(self):
        """Each non-INTERNET zone has at least one segment mapped to it."""
        zones_with_segments = {s["zoneId"] for s in _nodes_by_label(self.driver, "Segment")}
        for zone in _nodes_by_label(self.driver, "Zone"):
            if zone["zoneId"] not in ("INTERNET", "DMZ_INFRA"):
                assert zone["zoneId"] in zones_with_segments, (
                    f"Zone {zone['zoneId']} has no segments assigned"
                )

    def test_t2_3_9_segment_names_match_hld(self):
        """Segment names match the HLD specification."""
        expected_names = {"Employee", "Voice", "Printer", "Video",
                          "Guest", "IoT", "Management"}
        actual_names = {s["name"] for s in _nodes_by_label(self.driver, "Segment")}
        assert actual_names == expected_names

    def test_t2_3_10_unique_device_ids(self):
        """All device IDs are unique."""
        device_ids = [d["deviceId"] for d in _nodes_by_label(self.driver, "Device")]
        assert len(device_ids) == len(set(device_ids))

    def test_t2_3_11_unique_vlan_ids(self):
        """All VLAN IDs are unique."""
        vlan_ids = [v["vlanId"] for v in _nodes_by_label(self.driver, "VLAN")]
        assert len(vlan_ids) == len(set(vlan_ids))
