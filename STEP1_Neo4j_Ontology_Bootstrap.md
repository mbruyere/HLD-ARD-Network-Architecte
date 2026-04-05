# Step 1 — Neo4j Ontology Bootstrap

**Goal:** Deploy Neo4j, load the 9-layer ontology schema, seed it with HLD data, and validate with Campus profile constraints. This is the foundation for everything else in the closed loop.

**Prerequisites:** Docker, Docker Compose, `cypher-shell` or Neo4j Browser access.

---

## Step 1.1 — Deploy Neo4j

Stand up a Neo4j 5.x instance using Docker Compose. This will serve as both the Tier 1 SSoT and (later) the namespace-isolated backend for Graph-Memory (Tier 3).

Create `docker-compose.neo4j.yml`:

```yaml
services:
  neo4j:
    image: neo4j:5-community
    container_name: ibn-neo4j
    ports:
      - "7474:7474"   # HTTP Browser
      - "7687:7687"   # Bolt protocol
    environment:
      NEO4J_AUTH: neo4j/ibn-closed-loop-2026
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_server_memory_heap_initial__size: 1G
      NEO4J_server_memory_heap_max__size: 2G
    volumes:
      - neo4j-data:/data
      - neo4j-logs:/logs
    restart: unless-stopped

volumes:
  neo4j-data:
  neo4j-logs:
```

```bash
docker compose -f docker-compose.neo4j.yml up -d
# Wait for Neo4j to be ready
until curl -s http://localhost:7474 > /dev/null 2>&1; do sleep 2; done
echo "Neo4j is ready"
```

**Validation:** Open http://localhost:7474 in a browser. Log in with `neo4j` / `ibn-closed-loop-2026`.

---

## Step 1.2 — Load the Ontology Schema (DDL)

The file `Neo4j_Schema_Cypher.cypher` contains all constraints and indexes. It is already written with `IF NOT EXISTS` guards, so it is idempotent.

```bash
# Load the schema from the Cypher file
cat Neo4j_Schema_Cypher.cypher | cypher-shell -u neo4j -p ibn-closed-loop-2026 -a bolt://localhost:7687
```

If you don't have `cypher-shell` installed locally, use the Neo4j Browser: paste each SECTION of the file and execute. Or mount the file into the container:

```bash
docker cp Neo4j_Schema_Cypher.cypher ibn-neo4j:/tmp/schema.cypher
docker exec ibn-neo4j cypher-shell -u neo4j -p ibn-closed-loop-2026 -f /tmp/schema.cypher
```

**Validation query** — check that constraints and indexes were created:

```cypher
SHOW CONSTRAINTS;
// Expected: ~45 constraints across all 9 layers

SHOW INDEXES;
// Expected: ~45 backing indexes from constraints + ~25 explicit indexes
```

---

## Step 1.3 — Seed HLD Data (Layer 1–3)

This is the critical step: populate Neo4j with the real network described in the HLD. All seed data uses `modelState: 'POR'` because the HLD represents the approved Plan-of-Record design.

### 1.3.1 — Site

```cypher
CREATE (s:Site {
  siteId: 'site-hq',
  name: 'Headquarters',
  siteType: 'CAMPUS',
  location: 'Main Campus',
  tier: 'LARGE',
  modelState: 'POR',
  lifecycleState: 'OPERATIONAL',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});
```

### 1.3.2 — Devices

```cypher
// Access Switches (example: 4 per HLD)
UNWIND range(1, 4) AS i
CREATE (d:Device {
  deviceId: 'dev-hq-acc-' + toString(i),
  hostname: 'sw-hq-acc-0' + toString(i),
  deviceRole: 'ACCESS',
  vendor: 'Cisco',
  platform: 'Catalyst 9300',
  siteId: 'site-hq',
  modelState: 'POR',
  lifecycleState: 'PLANNED',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// Aggregation Switches (2, stacked)
UNWIND range(1, 2) AS i
CREATE (d:Device {
  deviceId: 'dev-hq-agg-' + toString(i),
  hostname: 'sw-hq-agg-0' + toString(i),
  deviceRole: 'AGGREGATION',
  vendor: 'Cisco',
  platform: 'Catalyst 9500',
  siteId: 'site-hq',
  modelState: 'POR',
  lifecycleState: 'PLANNED',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// User Services Firewalls (active-active pair)
UNWIND range(1, 2) AS i
CREATE (d:Device {
  deviceId: 'dev-hq-usf-' + toString(i),
  hostname: 'fw-hq-usr-0' + toString(i),
  deviceRole: 'FIREWALL',
  firewallFunction: 'USER_SERVICES',
  vendor: 'VyOS',
  platform: 'VyOS 1.4',
  siteId: 'site-hq',
  modelState: 'POR',
  lifecycleState: 'PLANNED',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// DMZ/Internet Firewalls (active-active pair)
UNWIND range(1, 2) AS i
CREATE (d:Device {
  deviceId: 'dev-hq-dmzfw-' + toString(i),
  hostname: 'fw-hq-dmz-0' + toString(i),
  deviceRole: 'FIREWALL',
  firewallFunction: 'DMZ_INTERNET',
  vendor: 'VyOS',
  platform: 'VyOS 1.4',
  siteId: 'site-hq',
  modelState: 'POR',
  lifecycleState: 'PLANNED',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// Internet Edge Routers (2)
UNWIND range(1, 2) AS i
CREATE (d:Device {
  deviceId: 'dev-hq-edge-' + toString(i),
  hostname: 'rtr-hq-edge-0' + toString(i),
  deviceRole: 'EDGE',
  vendor: 'Cisco',
  platform: 'ISR 4431',
  siteId: 'site-hq',
  modelState: 'POR',
  lifecycleState: 'PLANNED',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// Link devices to site
MATCH (s:Site {siteId: 'site-hq'})
MATCH (d:Device {siteId: 'site-hq'})
CREATE (s)-[:CONTAINS]->(d);
```

### 1.3.3 — VLANs (Population + DMZ + Transit)

```cypher
// Population VLANs
UNWIND [
  {id: 100, name: 'Employee',   subnet: '10.100.0.0/24',  pop: 'EMPLOYEE'},
  {id: 110, name: 'Voice',      subnet: '10.100.10.0/24', pop: 'VOICE'},
  {id: 120, name: 'Printer',    subnet: '10.100.20.0/24', pop: 'PRINTER'},
  {id: 130, name: 'Video',      subnet: '10.100.30.0/24', pop: 'VIDEO'},
  {id: 140, name: 'Guest',      subnet: '10.100.40.0/24', pop: 'GUEST'},
  {id: 150, name: 'IoT',        subnet: '10.100.50.0/24', pop: 'IOT'},
  {id: 160, name: 'Management', subnet: '10.100.60.0/24', pop: 'MANAGEMENT'}
] AS v
CREATE (vl:VLAN {
  vlanId: 'vlan-hq-' + toString(v.id),
  tag: v.id,
  name: v.name,
  siteId: 'site-hq',
  populationType: v.pop,
  category: 'POPULATION',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
})
CREATE (sn:Subnet {
  subnetId: 'subnet-hq-' + toString(v.id),
  prefix: v.subnet,
  vlanTag: v.id,
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime()
})
CREATE (vl)-[:HAS_SUBNET]->(sn);

// DMZ VLANs
UNWIND [
  {id: 200, name: 'DMZ-Servers',    subnet: '10.200.0.0/24'},
  {id: 210, name: 'DNS-DMZ',        subnet: '10.200.10.0/24'},
  {id: 220, name: 'AD-DMZ',         subnet: '10.200.20.0/24'},
  {id: 230, name: 'File-DMZ',       subnet: '10.200.30.0/24'},
  {id: 240, name: 'PBX-DMZ',        subnet: '10.200.40.0/24'},
  {id: 250, name: 'Publish',        subnet: '10.200.50.0/24'},
  {id: 260, name: 'Proxy',          subnet: '10.200.60.0/24'},
  {id: 270, name: 'Management-DMZ', subnet: '10.200.70.0/24'}
] AS v
CREATE (vl:VLAN {
  vlanId: 'vlan-hq-' + toString(v.id),
  tag: v.id,
  name: v.name,
  siteId: 'site-hq',
  category: 'DMZ',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
})
CREATE (sn:Subnet {
  subnetId: 'subnet-hq-' + toString(v.id),
  prefix: v.subnet,
  vlanTag: v.id,
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime()
})
CREATE (vl)-[:HAS_SUBNET]->(sn);

// Transit VLAN (USF ↔ DMZFW)
CREATE (vl:VLAN {
  vlanId: 'vlan-hq-300',
  tag: 300,
  name: 'Transit-USF-DMZFW',
  siteId: 'site-hq',
  category: 'TRANSIT',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
})
CREATE (sn:Subnet {
  subnetId: 'subnet-hq-300',
  prefix: '10.100.255.0/30',
  vlanTag: 300,
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime()
})
CREATE (vl)-[:HAS_SUBNET]->(sn);

// Link VLANs to site
MATCH (s:Site {siteId: 'site-hq'})
MATCH (v:VLAN {siteId: 'site-hq'})
CREATE (s)-[:CONTAINS]->(v);
```

### 1.3.4 — Zones and Segments (Layer 2)

```cypher
// Security zones (matching the HLD firewall model)
UNWIND [
  {id: 'zone-hq-user',     name: 'User Zone',     type: 'USER'},
  {id: 'zone-hq-dmz',      name: 'DMZ Zone',      type: 'DMZ'},
  {id: 'zone-hq-internet',  name: 'Internet Zone', type: 'INTERNET'},
  {id: 'zone-hq-management', name: 'Management',   type: 'MANAGEMENT'}
] AS z
CREATE (zn:Zone {
  zoneId: z.id,
  name: z.name,
  zoneType: z.type,
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// Population segments (one per population VLAN)
UNWIND [
  {id: 'seg-hq-employee', name: 'Employee Segment', vlanTag: 100, zone: 'zone-hq-user'},
  {id: 'seg-hq-voice',    name: 'Voice Segment',    vlanTag: 110, zone: 'zone-hq-user'},
  {id: 'seg-hq-printer',  name: 'Printer Segment',  vlanTag: 120, zone: 'zone-hq-user'},
  {id: 'seg-hq-video',    name: 'Video Segment',    vlanTag: 130, zone: 'zone-hq-user'},
  {id: 'seg-hq-guest',    name: 'Guest Segment',    vlanTag: 140, zone: 'zone-hq-user'},
  {id: 'seg-hq-iot',      name: 'IoT Segment',      vlanTag: 150, zone: 'zone-hq-user'},
  {id: 'seg-hq-mgmt',     name: 'Mgmt Segment',     vlanTag: 160, zone: 'zone-hq-management'}
] AS sg
CREATE (s:Segment {
  segmentId: sg.id,
  name: sg.name,
  vlanTag: sg.vlanTag,
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
})
WITH s, sg
MATCH (z:Zone {zoneId: sg.zone})
CREATE (z)-[:CONTAINS]->(s)
WITH s, sg
MATCH (v:VLAN {tag: sg.vlanTag, siteId: 'site-hq'})
CREATE (s)-[:REALIZED_BY]->(v);

// Firewall Pairs
CREATE (fp1:FirewallPair {
  pairId: 'fwpair-hq-usf',
  name: 'User Services Firewall Pair',
  haMode: 'ACTIVE_ACTIVE',
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

CREATE (fp2:FirewallPair {
  pairId: 'fwpair-hq-dmzfw',
  name: 'DMZ/Internet Firewall Pair',
  haMode: 'ACTIVE_ACTIVE',
  siteId: 'site-hq',
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});

// Link firewall devices to their pairs
MATCH (fp:FirewallPair {pairId: 'fwpair-hq-usf'})
MATCH (d:Device) WHERE d.hostname STARTS WITH 'fw-hq-usr'
CREATE (fp)-[:AGGREGATES]->(d);

MATCH (fp:FirewallPair {pairId: 'fwpair-hq-dmzfw'})
MATCH (d:Device) WHERE d.hostname STARTS WITH 'fw-hq-dmz'
CREATE (fp)-[:AGGREGATES]->(d);
```

### 1.3.5 — Architecture References (Layer 3)

```cypher
// Architecture root
CREATE (a:Architecture {
  archId: 'arch-campus-ibn',
  name: 'Enterprise Campus IBN Architecture',
  modelState: 'POR',
  createdAt: datetime()
});

CREATE (av:ArchitectureVersion {
  versionId: 'arch-campus-ibn-v2.1',
  version: '2.1',
  archId: 'arch-campus-ibn',
  status: 'CURRENT',
  modelState: 'POR',
  createdAt: datetime()
});

CREATE (hld:HLDDocument {
  docId: 'hld-campus-v1.0',
  title: 'Enterprise Campus Network HLD',
  version: '1.0',
  modelState: 'POR',
  createdAt: datetime()
});

// Link: Architecture → Version → HLD
MATCH (a:Architecture {archId: 'arch-campus-ibn'})
MATCH (av:ArchitectureVersion {versionId: 'arch-campus-ibn-v2.1'})
MATCH (hld:HLDDocument {docId: 'hld-campus-v1.0'})
CREATE (a)-[:HAS_VERSION]->(av)
CREATE (av)-[:DOCUMENTED_BY]->(hld);

// Business Use Cases from the HLD
UNWIND [
  {id: 'buc-employee-access',  name: 'Employee LAN Access',       priority: 'HIGH'},
  {id: 'buc-voice',            name: 'IP Telephony (Voice VLAN)',  priority: 'HIGH'},
  {id: 'buc-guest-isolation',  name: 'Guest Network Isolation',   priority: 'MEDIUM'},
  {id: 'buc-dmz-services',     name: 'DMZ Service Publishing',    priority: 'HIGH'},
  {id: 'buc-internet-access',  name: 'Controlled Internet Access', priority: 'MEDIUM'}
] AS b
CREATE (buc:BusinessUseCase {
  bucId: b.id,
  name: b.name,
  priority: b.priority,
  modelState: 'POR',
  createdAt: datetime(),
  createdBy: 'hld-bootstrap'
});
```

---

## Step 1.4 — Campus Profile Validation Queries

These Cypher queries validate that the seeded data conforms to the Campus profile constraints (see §13.2 of the architecture document). Run each query — it should return no violations.

```cypher
// CAMPUS PROFILE CONSTRAINT 1: Every site must have at least one FirewallPair
MATCH (s:Site)
WHERE NOT EXISTS { MATCH (s)-[:CONTAINS]->(:Device {deviceRole: 'FIREWALL'}) }
RETURN s.siteId AS site_missing_firewall, s.name;
// Expected: 0 rows

// CAMPUS PROFILE CONSTRAINT 2: Population VLANs in range 100-160
MATCH (v:VLAN {category: 'POPULATION'})
WHERE NOT (v.tag >= 100 AND v.tag <= 160)
RETURN v.vlanId, v.tag AS out_of_range_vlan;
// Expected: 0 rows

// CAMPUS PROFILE CONSTRAINT 3: Transit VLAN 300 exists connecting USF ↔ DMZFW
MATCH (v:VLAN {tag: 300, category: 'TRANSIT'})
RETURN v.vlanId, v.name;
// Expected: 1 row (vlan-hq-300)

// CAMPUS PROFILE CONSTRAINT 4: Dual firewall architecture (USF + DMZFW)
MATCH (fp:FirewallPair {siteId: 'site-hq'})
RETURN fp.pairId, fp.name, fp.haMode;
// Expected: 2 rows (fwpair-hq-usf, fwpair-hq-dmzfw)

// CAMPUS PROFILE CONSTRAINT 5: All POR entities have modelState set
MATCH (n)
WHERE n.modelState IS NULL AND any(label IN labels(n) WHERE label IN ['Site', 'Device', 'VLAN', 'Zone', 'Segment', 'FirewallPair'])
RETURN labels(n) AS type, n.name AS missing_model_state;
// Expected: 0 rows
```

---

## Step 1.5 — Verify the Graph

Run these queries to confirm the graph structure:

```cypher
// Count nodes by label
CALL db.labels() YIELD label
CALL db.stats.retrieve('GRAPH COUNTS') YIELD nodeCount
WITH label
OPTIONAL MATCH (n) WHERE label IN labels(n)
RETURN label, count(n) AS count
ORDER BY count DESC;

// Visualize the site topology (run in Neo4j Browser)
MATCH (s:Site {siteId: 'site-hq'})-[r]->(child)
RETURN s, r, child;

// Cross-layer traversal test: Zone → Segment → VLAN
MATCH path = (z:Zone)-[:CONTAINS]->(seg:Segment)-[:REALIZED_BY]->(v:VLAN)
RETURN z.name AS zone, seg.name AS segment, v.tag AS vlan, v.name AS vlan_name
ORDER BY v.tag;
```

---

## Step 1.6 — What You've Built

After completing these steps, your Neo4j graph contains:

| Layer | Nodes | What |
|-------|-------|------|
| L1 | ~14 | 1 Site, 12 Devices (4 Access, 2 Agg, 2 USF, 2 DMZFW, 2 Edge), VLANs, Subnets |
| L2 | ~13 | 4 Zones, 7 Segments, 2 FirewallPairs |
| L3 | ~8 | 1 Architecture, 1 Version, 1 HLD doc, 5 BusinessUseCases |

All nodes carry `modelState: 'POR'` and `createdBy: 'hld-bootstrap'`. The graph is ready for Agent 1 (Ingestion) to create its first Intent node against this baseline.

---

## Next Steps

After validating the ontology:

1. **Step 2 — Deploy Live-Memory** → Create the `ibn-loop-inner` and `ibn-loop-outer` spaces with consolidation rules
2. **Step 3 — Agent 1 (Ingestion) prototype** → Accept a structured intent template, validate against SSoT, create an Intent node in L4
3. **Step 4 — Agent 5 (Orchestration) prototype** → Generate `topology.yml` from Neo4j, push to NetLab
4. **Step 5 — Agent 6 (Monitoring) prototype** → Poll NetLab devices, create As-Built model in L5
