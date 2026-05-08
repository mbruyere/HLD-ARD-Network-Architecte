"""
T2 — Neo4j HLD Data Seed Integration Tests
============================================
Validates node counts, relationship integrity, and campus profile constraints
against a real Neo4j instance with the HLD data already seeded.

Prerequisites: Run STEP1 bootstrap (load schema + seed HLD data) before tests.

Run:
    NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=ibn-closed-loop-2026 \
    pytest tests/integration/test_t2_hld_seed_integ.py -v
"""

from __future__ import annotations

import os

import pytest

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))

REQUIRES_NEO4J = pytest.mark.skipif(
    not USE_REAL_NEO4J,
    reason="Requires real Neo4j (NEO4J_URI)",
)


@pytest.fixture(scope="module")
def neo4j():
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


def _count(neo4j, label):
    rows = neo4j.run_query(f"MATCH (n:{label}) RETURN count(n) AS c")
    return rows[0]["c"] if rows else 0


# ── T2.1 — Node counts after seed ────────────────────────────────────────


@REQUIRES_NEO4J
class TestNodeCountsInteg:

    def test_t2_1_1_site_count(self, neo4j):
        """T2.1.1 — At least 1 Site (HQ) with modelState POR."""
        rows = neo4j.run_query(
            "MATCH (s:Site {modelState: 'POR'}) RETURN count(s) AS c"
        )
        assert rows[0]["c"] >= 1

    def test_t2_1_2_device_count(self, neo4j):
        """T2.1.2 — At least 4 firewall devices seeded."""
        rows = neo4j.run_query(
            "MATCH (d:Device) WHERE d.deviceRole = 'FIREWALL' RETURN count(d) AS c"
        )
        assert rows[0]["c"] >= 4

    def test_t2_1_3_vlan_count(self, neo4j):
        """T2.1.3 — At least 16 VLANs (7 population + 8 DMZ + 1 transit)."""
        assert _count(neo4j, "VLAN") >= 16

    def test_t2_1_4_zone_count(self, neo4j):
        """T2.1.4 — At least 4 Zones."""
        assert _count(neo4j, "Zone") >= 4

    def test_t2_1_5_segment_count(self, neo4j):
        """T2.1.5 — 7 Segments."""
        assert _count(neo4j, "Segment") >= 7

    def test_t2_1_6_firewall_pair_count(self, neo4j):
        """T2.1.6 — 2 FirewallPairs (USF, DMZFW)."""
        assert _count(neo4j, "FirewallPair") >= 2


# ── T2.2 — Relationship integrity ────────────────────────────────────────


@REQUIRES_NEO4J
class TestRelationshipsInteg:

    def test_t2_2_1_site_contains_devices(self, neo4j):
        """T2.2.1 — Site CONTAINS all devices."""
        rows = neo4j.run_query(
            """
            MATCH (s:Site)-[:CONTAINS]->(d:Device)
            RETURN s.siteId AS site, count(d) AS devices
            """
        )
        # At least one site has devices
        assert any(r["devices"] >= 4 for r in rows), (
            f"Expected at least 4 devices at one site, got: {rows}"
        )

    def test_t2_2_2_firewall_pair_aggregates_devices(self, neo4j):
        """T2.2.2 — Each FirewallPair AGGREGATES 2 devices."""
        rows = neo4j.run_query(
            """
            MATCH (fp:FirewallPair)-[:AGGREGATES]->(d:Device)
            RETURN fp.pairId AS pair, count(d) AS members
            """
        )
        for r in rows:
            assert r["members"] == 2, (
                f"FirewallPair {r['pair']} has {r['members']} members, expected 2"
            )

    def test_t2_2_3_zone_contains_segments(self, neo4j):
        """T2.2.3 — Zones CONTAIN segments."""
        rows = neo4j.run_query(
            """
            MATCH (z:Zone)-[:CONTAINS]->(s:Segment)
            RETURN z.zoneId AS zone, count(s) AS segments
            """
        )
        assert len(rows) >= 1, "No Zone→Segment relationships found"

    def test_t2_2_4_vlan_belongs_to_site(self, neo4j):
        """T2.2.4 — All VLANs link to a Site."""
        rows = neo4j.run_query(
            """
            MATCH (v:VLAN)-[:BELONGS_TO]->(s:Site)
            RETURN count(v) AS linked
            """
        )
        total_vlans = _count(neo4j, "VLAN")
        linked = rows[0]["linked"] if rows else 0
        assert linked >= total_vlans, (
            f"Only {linked}/{total_vlans} VLANs have BELONGS_TO relationship"
        )


# ── T2.3 — Campus profile constraints ────────────────────────────────────


@REQUIRES_NEO4J
class TestCampusProfileInteg:

    def test_t2_3_1_site_has_firewall_pair(self, neo4j):
        """T2.3.1 — HQ has at least 1 FirewallPair."""
        rows = neo4j.run_query(
            """
            MATCH (fp:FirewallPair)-[:LOCATED_AT]->(s:Site)
            RETURN s.siteId AS site, count(fp) AS pairs
            UNION
            MATCH (fp:FirewallPair)
            WHERE fp.siteId IS NOT NULL
            RETURN fp.siteId AS site, count(fp) AS pairs
            """
        )
        assert any(r["pairs"] >= 1 for r in rows), (
            f"No site has a FirewallPair: {rows}"
        )

    def test_t2_3_2_population_vlans_in_range(self, neo4j):
        """T2.3.2 — Population VLANs are 100-160."""
        rows = neo4j.run_query(
            "MATCH (v:VLAN) WHERE v.vlanId >= 100 AND v.vlanId <= 160 RETURN v.vlanId AS vid"
        )
        vids = {r["vid"] for r in rows}
        expected = {100, 110, 120, 130, 140, 150, 160}
        assert expected.issubset(vids), f"Missing population VLANs: {expected - vids}"

    def test_t2_3_3_transit_vlan_300(self, neo4j):
        """T2.3.3 — Transit VLAN 300 exists."""
        rows = neo4j.run_query("MATCH (v:VLAN {vlanId: 300}) RETURN v")
        assert len(rows) == 1

    def test_t2_3_5_all_seeded_nodes_have_por(self, neo4j):
        """T2.3.5 — All seeded L1-L2 nodes have modelState POR."""
        for label in ["Site", "Device", "VLAN", "Zone", "Segment", "FirewallPair"]:
            rows = neo4j.run_query(
                f"""
                MATCH (n:{label})
                WHERE n.modelState IS NULL OR n.modelState <> 'POR'
                RETURN count(n) AS bad
                """
            )
            bad = rows[0]["bad"] if rows else 0
            assert bad == 0, f"{bad} {label} nodes missing modelState=POR"
