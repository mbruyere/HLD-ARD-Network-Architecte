# IBN Closed-Loop Pipeline and Control Loops — Diagram Reference

> **Purpose:** Complete reference for producing visual representations
> (Mermaid, TikZ, Visio, draw.io, etc.) of the IBN closed-loop
> architecture. Every box, arrow, label, and data flow listed here
> corresponds to implemented code. Nothing is aspirational.

---

## 1. System-Level View

### 1.1 External Actors

| Actor | Interface | Direction |
|---|---|---|
| **Operator** | Text editor + `git commit` | Intent in (HLD Markdown) |
| **Operator** | `python -m ibn.tools.approve <sha>` | Approval in |
| **Operator** | Neo4j Browser / Cypher | Query out (read SSoT) |
| **Operator** | Live-Memory notes | Rationale out (read why) |

### 1.2 Infrastructure Services

| Service | Container | Port | Protocol | Role |
|---|---|---|---|---|
| Neo4j | `neo4j` (host) | 7687 | Bolt | SSoT graph database (Tier 1) |
| Live-Memory MCP | `ibn-live-memory` | 8002 | HTTP (MCP Streamable) | Working memory (Tier 2) |
| Graph-Memory MCP | `ibn-graph-memory` | 8003 | HTTP (MCP Streamable) | Long-term knowledge (Tier 3) |
| Qdrant | `ibn-qdrant` | 6333/6334 | REST/gRPC | Vector embeddings (BGE-M3) |
| Redis | `ibn-redis` | 6379 | Redis Streams | Event bus |
| Embedding Proxy | `ibn-embedding-proxy` | 8004 | HTTP | LLMaaS proxy (consolidation + extraction) |

### 1.3 Network Devices (Containerlab)

| Device Type | Container Pattern | Push Transport | Verify Transport |
|---|---|---|---|
| Nokia SR Linux | `clab-<lab>-<name>` | `docker exec sr_cli` OR gNMI `:57400` | `sr_cli info from running` |
| FRRouting | `clab-<lab>-<name>` | `docker exec vtysh` | `vtysh -c "show running-config"` |
| VyOS | `clab-<lab>-<name>` | Paramiko SSH | SSH `show configuration` |

---

## 2. The Two Loops (RFC 9315)

### 2.1 Loop Structure

```
                    OUTER LOOP (human timescale)
    ┌──────────────────────────────────────────────────────┐
    │                                                      │
    │   Operator ──[edit HLD]──► git commit ──► Pipeline   │
    │       ▲                                      │       │
    │       │                                      ▼       │
    │   Reports ◄── A10 ◄── A9 ◄──────── INNER LOOP       │
    │                                  ┌───────────┐       │
    │                                  │ A6 → A7 → A8      │
    │                                  │  ▲         │      │
    │                                  │  └─────────┘      │
    │                                  │ (autonomous)      │
    │                                  └───────────┘       │
    └──────────────────────────────────────────────────────┘
```

### 2.2 Outer Loop

| Step | Actor | Action | Artefact |
|---|---|---|---|
| 1 | Operator | Edits HLD Markdown | `Enterprise_Campus_Network_HLD.md` |
| 2 | Git | `post-commit` hook fires | Commit SHA |
| 3 | Pipeline | Stages 1-12 execute | Neo4j nodes, config pushed, assessments |
| 4 | A9 | Aggregates compliance scores | Intent-level summaries |
| 5 | A10 | Generates reports | Human-readable compliance reports |
| 6 | Operator | Reviews, decides next edit | Back to step 1 |

### 2.3 Inner Loop

| Step | Agent | Action | Cadence |
|---|---|---|---|
| 1 | A6 (Monitoring) | Poll telemetry from devices | 30s default |
| 2 | A7 (Assessment) | Compare POR vs AS_BUILT | Per-cycle |
| 3 | A8 (Action) | Classify severity, decide action | Per-incident |
| 3a | A8 → A3 → A5 | Auto-remediate (INFO/LOW/MEDIUM) | Autonomous |
| 3b | A8 → Operator | Escalate (HIGH/CRITICAL) | Human required |

---

## 3. The Twelve-Stage Pipeline

### 3.1 Stage Sequence

```
git commit
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: DIFF (hld_parser.py)                               │
│   HLD Markdown → HldChangeset                              │
│   Fields: populations_{added,modified,removed}              │
│           dmz_{added,modified,removed}                      │
│           devices_{added,modified,removed}                  │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: A1 INGESTION (agent1_ingestion.py, 584 lines)      │
│   Writes: Intent, Device, VLAN nodes → L1, L4              │
│   State: modelState = CANDIDATE                             │
│   Sink: live_note() → ibn-candidate-<ver>                   │
│   Events: intent.ingested, device.added/modified/removed    │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 3: PROVISIONING (provisioner.py)                      │
│   Mutates: clab topology YAML                               │
│   Runs: clab deploy --reconfigure                           │
│   Path A: provision(entry) — single device                  │
│   Path B: provision_batch(entries) — N>1, one deploy        │
│   Writes: LifecycleEvent → L8                               │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 4: A2 INTENT→POLICY (agent2_intent_policy.py, 221 ln) │
│   Input: Intent IDs from Stage 2                            │
│   Writes: Policy (POL-<id>), FirewallRule (RUL-<id>-NN) → L4│
│   Dispatch: ACCESS_MATRIX[target] → rule list               │
│   Skip: device-only commits → "skipped"                     │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 5: A4 PLANNING (agent4_planning.py, 243 lines)        │
│   Writes: MigrationPlan (PLAN-<sha[:8]>) → L7              │
│   Severity: HIGH | MEDIUM | LOW | INFO                      │
│   Blast radius: count of affected devices                   │
│   Prior PENDING plans → SUPERSEDED                          │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 6: APPROVAL GATE                                      │
│                                                             │
│   ┌─ severity == HIGH ─────────────────────────────┐        │
│   │  Write: .git/ibn-pending-approval/<sha>.md     │        │
│   │  Pipeline HALTS                                 │        │
│   │  Operator runs: python -m ibn.tools.approve <sha>│       │
│   │  → PENDING → APPROVED                          │        │
│   │  → resume_from_approval(plan_id)                │        │
│   └─────────────────────────────────────────────────┘        │
│                                                             │
│   ┌─ severity == LOW/INFO ─────────────────────────┐        │
│   │  Auto-approve (or IBN_AUTO_APPROVE=1)           │        │
│   │  → Continue to Stage 7                          │        │
│   └─────────────────────────────────────────────────┘        │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
        ┌──────────────────────────────┐
        │  transition_artifacts_to_por │
        │  CANDIDATE → POR            │
        └──────────────┬───────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 7: A3 POLICY→CONFIG (agent3_policy_config.py, 420 ln)  │
│   Queries: 10 named Cypher queries against Neo4j            │
│     firewalls, zones, segments, policies, intents,          │
│     fw_interfaces, nat_rules, fw_transit, switches, vlans   │
│   Dispatch: _TEMPLATE_CHAINS[platform] → Jinja2 chain      │
│     vyos    → [vyos_base, vyos_policies, vyos_nat, vyos_ha] │
│     srlinux → [srl_base, srl_interfaces, srl_vlans]        │
│     frr     → [frr_base, frr_interfaces, frr_routing]       │
│   Writes: Configuration (CFG-<uuid8>) → L5                 │
│   Change detection: SHA-256[:16] content hash               │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 8: A5 ORCHESTRATION (agent5_orchestration.py, ~350 ln) │
│   Dispatch: _VENDOR_EXECUTORS[platform]                     │
│     vyos    → _default_ssh_executor (paramiko SSH)          │
│     srlinux → _srlinux_ssh_executor (docker exec sr_cli)    │
│              OR _srlinux_gnmi_executor (pygnmi SetRequest)  │
│              (selected by IBN_SRLINUX_TRANSPORT=gnmi|cli)   │
│     frr     → _frr_executor (docker exec vtysh)             │
│   gNMI path: CLI→YANG translator (_srlinux_yang.py)         │
│     10 rules, merges leaves per container path              │
│     Target: <mgmt-ipv4>:57400, TLS, skip_verify=True        │
│   Writes: DeploymentEvent → L5                              │
│   Skip: devices with empty rendered content                 │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 9: A6 MONITORING (agent6_monitoring.py)                │
│   Poll: show commands via SSH / docker exec                 │
│   Metrics: interface state, VRRP role, BGP peers, OSPF nbrs │
│   Writes: Telemetry, OperationalState → L5                  │
│   State: modelState = AS_BUILT                              │
│   Interval: 30s (configurable)                              │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 10: A7 ASSESSMENT (agent7_assessment.py, 417 lines)    │
│   Compare: POR subgraph vs AS_BUILT subgraph                │
│   Drift detectors (decorator-registered):                   │
│     firewall_rule  — missing/extra rules                    │
│     interface_state — admin/oper mismatch                   │
│     vrrp_role      — primary/backup mismatch                │
│   Verdicts: COMPLIANT | DEGRADED | NON_COMPLIANT | UNKNOWN  │
│   Root cause: traverse REALIZED_BY/AGGREGATES edges          │
│   Confidence: HIGH | LOW                                    │
│   Writes: ComplianceAssessment, Incident → L6               │
│   Severity: CRITICAL (≥3 drift) | HIGH | MEDIUM             │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 11: A8 ACTION (agent8_action.py, 405 lines)            │
│   Autonomy decision matrix:                                 │
│     INFO     → LOG                    (autonomous)          │
│     LOW      → AUTO_REMEDIATE         (autonomous)          │
│     MEDIUM   → AUTO_REMEDIATE_VERIFY  (autonomous)          │
│     HIGH     → ESCALATE              (human required)       │
│     CRITICAL → ROLLBACK_ESCALATE     (human required)       │
│   Auto-remediate: re-invoke A3 → A5 on affected devices    │
│   Rollback: walk PRECEDED_BY chain, re-push predecessor     │
│   Writes: Remediation (REM-<uuid8>) → L6                   │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 12: A9-A10 ABSTRACTION + REPORTING (stubs)             │
│   A9: Aggregate via ABSTRACTS edges → intent-level scores   │
│   A10: Generate human-facing compliance reports              │
│   MigrationPlan status: APPROVED → APPLIED                  │
│   Event: inner.loop.complete                                │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Pipeline Timing

| Operation | Wall-clock |
|---|---|
| No-op HLD commit (full cycle) | 8-10 s |
| VLAN addition (1 device) | 10-12 s |
| Device addition (4 devices, batch) | 20-40 s |
| gNMI SetRequest (7 updates) | <1 s |
| sr_cli push (typical) | ~2 s |
| vtysh push (typical) | ~1.5 s |
| SSH push to VyOS | ~3 s |
| Neo4j Cypher query (avg) | ~200 ms |

---

## 4. Five Model States and Transitions

### 4.1 State Definitions

| State | Meaning | Written By | Live-Memory Space |
|---|---|---|---|
| `WHAT_IF` | Exploratory scratch (planning simulations) | A4 | `ibn-whatif-<id>` |
| `CANDIDATE` | Freshly committed, not yet approved | A1 | `ibn-candidate-<ver>` |
| `POR` | Plan-of-Record — approved desired state | Approval gate | `ibn-por-<ver>` |
| `DEPLOYED` | Actually pushed to device | A5 | `ibn-deploy-<evt>` |
| `AS_BUILT` | Observed from telemetry (ground truth) | A6 | `ibn-asbuilt-<snap>` |

### 4.2 Legal Transition Graph

```
                    FORWARD PATH
    ┌──────────┐    ┌───────────┐    ┌─────┐    ┌──────────┐    ┌──────────┐
    │ WHAT_IF  │───►│ CANDIDATE │───►│ POR │───►│ DEPLOYED │───►│ AS_BUILT │
    └──────────┘    └───────────┘    └─────┘    └──────────┘    └──────────┘
         ▲               │              │            │               │
         │               ▼              ▼            ▼               ▼
         └───────────────┘              │            │               │
              rollback                  └────────────┘               │
                                         rollback                    │
                                                    └────────────────┘
                                                         rollback

    Forward:  WHAT_IF → CANDIDATE → POR → DEPLOYED → AS_BUILT
    Rollback: CANDIDATE → WHAT_IF
              POR → CANDIDATE
              DEPLOYED → POR         (used by A8 rollback)
              AS_BUILT → DEPLOYED
```

### 4.3 Transition Triggers

| Transition | Trigger | Actor |
|---|---|---|
| → CANDIDATE | A1 creates nodes from HLD commit | Agent 1 |
| CANDIDATE → POR | Approval gate cleared | `ibn.tools.approve` |
| POR → DEPLOYED | A5 executor returns success | Agent 5 |
| DEPLOYED → AS_BUILT | A6 telemetry collected | Agent 6 |
| DEPLOYED → POR | A8 rollback | Agent 8 |

---

## 5. Nine-Layer Ontology

### 5.1 Layer Map

```
    L9 ┌─────────────────────────┐  People / Process
       │ Operator, Team, Ticket, │  (all agents write AgentExecution)
       │ SLA, AgentExecution     │
    ───┤─────────────────────────┤───────────────────────────────────
    L8 │ LifecyclePhase,         │  Lifecycle
       │ LifecycleTransition,    │  (Provisioner, ModelStateController)
       │ LifecycleEvent          │
    ───┤─────────────────────────┤───────────────────────────────────
    L7 │ ChangeRequest,          │  Change Management
       │ MigrationPlan           │  (A4 Planning)
    ───┤─────────────────────────┤───────────────────────────────────
    L6 │ Alert, Incident,        │  Incidents
       │ RootCause,              │  (A7 Assessment, A8 Action)
       │ ComplianceAssessment,   │
       │ Remediation             │
    ───┤─────────────────────────┤───────────────────────────────────
    L5 │ Configuration,          │  Config & State
       │ DeploymentEvent,        │  (A3 Render, A5 Deploy, A6 Monitor)
       │ Telemetry,              │
       │ OperationalState        │
    ───┤─────────────────────────┤───────────────────────────────────
    L4 │ Intent, Policy,         │  Policy & Intent
       │ FirewallRule, SGT,      │  (A1 Ingestion, A2 Intent→Policy)
       │ QoSPolicy               │
    ───┤─────────────────────────┤───────────────────────────────────
    L3 │ Architecture,           │  Architecture
       │ ArchitectureVersion,    │  (A1 seed)
       │ HLD, ARD, BusinessUseCase│
    ───┤─────────────────────────┤───────────────────────────────────
    L2 │ Topology, TopologyLayer,│  Topology
       │ Zone, Segment,          │  (A1 seed)
       │ FirewallPair, StackGroup│
    ───┤─────────────────────────┤───────────────────────────────────
    L1 │ Site, Device, Interface,│  Infrastructure
       │ PhysicalLink,LogicalLink│  (A1 Ingestion)
       │ VLAN, VRF, Subnet,     │
       │ IPAddress               │
       └─────────────────────────┘
```

### 5.2 Cross-Layer Relationships (6 types)

| Relationship | Direction | Meaning | Primary User |
|---|---|---|---|
| `REALIZED_BY` | L4→L5 (descending) | Intent realized by config/state | A7 (drift audit trail) |
| `ABSTRACTS` | L5→L4 (ascending) | Device obs → intent compliance | A9 (aggregation) |
| `AGGREGATES` | L2→L1 (set membership) | FirewallPair aggregates Devices | A4 (blast radius) |
| `CONTAINS` | parent→child (nesting) | Site contains Devices | A1 (structure) |
| `TRAVERSES` | L4→L2 (policy crossing) | FirewallRule traverses FirewallPair | A4 (blast radius) |
| `PRECEDED_BY` | L5→L5 (temporal) | Config replaced by successor | A8 (rollback chain) |

---

## 6. Three-Tier Memory Architecture

### 6.1 Tier Overview

```
┌─────────────────┐     ┌─────────────────────┐     ┌──────────────────────┐
│   TIER 1        │     │   TIER 2            │     │   TIER 3             │
│   Neo4j SSoT    │     │   Live-Memory       │     │   Graph-Memory       │
│                 │     │   (Cloud-Temple)    │     │   (Cloud-Temple)     │
│  Port: 7687     │     │  Port: 8002         │     │  Port: 8003          │
│  Proto: Bolt    │     │  Proto: MCP/HTTP    │     │  Proto: MCP/HTTP     │
│                 │     │  Backend: S3        │     │  Backend: Neo4j +    │
│  9 layers       │     │                     │     │           Qdrant     │
│  5 model states │     │  7 spaces:          │     │                      │
│  typed nodes    │     │    ibn-whatif-*      │     │  IBN_LIFECYCLE_*     │
│  + relationships│     │    ibn-candidate-*  │     │  labels (namespaced) │
│                 │     │    ibn-por-*         │     │                      │
│  WHAT it IS     │     │    ibn-deploy-*     │     │  BGE-M3 embeddings   │
│                 │     │    ibn-asbuilt-*    │     │  1024 dimensions     │
│                 │     │    ibn-loop-inner   │     │                      │
│                 │     │    ibn-loop-outer   │     │  14 entity classes   │
│                 │     │                     │     │  8 relationship types│
│                 │     │  WHY it is so       │     │                      │
│                 │     │                     │     │  WHAT WAS LEARNED    │
└────────┬────────┘     └──────────┬──────────┘     └──────────┬───────────┘
         │                        │                            │
         │        ┌───────────────┘                            │
         │        │                                            │
         │        ▼                                            │
         │   live_note() ──► bank (append-only notes)          │
         │   bank_consolidate() ──► LLM summarises             │
         │   graph_push() ─────────────────────────────────────►│
         │                                                     │
         │◄──────────── question_answer() (graph-guided RAG) ──┘
         │              agents query historical knowledge
```

### 6.2 Consolidation Pipeline

```
TRIGGER ──────────────────────────────────────────────────────────────
  │
  ├─ (a) Model-state transition (e.g. CANDIDATE → POR)
  ├─ (b) Inner loop complete
  └─ (c) Note count > threshold (default: 20)
  │
  ▼
CONSOLIDATE ──────────────────────────────────────────────────────────
  │  bank_consolidate(space_id)
  │  Live-Memory MCP → LLM → structured bank file
  │  LLM: LLMAAS_MODEL (Claude Haiku 4.5 | Qwen3-235B)
  │
  ▼
PUSH (if push-eligible: to POR, DEPLOYED, or AS_BUILT) ──────────────
  │  bank_read_all(space_id) → bank files
  │  graph_push_batch(memory, bank_files, space_id)
  │  Graph-Memory MCP → LLM + IBN Lifecycle Ontology
  │    → extract entities (14 classes, 4 families)
  │    → extract relations (8 types)
  │    → embed with BGE-M3 (1024 dim) → Qdrant
  │    → store in Neo4j (IBN_LIFECYCLE_* namespace)
  │
  ▼
QUERY ────────────────────────────────────────────────────────────────
  question_answer(memory, question, max_results=5)
  │  1. Embed question with BGE-M3
  │  2. Nearest-neighbour entities from Qdrant
  │  3. Traverse graph neighbourhood via SIMILAR_TO / INFORMED_BY
  │  4. Return combined context
```

### 6.3 IBN Lifecycle Ontology (Graph-Memory Tier 3)

**Entity Families (14 classes):**

| Family | Entities |
|---|---|
| Decisions & Rationale | `PolicyDecision`, `DesignChoice`, `TradeOff`, `RejectedAlternative`, `ApprovalRecord` |
| Incidents & Remediation | `DriftEvent`, `RootCauseAnalysis`, `RemediationAction`, `EscalationRecord`, `ComplianceTrend` |
| Operations & Deployment | `DeploymentNarrative`, `ConfigurationRationale`, `RollbackRecord`, `VerificationResult` |
| Knowledge & Patterns | `RecurringPattern`, `LessonLearned`, `CapacityInsight`, `CorrelationFinding` |

**Relationship Types (8):**

| Relationship | Semantics |
|---|---|
| `CAUSED_BY` | Drift/remediation → root cause |
| `RESOLVED_BY` | Incident → fix action |
| `PRECEDED` | Temporal ordering |
| `JUSTIFIED_BY` | Decision → supporting rationale |
| `CONTRADICTS` | New finding vs old lesson |
| `CONFIRMS` | Event validates known pattern |
| `SIMILAR_TO` | Cross-iteration pattern matching (primary RAG link) |
| `INFORMED_BY` | Decision informed by precedent (query provenance) |

---

## 7. Agent Summary Table

| Agent | Name | Lines | RFC 9315 | Phase | Writes to | Input | Output |
|---|---|---|---|---|---|---|---|
| A1 | Ingestion | 584 | §5.1.1 | Fulfilment | L1, L4 | HldChangeset | Intent, Device, VLAN |
| A2 | Intent→Policy | 221 | §5.1.2 | Fulfilment | L4 | Intent IDs | Policy, FirewallRule |
| A3 | Policy→Config | 420 | §5.1.2 | Fulfilment | L5 | Neo4j context | Configuration |
| A4 | Planning | 243 | §5.1.2 | Fulfilment | L7 | Changeset+configs | MigrationPlan |
| A5 | Orchestration | ~350 | §5.1.3 | Fulfilment | L5 | Configuration | DeploymentEvent |
| A6 | Monitoring | ~380 | §5.2.1 | Assurance | L5 | Device list | Telemetry, OpState |
| A7 | Assessment | 417 | §5.2.2 | Assurance | L6 | POR vs AS_BUILT | Assessment, Incident |
| A8 | Action | 405 | §5.2.3 | Assurance | L6 | Incident | Remediation |
| A9 | Abstraction | stub | §5.2 | Assurance | all | Assessments | Aggregated scores |
| A10 | Reporting | stub | §5.2 | Assurance | L9 | Aggregations | Reports |

---

## 8. Dispatch Tables

### 8.1 Vendor → Containerlab Kind (`_KIND_MAP`)

| (vendor, platform) | kind | image | type |
|---|---|---|---|
| `("nokia", "srlinux")` | `nokia_srlinux` | `ghcr.io/nokia/srlinux:latest` | `ixrd2l` |
| `("vyos", "vyos")` | `linux` | `ghcr.io/sysoleg/vyos-container:latest` | — |
| `("frr", "frr")` | `linux` | `ibn-frr:local` | — |

### 8.2 Platform → Template Chain (`_TEMPLATE_CHAINS`)

| Platform | Templates (ordered) |
|---|---|
| `vyos` | `vyos_firewall_base.j2` → `vyos_firewall_policies.j2` → `vyos_nat.j2` → `vyos_ha.j2` |
| `srlinux` | `srl_base.j2` → `srl_interfaces.j2` → `srl_vlans.j2` |
| `frr` | `frr_base.j2` → `frr_interfaces.j2` → `frr_routing.j2` |

### 8.3 Platform → Executor (`_VENDOR_EXECUTORS`)

| Platform | Executor | Transport |
|---|---|---|
| `vyos` | `_default_ssh_executor` | Paramiko SSH |
| `srlinux` | `_srlinux_ssh_executor` | `docker exec -i <c> sr_cli` |
| `srlinux` (gnmi) | `_srlinux_gnmi_executor` | pygnmi `SetRequest` to `:57400` |
| `frr` | `_frr_executor` | `docker exec -i <c> vtysh` |

### 8.4 Adding a New Vendor

To add vendor X, touch exactly:
1. `_KIND_MAP`: 1 entry `("x", "x_platform") → {kind, image}`
2. `_TEMPLATE_CHAINS`: 1 entry `"x_platform" → [template1.j2, ...]`
3. `_VENDOR_EXECUTORS`: 1 entry `"x_platform" → _x_executor`
4. `_VENDOR_VERIFIERS`: 1 entry `"x_platform" → _x_verifier`
5. New Jinja2 templates in `firewall_pipeline/templates/`
6. (Optional) Dockerfile for the container image

**Zero existing agent code changes.**

---

## 9. Event Bus (Redis Streams)

### 9.1 Event Types

| Event | Publisher | Subscriber(s) |
|---|---|---|
| `model.state.transition` | ModelStateController | ConsolidationManager |
| `inner.loop.complete` | Agent 8 | ConsolidationManager |
| `deployment.complete` | Agent 5 | Event bus consumers |
| `deployment.failed` | Agent 5 | Event bus consumers |
| `config.rendered` | Agent 3 | Event bus consumers |
| `assessment.complete` | Agent 7 | Agent 8 |
| `remediation.complete` | Agent 8 | Event bus consumers |
| `escalation.required` | Agent 8 | Outer loop (A9/A10) |
| `intent.ingested` | Agent 1 | Event bus consumers |
| `device.added` | Agent 1 | Event bus consumers |
| `device.modified` | Agent 1 | Event bus consumers |
| `device.removed` | Agent 1 | Event bus consumers |

### 9.2 Stream Naming

- Pattern: `ibn:events:<event_type>`
- Consumer group: `ibn-agents`
- Example: `ibn:events:model.state.transition`

---

## 10. Invariants

| ID | Name | Enforcement | Mechanism |
|---|---|---|---|
| I1 | Every agent write is dual-sink | `BaseAgent._note()` | Neo4j write + `live_note()` to model-state space |
| I2 | Every node carries `modelState` | `ModelStateController` | `_LEGAL_TRANSITIONS` frozenset, raises `ModelStateTransitionError` |
| I3 | Every agent execution recorded | `BaseAgent` wrapper | `AgentExecution` node at L9 per run |

---

## 11. Severity Classification

### 11.1 A4 Planning Severity (changeset-based)

| Severity | Condition |
|---|---|
| `HIGH` | Devices added OR removed |
| `MEDIUM` | Populations removed OR DMZ removed |
| `LOW` | Populations/DMZ added or modified |
| `INFO` | No changes detected |

### 11.2 A8 Action Severity (incident-based)

| Severity | Condition | Action | Autonomous? |
|---|---|---|---|
| `INFO` | Metric deviation < 10% | Log only | Yes |
| `LOW` | 1 device, redundancy active | Auto-remediate | Yes |
| `MEDIUM` | 2+ devices affected | Remediate + verify | Yes |
| `HIGH` | Service impact + business critical | Escalate | No |
| `CRITICAL` | 3+ intents violated | Rollback + escalate | No |

---

## 12. MigrationPlan Lifecycle

```
PENDING ──[approve]──► APPROVED ──[A3→A5→A7 complete]──► APPLIED
   │                                                        
   ├──[reject]──► REJECTED (kept for audit)
   │
   └──[new commit]──► SUPERSEDED (kept for audit)
```

---

## 13. Testbed Topology

### 13.1 Current Lab (16 containers)

```
                        ┌──────────────────┐
                        │   INTERNET EDGE   │
                        │  edge-01 (FRR)    │
                        │  edge-02 (FRR)    │
                        └────────┬─────────┘
                                 │
                        ┌────────┴─────────┐
                        │   FIREWALLS       │
                        │  usf-01 (VyOS)    │
                        │  usf-02 (VyOS)    │
                        │  dmzfw-01 (VyOS)  │
                        │  dmzfw-02 (VyOS)  │
                        └────────┬─────────┘
                                 │
                        ┌────────┴─────────┐
                        │   AGGREGATION     │
                        │  agg-01 (SR Linux)│
                        └────────┬─────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
        ┌───────┴──────┐ ┌──────┴───────┐        │
        │   ACCESS     │ │   ACCESS     │   7 host stubs
        │ acc-sw-01    │ │ acc-01       │   (population
        │ (SR Linux)   │ │ (SR Linux)   │    VLANs)
        └──────────────┘ └──────────────┘

    Management: 192.168.100.0/24
    Lab prefix: ibnlab-switches
```

### 13.2 Management IPs

| Container | IP | Vendor |
|---|---|---|
| `clab-ibnlab-switches-acc-sw-01` | 192.168.100.121 | Nokia SR Linux |
| `clab-ibnlab-switches-acc-01` | 192.168.100.131 | Nokia SR Linux |
| `clab-ibnlab-switches-agg-01` | 192.168.100.141 | Nokia SR Linux |
| `clab-ibnlab-switches-edge-01` | 192.168.100.151 | FRR |
| `clab-ibnlab-switches-edge-02` | 192.168.100.152 | FRR |

---

## 14. Key File Paths

| File | Purpose |
|---|---|
| `src/ibn/pipeline/hld_commit.py` | Pipeline orchestrator (run, resume_from_approval) |
| `src/ibn/parser/hld_parser.py` | HLD Markdown → HldSnapshot/ChangeSet |
| `src/ibn/agents/agent1_ingestion.py` | A1: HLD → Neo4j L1/L4 |
| `src/ibn/agents/agent2_intent_policy.py` | A2: Intent → Policy + FirewallRule |
| `src/ibn/agents/agent3_policy_config.py` | A3: Policy → vendor config (Jinja2) |
| `src/ibn/agents/agent4_planning.py` | A4: Severity + MigrationPlan |
| `src/ibn/agents/agent5_orchestration.py` | A5: Push config to devices |
| `src/ibn/agents/_srlinux_yang.py` | CLI→YANG translator (gNMI path) |
| `src/ibn/agents/agent6_monitoring.py` | A6: Telemetry collection |
| `src/ibn/agents/agent7_assessment.py` | A7: POR vs AS_BUILT drift detection |
| `src/ibn/agents/agent8_action.py` | A8: Severity → action decision |
| `src/ibn/agents/provisioner.py` | Containerlab YAML + deploy |
| `src/ibn/core/model_state_controller.py` | Model state transitions (8 edges) |
| `src/ibn/core/neo4j_client.py` | Neo4j CRUD operations |
| `src/ibn/core/live_memory_client.py` | Live-Memory MCP client |
| `src/ibn/core/graph_memory_client.py` | Graph-Memory MCP client |
| `src/ibn/core/consolidation_manager.py` | Tier 2 → Tier 3 pipeline |
| `src/ibn/core/redis_event_bus.py` | Redis Streams event bus |
| `src/ibn/tools/approve.py` | CLI: approve/reject/list plans |
| `firewall_pipeline/templates/` | Jinja2 templates (VyOS, SR Linux, FRR) |
| `clab-ibnlab-switches.yml` | Containerlab topology YAML |
| `docker-compose.yml` | Infrastructure services |
| `src/ibn/ontology/ibn_lifecycle_ontology.yaml` | Graph-Memory extraction ontology |
