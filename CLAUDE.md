# IBN Closed-Loop Feedback Control Architecture

## What This Project Is

An Intent-Based Networking (IBN) closed-loop feedback control system for an enterprise campus network. The architecture is grounded in **RFC 9315** (Intent-Based Networking: Concepts and Definitions) and enhanced with Google's **MALT** multi-model lifecycle approach (Mogul et al., NSDI '20).

The system uses **10 AI agents** to manage the full network lifecycle — from intent ingestion through policy translation, config rendering, orchestration, monitoring, compliance assessment, and remediation — operating in two feedback loops (inner = autonomous, outer = human-in-the-loop).

## Architecture Decisions (non-negotiable)

- **SSoT**: Neo4j graph database with a 9-layer property graph ontology (L1 Infrastructure → L9 People/Process)
- **Target network**: NetLab (netlab.tools) virtual lab infrastructure with VyOS firewalls
- **5 concurrent model states** in Neo4j: What-If, Candidate, POR (Plan-of-Record), Deployed, As-Built
- **Three-tier memory**:
  - Tier 1 — Neo4j SSoT: structured network state (WHAT the network IS)
  - Tier 2 — Live-Memory (Cloud-Temple): working memory for agent reasoning (WHY it is in this state)
  - Tier 3 — Graph-Memory (Cloud-Temple): long-term knowledge graph + Qdrant RAG (WHAT WAS LEARNED)
- **Agent communication**: Neo4j SSoT + event bus (CDC/Kafka/Redis) + Live-Memory `live_note()` MCP + Graph-Memory `question_answer()` MCP
- **Two loops**: Inner (autonomous machine-to-machine) and Outer (human-in-the-loop) per RFC 9315 §6
- **Firewall pipeline**: Jinja2 templates rendering VyOS configs from Neo4j state (see `firewall_pipeline/`)

## Key Documents

| Document | Purpose |
|----------|---------|
| `IBN_Closed_Loop_Architecture.md` | **Master architecture document** (v2.1, 15 sections). The source of truth for all design decisions. Read this first. |
| `Neo4j_Ontology_Network_Lifecycle.md` | 9-layer ontology specification — node labels, properties, relationships, constraints |
| `Neo4j_Schema_Cypher.cypher` | Cypher DDL schema (616 lines) — constraints, indexes, seed data templates. **Theoretical design — not yet deployed.** |
| `Enterprise_Campus_Network_HLD (1).md` | The companion HLD — multi-site campus, dual firewall, population VLANs 100-160, DMZ VLANs 200-270 |
| `IBN_Closed_Loop_Diagram.mermaid` | Comprehensive Mermaid diagram of the full closed loop |
| `NetLab_Feasibility_Analysis.md` | Mapping HLD elements to netlab.tools capabilities |
| `topology_campus_large_site.yml` | NetLab topology YAML for the large site |
| `rfc9315.txt` | RFC 9315 full text |
| `firewall_pipeline/` | Jinja2 rendering pipeline: Cypher extraction → templates → VyOS config → SSH push |
| `STEP1_Neo4j_Ontology_Bootstrap.md` | Step-by-step guide: Deploy Neo4j, load 9-layer ontology, seed HLD data (~35 nodes L1-L3) |
| `STEP2_Live_Memory_Bootstrap.md` | Step-by-step guide: Deploy Live-Memory, create 7 IBN spaces with domain-specific consolidation rules |

## The 10 AI Agents

| Agent | Name | RFC 9315 | Function | Neo4j Write Target |
|-------|------|----------|----------|--------------------|
| A1 | Ingestion | §5.1.1 | Parse intent (NL/template/API), validate, conflict-check | Intent → L4 |
| A2 | Intent→Policy | §5.1.2 | Decompose intent into policy rules, SGT, zones | Policy, FWRule → L4 |
| A3 | Policy→Config | §5.1.2 | Render vendor-specific configs (Jinja2 for VyOS) | Configuration → L5 |
| A4 | Planning | §5.1.2 | What-If analysis, blast radius, migration sequencing | MigrationPlan → L7 |
| A5 | Orchestration | §5.1.3 | Push config to NetLab (SSH/NETCONF), rollback | DeploymentEvent → L5 |
| A6 | Monitoring | §5.2.1 | Collect telemetry (gNMI/SNMP/CLI), build As-Built model | Telemetry, OpState → L5 |
| A7 | Assessment | §5.2.2 | Compare POR vs As-Built, detect drift, root cause | ComplianceAssessment → L6 |
| A8 | Action | §5.2.3 | Decide: log / auto-remediate / re-orchestrate / escalate | Remediation → L6 |
| A9 | Abstraction | §5.2 | Aggregate across layers, produce trend summaries | Aggregated data → all layers |
| A10 | Reporting | §5.2 | Generate human-facing reports, dashboards, alerts | Reports → L9 |

## Neo4j 9-Layer Ontology

```
L1  Infrastructure    Site, Device, Interface, PhysicalLink, LogicalLink, VLAN, VRF, Subnet, IPAddress
L2  Topology          Topology, TopologyLayer, Zone, Segment, FirewallPair, StackGroup
L3  Architecture      Architecture, ArchitectureVersion, HLD, ARD, BusinessUseCase
L4  Policy & Intent   Intent, Policy, FirewallRule, SGT, QoSPolicy
L5  Config & State    Configuration, DeploymentEvent, Telemetry, OperationalState
L6  Incidents         Alert, Incident, RootCause, ComplianceAssessment, Remediation
L7  Change Mgmt       ChangeRequest, MigrationPlan
L8  Lifecycle         LifecyclePhase, LifecycleTransition
L9  People/Process    Operator, Team, Ticket, SLA, AgentExecution
```

Cross-layer relationships: `REALIZED_BY`, `ABSTRACTS`, `AGGREGATES`, `CONTAINS`, `TRAVERSES`, `PRECEDED_BY`

Model state property: every node carries `modelState` ∈ {`WHAT_IF`, `CANDIDATE`, `POR`, `DEPLOYED`, `AS_BUILT`}

## Three-Tier Memory Architecture

```
Tier 1: Neo4j SSoT          Tier 2: Live-Memory          Tier 3: Graph-Memory
(Structured State)           (Working Memory)              (Long-Term Knowledge)
   │                            │                             │
   │ Bolt 7687                  │ MCP :8002 (S3)             │ MCP :8002 (Neo4j ns + Qdrant)
   │                            │                             │
   │ 5 model states             │ live_note() → bank          │ Ontology-driven extraction
   │ 9-layer ontology           │ bank_consolidate()          │ BGE-M3 embeddings
   │ Typed nodes/rels           │ Space-per-model-state       │ Graph-guided RAG
   │                            │                             │
   │ WHAT it IS                 │ WHY it is this way          │ WHAT WAS LEARNED
   │                            │      │                      │
   │                            │      └── graph_push() ──────►│
   │◄───────────────────────────┼──────────────────────────────┘
   │  question_answer() (RAG)   │     (agents query history)
```

Live-Memory spaces: `ibn-whatif-{id}`, `ibn-candidate-{id}`, `ibn-por-{version}`, `ibn-deploy-{event}`, `ibn-asbuilt-{snapshot}`, `ibn-loop-inner`, `ibn-loop-outer`

## External Dependencies

| Component | Version | Purpose |
|-----------|---------|---------|
| Neo4j | 5.x (Community or Enterprise) | SSoT graph database |
| NetLab | latest (netlab.tools) | Virtual lab infrastructure |
| Live-Memory | latest (Cloud-Temple) | Working memory MCP server |
| Graph-Memory | v2.1+ (Cloud-Temple) | Knowledge graph MCP server |
| Qdrant | v1.16+ | Vector embeddings for Graph-Memory |
| VyOS | 1.4+ (rolling) | Firewall platform in NetLab |
| Python | 3.11+ | Agent runtime, Jinja2 pipeline |
| Docker Compose | latest | Container orchestration |

## Implementation Status

### Done (design phase)
- [x] HLD for the enterprise campus network
- [x] 9-layer ontology specification
- [x] Cypher DDL schema (theoretical — `Neo4j_Schema_Cypher.cypher`)
- [x] Closed-loop architecture document (v2.1, 15 sections)
- [x] Three-tier memory architecture design (Live-Memory + Graph-Memory)
- [x] Jinja2 firewall pipeline (templates + renderer + dry-run validated)
- [x] NetLab topology YAML
- [x] Mermaid diagram of the full closed loop

### Done (implementation guides)
- [x] Step 1 guide: Neo4j ontology bootstrap (`STEP1_Neo4j_Ontology_Bootstrap.md`)
- [x] Step 2 guide: Live-Memory bootstrap (`STEP2_Live_Memory_Bootstrap.md`)
- [x] Step 3 guide: Graph-Memory + Qdrant bootstrap (`STEP3_Graph_Memory_Bootstrap.md`)

---

### Phase 1 — Foundation (Months 1–3)

**Infrastructure (Steps 1–3):**
- [ ] Deploy Neo4j and load the 9-layer ontology schema (follow `STEP1_Neo4j_Ontology_Bootstrap.md`)
- [ ] Seed Neo4j with HLD data — sites, devices, VLANs, subnets, zones, segments, firewall pairs (~35 nodes L1–L3)
- [ ] Validate schema with Campus profile Cypher constraints
- [ ] Deploy Live-Memory MCP server with S3 backend, create 7 foundational spaces with consolidation rules (follow `STEP2_Live_Memory_Bootstrap.md`)
- [x] Configure event bus infrastructure — Redis Streams event bus (`src/ibn/core/redis_event_bus.py` + `docker-compose.yml`)

**Fulfillment agents (Steps 4–5):**
- [x] Implement Agent 1 (Ingestion) — structured template input, intent node creation (L4), conflict detection, `live_note()` integration (`src/ibn/agents/agent1_ingestion.py`)
- [x] Implement Agent 5 (Orchestration) — NetLab `topology.yml` generation, SSH config push, post-deploy verification, `live_note()` integration (`src/ibn/agents/agent5_orchestration.py`)
- [x] Implement Agent 6 (Monitoring) — CLI/SNMP polling from NetLab, telemetry node creation (L5/L6), OperationalState updates, `live_note()` integration (`src/ibn/agents/agent6_monitoring.py`)

**Validation:**
- [ ] End-to-end fulfillment path: Intent → SSoT (Neo4j) → Config → NetLab → Observed State → SSoT
- [ ] Establish baseline monitoring intervals (target 30s–5min for inner loop)

---

### Phase 2 — Inner Loop (Months 3–6)

**Assurance agents:**
- [x] Implement Agent 7 (Assessment) — desired vs. observed comparison, drift detection (RFC 9315 §5.2.2), root cause analysis via Neo4j dependency traversal, ComplianceAssessment/Incident nodes (L6)
- [x] Implement Agent 8 (Action) — severity classification, autonomy decision matrix (Info/Low/Medium = auto-remediate; High/Critical = escalate), rollback engine, Remediation nodes (L6)

**Fulfillment agent:**
- [x] Implement Agent 3 (Policy→Config) — Jinja2 multi-vendor config rendering (VyOS first), per-device config diff, Configuration nodes (L5), firewall pipeline integration (8 Cypher extraction queries + 4-template chain)

**Memory Tier 3:**
- [x] Deploy Graph-Memory + Qdrant — namespace-isolated Neo4j (`IBN_LIFECYCLE_*` labels), BGE-M3 1024-dim embeddings (`STEP3_Graph_Memory_Bootstrap.md` + `docker-compose.yml`)
- [x] Create `ibn-lifecycle` memory with IBN Network Lifecycle ontology (4 entity families: Decisions, Incidents, Operations, Knowledge; 6+ relationship types — see §10.2.2) (`src/ibn/ontology/ibn_lifecycle_ontology.yaml`)
- [x] Implement Live-Memory → Graph-Memory bridge — `graph_push()` for bank file ingestion (`src/ibn/core/graph_memory_client.py`)

**Consolidation pipeline:**
- [x] Implement LLM-driven `bank_consolidate()` with space-specific rules and trigger logic (note count thresholds, model state transitions) (`src/ibn/core/consolidation_manager.py`)
- [x] Implement Graph-Memory ingestion — ontology-driven entity/relation extraction from bank files, BGE-M3 embedding generation (`src/ibn/core/graph_memory_client.py` `graph_push()` / `graph_push_batch()`)
- [x] Implement consolidation lifecycle triggers per model state transitions (What-If→Candidate, Candidate→POR, POR→Deployed, Deployed→As-Built — see §10.5) (`src/ibn/core/model_state_controller.py` + `ConsolidationManager`)

**Validation:**
- [ ] Close the inner loop: detect drift → assess → re-orchestrate → verify (autonomous self-correction on NetLab)
- [ ] Validate Live-Memory → Graph-Memory bridge pipeline on remediation narratives
- [ ] Establish inner loop cycle time targets (30s–5min detection, 1–15min remediation)

---

### Phase 3 — Translation Intelligence (Months 6–9)

**Translation agents:**
- [ ] Implement Agent 2 (Intent→Policy) — full policy decomposition, Policy/FirewallRule/SGT/QoSPolicy nodes (L4), conflict resolution, segment/zone/QoS assignment per HLD population model
- [ ] Implement Agent 4 (Planning) — blast radius analysis via Neo4j graph traversal, migration plan generation, MigrationPlan/ChangeRequest nodes (L7), What-If model state management

**NLP upgrade:**
- [ ] Upgrade Agent 1 (Ingestion) — natural language intent parsing (beyond structured templates), semantic validation, interactive refinement dialog per RFC 9315 §4.2

**Validation:**
- [ ] Test conflict detection across multiple concurrent active intents
- [ ] Benchmark blast radius analysis and migration planning performance

---

### Phase 4 — Outer Loop and Reporting (Months 9–12)

**Reporting agents:**
- [ ] Implement Agent 9 (Abstraction) — aggregate device-level observations into intent-level compliance scores, multi-incident correlation into business-impact statements, trend analysis (improving/degrading/stable)
- [ ] Implement Agent 10 (Reporting) — compliance dashboards, per-intent/per-site/per-device reports, natural-language status generation, human notification triggers

**Outer loop closure:**
- [ ] Enable full outer loop: human reviews reports → modifies intent → system adapts (RFC 9315 §6)
- [ ] Implement intent retirement and decommission workflows — state transitions, cleanup, archival in Neo4j

**Knowledge integration:**
- [ ] Activate Live-Memory Graph Bridge — automated `graph_push()` on model state transitions (§10.5)
- [ ] Enable all agents to query Graph-Memory via `question_answer()` — historical precedent-based decision making, graph-guided RAG
- [ ] Expose Graph-Memory `/graph` web interface for human operator knowledge exploration

**Validation:**
- [ ] End-to-end outer loop testing with human-in-the-loop scenarios
- [ ] Compliance dashboard accuracy and report quality assessment

---

### Phase 5 — Learning and Optimization (Months 12+)

**Agent learning:**
- [ ] Enable Agent 4 learning — leverage Graph-Memory knowledge graph to analyze historical compliance data, identify recurring drift patterns, optimize rendering decisions
- [ ] Implement predictive drift detection — forecast violations before they occur using graph-guided RAG to surface correlated historical incidents

**Expansion and performance:**
- [ ] Expand NetLab coverage — additional device types and protocols beyond initial set
- [ ] Benchmark and optimize loop cycle times — target sub-minute detection, profile agent execution
- [ ] Evolve IBN Network Lifecycle ontology based on accumulated knowledge graph structure and real operational data

---

### Cross-Cutting (all phases)

**Security and supervision (§12):**
- [ ] Implement RBAC for intent author authorization
- [ ] Deploy Caddy WAF for Live-Memory and Graph-Memory (TLS termination, OWASP CRS, rate limiting)
- [ ] Implement token-based authentication — agent-scoped Live-Memory write tokens, operator read tokens, Graph-Memory read tokens (agents) / write tokens (bridge only)
- [ ] Implement intent verification pipeline — syntactic correctness, conflict detection, feasibility validation, authorization check
- [ ] Define and enforce autonomy boundaries — what the inner loop can/cannot do (see §12.2)
- [ ] Implement rollback safeguards — `PRECEDED_BY` chain traversal, severity-based approval gates

**Audit trail (§12.4):**
- [ ] Record every agent action in Neo4j — timestamp, agent ID, input, output — full traceability from intent to device to compliance

**Schema evolution and governance (§13):**
- [ ] Establish Schema Review Board (SRB) — network architect, lead agent developer, ontology expert
- [ ] Implement ontology versioning — semantic MAJOR.MINOR.PATCH, `OntologyVersion` nodes, backward-compatibility rules
- [ ] Implement profile system — Campus, Branch, Lab profiles as machine-checkable Cypher constraints
- [ ] Define stability rules — 6-month stability window per major version, deprecation protocol
- [ ] Build canned Cypher query library — named stored procedures for common access patterns, insulating agents from schema changes

**Operational observability:**
- [ ] Build operational metrics dashboard — inner loop cycle times, compliance latency, remediation success rates, agent execution times
- [ ] Create alerting for critical failures — agent errors, rollback triggers, escalation events

## Code Conventions

- Python 3.11+ for all agent code
- Neo4j Bolt driver (`neo4j` package) for graph access
- MCP Streamable HTTP for Live-Memory and Graph-Memory integration
- Jinja2 for all config rendering (see `firewall_pipeline/templates/`)
- YAML for NetLab topology definitions
- Cypher for all Neo4j queries — prefer canned queries (stored procedures) over inline Cypher
- Property naming: `camelCase` for Neo4j properties, `UPPER_SNAKE_CASE` for relationship types
- Every agent writes to Neo4j AND emits `live_note()` to the appropriate Live-Memory space
- Model state (`modelState` property) must be set on every node creation

## Working with This Project

When starting a session:
1. Read this file first
2. If working on the ontology/schema: read `Neo4j_Ontology_Network_Lifecycle.md` and `Neo4j_Schema_Cypher.cypher`
3. If working on agents: read `IBN_Closed_Loop_Architecture.md` §5 (agent decomposition) and §10 (three-tier memory)
4. If working on firewall pipeline: read `firewall_pipeline/` directory
5. If working on NetLab topology: read `topology_campus_large_site.yml` and `NetLab_Feasibility_Analysis.md`

## Documenting fixes and debugging sessions

After any non-trivial debugging, bug-hunt, or multi-step fix session, write
a short markdown note to the repo root so the work is re-readable outside
of the Claude Code conversation log. Do this **proactively** — don't wait
to be asked.

- Filename: `FIX_NOTES_<Topic>.md` at the repo root
- Contents: date, context, the bugs found (with file:line references),
  the fixes applied, before/after test results, and any known followups
- Keep it terse — bullet points and tables, not prose essays
- The goal is that someone reading the repo six months later can
  reconstruct *why* the change was made, not just *what* changed

Example: [FIX_NOTES_GraphMemory_Tier3.md](FIX_NOTES_GraphMemory_Tier3.md)
(the Tier-3 pipeline fix from 2026-04-11 — MCP schema mismatch plus
`LLMAAS_API_URL` missing `/v1` prefix).

## HLD Quick Reference

- **Sites**: HQ (large), Branch-A, Branch-B
- **Population VLANs**: 100 (Employee), 110 (Voice), 120 (Printer), 130 (Video), 140 (Guest), 150 (IoT), 160 (Management)
- **DMZ VLANs**: 200 (DMZ-Servers), 210 (DNS-DMZ), 220 (AD-DMZ), 230 (File-DMZ), 240 (PBX-DMZ), 250 (Publish), 260 (Proxy), 270 (Management-DMZ)
- **Transit VLAN**: 300 (USF ↔ DMZFW)
- **Firewalls**: User Services FW (USF, active-active), DMZ/Internet FW (DMZFW, active-active) — both VyOS
- **Topology**: Access → Aggregation → USF/DMZFW → Internet Edge
