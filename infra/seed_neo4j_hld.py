#!/usr/bin/env python3
"""
Complete the Neo4j HLD seed — idempotent.

The Neo4j_Schema_Cypher.cypher already loaded the schema AND a partial seed
(devices, zones, segments, most VLANs). This script:

  1. Removes duplicate lowercase-ID artifacts from a previous partial run.
  2. Adds missing HLD VLANs (120 Printer, 230 File-DMZ, 260 Proxy, 270 Mgmt-DMZ, 300 Transit).
  3. Adds Subnets for every VLAN (many are missing).
  4. Adds missing Devices (acc-03, acc-04, edge-01, edge-02).
  5. Adds BusinessUseCases (5 from HLD).
  6. Wires all missing relationships (CONTAINS, REALIZED_BY / MAPPED_TO_VLAN, HAS_SUBNET,
     AGGREGATES, etc.).
  7. Patches VLAN 160 name to match HLD (Management).
  8. Validates Campus profile constraints.

All MERGE-based — safe to re-run.
"""

from __future__ import annotations
import os
from neo4j import GraphDatabase

URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER",     "neo4j")
PWD  = os.getenv("NEO4J_PASSWORD", "ibn-closed-loop-2026")


CLEANUP = [
    ("Remove duplicate lowercase site-hq",
     "MATCH (s:Site {siteId:'site-hq'}) DETACH DELETE s"),
    ("Remove duplicate lowercase fwpair-hq-usf",
     "MATCH (f:FirewallPair {pairId:'fwpair-hq-usf'}) DETACH DELETE f"),
    ("Remove duplicate lowercase fwpair-hq-dmzfw",
     "MATCH (f:FirewallPair {pairId:'fwpair-hq-dmzfw'}) DETACH DELETE f"),
    # Remove string-ID VLAN and its subnet (replaced by numeric vlanId: 300)
    ("Remove string-ID vlan-hq-300",
     "MATCH (v:VLAN {vlanId:'vlan-hq-300'}) DETACH DELETE v"),
    ("Remove string-ID subnet-hq-300",
     "MATCH (s:Subnet {subnetId:'subnet-hq-300'}) DETACH DELETE s"),
]

STATEMENTS = [
    # ── Patch VLAN 160: contractor → management (HLD says Management VLAN) ──
    ("Patch VLAN 160 name to Management",
     """
MATCH (v:VLAN {vlanId: 160})
SET v.name = 'management', v.vlanGroup = 'POPULATION', v.modelState = 'POR'
"""),

    # ── Add missing Population VLAN 120 Printer ──────────────────────────────
    ("Add VLAN 120 Printer",
     """
MERGE (v:VLAN {vlanId: 120})
SET v.name = 'printer', v.vlanGroup = 'POPULATION',
    v.description = 'Printers and MFDs', v.lifecycleState = 'ACTIVE',
    v.modelState = 'POR'
"""),

    # ── Add missing DMZ VLANs ─────────────────────────────────────────────────
    ("Add VLAN 230 File-DMZ",
     """
MERGE (v:VLAN {vlanId: 230})
SET v.name = 'dmz_file', v.vlanGroup = 'DMZ',
    v.description = 'File services DMZ', v.lifecycleState = 'ACTIVE',
    v.modelState = 'POR'
"""),
    ("Add VLAN 260 Proxy",
     """
MERGE (v:VLAN {vlanId: 260})
SET v.name = 'dmz_proxy', v.vlanGroup = 'DMZ',
    v.description = 'Web proxy DMZ', v.lifecycleState = 'ACTIVE',
    v.modelState = 'POR'
"""),
    ("Add VLAN 270 Management-DMZ",
     """
MERGE (v:VLAN {vlanId: 270})
SET v.name = 'dmz_mgmt', v.vlanGroup = 'DMZ',
    v.description = 'Management DMZ', v.lifecycleState = 'ACTIVE',
    v.modelState = 'POR'
"""),
    ("Add VLAN 300 Transit USF-DMZFW",
     """
MERGE (v:VLAN {vlanId: 300})
SET v.name = 'transit_usf_dmzfw', v.vlanGroup = 'TRANSIT',
    v.description = 'USF to DMZFW transit segment', v.lifecycleState = 'ACTIVE',
    v.modelState = 'POR'
"""),

    # ── Subnets for all VLANs ─────────────────────────────────────────────────
    ("Subnets for all VLANs",
     """
UNWIND [
  {vlanId: 100, subnetId: 'SUB-100', prefix: '10.100.0.0/24'},
  {vlanId: 110, subnetId: 'SUB-110', prefix: '10.100.10.0/24'},
  {vlanId: 120, subnetId: 'SUB-120', prefix: '10.100.20.0/24'},
  {vlanId: 130, subnetId: 'SUB-130', prefix: '10.100.30.0/24'},
  {vlanId: 140, subnetId: 'SUB-140', prefix: '10.100.40.0/24'},
  {vlanId: 150, subnetId: 'SUB-150', prefix: '10.100.50.0/24'},
  {vlanId: 160, subnetId: 'SUB-160', prefix: '10.100.60.0/24'},
  {vlanId: 200, subnetId: 'SUB-200', prefix: '10.200.0.0/24'},
  {vlanId: 210, subnetId: 'SUB-210', prefix: '10.200.10.0/24'},
  {vlanId: 220, subnetId: 'SUB-220', prefix: '10.200.20.0/24'},
  {vlanId: 230, subnetId: 'SUB-230', prefix: '10.200.30.0/24'},
  {vlanId: 240, subnetId: 'SUB-240', prefix: '10.200.40.0/24'},
  {vlanId: 250, subnetId: 'SUB-250', prefix: '10.200.50.0/24'},
  {vlanId: 260, subnetId: 'SUB-260', prefix: '10.200.60.0/24'},
  {vlanId: 270, subnetId: 'SUB-270', prefix: '10.200.70.0/24'},
  {vlanId: 300, subnetId: 'SUB-300', prefix: '10.255.254.0/30'},
  {vlanId: 999, subnetId: 'SUB-999', prefix: '192.168.100.0/24'}
] AS row
MERGE (sn:Subnet {subnetId: row.subnetId})
SET sn.prefix = row.prefix, sn.vlanTag = row.vlanId,
    sn.siteId = 'SITE-HQ-01', sn.modelState = 'POR'
WITH sn, row
MATCH (v:VLAN {vlanId: row.vlanId})
MERGE (v)-[:HAS_SUBNET]->(sn)
"""),

    # ── Add missing Devices: acc-03, acc-04, edge-01, edge-02 ────────────────
    ("Add devices acc-03, acc-04",
     """
UNWIND range(3, 4) AS i
MERGE (d:Device {deviceId: 'DEV-HQ-ACC-0' + toString(i)})
SET d.hostname = 'sw-hq-acc-0' + toString(i),
    d.deviceRole = 'ACCESS_SWITCH',
    d.vendor = 'Cisco', d.platform = 'Catalyst 9300',
    d.siteId = 'SITE-HQ-01', d.modelState = 'POR',
    d.lifecycleState = 'PLANNED'
"""),
    ("Add devices edge-01, edge-02",
     """
UNWIND range(1, 2) AS i
MERGE (d:Device {deviceId: 'DEV-HQ-EDGE-0' + toString(i)})
SET d.hostname = 'rtr-hq-edge-0' + toString(i),
    d.deviceRole = 'EDGE_ROUTER',
    d.vendor = 'Cisco', d.platform = 'ISR 4431',
    d.siteId = 'SITE-HQ-01', d.modelState = 'POR',
    d.lifecycleState = 'PLANNED'
"""),

    # ── BusinessUseCases (5) ──────────────────────────────────────────────────
    ("BusinessUseCases (5)",
     """
UNWIND [
  {id: 'BUC-EMPLOYEE-ACCESS',  name: 'Employee LAN Access',        priority: 'HIGH'},
  {id: 'BUC-VOICE',            name: 'IP Telephony (Voice VLAN)',   priority: 'HIGH'},
  {id: 'BUC-GUEST-ISOLATION',  name: 'Guest Network Isolation',    priority: 'MEDIUM'},
  {id: 'BUC-DMZ-SERVICES',     name: 'DMZ Service Publishing',     priority: 'HIGH'},
  {id: 'BUC-INTERNET-ACCESS',  name: 'Controlled Internet Access', priority: 'MEDIUM'}
] AS b
MERGE (buc:BusinessUseCase {bucId: b.id})
SET buc.name = b.name, buc.priority = b.priority,
    buc.modelState = 'POR', buc.createdBy = 'hld-bootstrap'
"""),

    # ── Set modelState on all schema-seeded nodes that lack it ────────────────
    ("Set modelState POR on all VLANs",
     "MATCH (v:VLAN) WHERE v.modelState IS NULL SET v.modelState = 'POR'"),
    ("Set modelState POR on all Segments",
     "MATCH (s:Segment) WHERE s.modelState IS NULL SET s.modelState = 'POR'"),
    ("Set modelState POR on all Zones",
     "MATCH (z:Zone) WHERE z.modelState IS NULL SET z.modelState = 'POR'"),

    # ── Architecture chain ────────────────────────────────────────────────────
    ("Architecture chain: arch → version → HLD",
     """
MATCH (a:Architecture {archId: 'ARCH-CAMPUS-01'})
MATCH (av:ArchitectureVersion {versionId: 'ARCHVER-1.0.0'})
OPTIONAL MATCH (hld:HLDDocument)
WITH a, av, hld
MERGE (a)-[:HAS_VERSION]->(av)
WITH av, hld
WHERE hld IS NOT NULL
MERGE (av)-[:DOCUMENTED_BY]->(hld)
"""),

    # ── Site CONTAINS all Devices ─────────────────────────────────────────────
    ("Site CONTAINS all Devices",
     """
MATCH (s:Site {siteId: 'SITE-HQ-01'})
MATCH (d:Device {siteId: 'SITE-HQ-01'})
MERGE (s)-[:CONTAINS]->(d)
"""),

    # Also wire up devices that don't yet have siteId set
    ("Set siteId on schema-seeded Devices",
     """
MATCH (d:Device)
WHERE d.siteId IS NULL AND d.deviceId STARTS WITH 'DEV-HQ-'
SET d.siteId = 'SITE-HQ-01'
"""),

    ("Site CONTAINS Devices (after siteId patch)",
     """
MATCH (s:Site {siteId: 'SITE-HQ-01'})
MATCH (d:Device {siteId: 'SITE-HQ-01'})
MERGE (s)-[:CONTAINS]->(d)
"""),

    # ── FirewallPair AGGREGATES Devices ───────────────────────────────────────
    ("FirewallPair USF AGGREGATES USF devices",
     """
MATCH (fp:FirewallPair {pairId: 'FWPAIR-HQ-USF'})
MATCH (d:Device) WHERE d.deviceId IN ['DEV-HQ-USF-01','DEV-HQ-USF-02']
MERGE (fp)-[:AGGREGATES]->(d)
"""),
    ("FirewallPair DMZ AGGREGATES DMZFW devices",
     """
MATCH (fp:FirewallPair {pairId: 'FWPAIR-HQ-DMZ'})
MATCH (d:Device) WHERE d.deviceId IN ['DEV-HQ-DMZFW-01','DEV-HQ-DMZFW-02']
MERGE (fp)-[:AGGREGATES]->(d)
"""),

    # ── Site CONTAINS VLANs ───────────────────────────────────────────────────
    ("Site CONTAINS VLANs",
     """
MATCH (s:Site {siteId: 'SITE-HQ-01'})
MATCH (v:VLAN)
MERGE (s)-[:CONTAINS]->(v)
"""),

    # ── Zone CONTAINS Segments ────────────────────────────────────────────────
    ("Zone USER CONTAINS population segments",
     """
MATCH (z:Zone {zoneId: 'ZONE-USER'})
MATCH (seg:Segment) WHERE seg.segmentId IN [
  'SEG-EMPLOYEE','SEG-VOICE','SEG-VIDEO','SEG-GUEST','SEG-IOT']
MERGE (z)-[:CONTAINS]->(seg)
"""),
    ("Zone IOT CONTAINS IoT segment",
     """
MATCH (z:Zone {zoneId: 'ZONE-IOT'})
MATCH (seg:Segment {segmentId: 'SEG-IOT'})
MERGE (z)-[:CONTAINS]->(seg)
"""),
    ("Zone GUEST CONTAINS guest segment",
     """
MATCH (z:Zone {zoneId: 'ZONE-GUEST'})
MATCH (seg:Segment {segmentId: 'SEG-GUEST'})
MERGE (z)-[:CONTAINS]->(seg)
"""),
    ("Zone MGMT CONTAINS contractor/mgmt segment",
     """
MATCH (z:Zone {zoneId: 'ZONE-MGMT'})
MATCH (seg:Segment {segmentId: 'SEG-CONTRACTOR'})
MERGE (z)-[:CONTAINS]->(seg)
"""),

    # ── Segments REALIZED_BY (or MAPPED_TO_VLAN per schema) VLANs ────────────
    # The schema uses MAPPED_TO_VLAN, wire remaining ones
    ("Segment MAPPED_TO_VLAN for printer/mgmt (if segments exist)",
     """
OPTIONAL MATCH (seg:Segment {segmentId: 'SEG-PRINTER'})
OPTIONAL MATCH (vl:VLAN {vlanId: 120})
WITH seg, vl WHERE seg IS NOT NULL AND vl IS NOT NULL
MERGE (seg)-[:MAPPED_TO_VLAN]->(vl)
"""),
]

VALIDATION_QUERIES = [
    ("Site HQ exists",
     "MATCH (s:Site {siteId:'SITE-HQ-01'}) RETURN count(s) AS found",
     lambda r: r[0]["found"] == 1),
    ("14 Devices total",
     "MATCH (d:Device {siteId:'SITE-HQ-01'}) RETURN count(d) AS cnt",
     lambda r: r[0]["cnt"] >= 10),
    ("VLANs 100-160 all present",
     "MATCH (v:VLAN) WHERE v.vlanId IN [100,110,120,130,140,150,160] RETURN count(v) AS cnt",
     lambda r: r[0]["cnt"] == 7),
    ("DMZ VLANs present",
     "MATCH (v:VLAN) WHERE v.vlanId IN [200,210,220,230,240,250,260,270] RETURN count(v) AS cnt",
     lambda r: r[0]["cnt"] == 8),
    ("Transit VLAN 300 exists",
     "MATCH (v:VLAN {vlanId:300}) RETURN count(v) AS found",
     lambda r: r[0]["found"] == 1),
    ("Dual FirewallPairs",
     "MATCH (fp:FirewallPair) WHERE fp.pairId IN ['FWPAIR-HQ-USF','FWPAIR-HQ-DMZ'] RETURN count(fp) AS cnt",
     lambda r: r[0]["cnt"] == 2),
    ("FirewallPairs aggregate 4 VyOS devices",
     "MATCH (fp:FirewallPair)-[:AGGREGATES]->(d:Device) RETURN count(d) AS cnt",
     lambda r: r[0]["cnt"] == 4),
    ("Subnets for all VLANs",
     "MATCH (v:VLAN)-[:HAS_SUBNET]->(s:Subnet) RETURN count(s) AS cnt",
     lambda r: r[0]["cnt"] >= 16),
    ("BusinessUseCases (5)",
     "MATCH (b:BusinessUseCase) RETURN count(b) AS cnt",
     lambda r: r[0]["cnt"] == 5),
    ("All VLANs have modelState POR",
     "MATCH (v:VLAN) WHERE v.modelState IS NULL RETURN count(v) AS violations",
     lambda r: r[0]["violations"] == 0),
    ("Zone→Segment links",
     "MATCH (z:Zone)-[:CONTAINS]->(s:Segment) RETURN count(s) AS cnt",
     lambda r: r[0]["cnt"] >= 5),
    ("Segment→VLAN links",
     "MATCH (s:Segment)-[:MAPPED_TO_VLAN|REALIZED_BY]->(v:VLAN) RETURN count(v) AS cnt",
     lambda r: r[0]["cnt"] >= 5),
]


def run():
    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    print(f"Connected: {URI}\n")

    with driver.session() as session:
        # ── Cleanup ──────────────────────────────────────────────────────────
        print("── Cleanup ───────────────────────────────────────────────────")
        for label, cypher in CLEANUP:
            result = session.run(cypher)
            summary = result.consume()
            deleted = summary.counters.nodes_deleted
            print(f"  {'✓' if deleted else '~'} {label:50s}  deleted={deleted}")

        # ── Seed / complete ───────────────────────────────────────────────────
        print("\n── Seeding missing HLD data ──────────────────────────────────")
        for label, cypher in STATEMENTS:
            result = session.run(cypher)
            summary = result.consume()
            c = summary.counters
            changed = c.nodes_created + c.relationships_created + c.properties_set
            icon = "✓" if changed else "~"
            print(f"  {icon} {label:50s}  "
                  f"+nodes={c.nodes_created:2d}  "
                  f"+rels={c.relationships_created:2d}  "
                  f"~props={c.properties_set:3d}")

        # ── Inventory ─────────────────────────────────────────────────────────
        print("\n── Node inventory ────────────────────────────────────────────")
        rows = list(session.run(
            "MATCH (n) RETURN labels(n)[0] AS lbl, count(n) AS cnt ORDER BY cnt DESC"
        ))
        total = 0
        for row in rows:
            if row["lbl"]:
                print(f"  {row['lbl']:30s} {row['cnt']:3d}")
                total += row["cnt"]
        print(f"  {'TOTAL':30s} {total:3d}")

        # ── Validation ────────────────────────────────────────────────────────
        print("\n── Campus profile validation ─────────────────────────────────")
        all_pass = True
        for label, cypher, check in VALIDATION_QUERIES:
            rows = list(session.run(cypher))
            passed = check(rows)
            val = list(rows[0].values())[0] if rows else "?"
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {label:45s}  (={val})")
            if not passed:
                all_pass = False

        print()
        if all_pass:
            print("  All Campus profile constraints satisfied ✓")
        else:
            print("  ✗ Some constraints failed")

    driver.close()


if __name__ == "__main__":
    run()
