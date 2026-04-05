# IBN Closed-Loop Feedback Control Architecture
## Full Network Lifecycle Management

**Version:** 2.1
**Date:** March 2026
**Document Type:** Architecture Design — Closed-Loop Control System
**Normative Reference:** RFC 9315 — Intent-Based Networking: Concepts and Definitions
**Industry Reference:** Mogul et al., "Experiences with Modeling Network Topologies at Multiple Levels of Abstraction" (NSDI '20)
**Scope:** Full lifecycle management of the Enterprise Campus Network defined by the companion HLD
**SSoT:** Neo4j graph database with the proposed 9-layer ontology
**Target Network:** NetLab (netlab.tools) virtual infrastructure
**Classification:** Internal Use

---

## INDEX

1. [Executive Summary](#1-executive-summary)
2. [RFC 9315 Closed-Loop Recap](#2-rfc-9315-closed-loop-recap)
3. [Multi-Model Lifecycle Representation](#3-multi-model-lifecycle-representation)
4. [Architecture Overview](#4-architecture-overview)
5. [Loop Phases and AI Agent Decomposition](#5-loop-phases-and-ai-agent-decomposition)
6. [Neo4j as SSoT — Role per Phase](#6-neo4j-as-ssot--role-per-phase)
7. [NetLab as Target Network](#7-netlab-as-target-network)
8. [Inner Loop vs. Outer Loop](#8-inner-loop-vs-outer-loop)
9. [Agent Communication and Orchestration](#9-agent-communication-and-orchestration)
10. [Three-Tier Memory Architecture (Live-Memory + Graph-Memory)](#10-three-tier-memory-architecture-live-memory--graph-memory)
11. [Lifecycle State Transitions Driven by the Loop](#11-lifecycle-state-transitions-driven-by-the-loop)
12. [Security and Supervision Model](#12-security-and-supervision-model)
13. [Schema Evolution and Governance](#13-schema-evolution-and-governance)
14. [Implementation Roadmap](#14-implementation-roadmap)
15. [References](#15-references)

---

## 1. Executive Summary

This document defines the closed-loop feedback control architecture that governs the **full lifecycle** of the enterprise campus network described in the companion HLD. The architecture is grounded in RFC 9315's Intent-Based Networking model and implements both the **inner loop** (autonomous, machine-to-machine) and the **outer loop** (human-in-the-loop) as defined in RFC 9315 Section 6.

Version 2.0 of this architecture incorporates principles from Google's MALT (Multi-Abstraction-Layer Topology) system (Mogul et al., NSDI '20), which demonstrates that **supporting the entire network lifecycle** — from capacity planning through design, deployment, configuration, operation, measurement, and decommissioning — requires a topology representation that maintains **multiple concurrent model states** with **explicit abstraction relationships** between them. Rather than a simple "desired vs. observed" dichotomy, our SSoT now supports a full spectrum of model states that coexist in the graph.

The core design decisions are:

- **Neo4j** (with the proposed 9-layer ontology) serves as the **Single Source of Truth (SSoT)** — the authoritative repository of declared intents, desired state, observed state, compliance records, and lifecycle history. Following MALT's multi-model principle, the SSoT holds **five concurrent model states** (Candidate, Plan-of-Record, Deployed, As-Built, What-If) for each network entity, enabling what-if analysis, drain-impact assessment, and rollback at any lifecycle phase.
- **AI Agents** implement each functional block of the RFC 9315 translation pipeline. Each agent is a specialized, bounded actor responsible for one phase of the loop. Agents operate as a **declarative dataflow pipeline** (per MALT §7.1): each agent declares what it needs, not how to get it, and its output becomes the input of the next agent. Agent outputs are **immutable model instances** recorded in the graph.
- **NetLab** (netlab.tools) is the **target network** — the physical (virtual) infrastructure against which intents are orchestrated, configurations are deployed, and telemetry is collected.
- **Live-Memory + Graph-Memory** (Cloud-Temple) provide a **three-tier memory architecture**: Live-Memory as the working memory (real-time notes + LLM-consolidated documentation) for operational reasoning and coordination; Graph-Memory as the long-term knowledge graph (ontology-driven entity extraction + Qdrant vector embeddings) for institutional memory and graph-guided RAG. Together they bridge the gap between what the network *is* (Neo4j SSoT), *why* it is in that state (Live-Memory), and *what was learned* across all past loop iterations (Graph-Memory).
- **Multi-level abstraction** — following MALT's core insight that different lifecycle phases require different levels of abstraction, the SSoT maintains **explicit `REALIZED_BY` relationships** linking high-level design intent (abstract) to physical device configuration (concrete). This enables traceability from business use case to individual firewall rule, and allows both capacity planners and device operators to use the same model.

The closed loop continuously compares the **desired state** (held in Neo4j) against the **observed state** (collected from NetLab) and triggers corrective actions when drift is detected, achieving the autonomous self-correction that RFC 9315 demands.

---

## 2. RFC 9315 Closed-Loop Recap

RFC 9315 (IRTF NMRG, October 2022) defines the normative model for Intent-Based Networking. The lifecycle is divided into two functional planes (**Fulfillment** and **Assurance**) operating across three spaces (**User**, **Translation/IBS**, **Network Operations**):

```
        User Space   :       Translation / IBS       :  Network Ops
                     :            Space              :     Space
                     :                               :
       +----------+  :  +----------+   +-----------+ : +-----------+
Fulfill|recognize/|---> |translate/|-->|  learn/   |-->| configure/|
       |generate  |     |          |   |  plan/    |   | provision |
       |intent    |<--- |  refine  |   |  render   | : |           |
       +----^-----+  :  +----------+   +-----^-----+ : +-----------+
            |        :                       |       :        |
............|................................|................|.....
            |        :                  +----+---+   :        v
            |        :                  |validate|   :  +----------+
            |        :                  +----^---+ <----| monitor/ |
Assure  +---+---+    :  +---------+    +-----+---+   :  | observe/ |
        |report | <---- |abstract |<---| analyze | <----|          |
        +-------+    :  +---------+    |aggregate|   :  +----------+
                     :                 +---------+   :

                    Figure: RFC 9315 Intent Life Cycle
```

**Two loops emerge:**

- **Inner loop** (Translation/IBS ↔ Network Operations): Fully autonomous. Observations from the network feed back into the learn/plan/render block, which adjusts configurations without human intervention. This loop counteracts **intent drift**.
- **Outer loop** (User ↔ Translation/IBS ↔ Network Operations): Human-in-the-loop. The user receives abstracted reports, assesses outcomes, and may modify or retract intent. This loop governs the **intent lifecycle** (creation, refinement, modification, retirement).

---

## 3. Multi-Model Lifecycle Representation

### 3.1 Motivation: The Entire Network Lifecycle

RFC 9315 defines the closed-loop control for intent fulfillment and assurance, but the full lifecycle of a network extends far beyond runtime compliance. Mogul et al. (NSDI '20) demonstrate through Google's MALT system that a single topology representation must support **all management phases**: capacity planning, high-level and detailed design, deployment planning, configuration generation, live operation, monitoring, measurement, analysis, upgrade planning, and decommissioning.

The critical insight is that at any given moment, multiple versions of the network's representation coexist — a capacity planner is evaluating a future topology while an operator is debugging the current one, and a deployment engineer is halfway through a migration that has not yet completed. A closed-loop system that only tracks "desired" and "observed" cannot support this reality. Following MALT's approach, we extend the SSoT to maintain **five concurrent model states** in the Neo4j graph.

### 3.2 Five Model States

Each network entity (device, link, VLAN, zone, policy, configuration) can exist simultaneously in multiple model states within the Neo4j SSoT. These states are **not** lifecycle phases of the entity itself (which are tracked separately via `lifecycleState`) — they represent **different models of the same network**, coexisting in the graph, each serving a different lifecycle function.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NEO4J SSoT — CONCURRENT MODEL STATES             │
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │ WHAT-IF   │    │ CANDIDATE │    │   POR     │    │ DEPLOYED  │ │
│  │           │    │           │    │ (Plan of  │    │           │ │
│  │ Explore   │───►│ Proposed  │───►│  Record)  │───►│ Pushed to │ │
│  │ options   │    │ change    │    │ Approved  │    │ NetLab    │ │
│  │ (many)    │    │ (one)     │    │ design    │    │ devices   │ │
│  └───────────┘    └───────────┘    └───────────┘    └─────┬─────┘ │
│                                                           │       │
│                                          ┌────────────────▼─────┐ │
│                                          │     AS-BUILT         │ │
│                                          │                      │ │
│                                          │  Observed actual     │ │
│                                          │  state (telemetry)   │ │
│                                          └──────────────────────┘ │
│                                                                     │
│  Drift = delta(DEPLOYED, AS-BUILT)                                 │
│  Compliance = match(POR.intent, AS-BUILT.state)                    │
└─────────────────────────────────────────────────────────────────────┘
```

| Model State | Purpose | Who Creates It | Lifecycle Phase Served | Persistence |
|-------------|---------|---------------|----------------------|-------------|
| **What-If** | Explore candidate designs before committing; evaluate capacity options, failure scenarios, alternative topologies | Planning Agent (Agent 4), Human Operator | Capacity planning, design exploration, upgrade planning | Ephemeral — multiple what-if models may exist; pruned after decision |
| **Candidate** | A specific proposed change selected from what-if analysis; subject to validation and approval | Translation Agents (Agent 2, 3), Planning Agent (Agent 4) | Detailed design, change proposal | Persistent until promoted or rejected |
| **Plan-of-Record (POR)** | The approved, authoritative design — the desired state against which compliance is measured | Human approval (outer loop) or automated policy | Approved design, deployment baseline | Persistent and versioned; the SSoT "source of truth" for intent compliance |
| **Deployed** | The configuration that has been pushed to the target network (NetLab) but not yet verified | Orchestration Agent (Agent 5) | Deployment, configuration push | Persistent; replaced after verification |
| **As-Built** | The observed actual state of the running network, collected from telemetry and device interrogation | Monitoring Agent (Agent 6) | Operations, monitoring, assurance | Continuously updated; historical snapshots versioned |

### 3.3 Model State Transitions in the Closed Loop

The five model states create a **pipeline of progressively more concrete representations**, directly corresponding to MALT's concept of a declarative dataflow where each stage's output becomes the next stage's input:

```
 Human Operator                    Inner Loop Feedback
      │                                    │
      ▼                                    ▼
 ┌─────────┐  select  ┌───────────┐  approve  ┌─────┐  deploy  ┌──────────┐
 │ WHAT-IF │────────►│ CANDIDATE │──────────►│ POR │────────►│ DEPLOYED │
 └─────────┘         └───────────┘           └─────┘         └────┬─────┘
      ▲                    ▲                    ▲                  │
      │                    │                    │             verify│
      │              reject│              update│                  ▼
      │                    │                    │           ┌──────────┐
      │                    └────────────────────┼───────────│ AS-BUILT │
      │                                        │           └──────┬───┘
      │                                        │                  │
      │                              drift detected               │
      └───────────── (re-plan) ◄──────────────────────────────────┘
```

**Fulfillment flow (left to right):** A new intent enters as a What-If model (or multiple), is narrowed to a single Candidate, approved as POR, deployed to NetLab, and verified against the As-Built state.

**Assurance flow (right to left):** The Compliance Assessment Agent compares POR against As-Built. Drift triggers the inner loop, which may generate new Candidate models to correct the deviation — without modifying the POR intent.

**Outer loop refinement:** When the operator reviews reports and decides to change the intent itself, a new What-If exploration begins, eventually producing a new POR version. The old POR is linked via `PRECEDED_BY` and archived.

### 3.4 Multiple Levels of Abstraction

MALT's second core motivation (§2.1) is that different management processes operate at different levels of abstraction: capacity planners reason about abstract capacity between sites, while device engineers configure specific interface parameters. Both must work with the same underlying model.

Our Neo4j ontology already implements this through the 9-layer structure (L1 Infrastructure → L9 People/Process). The MALT-inspired enhancement adds **explicit abstraction relationships** that allow traversal between layers:

| Relationship | Direction | Meaning | Example |
|-------------|-----------|---------|---------|
| `REALIZED_BY` | Abstract → Concrete | An abstract entity is physically realized by a concrete entity | `(:Intent)-[:REALIZED_BY]->(:Policy)-[:REALIZED_BY]->(:FirewallRule)-[:REALIZED_BY]->(:Configuration)` |
| `ABSTRACTS` | Concrete → Abstract | A concrete entity is an implementation of an abstract concept | `(:Device)-[:ABSTRACTS]->(:TopologyLayer)` |
| `AGGREGATES` | Group → Members | A group entity aggregates its members (MALT's `RK_AGGREGATES`) | `(:FirewallPair)-[:AGGREGATES]->(:Device)` |
| `CONTAINS` | Parent → Child | Physical or logical containment hierarchy (MALT's `RK_CONTAINS`) | `(:Site)-[:CONTAINS]->(:Device)-[:CONTAINS]->(:Interface)` |
| `TRAVERSES` | Link → Path | A logical link traverses a physical path (MALT's `RK_TRAVERSES`) | `(:LogicalLink)-[:TRAVERSES]->(:PhysicalLink)` |

These relationships enable **cross-layer queries** that are essential for lifecycle management:

- **Capacity planning:** "If I add 200 users to this site, which VLANs, switches, and firewall rules need to change?" — traverses L9→L4→L2→L1
- **Impact analysis:** "If this interface fails, which intents are violated?" — traverses L1→L5→L4→L3
- **Blast radius:** "What is the full impact of deploying this candidate model?" — compares Candidate vs. POR at every abstraction level

### 3.5 What-If Analysis and Drain-Impact Assessment

Following MALT §2.2 (WAN capacity planning and datacenter fabric expansion), our Planning Agent (Agent 4) now supports two critical lifecycle functions:

**What-If Analysis:** Before committing to a change, the agent creates one or more **What-If model instances** in Neo4j. Each instance is a complete, self-contained representation of the proposed future network state. The agent then evaluates each instance against:

- Existing intents (will any be violated?)
- Capacity constraints (are there enough switch ports, VLAN IDs, firewall rule slots?)
- Failure scenarios (what happens if a link or device fails in this design?)
- Cost and lead time (does this option require new hardware?)

What-If models are tagged with `modelState: 'WHAT_IF'` and a `scenarioId` that groups related alternatives. After evaluation, the best option is promoted to Candidate.

**Drain-Impact Assessment:** For changes to the live network (MALT §2.2, Fig. 2), the Planning Agent computes a **drain-impact analysis** before each deployment step. This involves:

1. Querying the As-Built model for current traffic patterns and link utilization
2. Simulating the effect of the proposed change on active sessions and traffic paths
3. Computing the maximum capacity reduction per step (e.g., "this step reduces redundancy by 12.5% — acceptable" vs. "this step eliminates the only path to the DNS DMZ — block")
4. Generating a sequenced `MigrationPlan` with capacity-preserving steps

This is especially critical for the firewall pipeline: deploying a new zone policy must not disrupt existing sessions that traverse the firewall.

### 3.6 Declarative Dataflow Pipeline

MALT §7.1 and §11.2 advocate a **declarative dataflow** approach over imperative orchestration. In our architecture, this means each AI Agent operates as a **stateless function** that:

1. **Declares** its input requirements (a Cypher query pattern against the SSoT)
2. **Reads** the current model state from Neo4j (immutable snapshot)
3. **Produces** a new model instance (written back to Neo4j as a new, immutable version)
4. **Triggers** downstream agents via the event bus

The agent never mutates existing model state — it creates new versions linked by `PRECEDED_BY` relationships. This creates a complete, auditable **dataflow graph** in Neo4j where every model instance records its provenance: which agent created it, from which input model, at what time.

```
Model Instance A (v1)
  ├── created_by: Agent 2 (Translation)
  ├── input_model: Intent INT-001 (v1)
  ├── output_model: Policy POL-USF-001 (v1)
  └── PRECEDED_BY → (none, first version)

Model Instance B (v2)
  ├── created_by: Agent 8 (Compliance Action)
  ├── input_model: ComplianceAssessment CA-042
  ├── output_model: Policy POL-USF-001 (v2)
  └── PRECEDED_BY → Model Instance A (v1)
```

This aligns with MALT's "dataflow rather than database" philosophy (§5.3) — the SSoT is not a mutable database that agents update in place, but a versioned repository of immutable model instances that flow between agents.

### 3.7 As-Built Auditing

MALT §2.2 (Fig. 2, step ⑧) describes the critical practice of auditing the actual network after deployment to update the "as-built" model, ensuring the SSoT does not drift from reality. In our closed loop, the Monitoring Agent (Agent 6) continuously maintains the As-Built model state by:

1. **Configuration auditing:** Periodically pulling the running configuration from each NetLab device and comparing it against the Deployed model. Differences are flagged as `configDrift` alerts.
2. **State auditing:** Comparing the observed operational state (interface up/down, VRRP role, routing table) against the expected state recorded in the POR model.
3. **Topology auditing:** Verifying that the physical and logical topology (LLDP neighbors, STP root, LAG members) matches the SSoT topology model.

Any discrepancy between Deployed and As-Built triggers the inner loop, while systematic discrepancies between POR and As-Built may trigger the outer loop (the network has been manually changed outside the closed loop, requiring the operator to reconcile).

---

## 4. Architecture Overview

The following diagram maps the RFC 9315 model to our concrete implementation stack:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           OUTER LOOP (Human)                            │
│                                                                         │
│  ┌───────────────┐                                    ┌───────────────┐ │
│  │ Human Operator │◄──── Reporting Agent ◄────────────│  Report Store │ │
│  │ (Intent Author)│                                   │  (Neo4j L9)   │ │
│  └───────┬───────┘                                    └───────────────┘ │
│          │ Intent (NL / structured / template)                          │
│          ▼                                                              │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    INTENT FULFILLMENT PLANE                       │  │
│  │                                                                   │  │
│  │  ┌─────────────┐   ┌─────────────┐   ┌──────────────────────┐   │  │
│  │  │  Ingestion  │──►│ Translation │──►│  Orchestration       │   │  │
│  │  │   Agent     │   │   Agent(s)  │   │   Agent              │   │  │
│  │  │             │   │             │   │                      │   │  │
│  │  │ • NLP parse │   │ • HLD→policy│   │ • NetLab topology.yml│   │  │
│  │  │ • validate  │   │ • policy→cfg│   │ • config generation  │   │  │
│  │  │ • SSoT write│   │ • conflict  │   │ • deployment push    │   │  │
│  │  │             │   │   detect    │   │ • post-deploy verify │   │  │
│  │  └─────────────┘   └─────────────┘   └──────────┬───────────┘   │  │
│  │         │                │                       │               │  │
│  │         ▼                ▼                       ▼               │  │
│  │  ┌─────────────────────────────────────────────────────────┐    │  │
│  │  │                    NEO4J  (SSoT)                         │    │  │
│  │  │  L4: Intent, Policy  │  L5: Config, State  │ L1: Infra  │    │  │
│  │  │  L3: Architecture    │  L6: Incidents       │ L2: Topo   │    │  │
│  │  │  L7: Change Mgmt     │  L8: Lifecycle       │ L9: People │    │  │
│  │  └─────────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                      │                                  │
│                                      │ (Config push / Telemetry pull)   │
│                                      ▼                                  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    TARGET NETWORK: NETLAB                         │  │
│  │                                                                   │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │  │
│  │  │ Access   │  │ Aggreg.  │  │ Firewalls│  │ Internet Edge /  │ │  │
│  │  │ Switches │  │ Switches │  │ (User/DMZ│  │ VPN / ISP stubs  │ │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                      │                                  │
│                                      │ (Telemetry / State)              │
│                                      ▼                                  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    INTENT ASSURANCE PLANE                         │  │
│  │                                                                   │  │
│  │  ┌─────────────┐   ┌─────────────────┐   ┌──────────────────┐   │  │
│  │  │  Monitoring │──►│   Compliance    │──►│  Compliance      │   │  │
│  │  │   Agent     │   │   Assessment    │   │  Action Agent    │   │  │
│  │  │             │   │   Agent         │   │                  │   │  │
│  │  │ • gNMI/     │   │ • desired vs   │   │ • auto-remediate │   │  │
│  │  │   NETCONF   │   │   observed     │   │ • escalate       │   │  │
│  │  │ • syslog    │   │ • drift detect │   │ • rollback       │   │  │
│  │  │ • flow data │   │ • root cause   │   │ • re-orchestrate │   │  │
│  │  └─────────────┘   └─────────────────┘   └────────┬─────────┘   │  │
│  │                                                    │             │  │
│  │         INNER LOOP ◄───────────────────────────────┘             │  │
│  │         (feeds back to Orchestration Agent)                      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    REPORTING / ABSTRACTION                        │  │
│  │                                                                   │  │
│  │  ┌─────────────┐   ┌─────────────────┐                           │  │
│  │  │ Abstraction │──►│   Reporting     │──► Human Operator          │  │
│  │  │   Agent     │   │   Agent         │   (outer loop feedback)    │  │
│  │  │             │   │                 │                            │  │
│  │  │ • aggregate │   │ • dashboards   │                            │  │
│  │  │ • correlate │   │ • compliance % │                            │  │
│  │  │ • up-level  │   │ • alerts       │                            │  │
│  │  └─────────────┘   └─────────────────┘                           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Loop Phases and AI Agent Decomposition

RFC 9315 defines functional blocks but does not prescribe implementation. Our architecture decomposes the Translation/IBS space into **eight specialized AI Agents**. Each agent has a single responsibility, reads from and writes to the Neo4j SSoT, and communicates with adjacent agents through the graph (event-driven via Neo4j change data capture or message queue).

### 5.1 Fulfillment Plane Agents

#### Agent 1 — Intent Ingestion Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Ingestion and Interaction with Users (§5.1.1) |
| **RFC 9315 space** | User Space |
| **Input** | Natural language, structured API call, or template from the human operator |
| **Output** | Validated `Intent` node in Neo4j (Layer 4), linked to `BusinessUseCase` (Layer 3) |
| **Capabilities** | NLP parsing of operator intent; interactive dialog for refinement (the "one touch but not one shot" principle of RFC 9315 §4.2); conflict detection against existing intents in the SSoT; validation that the intent is well-formed and achievable given current network capabilities |
| **Neo4j writes** | Creates `(:Intent {intentId, statement, status: 'INGESTED', createdAt})` node; creates `(:Intent)-[:ADDRESSES]->(:BusinessUseCase)` relationship; if refinement needed, creates `(:IntentRefinement)` linked to the original intent |
| **Human interaction** | Yes — this is the primary human-machine interface. Supports iterative refinement per RFC 9315 §4.2 |

#### Agent 2 — Intent-to-Policy Translation Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Translation (§5.1.2) — first stage |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | `Intent` node from Neo4j (status = `INGESTED`) |
| **Output** | `Policy`, `FirewallRule`, `SGT`, `ComplianceReq` nodes in Neo4j (Layer 4) |
| **Capabilities** | Maps declarative business intent to structured policy objects; decomposes compound intents into individual policy rules; resolves policy conflicts by consulting existing policies in Neo4j; assigns `segmentId`, `zoneId`, and `qosDscp` values aligned with the HLD population model |
| **Neo4j writes** | Creates `(:Policy)-[:IMPLEMENTS]->(:Intent)` relationships; creates `(:FirewallRule)-[:ENFORCES]->(:Policy)` relationships; updates Intent status to `TRANSLATED` |
| **Example** | Intent: *"Guest users must only access the internet, never internal resources"* → Policy: `Segment(GUEST) → Zone(INTERNET) = PERMIT; Segment(GUEST) → Zone(USER) = DENY; Segment(GUEST) → Zone(DMZ_INFRA) = DENY` |

#### Agent 3 — Policy-to-Configuration Translation Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Translation (§5.1.2) — second stage |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | `Policy` nodes from Neo4j (status = `APPROVED`) |
| **Output** | `Configuration` nodes in Neo4j (Layer 5), containing device-specific configuration snippets |
| **Capabilities** | Renders abstract policies into vendor-specific device configurations (IOS-XE CLI, EOS, FortiOS, etc.); generates per-device configuration diffs; respects the HLD naming conventions, VLAN assignments, and VRF model; produces NetLab-compatible configuration templates (Jinja2) |
| **Neo4j writes** | Creates `(:Configuration {configId, deviceId, content, format, version})-[:RENDERS]->(:Policy)` relationships; links configuration to target `(:Device)` node; updates Policy status to `RENDERED` |
| **Learning** | Over time, learns which configuration patterns produce the best compliance outcomes (RFC 9315 §4.4 — Learning principle) |

#### Agent 4 — Planning and Optimization Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Learn / Plan / Render (§5.1.2, §6 inner loop) |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | Current network state from Neo4j (Layer 5: `OperationalState`, `Telemetry`); compliance history; configuration performance metrics |
| **Output** | Optimized rendering decisions; migration plans; change sequencing |
| **Capabilities** | Determines the optimal order for configuration deployment across devices; computes blast radius analysis using Neo4j graph traversal; generates `MigrationPlan` nodes for multi-step changes; incorporates feedback from the assurance plane to improve future rendering decisions |
| **Neo4j writes** | Creates `(:MigrationPlan)-[:TARGETS]->(:Device)` relationships; creates `(:ChangeRequest)-[:PART_OF]->(:MigrationPlan)`; updates `ArchitectureVersion` if the plan involves structural changes |
| **Key differentiator** | This is the **learning agent** of the loop — it continuously improves by analyzing which actions led to compliant outcomes and which caused drift |

#### Agent 5 — Orchestration Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Orchestration (§5.1.3) |
| **RFC 9315 space** | Network Operations Space |
| **Input** | `Configuration` nodes from Neo4j (status = `APPROVED`); `MigrationPlan` from Agent 4 |
| **Output** | Deployed configurations on NetLab devices; post-deployment verification results |
| **Capabilities** | Generates or updates the NetLab `topology.yml` file; pushes device configurations via NETCONF/SSH to the NetLab virtual devices; executes deployment in the order prescribed by the `MigrationPlan`; performs post-deployment verification (config diff between intended and running); rolls back on failure |
| **Neo4j writes** | Creates `(:DeploymentEvent {eventId, timestamp, status, targetDeviceId})-[:DEPLOYS]->(:Configuration)` nodes; updates `(:Device).operationalState`; updates Intent status to `ORCHESTRATED` |
| **NetLab interaction** | Direct — this is the only agent that touches the target network |

### 5.2 Assurance Plane Agents

#### Agent 6 — Monitoring Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Monitoring (§5.2.1) |
| **RFC 9315 space** | Network Operations Space |
| **Input** | Telemetry streams from NetLab devices (gNMI, NETCONF operational data, syslog, SNMP, NetFlow/IPFIX) |
| **Output** | `Telemetry`, `OperationalState`, and `Alert` nodes in Neo4j (Layer 5 and Layer 6) |
| **Capabilities** | Continuously collects network state from all NetLab devices; normalizes multi-vendor telemetry into the Neo4j ontology format; detects anomalies and state transitions; generates `Alert` nodes when thresholds are crossed |
| **Neo4j writes** | Creates `(:Telemetry {timestamp, metric, value, deviceId})` nodes; updates `(:Device).operState` and `(:Interface).operState`; creates `(:Alert)-[:DETECTED_ON]->(:Device)` |
| **Collection methods** | For NetLab: SSH polling (show commands), SNMP, syslog receiver, and where supported, gNMI streaming |

#### Agent 7 — Compliance Assessment Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Compliance Assessment (§5.2.2) |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | Observed state from Neo4j (Layer 5: `OperationalState`, `Telemetry`); desired state from Neo4j (Layer 4: `Intent`, `Policy`; Layer 5: `Configuration`) |
| **Output** | Compliance verdicts; drift detection events; root cause analysis |
| **Capabilities** | Compares desired state (SSoT) against observed state for every active intent; classifies each intent as `COMPLIANT`, `NON_COMPLIANT`, `DEGRADED`, or `UNKNOWN`; detects **intent drift** (RFC 9315 §5.2.2) — gradual deviation from intended behavior; performs root cause analysis by traversing the Neo4j dependency graph (intent → policy → config → device → interface → telemetry) |
| **Neo4j writes** | Creates `(:ComplianceAssessment {assessmentId, intentId, verdict, timestamp, details})-[:ASSESSES]->(:Intent)` nodes; creates `(:Incident)-[:CAUSED_BY]->(:RootCause)` when non-compliance is detected; updates `(:Intent).complianceStatus` |
| **Key query** | `MATCH (i:Intent)-[:IMPLEMENTED_BY]->(p:Policy)-[:RENDERED_AS]->(c:Configuration)-[:DEPLOYED_ON]->(d:Device)-[:HAS_STATE]->(s:OperationalState) WHERE s.observed <> c.expected RETURN i, d, s` |

#### Agent 8 — Compliance Action Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Intent Compliance Actions (§5.2.3) |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | `ComplianceAssessment` nodes with verdict = `NON_COMPLIANT` or `DEGRADED` |
| **Output** | Remediation actions or escalation events |
| **Capabilities** | Decides the appropriate response based on severity and autonomy policy |
| **Action matrix** | See table below |
| **Neo4j writes** | Creates `(:Remediation {action, timestamp, success})-[:RESOLVES]->(:Incident)` nodes; if escalated, creates `(:Ticket)-[:ASSIGNED_TO]->(:Team)` (Layer 9) |

**Compliance Action Decision Matrix:**

| Severity | Condition | Action | Autonomy | Loop |
|----------|-----------|--------|----------|------|
| **Info** | Minor metric fluctuation within tolerance | Log to Neo4j, no action | Fully autonomous | Inner |
| **Low** | Single interface down, redundancy active | Alert + auto-remediate (re-push config via Orchestration Agent) | Autonomous with audit | Inner |
| **Medium** | Intent drift detected on multiple devices | Alert + re-orchestrate affected scope + verify | Autonomous with approval hold (configurable) | Inner |
| **High** | Service-impacting non-compliance | Alert + escalate to human + pause automated changes | Human-in-the-loop | Outer |
| **Critical** | Multiple intents violated, potential cascading failure | Alert + rollback to last-known-good + escalate + freeze orchestration | Human-in-the-loop | Outer |

### 5.3 Reporting Plane Agents

#### Agent 9 — Abstraction Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Abstraction, Aggregation, Reporting (§5.2.4) |
| **RFC 9315 space** | Translation / IBS Space |
| **Input** | Raw compliance assessments, telemetry aggregates, incident records from Neo4j |
| **Output** | Up-leveled, business-relevant summaries written to Neo4j |
| **Capabilities** | Aggregates device-level observations into intent-level compliance scores; correlates multiple incidents into business-impact statements; produces trend analysis (improving / degrading / stable); generates natural-language explanations of network state relative to declared intents |

#### Agent 10 — Reporting Agent

| Attribute | Value |
|-----------|-------|
| **RFC 9315 block** | Report (§6, User Space) |
| **RFC 9315 space** | User Space |
| **Input** | Abstracted summaries from Agent 9 |
| **Output** | Human-readable reports, dashboards, alerts to the operator |
| **Capabilities** | Generates compliance dashboards (per-intent, per-site, per-device); produces natural-language status reports; triggers notifications for human attention; supports the outer loop by presenting information the operator needs to decide whether to modify, retain, or retract intents |

---

## 6. Neo4j as SSoT — Role per Phase

Neo4j is not a passive data store — it is the **active backbone** of the closed loop. Every agent reads from and writes to the graph. The SSoT function is distributed across the ontology layers as follows:

| Loop Phase | RFC 9315 Function | Neo4j Layer(s) Used | Read / Write | What is stored |
|------------|-------------------|---------------------|-------------|----------------|
| **Ingestion** | Recognize / Generate Intent | L3 (Architecture, BUC), L4 (Intent) | Write | New `Intent` nodes linked to `BusinessUseCase` and `Architecture` |
| **Translation** | Translate / Refine | L4 (Policy, FirewallRule, SGT), L1 (VLAN, Segment, Zone) | Read + Write | Policy objects derived from intent; validation against existing infrastructure |
| **Rendering** | Learn / Plan / Render | L5 (Configuration), L7 (ChangeRequest, MigrationPlan) | Read + Write | Device-specific configs; change plans; learned optimization data |
| **Orchestration** | Configure / Provision | L1 (Device, Interface), L5 (DeploymentEvent), L8 (LifecycleTransition) | Read + Write | Deployment events; device state updates; lifecycle transitions |
| **Monitoring** | Monitor / Observe | L5 (Telemetry, OperationalState), L6 (Alert) | Write | Raw telemetry data; operational state snapshots; alert events |
| **Assessment** | Validate / Analyze | L4 (Intent.complianceStatus), L6 (Incident, RootCause) | Read + Write | Compliance verdicts; drift detection; root cause analysis results |
| **Compliance Action** | Remediate / Escalate | L6 (Remediation), L7 (ChangeRequest), L9 (Ticket, Team) | Read + Write | Remediation records; escalation tickets; rollback events |
| **Abstraction** | Abstract / Aggregate | All layers (traversal) | Read + Write | Aggregated compliance scores; trend data; business-impact correlations |
| **Reporting** | Report | L9 (Operator, Team), all layers (read) | Read | Human-consumable views derived from the graph |

**Key SSoT invariants (per RFC 9315 §4.1):**

1. **Desired state** is always recorded in Neo4j before any configuration is deployed to NetLab. The graph is the authority; the network is the follower.
2. **Observed state** is always written back to Neo4j after collection. The graph holds both the "what should be" and the "what is."
3. **Drift** is computed as the difference between desired and observed state — a graph query, not an external calculation.
4. **History** is preserved through versioned nodes and temporal relationships (`since` / `until`). No state is ever overwritten.

---

## 7. NetLab as Target Network

### 7.1 Role in the Closed Loop

NetLab occupies the **Network Operations Space** of RFC 9315. It is the concrete infrastructure where intent is realized and observed:

```
┌──────────────────────────────────────────────────────────┐
│                   NETLAB ENVIRONMENT                      │
│                                                          │
│  topology.yml ──► netlab up ──► Virtual Network          │
│                                                          │
│  ┌────────────┐    ┌────────────┐    ┌───────────────┐  │
│  │ Containerlab│ or │  libvirt   │ or │   external    │  │
│  │  (clab)    │    │  (Vagrant) │    │   provider    │  │
│  └────────────┘    └────────────┘    └───────────────┘  │
│                                                          │
│  Devices: IOS-XE, EOS, FRR, FortiOS, VyOS, NX-OS       │
│  Protocols: OSPF, BGP, STP, VLAN, VRF, LAG              │
│  Telemetry: SSH/CLI, SNMP, syslog, (gNMI where avail.)  │
└──────────────────────────────────────────────────────────┘
```

### 7.2 Orchestration Agent → NetLab Interface

The Orchestration Agent (Agent 5) interacts with NetLab through two mechanisms:

**Mechanism A — Topology lifecycle:** When the intent requires structural changes (new devices, new links, new VLANs), the agent regenerates the `topology.yml` from the Neo4j graph and executes `netlab up` or `netlab restart` to instantiate the updated topology.

**Mechanism B — Configuration push:** When the intent requires only configuration changes on existing devices, the agent generates device-specific configuration templates (Jinja2) and pushes them to running devices via NETCONF, SSH, or the NetLab initial configuration mechanism.

### 7.3 Monitoring Agent → NetLab Interface

The Monitoring Agent (Agent 6) collects observed state from NetLab devices through:

| Method | Protocol | Data Collected | Update Frequency |
|--------|----------|---------------|-----------------|
| CLI polling | SSH (Netmiko/Napalm) | Running config, interface state, routing table, ARP/MAC tables | Periodic (30s–5min) |
| SNMP polling | SNMPv2c/v3 | Interface counters, CPU/memory, STP state | Periodic (60s) |
| Syslog receiver | UDP 514 | State change events, error messages | Event-driven |
| gNMI streaming | gRPC (where supported) | Interface stats, BGP state, LLDP neighbors | Streaming (sub-second) |
| NETCONF get | NETCONF 1.1 | Operational datastore | On-demand |

### 7.4 NetLab Feasibility Boundaries

Per the companion feasibility analysis, NetLab provides full structural/L2-L3 coverage but limited security policy coverage. The closed loop accounts for this:

| Loop function | NetLab coverage | Workaround |
|--------------|----------------|------------|
| Topology orchestration | ✅ Full | Direct `topology.yml` generation |
| VLAN/VRF deployment | ✅ Full | Netlab VLAN/VRF modules |
| Routing protocol config | ✅ Full | Netlab OSPF/BGP modules |
| STP/LACP config | ✅ Full | Netlab STP/LAG modules |
| Firewall policy enforcement | ❌ Not native | **Jinja2 pipeline** — see §7.5 below |
| QoS marking | ❌ Not native | Jinja2 config templates; limited verification |
| NAT/PAT | ❌ Not native | **Jinja2 pipeline** — see §7.5 below |
| 802.1X/NAC | ❌ Not native | Out of scope for automated loop; modelled in Neo4j only |

### 7.5 Jinja2 Firewall Configuration Pipeline

NetLab does not natively express firewall zone policies, NAT rules, HA clustering, or QoS in `topology.yml`. These capabilities are provided by a **Jinja2 rendering pipeline** that extracts configuration state from the Neo4j SSoT and renders VyOS-compatible device configurations.

This pipeline is the **critical bridge** between the intent stored in Neo4j and the firewall devices running in NetLab.

#### 7.5.1 Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                  JINJA2 FIREWALL PIPELINE                            │
│                  (Orchestration Agent — Agent 5)                     │
│                                                                      │
│  ┌─────────────┐    ┌────────────────┐    ┌───────────────────────┐ │
│  │   NEO4J     │    │  EXTRACTION    │    │  JINJA2 TEMPLATES     │ │
│  │   SSoT      │───►│  QUERIES       │───►│                       │ │
│  │             │    │  (8 Cypher)    │    │  vyos_firewall_base   │ │
│  │ L1: Device  │    │                │    │  vyos_firewall_policy │ │
│  │ L2: Zone    │    │ firewalls      │    │  vyos_nat             │ │
│  │ L4: Policy  │    │ zones          │    │  vyos_ha              │ │
│  │ L4: FWRule  │    │ segments       │    │                       │ │
│  │ L5: Config  │    │ policies       │    └───────────┬───────────┘ │
│  │             │    │ intents        │                │             │
│  │             │    │ fw_interfaces  │                ▼             │
│  │             │    │ nat_rules      │    ┌───────────────────────┐ │
│  │             │    │ fw_transit     │    │  RENDERED CONFIG      │ │
│  │             │    └────────────────┘    │  (per device .conf)   │ │
│  │             │                          │                       │ │
│  │             │◄─── DeploymentEvent ─────│  fw-hq-usr-01.conf   │ │
│  │             │     (audit trail)        │  fw-hq-usr-02.conf   │ │
│  │             │                          │  fw-hq-dmz-01.conf   │ │
│  └─────────────┘                          │  fw-hq-dmz-02.conf   │ │
│                                           └───────────┬───────────┘ │
│                                                       │             │
│                                                       ▼             │
│                                           ┌───────────────────────┐ │
│                                           │  NETLAB DEVICES       │ │
│                                           │  (VyOS via SSH push)  │ │
│                                           └───────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

#### 7.5.2 Extraction Queries (Neo4j → Context)

The pipeline executes 8 Cypher queries against the SSoT to extract the full firewall configuration state. Each query populates a template variable:

| Query | Template Variable | Neo4j Source | Description |
|-------|-------------------|-------------|-------------|
| Q1 | `firewalls` | `Device`, `FirewallPair`, `Site` | Active firewall inventory with HA role and pair membership |
| Q2 | `zones` | `Zone` | All security zones with security levels and default policies |
| Q3 | `segments` | `Segment`, `VLAN`, `Subnet`, `Zone` | Population segments with VLAN/subnet/zone mappings |
| Q4 | `policies` | `Policy`, `FirewallRule`, `Zone`, `Device` | Active zone-to-zone firewall rules per target device |
| Q5 | `intents` | `Intent`, `IntentTranslation`, `Policy` | Intent traceability for audit headers |
| Q6 | `fw_interfaces` | `Device`, `Interface`, `VLAN`, `Subnet` | Interface-to-VLAN mappings per firewall |
| Q7 | `nat_rules` | `Policy` (type=NAT_RULE), `FirewallRule` | NAT/PAT rules for user internet access |
| Q8 | `fw_transit` | `VLAN` (id=300), `Subnet` | Inter-firewall transit link parameters |

Full query source: `firewall_pipeline/cypher/extract_firewall_state.cypher`

#### 7.5.3 Template Chain (Context → VyOS Config)

The rendering engine processes four templates in sequence for each firewall device. Templates are concatenated to produce a single unified configuration file:

| Order | Template | Scope | What It Renders |
|-------|----------|-------|----------------|
| 1 | `vyos_firewall_base.j2` | Both USF and DMZFW | Audit header (intent traceability); system parameters; VLAN sub-interfaces with IP addresses; zone definitions and interface-to-zone assignments; inter-firewall transit link; HA heartbeat interface; management interface |
| 2 | `vyos_firewall_policies.j2` | Both (role-aware) | Dynamic zone-to-zone rulesets from Neo4j `FirewallRule` nodes; global default-deny with established/related allow; HLD baseline policies (DNS, AD, File, PBX, Guest isolation for USF; DNS-to-internet, AD-to-internet, internet-to-publish, inter-DMZ deny for DMZFW); zone-policy from/to assignments |
| 3 | `vyos_nat.j2` | Both (role-aware) | Source NAT (masquerade) for user internet access (USF); source NAT for DMZ outbound (DMZFW); destination NAT for publishing DMZ inbound (DMZFW); baseline SNAT from segment definitions |
| 4 | `vyos_ha.j2` | Both | VRRP groups per VLAN (virtual gateway addresses); VRRP sync group for coordinated failover; conntrack-sync for session state replication; priority-based active/passive or active/active election |

Full template source: `firewall_pipeline/templates/`

#### 7.5.4 Rendering Pipeline Execution

The Python pipeline script (`firewall_pipeline/render_firewall_config.py`) implements the full flow:

**Step 1 — Extract:** Connect to Neo4j and execute 8 Cypher queries. Build a structured context dictionary.

**Step 2 — Enrich:** Add device-level metadata (interface mappings, transit IPs, HA peer addresses) that bridges the Neo4j model to VyOS physical interface names.

**Step 3 — Render:** For each active firewall device, process the 4-template chain with the device-specific context. Produce a `<hostname>.conf` file containing the complete VyOS `set` command configuration.

**Step 4 — Audit:** Record a `DeploymentEvent` node in Neo4j for each rendered configuration, including a SHA-256 content hash and a link to the target device. This closes the traceability chain: Intent → Policy → FirewallRule → Configuration → DeploymentEvent → Device.

**Step 5 — Deploy:** Push the rendered configuration to the live NetLab VyOS device via SSH (`vbash` / `configure` mode) or via the NetLab custom config mechanism.

#### 7.5.5 Compliance Verification for Firewall Config

After deployment, the Monitoring Agent (Agent 6) verifies firewall compliance by:

1. **Config diff:** SSH into VyOS, run `show configuration commands`, compare against the rendered `.conf` file line-by-line.
2. **Zone verification:** Run `show zone-policy zone <name>` and validate that all expected interfaces are assigned.
3. **Rule hit counters:** Run `show firewall name <ruleset> statistics` to confirm rules are active and traffic is matching expected patterns.
4. **Session table:** Run `show conntrack table` to verify stateful inspection is operational.
5. **VRRP state:** Run `show vrrp` to confirm HA role matches the SSoT expected state.

Deviations trigger the Compliance Assessment Agent (Agent 7) → Compliance Action Agent (Agent 8) → re-rendering and re-deployment through the inner loop.

---

## 8. Inner Loop vs. Outer Loop

### 8.1 Inner Loop (Autonomous)

The inner loop operates continuously without human intervention. It is the machine-to-machine feedback cycle between the Translation/IBS space and the Network Operations space:

```
Orchestration Agent ──► NetLab (deploy config)
         ▲                        │
         │                        ▼
Planning Agent ◄── Compliance ◄── Monitoring Agent
                   Action Agent    (collect telemetry)
                        ▲
                        │
                   Compliance
                   Assessment Agent
                   (desired vs. observed)
```

**Timing:** The inner loop cycle time depends on the monitoring interval and the complexity of the compliance assessment. Target: 30 seconds to 5 minutes for detection, 1–15 minutes for automated remediation.

**Scope of autonomy:** The inner loop can auto-remediate issues classified as Info, Low, or Medium severity. It cannot modify the declared intent — only the rendered configuration and deployment sequence.

### 8.2 Outer Loop (Human-in-the-Loop)

The outer loop extends to the human operator and operates on a longer timescale:

```
Human Operator ──► Ingestion Agent ──► (Fulfillment pipeline)
       ▲                                        │
       │                                        ▼
Reporting Agent ◄── Abstraction Agent ◄── (Assurance pipeline)
```

**Timing:** The outer loop operates on human timescales — minutes to days. The operator reviews compliance reports, assesses whether intents are achieving desired outcomes, and may modify, add, or retract intents.

**Triggers for outer loop engagement:**

1. **Escalation:** The Compliance Action Agent escalates a High or Critical severity issue.
2. **Periodic review:** Scheduled compliance reports prompt the operator to review intent effectiveness.
3. **Business change:** The operator proactively submits new intents or modifies existing ones based on business requirements.
4. **Intent retirement:** The operator retracts an intent that is no longer needed, triggering decommission workflows.

---

## 9. Agent Communication and Orchestration

### 9.1 Communication Pattern

Agents communicate through the **Neo4j SSoT** as the shared medium, supplemented by an event bus for real-time triggering:

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Agent N  │────►│   NEO4J      │◄────│ Agent M  │
│          │     │  (SSoT)      │     │          │
│          │◄───►│              │◄───►│          │
└──────────┘     └──────┬───────┘     └──────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │  Event Bus   │
                 │ (CDC / Queue)│
                 │              │
                 │ • Neo4j CDC  │
                 │ • or Kafka   │
                 │ • or Redis   │
                 └──────────────┘
```

**Pattern:** Each agent writes its output to Neo4j as new nodes/relationships. The change triggers a downstream agent via the event bus. This creates a **data-driven pipeline** where agents are loosely coupled and the SSoT is always consistent.

### 9.2 Agent Triggering Rules

| Trigger Event (Neo4j) | Downstream Agent | Action |
|-----------------------|------------------|--------|
| New `Intent` node (status = `INGESTED`) | Agent 2 (Intent→Policy) | Begin translation |
| New `Policy` node (status = `APPROVED`) | Agent 3 (Policy→Config) | Begin rendering |
| New `Configuration` node (status = `READY`) | Agent 4 (Planning) | Compute deployment plan |
| `MigrationPlan` node (status = `APPROVED`) | Agent 5 (Orchestration) | Deploy to NetLab |
| New `Telemetry` or `OperationalState` update | Agent 7 (Assessment) | Run compliance check |
| `ComplianceAssessment` (verdict ≠ `COMPLIANT`) | Agent 8 (Action) | Decide remediation |
| `Remediation` (action = `RE_ORCHESTRATE`) | Agent 5 (Orchestration) | Re-deploy corrected config |
| `Remediation` (action = `ESCALATE`) | Agent 10 (Reporting) | Notify human operator |

### 9.3 Agent Lifecycle

Each AI Agent itself has a lifecycle managed by a **supervisor process**:

| State | Description |
|-------|-------------|
| `IDLE` | Waiting for trigger |
| `PROCESSING` | Actively working on a task |
| `WAITING_APPROVAL` | Output produced, awaiting human or policy approval |
| `ERROR` | Failed; logged to Neo4j as `(:AgentError)` |
| `DISABLED` | Administratively disabled by operator |

---

## 10. Three-Tier Memory Architecture (Live-Memory + Graph-Memory)

### 10.1 Motivation: The Memory Gap in Multi-Agent Loops

The architecture described in §9 treats Neo4j as the sole communication substrate between agents — every agent reads from and writes to the graph. This works well for **structured, schema-conformant artifacts** (intents, policies, configurations, telemetry), but the closed loop also generates a significant volume of **unstructured operational context** that does not belong in the ontology:

- An agent's reasoning trace explaining *why* it chose a particular policy decomposition.
- Observations noted during a compliance assessment that do not yet constitute an incident.
- Coordination notes between the inner loop and the outer loop ("Agent 8 deferred remediation pending Agent 10 report to human").
- Intermediate analysis products from what-if exploration that did not produce a Candidate model.
- Audit narratives that link a sequence of agent actions into a coherent change story.

Forcing this context into Neo4j would violate schema governance (§13) and pollute the ontology with transient, unstructured data. Discarding it would lose the institutional memory that allows agents (and humans) to understand *why* the network is in its current state — not just *what* that state is.

**Live-Memory** (Cloud-Temple, Apache 2.0) fills this gap as a dedicated **working memory layer** for the closed loop's AI agents. It provides a dual-mode memory system — real-time note capture (Live) plus LLM-consolidated structured documentation (Bank) — purpose-built for multi-agent collaboration, backed by S3 object storage.

### 10.2 Architecture Fit: Three-Tier Memory Model

The closed loop requires three distinct memory tiers, each serving a different temporal scope and structural purpose. Two open-source projects from Cloud-Temple — **Live-Memory** and **Graph-Memory** — complement the existing Neo4j SSoT to form a complete memory architecture grounded in the multi-agent LLM system framework (Tran et al., arXiv:2501.06322).

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │              CLOSED-LOOP THREE-TIER MEMORY ARCHITECTURE                      │
 │                                                                              │
 │  ┌─────────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
 │  │  TIER 1: NEO4J      │  │  TIER 2: LIVE-   │  │  TIER 3: GRAPH-       │  │
 │  │  SSoT               │  │  MEMORY           │  │  MEMORY               │  │
 │  │  (Structured State)  │  │  (Working Memory) │  │  (Long-Term Knowledge)│  │
 │  │                     │  │                   │  │                       │  │
 │  │ • 5 Model States    │  │ • Live Notes      │  │ • Knowledge Graph     │  │
 │  │ • 9-Layer Ontology  │  │   (append-only)   │  │   (Neo4j namespace)   │  │
 │  │ • Typed Nodes/Rels  │  │ • Bank files      │  │ • Vector Embeddings   │  │
 │  │ • Schema-governed   │  │   (LLM-consolid.) │  │   (Qdrant BGE-M3)    │  │
 │  │                     │  │ • S3-only backend │  │ • Ontology-driven     │  │
 │  │                     │  │                   │  │   entity extraction   │  │
 │  │                     │  │                   │  │ • Graph-guided RAG    │  │
 │  │                     │  │                   │  │                       │  │
 │  │ Authoritative for:  │  │ Authoritative for:│  │ Authoritative for:    │  │
 │  │ WHAT the network    │  │ WHY the network   │  │ WHAT WAS LEARNED      │  │
 │  │ IS (desired +       │  │ is in this state  │  │ across all past loop  │  │
 │  │ observed state)     │  │ (agent reasoning, │  │ iterations (patterns, │  │
 │  │                     │  │ context, audit)   │  │ precedents, Q&A)     │  │
 │  └──────────┬──────────┘  └─────────┬─────────┘  └──────────┬────────────┘  │
 │             │                       │                        │               │
 │             │          ┌────────────┴────────────┐           │               │
 │             │          │    Data Flow            │           │               │
 │             │          │                         │           │               │
 │             │          │  live_note() ──► bank   │           │               │
 │             │          │  bank_consolidate()     │           │               │
 │             │          │  graph_push() ──────────┼──────────►│               │
 │             │          │                         │           │               │
 │             │◄─────────┼── graph_push() enriches │           │               │
 │             │          │   SSoT via Graph Bridge │           │               │
 │             │          └─────────────────────────┘           │               │
 │             │                                                │               │
 │             │◄───────── question_answer() (RAG) ─────────────┘               │
 │             │           (agents query historical knowledge)                  │
 └─────────────┴────────────────────────────────────────────────────────────────┘
```

| Tier | System | Memory Type | Temporal Scope | Data Shape | Backend |
|------|--------|-------------|---------------|------------|---------|
| **1 — SSoT** | Neo4j (§6) | Structured state | Current — the live network model | Schema-governed nodes & relationships (9-layer ontology, 5 model states) | Neo4j Bolt |
| **2 — Working** | Live-Memory | Operational context | Session — the current loop iteration | Append-only notes → LLM-consolidated Markdown bank files | S3 object storage |
| **3 — Long-term** | Graph-Memory | Institutional knowledge | Historical — all past iterations | Ontology-driven knowledge graph + vector embeddings | Neo4j (namespace-isolated) + Qdrant |

**Tier 1 — Neo4j SSoT** remains the authoritative store for all structured network state — intents, policies, configurations, telemetry, compliance verdicts, and model state transitions. No change to the existing design (§6).

**Tier 2 — Live-Memory** becomes the working memory where agents record unstructured operational context — reasoning, coordination notes, and audit narratives — during each loop iteration. This context is append-only (Live mode), periodically consolidated by an LLM into structured Markdown documentation (Bank mode), and pushed to Tier 3 via the Graph Bridge.

**Tier 3 — Graph-Memory** provides long-term knowledge persistence. When Live-Memory's bank files are pushed via `graph_push()`, Graph-Memory's LLM extraction pipeline decomposes the consolidated documentation into typed entities and relationships using a domain-specific ontology, stores them in a namespace-isolated Neo4j graph, and creates BGE-M3 vector embeddings in Qdrant. This enables **graph-guided RAG**: agents can query historical knowledge ("What happened last time we saw VLAN 110 latency spikes?") and receive answers grounded in typed entity traversal rather than approximate semantic similarity.

### 10.2.1 Graph-Memory: Architecture and Integration

Graph-Memory (Cloud-Temple, Apache 2.0) is a "Knowledge Graph as a Service" MCP server that implements the **graph-first** retrieval principle: Neo4j as the primary source, vectorial RAG in Qdrant as a complement. Key capabilities relevant to the closed loop:

**Ontology-driven extraction.** Graph-Memory uses YAML-defined ontologies to guide LLM entity/relation extraction. Each ontology constrains the types of entities and relationships the LLM can produce, reducing hallucinations and ensuring structural consistency. We define a custom **IBN Network Lifecycle ontology** (see §10.2.2) for the closed loop's domain.

**Namespace isolation.** Each Graph-Memory "memory" gets prefixed Neo4j labels (e.g., `IBN_LIFECYCLE_Entity`, `IBN_LIFECYCLE_Document`), ensuring complete isolation from the SSoT's 9-layer ontology operating in the same Neo4j instance. The SSoT graph and the knowledge graph coexist without schema interference.

**Graph-guided RAG.** When an agent queries Graph-Memory via `question_answer()`, the system first identifies relevant entities through fuzzy + semantic search in Neo4j, then constrains the Qdrant vector search to only those source documents. This produces precise, context-filtered answers rather than the noisy results typical of pure vector RAG.

**30 MCP tools** over Streamable HTTP for memory management, document ingestion, entity search, question answering, backup/restore, and administration — all accessible to the closed-loop agents.

### 10.2.2 IBN Network Lifecycle Ontology for Graph-Memory

Following Graph-Memory's ontology system, we define a custom ontology tailored to the network lifecycle domain. This ontology guides entity/relation extraction when Live-Memory bank files are pushed to Graph-Memory:

**Entity types (4 families):**

- *Decisions & Rationale:* `PolicyDecision`, `DesignChoice`, `TradeOff`, `RejectedAlternative`, `ApprovalRecord`
- *Incidents & Remediation:* `DriftEvent`, `RootCauseAnalysis`, `RemediationAction`, `EscalationRecord`, `ComplianceTrend`
- *Operations & Deployment:* `DeploymentNarrative`, `ConfigurationRationale`, `RollbackRecord`, `VerificationResult`
- *Knowledge & Patterns:* `RecurringPattern`, `LessonLearned`, `CapacityInsight`, `CorrelationFinding`

**Relationship types:**

- `CAUSED_BY` — links drift events to root causes
- `RESOLVED_BY` — links incidents to remediations
- `PRECEDED` — temporal ordering of decisions
- `JUSTIFIED_BY` — links design choices to rationale
- `CONTRADICTS` / `CONFIRMS` — knowledge evolution tracking
- `SIMILAR_TO` — cross-iteration pattern matching
- `INFORMED_BY` — links current decisions to historical precedents

This ontology ensures that when bank files like `policy-decisions.md` or `remediation-log.md` are ingested by Graph-Memory, the extracted knowledge graph captures the causal and temporal structure of operational decisions — not just keywords.

### 10.3 Space-per-Model-State Pattern

Live-Memory's **space** abstraction — an isolated namespace with immutable rules, live notes, and bank files — maps naturally to our five concurrent model states. We define one space per active model state instance, plus cross-cutting spaces for loop-level coordination:

| Live-Memory Space | Maps to Model State | Purpose | Lifecycle |
|-------------------|--------------------| ---------|-----------|
| `ibn-whatif-{id}` | What-If | Capture exploration reasoning, trade-off analysis, discarded alternatives | Ephemeral — archived or pruned when What-If model is discarded or promoted |
| `ibn-candidate-{id}` | Candidate | Record translation decisions, policy decomposition rationale, validation results | Persistent until promotion to POR or rejection |
| `ibn-por-{version}` | Plan-of-Record | Audit trail of approval decisions, human sign-off notes, governance evidence | Persistent and versioned; linked to POR model version in Neo4j |
| `ibn-deploy-{event}` | Deployed | Deployment execution log, Jinja2 rendering context, device response notes | Persistent; linked to `DeploymentEvent` node in Neo4j |
| `ibn-asbuilt-{snapshot}` | As-Built | Monitoring observations, anomaly analysis narratives, telemetry interpretation | Rolling — consolidated periodically, older snapshots archived |
| `ibn-loop-inner` | (Cross-cutting) | Inner loop coordination: remediation decisions, re-orchestration triggers | Long-lived; consolidated regularly |
| `ibn-loop-outer` | (Cross-cutting) | Outer loop coordination: escalation context, human decision records | Long-lived; feeds Agent 10 reporting |

Each space has **immutable rules** (`_rules.md`) that define how the LLM consolidation should structure the bank files for that model state. For example, the `ibn-candidate-{id}` space rules would require bank files structured as: `policy-decisions.md`, `validation-results.md`, `rejected-alternatives.md`, `approval-readiness.md`.

### 10.4 Agent Integration: Live Notes as Operational Telemetry

Every agent in the closed loop emits live notes to the appropriate Live-Memory space as it works. This creates an **operational telemetry stream** parallel to the structured telemetry in Neo4j:

| Agent | Live Note Category | Example Note | Target Space |
|-------|-------------------|--------------|--------------|
| A1 — Ingestion | `observation`, `decision` | "Intent ambiguity detected: 'secure guest access' could mean isolation OR bandwidth limiting. Chose isolation based on HLD §4.2 population model." | `ibn-candidate-{id}` |
| A2 — Intent→Policy | `decision`, `insight` | "Decomposed intent into 4 FW rules. Rule 3 (DNS redirection) conflicts with existing DMZFW rule R-202. Resolved by adding exception for VLAN 140." | `ibn-candidate-{id}` |
| A3 — Policy→Config | `progress`, `issue` | "VyOS Jinja2 rendering complete for fw-hq-usr-01. 47 set commands generated. Template version: vyos_firewall_policies.j2 v1.3." | `ibn-deploy-{event}` |
| A4 — Planning | `observation`, `decision` | "What-If analysis: adding 200 users to VLAN 100 requires upstream aggregation switch port upgrade. Blast radius: 3 devices, 12 interfaces." | `ibn-whatif-{id}` |
| A5 — Orchestration | `progress`, `issue` | "SSH push to fw-hq-dmz-01 completed in 3.2s. Post-deploy verification: 47/47 rules confirmed. Rollback point saved." | `ibn-deploy-{event}` |
| A6 — Monitoring | `observation` | "gNMI subscription on fw-hq-usr-01 showing 12ms latency increase on VLAN 110 (voice). Not yet threshold-crossing. Watching." | `ibn-asbuilt-{snapshot}` |
| A7 — Assessment | `decision`, `insight` | "POR vs AS-BUILT comparison: 2 drift items detected. Rule R-140-GUEST has additional permit not in POR. Root cause: manual CLI edit outside loop." | `ibn-loop-inner` |
| A8 — Action | `decision` | "Severity: MEDIUM. Action: RE_ORCHESTRATE. Rationale: drift is a policy addition, not a removal — no service impact, but violates compliance. Initiating inner loop correction." | `ibn-loop-inner` |
| A9 — Abstraction | `insight` | "Aggregating 3 incidents from past 24h into single trend: VLAN 110 latency correlation with peak usage hours. Not escalation-worthy yet." | `ibn-loop-outer` |
| A10 — Reporting | `progress` | "Generated weekly compliance report for outer loop. Overall: 94% compliant. 3 open remediations, all LOW severity." | `ibn-loop-outer` |

### 10.5 Consolidation Lifecycle: From Notes to Knowledge

Live-Memory's LLM consolidation process maps to the closed-loop lifecycle as follows:

```
 Agent activity → live_note()        [Real-time, append-only, per-agent]
       │
       ▼
 Space accumulates notes              [S3: {space}/live/*.md with YAML front-matter]
       │
       ▼ (triggered by loop iteration, or note count threshold)
 bank_consolidate()                   [LLM reads notes + rules + prior synthesis]
       │                              [Produces surgical Markdown edits to bank files]
       ▼
 Bank files updated                   [S3: {space}/bank/*.md — structured knowledge]
       │                              [Processed notes deleted (append-only → consumed)]
       ▼
 _synthesis.md updated                [Residual context for next consolidation cycle]
       │
       ▼ (on model state promotion, or periodic schedule)
 graph_push()                         [Bank files → Graph-Memory via MCP Bridge]
       │                              [Ontology-driven entity/relation extraction]
       ▼
 Graph-Memory ingestion               [LLM extracts typed entities + relations]
       │                              [BGE-M3 embeddings stored in Qdrant]
       ▼
 Knowledge graph enriched             [Neo4j namespace: IBN_LIFECYCLE_*]
       │                              [Agents can query via question_answer()]
       ▼
 Feedback to agents                   [Graph-guided RAG answers historical queries]
                                      ["Last time VLAN 110 spiked, root cause was X"]
```

**Trigger points for consolidation** align with the model state transitions defined in §3.3:

- **What-If → Candidate (select):** Consolidate the what-if space to capture the rationale for the selected option. Archive or prune discarded what-if spaces.
- **Candidate → POR (approve):** Consolidate the candidate space to produce the approval audit trail. Push to Neo4j as governance evidence.
- **POR → Deployed (deploy):** Consolidate the deployment space after orchestration completes. Link bank files to the `DeploymentEvent` node.
- **Deployed → As-Built (verify):** Consolidate as-built observations after post-deployment verification. Capture any drift notes.
- **Inner loop iteration:** Consolidate `ibn-loop-inner` after each remediation cycle. This produces a running narrative of autonomous corrections.
- **Outer loop reporting:** Consolidate `ibn-loop-outer` before Agent 10 generates the human-facing report.

### 10.6 MCP Integration with the Event Bus

Live-Memory exposes 35 MCP tools and Graph-Memory exposes 30 MCP tools, both over Streamable HTTP. The event bus (§9.1) is extended to include memory-tier triggers alongside Neo4j CDC events:

| Trigger Source | Event | Consumer | Action |
|---------------|-------|----------|--------|
| Neo4j CDC | Model state transition (`WHAT_IF → CANDIDATE`) | Live-Memory consolidator | `bank_consolidate(space="ibn-whatif-{id}")` |
| Neo4j CDC | `ComplianceAssessment` created (verdict ≠ COMPLIANT) | Agent 8 + Live-Memory | Agent writes decision note; consolidation triggered on resolution |
| Live-Memory | Note count threshold exceeded in space | LLM consolidator | `bank_consolidate(space)` — prevents unbounded note accumulation |
| Live-Memory | Bank consolidated + model state is POR | Graph Bridge → Graph-Memory | `graph_push(space)` → `memory_ingest()` — bank files decomposed into knowledge graph entities |
| Graph-Memory | Ingestion complete for POR space | Agent 4 (Planning) | Historical knowledge now queryable; agent can use `question_answer()` for precedent-based planning |
| Agent (any) | Needs historical context before decision | Graph-Memory | `question_answer("What happened last time we changed VLAN 110 policy?")` — graph-guided RAG |
| Agent scheduler | Periodic (hourly) | All active Live-Memory spaces | Consolidation sweep to keep bank files current |
| Agent scheduler | Periodic (daily) | Graph-Memory | `storage_cleanup()` — remove orphaned S3 objects |

### 10.7 Security and Access Control

Both Live-Memory and Graph-Memory use token-based authentication that integrates with the security model defined in §12:

**Live-Memory tokens:**
- Each agent receives a **dedicated token** scoped to the spaces it is authorized to write. For example, Agent 3 (Policy→Config) can write to `ibn-candidate-*` and `ibn-deploy-*` spaces, but not to `ibn-loop-outer`.
- The **human operator** (outer loop) receives a read token for all spaces and a write token for `ibn-loop-outer` to annotate reporting bank files.
- **Admin tokens** for space lifecycle management (create/delete) are held only by the supervisor process that manages model state transitions.

**Graph-Memory tokens:**
- All agents receive a **read token** scoped to the `ibn-lifecycle` memory, enabling `question_answer()` queries for historical context.
- **Write tokens** for ingestion (`memory_ingest`) are held only by the Graph Bridge process that pushes Live-Memory bank files. Individual agents never write directly to Graph-Memory — this preserves the ontology-driven extraction guarantee.
- The **human operator** receives a read token plus access to the `/graph` web visualization interface for exploring the knowledge graph.

**Shared security posture:** Both services run behind Caddy WAF (TLS, OWASP CRS, rate limiting), consistent with the defense-in-depth approach in §12. Graph-Memory's Neo4j and Qdrant backends are on an internal Docker network, never exposed externally.

### 10.8 Deployment Topology

The three memory tiers are deployed alongside the closed-loop infrastructure:

```
 ┌───────────────────────────────────────────────────────────────────────────┐
 │  IBN CLOSED-LOOP INFRASTRUCTURE                                           │
 │                                                                           │
 │  TIER 1                TIER 2                 TIER 3                      │
 │  ┌─────────────┐       ┌──────────────────┐   ┌────────────────────────┐ │
 │  │ Neo4j       │       │ Live-Memory      │   │ Graph-Memory           │ │
 │  │ (SSoT)      │       │ (Working Memory) │   │ (Long-Term Knowledge)  │ │
 │  │             │       │                  │   │                        │ │
 │  │ Bolt 7687   │       │ Caddy WAF (:443) │   │ Caddy WAF (:8080)     │ │
 │  │ HTTP 7474   │       │ MCP Server(:8002)│   │ MCP Server (:8002)    │ │
 │  │             │       │ S3 backend       │   │ Neo4j (namespace)     │ │
 │  │ 9-layer     │       │                  │   │ Qdrant (BGE-M3)       │ │
 │  │ ontology    │       │  graph_push() ───┼──►│ S3 backend            │ │
 │  │ 5 model     │       │                  │   │                        │ │
 │  │ states      │       │                  │   │ IBN Lifecycle ontology │ │
 │  └──────┬──────┘       └────────┬─────────┘   └───────────┬────────────┘ │
 │         │                       │                          │              │
 │  ┌──────┴──────┐                │                          │              │
 │  │ NetLab      │                │                          │              │
 │  │ (Target)    │   ┌────────────┴──────────────────────────┘              │
 │  │ SSH/NETCONF │   │                                                     │
 │  └──────┬──────┘   │                                                     │
 │         │          │                                                     │
 │         └──────────┴──────────┬──────────────────────┐                   │
 │                               │                      │                   │
 │                      ┌────────┴────────┐             │                   │
 │                      │   Event Bus     │             │                   │
 │                      │ (Kafka / Redis) │             │                   │
 │                      └────────┬────────┘             │                   │
 │                               │                      │                   │
 │               ┌───────────────┴──────────────────┐   │                   │
 │               │        10 AI Agents              │   │                   │
 │               │                                  │   │                   │
 │               │  Neo4j R/W ──► Tier 1 (SSoT)    │   │                   │
 │               │  live_note() ──► Tier 2 (Working)│   │                   │
 │               │  question_answer() ◄── Tier 3    │◄──┘                   │
 │               │  (Long-Term RAG)                 │                       │
 │               └──────────────────────────────────┘                       │
 └───────────────────────────────────────────────────────────────────────────┘
```

**Resource footprint:**

| Component | vCPU | RAM | Storage | Notes |
|-----------|------|-----|---------|-------|
| Neo4j (Tier 1 SSoT) | 2 | 4 GB | SSD | Already in baseline architecture |
| Live-Memory (Tier 2) | 1 | 1–2 GB | S3 | Lightweight; no database dependency |
| Graph-Memory (Tier 3) | 2 | 4 GB | SSD + S3 | Neo4j namespace + Qdrant vectors |
| Qdrant (Tier 3) | 1 | 2 GB | SSD | BGE-M3 embeddings (1024-dim) |

Graph-Memory's Neo4j backend can **share the same Neo4j instance** as the SSoT, since namespace-prefixed labels (`IBN_LIFECYCLE_Entity`, `IBN_LIFECYCLE_Document`) provide complete isolation from the 9-layer ontology labels. This eliminates the need for a second Neo4j deployment. Qdrant is the only net-new infrastructure component.

---

## 11. Lifecycle State Transitions Driven by the Loop

The Neo4j ontology defines a lifecycle state machine for all entities (Section 5 of the ontology document). The closed loop drives these transitions:

```
                    Ingestion Agent
                         │
    ┌────────────────────▼────────────────────┐
    │              DESIGNED                    │
    │  (Intent created, policies defined)      │
    └────────────────────┬────────────────────┘
                         │ Translation + Rendering complete
                         ▼
    ┌────────────────────────────────────────┐
    │              PLANNED                    │
    │  (Config generated, migration planned)  │
    └────────────────────┬───────────────────┘
                         │ Orchestration Agent deploys
                         ▼
    ┌────────────────────────────────────────┐
    │             PROVISIONED                 │
    │  (Config pushed, awaiting verification) │
    └────────────────────┬───────────────────┘
                         │ Post-deploy verification passes
                         ▼
    ┌────────────────────────────────────────┐
    │              ACTIVE                     │
    │  (Running, monitored by assurance loop) │
    └──────┬─────────────┬───────────────────┘
           │             │
    drift detected    operator retracts intent
           │             │
           ▼             ▼
    ┌──────────────┐  ┌──────────────────────┐
    │  DEGRADED    │  │   DECOMMISSIONING    │
    │  (inner loop │  │  (graceful removal)   │
    │   remediates)│  │                       │
    └──────┬───────┘  └──────────┬───────────┘
           │                     │
    remediation succeeds    cleanup complete
           │                     │
           ▼                     ▼
    ┌──────────────┐  ┌──────────────────────┐
    │   ACTIVE     │  │   DECOMMISSIONED     │
    │  (restored)  │  │  (archived in Neo4j) │
    └──────────────┘  └──────────────────────┘
```

---

## 12. Security and Supervision Model

Per RFC 9315 §9 (Security Considerations), the closed loop must implement safeguards:

### 12.1 Intent Verification

Every intent passes through validation before entering the fulfillment pipeline. The Ingestion Agent checks: syntactic correctness of the intent statement; conflict with existing intents (Neo4j query across all active intents); feasibility given current network capabilities (Neo4j query against infrastructure inventory); authorization of the intent author (RBAC).

### 12.2 Autonomy Boundaries

The inner loop operates within defined boundaries. It **can** re-push a configuration that matches the SSoT desired state, restart a protocol process, or adjust a non-critical parameter. It **cannot** modify the declared intent, change the network topology (add/remove devices), override a human-approved policy, or take actions on entities in `DECOMMISSIONING` state.

### 12.3 Rollback and Safeguards

Because Neo4j preserves full version history (ontology Principle 3 — Immutability Through Versioning), any configuration or state can be rolled back by traversing the `PRECEDED_BY` relationship chain and redeploying the previous version. The Compliance Action Agent can trigger rollback autonomously for Low/Medium severity, or hold for human approval for High/Critical.

### 12.4 Audit Trail

Every action taken by every agent is recorded in Neo4j as a node with a timestamp, the agent identifier, the input that triggered the action, and the output produced. This creates a complete, traversable audit trail from business intent to device configuration to observed compliance.

---

## 13. Schema Evolution and Governance

MALT §10 describes the challenges of evolving a topology schema that is consumed by hundreds of software systems. Our Neo4j ontology will face the same challenge as the closed loop matures. Following MALT's hard-won lessons, we adopt the following governance principles.

### 13.1 Ontology Versioning

The Neo4j ontology schema is versioned using semantic versioning (MAJOR.MINOR.PATCH). Each version is recorded as an `(:OntologyVersion)` node in the graph. All model instances reference the ontology version under which they were created.

**Minor versions** add new node labels, relationship types, or optional properties. They are backward-compatible: agents built for v1.2 can safely read models produced under v1.3 (they simply ignore new elements). **Major versions** change the meaning of existing elements, remove labels, or alter relationship cardinality. They require coordinated migration of all agents.

### 13.2 Profile System

Following MALT §3.5, we introduce **profiles** to specialize the ontology for different network types without fragmenting the schema:

- **Campus profile:** Asserts that every site has at least one `FirewallPair`, that population VLANs exist in the 100–160 range, and that a transit VLAN 300 connects the USF to the DMZFW. This is the primary profile for the current HLD.
- **Branch profile:** Asserts a collapsed two-tier topology with a single active-passive firewall pair. Relaxes the dual-firewall constraint.
- **Lab profile:** The NetLab environment profile. Asserts VyOS as the firewall platform; relaxes HA constraints for single-node testing.

Profiles are machine-checkable constraints expressed as Cypher validation queries. The Planning Agent (Agent 4) validates every Candidate model against the applicable profile before promotion to POR.

### 13.3 Stability Rules and Deprecation

To prevent schema churn (MALT §10 — "schema evolution has been much harder than expected"), we adopt:

- **Stability window:** No breaking changes to an ontology major version for at least 6 months after release. Agents can rely on the schema being stable during this window.
- **Deprecation protocol:** Before removing a node label, relationship type, or property, it is marked as `deprecated` in the ontology metadata for one full major version cycle. Agents emit warnings when they encounter deprecated elements.
- **Canned queries:** Following MALT §6.1, common access patterns are encapsulated as **named Cypher queries** (stored procedures in Neo4j). Agents use these rather than writing raw Cypher, insulating them from schema changes. When the schema evolves, only the canned queries need to be updated.

### 13.4 Schema Review Board

Following MALT §9's Meta-lesson, a **Schema Review Board** (SRB) — composed of the network architect, the lead agent developer, and an ontology expert — must approve all changes to the Neo4j ontology schema. The SRB maintains a written style guide for naming conventions (`camelCase` for properties, `UPPER_SNAKE_CASE` for relationships) and evaluates proposals against two tests (MALT §9.1):

- **Orthogonality test:** Do the use cases for this new entity share the same relationship structure? If not, create separate entities rather than overloading one.
- **Attribute overlap test:** Do the use cases share the same attributes? If not, prefer multiple specific entities over one general entity with subtype attributes.

---

## 14. Implementation Roadmap

### Phase 1 — Foundation (Months 1–3)

Deploy Neo4j with the 9-layer ontology schema. Deploy Live-Memory MCP server alongside Neo4j with S3 backend; create foundational spaces (`ibn-loop-inner`, `ibn-loop-outer`) and define their consolidation rules. Implement Agent 1 (Ingestion) with structured template input (not yet NLP). Implement Agent 5 (Orchestration) with basic NetLab `topology.yml` generation and SSH config push. Implement Agent 6 (Monitoring) with CLI/SNMP polling from NetLab devices. Integrate `live_note()` calls into all Phase 1 agents for operational context capture. Validate the basic fulfillment path: Intent → SSoT → Config → NetLab → Observed State → SSoT.

### Phase 2 — Inner Loop (Months 3–6)

Implement Agent 7 (Compliance Assessment) — desired vs. observed comparison. Implement Agent 8 (Compliance Action) with auto-remediation for Low severity. Implement Agent 3 (Policy→Config) to generate multi-vendor configs. Close the inner loop: detect drift → re-orchestrate → verify. Validate autonomous self-correction on NetLab. Deploy Graph-Memory with Qdrant; create the `ibn-lifecycle` memory with the IBN Network Lifecycle ontology (§10.2.2). Validate the Live-Memory → Graph-Memory bridge pipeline on inner loop remediation narratives.

### Phase 3 — Translation Intelligence (Months 6–9)

Implement Agent 2 (Intent→Policy) with full policy decomposition. Implement Agent 4 (Planning/Optimization) with blast radius analysis and migration planning. Upgrade Agent 1 (Ingestion) with NLP capabilities for natural language intent. Implement conflict detection and resolution across multiple active intents.

### Phase 4 — Outer Loop and Reporting (Months 9–12)

Implement Agent 9 (Abstraction) and Agent 10 (Reporting). Build compliance dashboards and natural-language status reports. Enable the full outer loop: human reviews reports → modifies intent → system adapts. Implement intent retirement and decommission workflows. Activate Live-Memory Graph Bridge to push consolidated bank files into Graph-Memory for long-term knowledge persistence. Implement automated consolidation triggers on model state transitions (§10.5). Enable agents to query Graph-Memory via `question_answer()` for historical precedent-based decision making. Expose the Graph-Memory `/graph` web interface for human operator knowledge exploration.

### Phase 5 — Learning and Optimization (Months 12+)

Enable Agent 4 learning capabilities — leverage Graph-Memory's knowledge graph to analyze historical compliance data, identify recurring drift patterns, and optimize rendering. Implement predictive drift detection (forecast violations before they occur) using Graph-Memory's graph-guided RAG to surface correlated historical incidents. Expand NetLab coverage with additional device types and protocols. Benchmark loop cycle times and optimize for sub-minute detection. Evolve the IBN Network Lifecycle ontology based on accumulated knowledge graph structure.

---

## 15. References

| Reference | Title |
|-----------|-------|
| RFC 9315 | Intent-Based Networking — Concepts and Definitions (IRTF NMRG, October 2022) |
| Companion HLD | Enterprise Campus Network Architecture — High-Level Design v1.0 |
| Companion ARD | Cisco SD-Access / IBN Architecture Reference Design v1.0 |
| Companion Ontology | Neo4j Ontology — Network Architecture Lifecycle v1.0 |
| Companion Feasibility | NetLab Feasibility Analysis — Enterprise Campus Network |
| netlab.tools | netlab documentation — https://netlab.tools |
| Neo4j | Neo4j Graph Database — https://neo4j.com |
| RFC 7950 | The YANG 1.1 Data Modeling Language |
| RFC 8345 | A YANG Data Model for Network Topologies |
| Mogul et al. (NSDI '20) | Experiences with Modeling Network Topologies at Multiple Levels of Abstraction — Google MALT system |
| ITIL v4 | ITIL 4 Foundation — IT Service Management |
| Cloud-Temple Live-Memory | Live-Memory MCP Server — Working Memory for Collaborative AI Agents (Apache 2.0) — https://github.com/Cloud-Temple/live-memory |
| Cloud-Temple Graph-Memory | Graph-Memory MCP Server — Knowledge Graph as a Service for AI Agents (Apache 2.0) — https://github.com/Cloud-Temple/graph-memory |
| Tran et al. (arXiv:2501.06322) | A Survey on Multi-Agent LLM Systems: Techniques and Business Perspectives — Multi-agent shared memory framework |
