# Test Plan — IBN Closed-Loop Phases 1–2

**Version:** 1.0
**Date:** April 2026
**Scope:** Foundation (Phase 1) and Inner Loop (Phase 2) — Neo4j ontology, Live-Memory, Graph-Memory, Agents 1/3/5/6/7/8, consolidation pipeline, inner loop self-correction
**Approach:** Layered — mock-based unit tests + integration tests against real infrastructure
**Framework:** Python 3.11+, pytest, neo4j-driver, httpx (MCP calls)
**Normative references:** RFC 9315 §5.1–5.2, §6; architecture document §5, §10, §12

---

## INDEX

1. [Test Strategy](#1-test-strategy)
2. [T1 — Neo4j Ontology and Schema](#2-t1--neo4j-ontology-and-schema)
3. [T2 — Neo4j HLD Data Seed](#3-t2--neo4j-hld-data-seed)
4. [T3 — Live-Memory Spaces and Pipeline](#4-t3--live-memory-spaces-and-pipeline)
5. [T4 — Agent 1: Ingestion](#5-t4--agent-1-ingestion)
6. [T5 — Agent 3: Policy→Config (Jinja2 pipeline)](#6-t5--agent-3-policyconfig-jinja2-pipeline)
7. [T6 — Agent 5: Orchestration](#7-t6--agent-5-orchestration)
8. [T7 — Agent 6: Monitoring](#8-t7--agent-6-monitoring)
9. [T8 — Agent 7: Compliance Assessment](#9-t8--agent-7-compliance-assessment)
10. [T9 — Agent 8: Compliance Action](#10-t9--agent-8-compliance-action)
11. [T10 — Graph-Memory (Tier 3)](#11-t10--graph-memory-tier-3)
12. [T11 — Consolidation Pipeline](#12-t11--consolidation-pipeline)
13. [T12 — Inner Loop End-to-End](#13-t12--inner-loop-end-to-end)
14. [T13 — Event Bus and Agent Communication](#14-t13--event-bus-and-agent-communication)
15. [T14 — Security and Audit Trail](#15-t14--security-and-audit-trail)
16. [T15 — Model State Lifecycle](#16-t15--model-state-lifecycle)

---

## 1. Test Strategy

### 1.1 Test Layers

| Layer | Purpose | External deps | Execution |
|-------|---------|---------------|-----------|
| **Unit** | Test agent logic, Neo4j queries, Jinja2 rendering in isolation | Mocked (Neo4j driver, MCP HTTP, SSH) | `pytest tests/unit/` — fast, no infra required |
| **Integration** | Test real Neo4j reads/writes, real Live-Memory MCP calls, real Jinja2 rendering against live services | Real Neo4j, Real Live-Memory, Real Graph-Memory | `pytest tests/integration/` — requires Docker Compose stack |
| **End-to-end** | Test full inner loop closure on NetLab | Real Neo4j + Live-Memory + Graph-Memory + NetLab | `pytest tests/e2e/` — requires full stack including NetLab |

### 1.2 Mock Strategy

All unit tests mock three boundaries:

1. **Neo4j** — Mock the `neo4j.Session` object. Provide canned query results for each Cypher query the agent executes. Assert that the agent issues the correct Cypher with the correct parameters.
2. **Live-Memory MCP** — Mock the HTTP transport. Intercept `live_note()`, `bank_consolidate()`, `bank_read_all()`, `space_create()` JSON-RPC calls. Return canned responses.
3. **SSH/NETCONF** — Mock the Netmiko/Napalm/Paramiko connections. Provide canned `show` command outputs and config push results.

### 1.3 Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `neo4j_session` | function | Mock `neo4j.Session` with configurable `run()` returns |
| `neo4j_real` | session | Real Neo4j Bolt connection (integration only) |
| `live_memory_client` | function | Mock MCP HTTP client |
| `live_memory_real` | session | Real MCP client pointing to Live-Memory :8002 |
| `graph_memory_client` | function | Mock MCP HTTP client for Graph-Memory |
| `graph_memory_real` | session | Real MCP client pointing to Graph-Memory :8002 |
| `ssh_connection` | function | Mock Netmiko ConnectHandler |
| `sample_intent` | function | Pre-built Intent dict matching the ontology schema |
| `sample_hld_seed` | session | Full HLD seed data (sites, devices, VLANs, zones) as dicts |
| `vyos_show_output` | function | Canned VyOS `show` command outputs for monitoring tests |

### 1.4 Naming Convention

```
tests/
├── unit/
│   ├── test_t1_neo4j_schema.py
│   ├── test_t2_hld_seed.py
│   ├── test_t3_live_memory.py
│   ├── test_t4_agent1_ingestion.py
│   ├── test_t5_agent3_policy_config.py
│   ├── test_t6_agent5_orchestration.py
│   ├── test_t7_agent6_monitoring.py
│   ├── test_t8_agent7_assessment.py
│   ├── test_t9_agent8_action.py
│   ├── test_t10_graph_memory.py
│   ├── test_t11_consolidation.py
│   ├── test_t13_event_bus.py
│   ├── test_t14_security.py
│   └── test_t15_model_state.py
├── integration/
│   ├── test_t1_neo4j_schema_integ.py
│   ├── test_t2_hld_seed_integ.py
│   ├── test_t3_live_memory_integ.py
│   ├── test_t10_graph_memory_integ.py
│   ├── test_t11_consolidation_integ.py
│   └── test_t12_inner_loop_integ.py
├── e2e/
│   └── test_t12_inner_loop_e2e.py
├── conftest.py
└── fixtures/
    ├── neo4j_canned.py
    ├── live_memory_canned.py
    ├── vyos_outputs.py
    └── sample_data.py
```

---

## 2. T1 — Neo4j Ontology and Schema

**What:** Validate that the 9-layer ontology schema loads correctly and enforces constraints.

### T1.1 — Schema DDL loads without errors

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T1.1.1 | Load `Neo4j_Schema_Cypher.cypher` | Integration | Full DDL file | All constraints and indexes created, zero errors |
| T1.1.2 | Idempotent reload | Integration | Load DDL twice | Second load produces no errors (IF NOT EXISTS guards) |

### T1.2 — Constraint enforcement

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T1.2.1 | Unique `intentId` on Intent node | Unit + Integ | Insert two Intent nodes with same `intentId` | `ConstraintValidationFailed` exception |
| T1.2.2 | Unique `deviceId` on Device node | Unit + Integ | Insert two Devices with same `deviceId` | `ConstraintValidationFailed` exception |
| T1.2.3 | Unique `vlanId+siteId` on VLAN node | Unit + Integ | Insert duplicate VLAN in same site | `ConstraintValidationFailed` exception |
| T1.2.4 | Required `modelState` on every node | Unit | Create node without `modelState` | Validation failure (application-level check) |

### T1.3 — Index verification

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T1.3.1 | Index exists on `Device.deviceId` | Integration | `SHOW INDEXES` | Index present, status ONLINE |
| T1.3.2 | Index exists on `Intent.intentId` | Integration | `SHOW INDEXES` | Index present, status ONLINE |
| T1.3.3 | Index exists on `modelState` (composite) | Integration | `SHOW INDEXES` | Index present for cross-label modelState queries |

### T1.4 — Layer node labels exist

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T1.4.1 | All L1 labels creatable | Unit + Integ | Create one of each: Site, Device, Interface, PhysicalLink, LogicalLink, VLAN, VRF, Subnet, IPAddress | All created successfully |
| T1.4.2 | All L2 labels creatable | Unit + Integ | Create: Topology, TopologyLayer, Zone, Segment, FirewallPair, StackGroup | All created successfully |
| T1.4.3 | All L3 labels creatable | Unit + Integ | Create: Architecture, ArchitectureVersion, HLD, ARD, BusinessUseCase | All created successfully |
| T1.4.4 | All L4 labels creatable | Unit + Integ | Create: Intent, Policy, FirewallRule, SGT, QoSPolicy | All created successfully |
| T1.4.5 | All L5 labels creatable | Unit + Integ | Create: Configuration, DeploymentEvent, Telemetry, OperationalState | All created successfully |
| T1.4.6 | All L6 labels creatable | Unit + Integ | Create: Alert, Incident, RootCause, ComplianceAssessment, Remediation | All created successfully |
| T1.4.7 | All L7–L9 labels creatable | Unit + Integ | Create: ChangeRequest, MigrationPlan, LifecyclePhase, LifecycleTransition, Operator, Team, Ticket, SLA, AgentExecution | All created successfully |

---

## 3. T2 — Neo4j HLD Data Seed

**What:** Validate that the HLD seed from Step 1 produces the correct graph structure.

### T2.1 — Node counts after seed

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T2.1.1 | Site count | Integration | Run seed Cypher | 1 Site (HQ), all with `modelState: 'POR'` |
| T2.1.2 | Device count | Integration | Run seed Cypher | 12 Devices (4 access, 2 agg, 2 USF, 2 DMZFW, 2 edge) |
| T2.1.3 | VLAN count | Integration | Run seed Cypher | 16 VLANs (7 population 100–160, 8 DMZ 200–270, 1 transit 300) |
| T2.1.4 | Zone count | Integration | Run seed Cypher | 4 Zones (User, DMZ, Internet, Management) |
| T2.1.5 | Segment count | Integration | Run seed Cypher | 7 Segments (Employee, Voice, Printer, Video, Guest, IoT, Management) |
| T2.1.6 | FirewallPair count | Integration | Run seed Cypher | 2 (USF pair, DMZFW pair) |
| T2.1.7 | Architecture + HLD | Integration | Run seed Cypher | 1 Architecture, 1 ArchitectureVersion, 1 HLD node |
| T2.1.8 | BusinessUseCase count | Integration | Run seed Cypher | 5 BUCs |

### T2.2 — Relationship integrity

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T2.2.1 | Site CONTAINS all devices | Integration | Traverse `(:Site)-[:CONTAINS]->(:Device)` | 12 devices reachable from HQ |
| T2.2.2 | FirewallPair AGGREGATES devices | Integration | Traverse `(:FirewallPair)-[:AGGREGATES]->(:Device)` | USF pair → 2 devices, DMZFW pair → 2 devices |
| T2.2.3 | Zone CONTAINS segments | Integration | Traverse `(:Zone)-[:CONTAINS]->(:Segment)` | User zone → 7 segments |
| T2.2.4 | VLAN BELONGS_TO site | Integration | Traverse `(:VLAN)-[:BELONGS_TO]->(:Site)` | All 16 VLANs link to HQ |

### T2.3 — Campus profile constraints

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T2.3.1 | Every site has ≥1 FirewallPair | Integration | Cypher assertion query | HQ has 2 FirewallPairs |
| T2.3.2 | Population VLANs in 100–160 range | Integration | `MATCH (v:VLAN) WHERE v.vlanType = 'population' RETURN v.vlanId` | All in [100,110,120,130,140,150,160] |
| T2.3.3 | Transit VLAN 300 exists | Integration | `MATCH (v:VLAN {vlanId: 300})` | Exactly 1 match |
| T2.3.4 | USF and DMZFW connected via transit | Integration | Path query through VLAN 300 | Path exists: USF → Transit300 → DMZFW |
| T2.3.5 | All seeded nodes have `modelState: 'POR'` | Integration | `MATCH (n) WHERE n.modelState IS NULL OR n.modelState <> 'POR'` | Zero results |

---

## 4. T3 — Live-Memory Spaces and Pipeline

**What:** Validate Live-Memory deployment, space creation, note ingestion, and consolidation.

### T3.1 — Space creation

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T3.1.1 | Create `ibn-loop-inner` space | Unit + Integ | `space_create()` with consolidation rules | Space created, 4 bank files defined |
| T3.1.2 | Create `ibn-loop-outer` space | Unit + Integ | `space_create()` | Space created, 5 bank files defined |
| T3.1.3 | Create `ibn-por-v1` space | Unit + Integ | `space_create()` | Space created, 4 bank files |
| T3.1.4 | Create `ibn-candidate-bootstrap` | Unit + Integ | `space_create()` | Space created, 4 bank files |
| T3.1.5 | Create `ibn-deploy-bootstrap` | Unit + Integ | `space_create()` | Space created, 3 bank files |
| T3.1.6 | Create `ibn-asbuilt-current` | Unit + Integ | `space_create()` | Space created, 3 bank files |
| T3.1.7 | Create `ibn-whatif-bootstrap` | Unit + Integ | `space_create()` | Space created, 3 bank files |
| T3.1.8 | `space_list()` returns all 7 | Integration | Call `space_list()` | 7 spaces with correct names |

### T3.2 — Note ingestion

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T3.2.1 | Write a live_note to ibn-loop-inner | Unit + Integ | `live_note(space='ibn-loop-inner', category='drift-detection', content='...')` | Note stored, note_id returned |
| T3.2.2 | Write multiple notes with different categories | Unit + Integ | 4 notes: drift-detection, remediation-attempt, remediation-result, loop-metrics | All 4 stored, distinct IDs |
| T3.2.3 | Read notes back from space | Unit + Integ | `note_list(space='ibn-loop-inner')` | 4 notes returned with correct categories |
| T3.2.4 | Note category maps to correct bank file | Unit | Check consolidation mapping rules | drift-detection → drift-analysis bank, remediation-attempt → active-remediations bank |

### T3.3 — Consolidation

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T3.3.1 | `bank_consolidate()` consumes notes | Integration | Write 5 notes → consolidate | Notes consumed, bank file updated with consolidated content |
| T3.3.2 | Bank file contains structured Markdown | Integration | `bank_read_all()` after consolidation | Each bank file contains structured Markdown per consolidation rules |
| T3.3.3 | Consolidation respects category→bank mapping | Integration | Notes with category X → consolidate | Only the corresponding bank file is updated |
| T3.3.4 | Empty space consolidation is a no-op | Unit + Integ | `bank_consolidate()` on space with no notes | No error, bank files unchanged |

### T3.4 — Token authentication

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T3.4.1 | Agent write token can write notes | Integration | Use agent-write token for `live_note()` | Success |
| T3.4.2 | Operator read token cannot write notes | Integration | Use operator-read token for `live_note()` | 403 Forbidden |
| T3.4.3 | Invalid token rejected | Unit + Integ | Use garbage token | 401 Unauthorized |

---

## 5. T4 — Agent 1: Ingestion

**What:** Validate intent parsing, validation, conflict detection, and Neo4j writes.

### T4.1 — Structured template ingestion

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T4.1.1 | Parse valid structured intent | Unit | `{"type": "access-policy", "subject": "Guest", "action": "permit", "target": "Internet"}` | Intent object created with all required fields |
| T4.1.2 | Reject malformed intent | Unit | Missing required field `subject` | Validation error with descriptive message |
| T4.1.3 | Reject empty intent statement | Unit | `{"type": "access-policy", "statement": ""}` | Validation error |

### T4.2 — Neo4j writes

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T4.2.1 | Creates Intent node in L4 | Unit | Valid intent | Cypher `CREATE (:Intent {intentId, statement, status: 'INGESTED', modelState: 'CANDIDATE', createdAt})` issued |
| T4.2.2 | Links Intent to BusinessUseCase | Unit | Intent referencing BUC | `(:Intent)-[:ADDRESSES]->(:BusinessUseCase)` relationship created |
| T4.2.3 | Sets `modelState: 'CANDIDATE'` | Unit | Any new intent | Node carries `modelState: 'CANDIDATE'` |
| T4.2.4 | Writes AgentExecution record | Unit | After ingestion | `(:AgentExecution {agentId: 'A1', timestamp, input, output})` created in L9 |

### T4.3 — Conflict detection

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T4.3.1 | Detect conflicting intent (same subject, opposite action) | Unit | Existing: Guest→PERMIT→Internet; New: Guest→DENY→Internet | Conflict detected, intent flagged |
| T4.3.2 | No conflict for non-overlapping intents | Unit | Existing: Guest→Internet; New: Employee→DMZ | No conflict |
| T4.3.3 | Detect duplicate intent | Unit | New intent identical to existing active intent | Duplicate flagged |

### T4.4 — Live-Memory integration

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T4.4.1 | Emits live_note on successful ingestion | Unit | Valid intent ingested | `live_note()` called with space=`ibn-candidate-{id}`, category='intent-ingestion' |
| T4.4.2 | Emits live_note on conflict detection | Unit | Conflicting intent | `live_note()` called with category='conflict-detection', content includes conflict details |

---

## 6. T5 — Agent 3: Policy→Config (Jinja2 Pipeline)

**What:** Validate Jinja2 template rendering from Neo4j policy data to VyOS device configurations.

### T5.1 — Cypher extraction queries

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T5.1.1 | `firewalls` query returns device pairs | Unit | Canned Neo4j response | 2 FirewallPairs with 4 devices total |
| T5.1.2 | `zones` query returns all zones | Unit | Canned Neo4j response | 4 zones with correct VLAN mappings |
| T5.1.3 | `segments` query returns population segments | Unit | Canned response | 7 segments with VLAN assignments |
| T5.1.4 | `policies` query returns active firewall rules | Unit | Canned response | FirewallRule nodes linked to Policy nodes |
| T5.1.5 | `fw_interfaces` query returns per-device interfaces | Unit | Canned response | Interface list with VLAN trunks and IP assignments |
| T5.1.6 | `nat_rules` query returns NAT configuration | Unit | Canned response | Source NAT and destination NAT rules |
| T5.1.7 | `fw_transit` query returns transit VLAN 300 | Unit | Canned response | Transit VLAN connecting USF↔DMZFW |
| T5.1.8 | All 8 queries execute without error on seeded DB | Integration | Real Neo4j with HLD seed | All return non-empty results |

### T5.2 — Jinja2 template rendering

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T5.2.1 | `vyos_firewall_base.j2` renders hostname, interfaces, system | Unit | Sample extraction dict | Valid VyOS config block with `set system host-name`, `set interfaces` |
| T5.2.2 | `vyos_firewall_policies.j2` renders zone policies | Unit | Sample zones + rules | `set firewall name`, `set zone-policy` commands |
| T5.2.3 | `vyos_nat.j2` renders NAT rules | Unit | Sample NAT rules | `set nat source rule` / `set nat destination rule` |
| T5.2.4 | `vyos_ha.j2` renders VRRP HA config | Unit | HA parameters | `set high-availability vrrp group` commands |
| T5.2.5 | Full 4-template chain renders complete config | Unit | Complete extraction data | Concatenated config is valid VyOS boot config |
| T5.2.6 | Rendering produces per-device output | Unit | Two USF devices | Two distinct config files with different hostnames/IPs |

### T5.3 — Configuration node creation

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T5.3.1 | Creates Configuration node in L5 | Unit | Rendered config | `(:Configuration {configId, deviceId, content, format: 'vyos-set', version, modelState: 'CANDIDATE'})` |
| T5.3.2 | Links Configuration to Policy via RENDERS | Unit | Config from policy | `(:Configuration)-[:RENDERS]->(:Policy)` created |
| T5.3.3 | Links Configuration to Device | Unit | Per-device config | `(:Configuration)-[:TARGETS]->(:Device)` created |
| T5.3.4 | Emits live_note to ibn-candidate space | Unit | After rendering | `live_note(category='config-rendering')` called |

### T5.4 — Diff generation

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T5.4.1 | Diff between existing and new config | Unit | Previous config v1, new config v2 | Line-by-line diff with additions/removals |
| T5.4.2 | Empty diff when config unchanged | Unit | Same config twice | No differences detected |

---

## 7. T6 — Agent 5: Orchestration

**What:** Validate config deployment to NetLab, post-deploy verification, and rollback.

### T6.1 — Config push

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T6.1.1 | SSH push to VyOS device succeeds | Unit | Mock SSH, valid config | Config commands sent in correct order, session closed cleanly |
| T6.1.2 | SSH push records DeploymentEvent | Unit | Successful push | `(:DeploymentEvent {eventId, timestamp, status: 'DEPLOYED', targetDeviceId})` created in L5 |
| T6.1.3 | SSH push failure records failed event | Unit | Mock SSH returns error | `(:DeploymentEvent {status: 'FAILED'})` created, no config applied |
| T6.1.4 | Push follows MigrationPlan order | Unit | Plan with 4 devices, sequenced | Devices configured in plan order, not arbitrary |
| T6.1.5 | Post-push config verification | Unit | Push + mock `show configuration` | Running config compared to intended config, match confirmed |

### T6.2 — Rollback

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T6.2.1 | Rollback on push failure | Unit | Device 3 of 4 fails | Devices 1–2 rolled back to previous config via `PRECEDED_BY` chain |
| T6.2.2 | Rollback event recorded in Neo4j | Unit | After rollback | `(:DeploymentEvent {status: 'ROLLED_BACK'})` nodes for rolled-back devices |

### T6.3 — Model state transitions

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T6.3.1 | Config nodes transition CANDIDATE → DEPLOYED | Unit | Successful push | `modelState` updated from `CANDIDATE` to `DEPLOYED` |
| T6.3.2 | Intent status updated to ORCHESTRATED | Unit | All configs for intent deployed | `(:Intent).status` = `ORCHESTRATED` |

### T6.4 — Live-Memory integration

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T6.4.1 | Emits live_note on deploy start | Unit | Deploy begins | `live_note(space='ibn-deploy-{event}', category='deployment-start')` |
| T6.4.2 | Emits live_note per device result | Unit | Per-device outcome | One note per device with success/failure detail |
| T6.4.3 | Emits live_note on rollback | Unit | Rollback triggered | `live_note(category='rollback-triggered')` with affected devices |

---

## 8. T7 — Agent 6: Monitoring

**What:** Validate telemetry collection, state normalization, and As-Built model updates.

### T7.1 — CLI polling

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T7.1.1 | Parse VyOS `show interfaces` output | Unit | Canned CLI output | Interface list with admin/oper state, IP, counters |
| T7.1.2 | Parse VyOS `show firewall` output | Unit | Canned CLI output | Zone policy hit counters extracted |
| T7.1.3 | Parse VyOS `show vrrp` output | Unit | Canned CLI output | VRRP state (master/backup), priority, virtual IP |
| T7.1.4 | Parse VyOS `show ip route` output | Unit | Canned CLI output | Route table entries with next-hop, metric |
| T7.1.5 | SSH connection failure handled gracefully | Unit | Mock SSH timeout | Alert generated, no crash, retry scheduled |

### T7.2 — Neo4j As-Built writes

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T7.2.1 | Creates Telemetry nodes in L5 | Unit | Parsed interface counters | `(:Telemetry {timestamp, metric, value, deviceId, modelState: 'AS_BUILT'})` |
| T7.2.2 | Updates OperationalState on Device | Unit | Parsed device state | `(:Device).operState` updated to match observed |
| T7.2.3 | Updates Interface oper state | Unit | Interface up/down observed | `(:Interface).operState` updated |
| T7.2.4 | Creates Alert on threshold breach | Unit | CPU > 90% | `(:Alert {severity: 'MEDIUM'})-[:DETECTED_ON]->(:Device)` |
| T7.2.5 | As-Built nodes carry `modelState: 'AS_BUILT'` | Unit | Any telemetry write | All new nodes have `modelState: 'AS_BUILT'` |

### T7.3 — Live-Memory integration

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T7.3.1 | Emits live_note per polling cycle | Unit | After poll of all devices | `live_note(space='ibn-asbuilt-current', category='telemetry-snapshot')` |
| T7.3.2 | Emits live_note on anomaly detection | Unit | Unexpected state change | `live_note(category='anomaly-detected')` with details |

---

## 9. T8 — Agent 7: Compliance Assessment

**What:** Validate desired vs. observed comparison, drift detection, and root cause analysis.

### T8.1 — Compliance comparison

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T8.1.1 | COMPLIANT when POR matches As-Built | Unit | POR config = observed running config | Verdict: `COMPLIANT` |
| T8.1.2 | NON_COMPLIANT when config drift detected | Unit | POR firewall rule present, observed missing | Verdict: `NON_COMPLIANT`, drift details populated |
| T8.1.3 | DEGRADED when partial compliance | Unit | 3 of 4 policies compliant, 1 drifted | Verdict: `DEGRADED` |
| T8.1.4 | UNKNOWN when device unreachable | Unit | Monitoring returns no data for device | Verdict: `UNKNOWN` |

### T8.2 — Drift detection

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T8.2.1 | Detect firewall rule drift | Unit | POR has rule, As-Built missing rule | Drift event: type=`config_drift`, element=`FirewallRule`, detail=rule ID |
| T8.2.2 | Detect interface state drift | Unit | POR expects up, As-Built shows down | Drift event: type=`state_drift`, element=`Interface` |
| T8.2.3 | Detect VRRP role drift | Unit | POR expects master, As-Built shows backup | Drift event: type=`ha_drift`, element=`FirewallPair` |
| T8.2.4 | No drift when states match | Unit | All match | No drift events generated |

### T8.3 — Root cause analysis

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T8.3.1 | Traverse dependency graph for root cause | Unit | Interface down → firewall rule drift | Root cause: `Interface` down, affected: `FirewallRule`, `Policy`, `Intent` |
| T8.3.2 | Multiple drift events → single root cause | Unit | 3 rules drifted, all on same device | Single Incident with 3 related ComplianceAssessments |

### T8.4 — Neo4j writes

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T8.4.1 | Creates ComplianceAssessment node in L6 | Unit | Any assessment | `(:ComplianceAssessment {assessmentId, intentId, verdict, timestamp})` |
| T8.4.2 | Links assessment to intent | Unit | Assessment for intent X | `(:ComplianceAssessment)-[:ASSESSES]->(:Intent)` |
| T8.4.3 | Creates Incident on NON_COMPLIANT | Unit | Non-compliant verdict | `(:Incident)-[:CAUSED_BY]->(:RootCause)` |
| T8.4.4 | Updates Intent.complianceStatus | Unit | After assessment | `(:Intent).complianceStatus` set to verdict |

### T8.5 — Live-Memory integration

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T8.5.1 | Emits live_note on drift detection | Unit | Drift found | `live_note(space='ibn-loop-inner', category='drift-detection')` |
| T8.5.2 | Emits live_note on compliance verdict | Unit | Assessment complete | `live_note(category='assessment-result')` with verdict and details |

---

## 10. T9 — Agent 8: Compliance Action

**What:** Validate severity classification, autonomy decision matrix, remediation, and escalation.

### T9.1 — Severity classification

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T9.1.1 | Info — minor metric fluctuation | Unit | CPU at 72% (threshold 90%) | Severity: `INFO` |
| T9.1.2 | Low — single interface down, redundancy active | Unit | 1 interface down, VRRP backup active | Severity: `LOW` |
| T9.1.3 | Medium — drift on multiple devices | Unit | Same policy drifted on 2+ devices | Severity: `MEDIUM` |
| T9.1.4 | High — service-impacting non-compliance | Unit | Intent verdict NON_COMPLIANT, business-critical BUC | Severity: `HIGH` |
| T9.1.5 | Critical — multiple intents violated | Unit | 3+ intents non-compliant simultaneously | Severity: `CRITICAL` |

### T9.2 — Autonomy decision matrix

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T9.2.1 | Info → log only | Unit | Severity INFO | Action: log to Neo4j, no remediation, no escalation |
| T9.2.2 | Low → auto-remediate | Unit | Severity LOW | Action: re-push config via Agent 5, no human involved |
| T9.2.3 | Medium → auto-remediate with scope | Unit | Severity MEDIUM | Action: re-orchestrate affected scope, verify after |
| T9.2.4 | High → escalate | Unit | Severity HIGH | Action: create Ticket in L9, pause auto changes, notify human |
| T9.2.5 | Critical → rollback + escalate | Unit | Severity CRITICAL | Action: rollback to last-known-good, freeze orchestration, create Ticket |

### T9.3 — Remediation execution

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T9.3.1 | Triggers Agent 5 re-push for LOW | Unit | LOW severity incident | Calls Agent 5 orchestration with `PRECEDED_BY` config |
| T9.3.2 | Creates Remediation node in L6 | Unit | Any remediation | `(:Remediation {action, timestamp, success})-[:RESOLVES]->(:Incident)` |
| T9.3.3 | Records success after re-verification | Unit | Agent 7 re-assesses as COMPLIANT | `(:Remediation).success = true` |
| T9.3.4 | Records failure and escalates | Unit | Re-push fails or re-assessment still NON_COMPLIANT | `(:Remediation).success = false`, escalate to next severity tier |

### T9.4 — Rollback via PRECEDED_BY

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T9.4.1 | Traverse PRECEDED_BY to find last-known-good | Unit | Config v3 broken, v2 was last COMPLIANT | Traverses `(:Configuration)-[:PRECEDED_BY]->(:Configuration)` to find v2 |
| T9.4.2 | Rollback deploys previous config version | Unit | After finding v2 | Agent 5 called with v2 config, new DeploymentEvent created |

### T9.5 — Live-Memory integration

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T9.5.1 | Emits live_note on remediation attempt | Unit | Starting remediation | `live_note(space='ibn-loop-inner', category='remediation-attempt')` |
| T9.5.2 | Emits live_note on remediation result | Unit | Remediation complete | `live_note(category='remediation-result')` with success/failure |
| T9.5.3 | Emits live_note on escalation | Unit | Escalating to human | `live_note(space='ibn-loop-outer', category='escalation')` with full context |

---

## 11. T10 — Graph-Memory (Tier 3)

**What:** Validate Graph-Memory deployment, namespace isolation, ontology-driven ingestion, and RAG queries.

### T10.1 — Namespace isolation

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T10.1.1 | Graph-Memory uses `IBN_LIFECYCLE_*` labels | Unit + Integ | Create entity via Graph-Memory | Neo4j label is `IBN_LIFECYCLE_Entity`, not `Entity` |
| T10.1.2 | No collision with SSoT labels | Integration | Query SSoT labels vs Graph-Memory labels | Zero overlap |
| T10.1.3 | Same Neo4j instance, different namespaces | Integration | Both SSoT and Graph-Memory write | Both readable, no interference |

### T10.2 — IBN Network Lifecycle ontology

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T10.2.1 | Entity families extractable | Unit | Consolidated bank file mentioning a policy decision | Extracts: `PolicyDecision` entity with correct properties |
| T10.2.2 | Relationship types created | Unit | Bank file mentioning drift caused by config change | Creates `CAUSED_BY` relationship between DriftEvent and ConfigChange |
| T10.2.3 | All 4 entity families supported | Unit | Various bank files | Decisions, Incidents, Operations, Knowledge entities all creatable |

### T10.3 — Qdrant embeddings

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T10.3.1 | BGE-M3 embedding generated | Unit + Integ | Text from bank file | 1024-dimension vector stored in Qdrant |
| T10.3.2 | Semantic search returns relevant results | Integration | Query: "firewall rule drift" | Returns entities related to firewall drift events |

### T10.4 — Graph-guided RAG

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T10.4.1 | `question_answer()` returns relevant knowledge | Unit + Integ | "What happened last time USF firewall drifted?" | Returns historical DriftEvent + Remediation narrative |
| T10.4.2 | Graph traversal augments vector search | Unit | Query that matches entity with graph neighbors | Response includes related entities found via graph traversal, not just vector similarity |

---

## 12. T11 — Consolidation Pipeline

**What:** Validate the full Live-Memory → Graph-Memory bridge pipeline.

### T11.1 — bank_consolidate()

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T11.1.1 | LLM-driven consolidation produces structured Markdown | Integration | 10 raw notes in `ibn-loop-inner` | Bank files contain consolidated, structured Markdown |
| T11.1.2 | Notes consumed after consolidation | Integration | After consolidation | `note_list()` returns empty (notes moved to bank) |
| T11.1.3 | Consolidation rules respected | Integration | Notes with mixed categories | Each note consolidated into the correct bank file per mapping |

### T11.2 — graph_push()

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T11.2.1 | Bank files pushed to Graph-Memory | Integration | Consolidated bank files | `graph_push()` sends content to Graph-Memory ingestion |
| T11.2.2 | Ontology-driven extraction from bank content | Integration | Bank file with remediation narrative | Entities (RemediationAction, DriftEvent) and relationships extracted |
| T11.2.3 | Embeddings generated for pushed content | Integration | After graph_push | Qdrant collection contains new vectors |

### T11.3 — Model state transition triggers

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T11.3.1 | What-If → Candidate triggers consolidation | Unit | Model state transition event | `bank_consolidate()` called on `ibn-whatif-{id}` space |
| T11.3.2 | Candidate → POR triggers consolidation | Unit | Model state transition | `bank_consolidate()` called on `ibn-candidate-{id}` |
| T11.3.3 | POR → Deployed triggers consolidation | Unit | Model state transition | `bank_consolidate()` called on `ibn-por-{version}` |
| T11.3.4 | Deployed → As-Built triggers consolidation | Unit | Model state transition | `bank_consolidate()` called on `ibn-deploy-{event}` |
| T11.3.5 | Inner loop iteration triggers consolidation | Unit | After remediation cycle completes | `bank_consolidate()` called on `ibn-loop-inner` |

---

## 13. T12 — Inner Loop End-to-End

**What:** Validate the complete inner loop: drift → assess → act → re-orchestrate → verify.

### T12.1 — Fulfillment path (Phase 1 E2E)

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T12.1.1 | Intent → SSoT → Config → Deploy → Observe | E2E | Structured intent: "Employee VLAN 100 must reach Internet via USF" | Intent created (L4), Policy created (L4), Config rendered (L5), deployed to NetLab, telemetry collected, As-Built updated |
| T12.1.2 | All model states present after fulfillment | E2E | After full path | Neo4j contains: CANDIDATE intent, POR policy, DEPLOYED config, AS_BUILT telemetry |

### T12.2 — Assurance path (Phase 2 E2E)

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T12.2.1 | Inject drift → detect → assess | E2E | Manually remove a firewall rule on NetLab device | Agent 6 detects missing rule, Agent 7 assesses as NON_COMPLIANT |
| T12.2.2 | Auto-remediate LOW severity drift | E2E | Single rule missing, redundancy active | Agent 8 classifies LOW, triggers Agent 5 re-push, Agent 7 re-assesses as COMPLIANT |
| T12.2.3 | Escalate HIGH severity drift | E2E | Multiple intents violated | Agent 8 classifies HIGH, creates Ticket, pauses orchestration |

### T12.3 — Full inner loop cycle time

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T12.3.1 | Detection latency | E2E | Inject drift, measure time to Alert | ≤ 5 minutes (monitoring interval) |
| T12.3.2 | Remediation latency | E2E | From Alert to COMPLIANT | ≤ 15 minutes for LOW severity |
| T12.3.3 | Full cycle: drift → remediated | E2E | Inject → detect → assess → remediate → verify | Complete cycle within 20 minutes |

### T12.4 — Memory tier integration during loop

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T12.4.1 | All agents emit live_notes during loop | E2E | After full cycle | `ibn-loop-inner` space contains notes from Agents 6, 7, 8 |
| T12.4.2 | Consolidation produces bank files | E2E | Trigger consolidation after loop | Bank files: drift-analysis, active-remediations, remediation-history populated |
| T12.4.3 | Graph-Memory receives knowledge | E2E | After graph_push | Knowledge graph contains DriftEvent + Remediation entities |

---

## 14. T13 — Event Bus and Agent Communication

**What:** Validate that agents communicate through Neo4j CDC / event bus correctly.

### T13.1 — Event routing

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T13.1.1 | Intent creation triggers Agent 2 notification | Unit | New Intent node in Neo4j | CDC/event bus emits `intent.created` event, routed to Agent 2 |
| T13.1.2 | Policy creation triggers Agent 3 notification | Unit | New Policy node | `policy.approved` event routed to Agent 3 |
| T13.1.3 | Configuration created triggers Agent 5 | Unit | New Configuration node | `config.ready` event routed to Agent 5 |
| T13.1.4 | DeploymentEvent triggers Agent 6 | Unit | Deploy complete | `deployment.complete` event routed to Agent 6 |
| T13.1.5 | ComplianceAssessment triggers Agent 8 | Unit | NON_COMPLIANT verdict | `assessment.non_compliant` event routed to Agent 8 |
| T13.1.6 | Remediation triggers Agent 5 (re-push) | Unit | AUTO_REMEDIATE action | `remediation.re_orchestrate` event routed to Agent 5 |

### T13.2 — Event ordering

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T13.2.1 | Events processed in causal order | Unit | Multiple concurrent events | Events for same intent processed sequentially |
| T13.2.2 | No duplicate event delivery | Unit | Single Neo4j write | Exactly one event emitted per write |

---

## 15. T14 — Security and Audit Trail

**What:** Validate RBAC, token auth, autonomy boundaries, and audit completeness.

### T14.1 — Intent verification pipeline

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T14.1.1 | Syntactically invalid intent rejected | Unit | Malformed JSON | Rejected at syntactic check |
| T14.1.2 | Conflicting intent flagged | Unit | Conflicts with active intent | Flagged at conflict check |
| T14.1.3 | Infeasible intent rejected | Unit | Requires nonexistent VLAN | Rejected at feasibility check |
| T14.1.4 | Unauthorized author rejected | Unit | Author without `intent.create` permission | Rejected at RBAC check |

### T14.2 — Autonomy boundaries

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T14.2.1 | Inner loop cannot modify intent | Unit | Agent 8 attempts to change Intent.statement | Blocked, error logged |
| T14.2.2 | Inner loop cannot add/remove devices | Unit | Agent 8 attempts to create Device node | Blocked, error logged |
| T14.2.3 | Inner loop can re-push existing config | Unit | Agent 8 triggers re-push of POR config | Allowed |
| T14.2.4 | Inner loop blocked on DECOMMISSIONING entities | Unit | Agent 8 attempts action on decommissioning intent | Blocked, error logged |

### T14.3 — Audit trail completeness

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T14.3.1 | Every agent action recorded | Unit | Any agent action | `(:AgentExecution)` node created with timestamp, agentId, input, output |
| T14.3.2 | Full traceability: intent → device | Integration | Given an intent ID | Cypher traversal returns: Intent → Policy → Config → DeploymentEvent → Device |
| T14.3.3 | Full traceability: device → intent | Integration | Given a device ID | Reverse traversal returns: Device → Config → Policy → Intent |

---

## 16. T15 — Model State Lifecycle

**What:** Validate correct model state transitions and immutability.

### T15.1 — State transitions

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T15.1.1 | WHAT_IF → CANDIDATE | Unit | Agent approves what-if | `modelState` updated, `PRECEDED_BY` link created |
| T15.1.2 | CANDIDATE → POR | Unit | Candidate approved | `modelState` updated to `POR` |
| T15.1.3 | POR → DEPLOYED | Unit | Orchestration succeeds | Config `modelState` updated to `DEPLOYED` |
| T15.1.4 | DEPLOYED → AS_BUILT | Unit | Monitoring verifies | As-Built nodes created with `modelState: 'AS_BUILT'` |
| T15.1.5 | Invalid transition rejected | Unit | Attempt WHAT_IF → DEPLOYED directly | Transition blocked, error logged |

### T15.2 — Immutability

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T15.2.1 | Nodes are never mutated, only versioned | Unit | Config update | New Configuration node created with `PRECEDED_BY` → old node |
| T15.2.2 | PRECEDED_BY chain is traversable | Integration | 3 versions of same config | `v3 -[:PRECEDED_BY]-> v2 -[:PRECEDED_BY]-> v1` |
| T15.2.3 | Old versions remain readable | Integration | After creating v2 | v1 still exists with original properties |

### T15.3 — Cross-model-state queries

| ID | Test | Type | Input | Expected |
|----|------|------|-------|----------|
| T15.3.1 | Query all POR nodes | Integration | `MATCH (n) WHERE n.modelState = 'POR'` | Returns only POR nodes |
| T15.3.2 | Compare POR vs AS_BUILT for device | Integration | Same device, both states | Returns both sets of nodes for comparison |
| T15.3.3 | Count nodes per model state | Integration | `MATCH (n) RETURN n.modelState, count(n)` | Correct counts across all 5 states |

---

## Test Coverage Matrix

| Component | Unit Tests | Integration Tests | E2E Tests | Total |
|-----------|-----------|-------------------|-----------|-------|
| T1 Neo4j Schema | 5 | 8 | — | 13 |
| T2 HLD Seed | — | 13 | — | 13 |
| T3 Live-Memory | 8 | 8 | — | 16 |
| T4 Agent 1 (Ingestion) | 11 | — | — | 11 |
| T5 Agent 3 (Policy→Config) | 14 | 1 | — | 15 |
| T6 Agent 5 (Orchestration) | 11 | — | — | 11 |
| T7 Agent 6 (Monitoring) | 9 | — | — | 9 |
| T8 Agent 7 (Assessment) | 14 | — | — | 14 |
| T9 Agent 8 (Action) | 15 | — | — | 15 |
| T10 Graph-Memory | 5 | 4 | — | 9 |
| T11 Consolidation | 3 | 5 | — | 8 |
| T12 Inner Loop E2E | — | — | 9 | 9 |
| T13 Event Bus | 8 | — | — | 8 |
| T14 Security/Audit | 8 | 2 | — | 10 |
| T15 Model State | 5 | 4 | — | 9 |
| **Total** | **116** | **45** | **9** | **170** |

---

## RFC 9315 Traceability

| RFC 9315 Section | Functional Block | Test IDs |
|------------------|-----------------|----------|
| §5.1.1 | Intent Ingestion | T4.* |
| §5.1.2 | Intent Translation (Policy) | T5.* |
| §5.1.2 | Intent Translation (Config) | T5.* |
| §5.1.3 | Intent Orchestration | T6.* |
| §5.2.1 | Monitoring | T7.* |
| §5.2.2 | Compliance Assessment | T8.* |
| §5.2.3 | Compliance Action | T9.* |
| §6 | Inner Loop (autonomous) | T12.* |
| §6 | Outer Loop (human) | T9.2.4, T9.2.5 (escalation only — full outer loop is Phase 4) |
| §9 | Security Considerations | T14.* |
