# Cisco SD-Access / Intent-Based Networking — Architecture Reference Design (ARD)
## Synthesized Reference Document

**Framework:** Cisco Software-Defined Access (SD-Access) / Intent-Based Networking (IBN)
**Document Type:** Architecture Reference Design
**Domain:** Enterprise Campus IBN Closed-Loop Architecture
**Source Basis:** Cisco SD-Access Solution Design Guide (CVD) + RFC 9315 (IBN Closed-Loop)
**Version:** 1.0 (synthesized March 2026)
**Classification:** Reference Use

---

## INDEX

1. [IBN Design Philosophy](#1-ibn-design-philosophy)
2. [SD-Access Architecture Overview](#2-sd-access-architecture-overview)
3. [Fabric Architecture](#3-fabric-architecture)
4. [Policy and Segmentation Model](#4-policy-and-segmentation-model)
5. [IBN Closed-Loop Architecture (RFC 9315)](#5-ibn-closed-loop-architecture-rfc-9315)
6. [Management and Control Plane](#6-management-and-control-plane)
7. [Integration with Traditional Campus (HLD Mapping)](#7-integration-with-traditional-campus-hld-mapping)
8. [Architecture Requirements (Quantitative Criteria)](#8-architecture-requirements-quantitative-criteria)
9. [Compliance Mapping to HLD](#9-compliance-mapping-to-hld)
10. [References](#10-references)

---

## 1. IBN Design Philosophy

### 1.1 From Configuration-Driven to Intent-Driven

Traditional campus networks (as documented in the companion HLD) are **configuration-driven**: operators translate business requirements manually into device-level CLI configurations. This introduces human error, inconsistency across sites, and slow response to change.

Intent-Based Networking (IBN) inverts this model. The operator specifies **what** the network must do (the intent), and the system translates that intent into device configurations, monitors compliance, and automatically corrects deviations. This is the **closed-loop** model defined in RFC 9315.

### 1.2 RFC 9315 — Foundational Definitions

RFC 9315 (IRTF NMRG, October 2022) defines the normative vocabulary and closed-loop model for IBN:

| Term | RFC 9315 Definition |
|------|---------------------|
| **Intent** | A high-level, declarative specification of a desired outcome, expressed in business or operational terms, without prescribing implementation details |
| **Intent-Based System (IBS)** | A system that ingests, translates, orchestrates, and assures intents throughout their lifecycle |
| **Intent Lifecycle** | Ingestion → Translation → Orchestration → Assurance → (Re-ingestion on deviation) |
| **Intent Assurance** | The process of monitoring network state, assessing compliance with declared intents, and triggering corrective actions when deviations are detected |
| **Closed Loop** | The feedback mechanism that connects assurance outputs back to orchestration inputs, enabling autonomous self-correction |
| **SSoT (Single Source of Truth)** | The authoritative repository of current and desired network state, against which compliance is measured |
| **IBA (Intent-Based Analytics)** | Analytics functions that interpret telemetry data in the context of declared intents to produce actionable compliance assessments |

### 1.3 IBN vs. SDN vs. Traditional Automation

| Characteristic | Traditional CLI | SDN / OpenFlow | IBN (RFC 9315) |
|---------------|----------------|---------------|----------------|
| Operator input | Device commands | Flow rules | Business intent |
| Abstraction level | Device | Network-wide | Business outcome |
| Change management | Manual, per-device | Programmatic, per-flow | Intent lifecycle |
| Compliance assurance | Manual audit | State snapshots | Continuous closed-loop |
| Self-correction | Human operator | Limited | Autonomous (bounded) |

---

## 2. SD-Access Architecture Overview

### 2.1 What is SD-Access

Cisco Software-Defined Access (SD-Access) is Cisco's IBN implementation for campus networks. It provides:

- **Policy-based network segmentation** using Virtual Networks (VNs) and Scalable Group Tags (SGTs)
- **Automated fabric provisioning** via Cisco DNA Center (now Cisco Catalyst Center)
- **Continuous assurance** through AI/ML-driven analytics (Cisco AI Endpoint Analytics, Assurance)
- **Closed-loop automation** connecting assurance outputs to orchestration actions

SD-Access is composed of three integrated planes: **Data Plane** (VXLAN fabric), **Control Plane** (LISP), and **Policy Plane** (TrustSec SGT).

### 2.2 Relationship to Traditional Campus Architecture

SD-Access does not replace the physical topology described in the companion HLD. It is an **overlay** that operates on top of the existing physical underlay:

```
┌─────────────────────────────────────────────────────────────┐
│                    SD-ACCESS OVERLAY                         │
│  ┌──────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │ Policy Plane │  │Control Plane│  │   Data Plane       │  │
│  │  (TrustSec/  │  │   (LISP)    │  │  (VXLAN/EVPN)     │  │
│  │    SGT)      │  │             │  │                    │  │
│  └──────────────┘  └─────────────┘  └────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                  PHYSICAL UNDERLAY                           │
│  [Access Layer] → [Distribution Layer] → [Core/Firewall]    │
│  (as defined in companion HLD: RSTP, 802.1Q, IP routing)    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Fabric Architecture

### 3.1 SD-Access Fabric Roles

| Role | Function | Physical Mapping |
|------|----------|-----------------|
| **Fabric Edge Node** | First point of SD-Access policy enforcement; connects endpoints; maps identity to SGT | Access switches |
| **Fabric Border Node** | Connects the fabric to external networks (internet edge, data center, WAN) | Core/firewall-adjacent routers or the firewall itself |
| **Fabric Control Plane Node** | Hosts the LISP Map Server/Resolver; tracks endpoint location and identity | Dedicated or shared device (DNA Center can use this) |
| **Intermediate Nodes** | Forward VXLAN-encapsulated traffic; no fabric policy awareness needed | Distribution switches |
| **DNA Center (Catalyst Center)** | Intent management, provisioning orchestration, assurance, and analytics | Management plane |

### 3.2 Data Plane: VXLAN

SD-Access uses **VXLAN (RFC 7348)** as the data plane encapsulation:

- Endpoints are encapsulated in VXLAN frames at the Fabric Edge Node
- VXLAN Network Identifier (VNI) maps to a Virtual Network (VN) — the macro-segmentation unit
- SGT is embedded in the VXLAN header (Group Policy Option) for micro-segmentation
- The underlay only sees IP/UDP traffic — no VLAN trunks between fabric nodes

### 3.3 Control Plane: LISP

SD-Access uses **LISP (Locator/ID Separation Protocol, RFC 6830)** for endpoint mobility and identity tracking:

- Endpoint Identifiers (EIDs) = IP addresses of endpoints
- Routing Locators (RLOCs) = IP addresses of Fabric Edge Nodes
- The LISP Map Server tracks which Edge Node currently hosts each EID
- Enables seamless endpoint mobility without spanning tree changes or VLAN extension

### 3.4 Policy Plane: TrustSec SGT

**Security Group Tags (SGTs)** provide micro-segmentation independent of IP addressing or VLAN:

- Each endpoint is assigned an SGT at authentication (via ISE + 802.1X)
- SGT is carried in the VXLAN header across the fabric
- **Security Group ACLs (SGACLs)** at Fabric Border Nodes or enforcement points define permitted SGT-to-SGT communications
- Policy changes are applied centrally in DNA Center and pushed automatically — no per-device ACL management

---

## 4. Policy and Segmentation Model

### 4.1 Two-Level Segmentation Architecture

SD-Access implements a two-level segmentation hierarchy that maps directly to the companion HLD's VLAN-based model:

| Level | Mechanism | Granularity | HLD Equivalent |
|-------|-----------|-------------|---------------|
| **Macro-segmentation** | Virtual Networks (VN) / VRF | Group of users/devices | VLAN groups (e.g., Employee, Guest) |
| **Micro-segmentation** | SGT / SGACL | Individual user or device identity | Firewall inter-VLAN policy |

### 4.2 Virtual Network (VN) Model

VNs replace traditional VLANs as the primary isolation boundary. Recommended VN structure for campus:

| Virtual Network | Populations Included | Internet Access | Internal Access |
|----------------|---------------------|-----------------|----------------|
| **Employee VN** | Employees, trusted contractors | Yes (inspected) | Yes (policy-controlled) |
| **Guest VN** | Visitors, untrusted | Yes (direct) | No |
| **IoT VN** | Building systems, cameras, printers | No | Restricted (controllers only) |
| **Voice VN** | IP phones, video conferencing | No | Voice infra only |
| **Management VN** | OOB management devices | No | Jump host only |

### 4.3 SGT Assignment Model

SGTs are assigned dynamically by ISE based on authentication outcome:

| SGT Name | SGT Value (example) | Assignment Criteria |
|----------|--------------------|--------------------|
| Employee | 10 | AD group membership (full employee) |
| Contractor | 20 | AD group membership (contractor OU) |
| Guest | 30 | Guest portal authentication |
| Printer | 40 | MAB + device profiling |
| Camera | 50 | MAB + device profiling (IP camera OUI) |
| Unknown | 0 | Failed authentication or profiling |

### 4.4 SGT Policy Matrix (SGACL)

The SGT matrix defines permitted communications between groups. Example:

| Source SGT → Dest SGT | Employee | Contractor | Guest | Printer | Camera | Management |
|----------------------|----------|-----------|-------|---------|--------|-----------|
| **Employee** | Permit | Deny | Deny | Permit (print) | Deny | Deny |
| **Contractor** | Deny | Deny | Deny | Permit (print) | Deny | Deny |
| **Guest** | Deny | Deny | Deny | Deny | Deny | Deny |
| **Printer** | Deny | Deny | Deny | Deny | Deny | Deny |
| **Camera** | Deny | Deny | Deny | Deny | Permit (NVR) | Deny |
| **Management** | Deny | Deny | Deny | Deny | Deny | Permit |

---

## 5. IBN Closed-Loop Architecture (RFC 9315)

### 5.1 Closed-Loop Functional Blocks

RFC 9315 defines the following functional blocks of an Intent-Based System:

```
                    ┌─────────────────────────────────────┐
                    │         INTENT PLANE                │
                    │  ┌──────────────────────────────┐   │
 Human Operator ───►│  │    Intent Ingestion          │   │
 (Natural Language, │  │  (GUI / NLP / API / Template)│   │
  API, Template)    │  └──────────────┬───────────────┘   │
                    │                 │                    │
                    │  ┌──────────────▼───────────────┐   │
                    │  │    Intent Translation        │   │
                    │  │  (Policy Model / SSoT Update)│   │
                    │  └──────────────┬───────────────┘   │
                    │                 │                    │
                    │  ┌──────────────▼───────────────┐   │
                    │  │   Intent Orchestration       │   │
                    │  │  (Config Generation, Push,   │   │
                    │  │   Verification)              │   │
                    │  └──────────────┬───────────────┘   │
                    └─────────────────┼───────────────────┘
                                      │ (Network State)
                    ┌─────────────────▼───────────────────┐
                    │         ASSURANCE PLANE              │
                    │  ┌──────────────────────────────┐   │
                    │  │   Intent Monitoring          │   │
                    │  │  (Telemetry: gRPC, NETCONF,  │   │
                    │  │   SNMP, syslog, flow data)   │   │
                    │  └──────────────┬───────────────┘   │
                    │                 │                    │
                    │  ┌──────────────▼───────────────┐   │
                    │  │  Compliance Assessment (IBA) │   │
                    │  │  (Compare observed state to  │   │
                    │  │   SSoT / intent definition)  │   │
                    │  └──────────────┬───────────────┘   │
                    │                 │                    │
                    │  ┌──────────────▼───────────────┐   │
                    │  │   Compliance Actions         │   │
                    │  │  (Alert / Remediate / Adapt) │   │
                    │  └──────────────┬───────────────┘   │
                    └─────────────────┼───────────────────┘
                                      │ (Closed-Loop Feedback)
                                      └──► Intent Orchestration
```

### 5.2 Intent Ingestion

The ingestion interface through which human operators or northbound systems express desired outcomes:

| Ingestion Method | Description | Maturity |
|-----------------|-------------|---------|
| GUI / Workflow Wizard | Step-by-step UI in DNA Center | Production |
| REST API | Programmatic intent submission | Production |
| Template-based | Pre-defined intent templates for common use cases | Production |
| Natural Language (NLP) | Free-text intent expression, parsed by AI/LLM | Emerging |

### 5.3 Intent Translation

The process of converting a declared intent into a structured policy model:

- Input: high-level intent ("Employees must not communicate with Guest devices")
- Output: SGT policy matrix entry + SGACL definition + VN routing policy
- The translation result is written to the **SSoT** (DNA Center intent store)
- Validation occurs at this stage: the system checks for conflicting intents

### 5.4 Intent Orchestration

The process of converting translated policy into device configurations:

- DNA Center generates device-specific configurations (IOS-XE, NX-OS, etc.)
- Configurations are deployed via **NETCONF/YANG** or **gRPC** (telemetry model-driven)
- Deployment is transactional: all-or-nothing per intent scope
- Post-deployment verification confirms the intended state was achieved

### 5.5 Intent Assurance (Closed Loop)

The continuous monitoring and compliance assessment process:

**Monitoring sources:**
- **Streaming telemetry** (gRPC/gNMI from IOS-XE 16.x+): interface stats, BGP state, hardware tables
- **NETCONF** operational data: current running configuration snapshot
- **NetFlow / IPFIX**: traffic matrix, application visibility
- **Syslog / SNMP traps**: event-driven state changes
- **Cisco AI Endpoint Analytics**: device profiling, behavioral baseline

**Compliance assessment:**
- IBA compares observed telemetry against the SSoT intent definition
- Deviations are classified: **Compliant / Non-compliant / Degraded / Unknown**
- Root cause analysis attempts to identify the source of deviation

**Compliance actions (closed-loop response):**
| Severity | Action | Autonomy Level |
|---------|--------|---------------|
| Information | Alert to NOC dashboard | Automated |
| Minor deviation | Automated remediation (re-push config) | Automated (with audit log) |
| Major deviation | Alert + hold for human approval | Human-in-the-loop |
| Critical / unknown | Alert + escalate + optional rollback | Human-in-the-loop |

### 5.6 SSoT (Single Source of Truth)

The SSoT is the authoritative record of:
- All declared intents and their current lifecycle state
- The translated policy model derived from each intent
- The current verified network state (post-assurance)
- Historical compliance records and remediation actions

In the SD-Access implementation, the SSoT is hosted in **Cisco DNA Center's intent store** (backed by Elasticsearch and a graph database). For multi-vendor or RFC 9315-compliant implementations, the SSoT may be an external system (e.g., a YANG-modeled configuration database).

---

## 6. Management and Control Plane

### 6.1 DNA Center (Catalyst Center) Functions

| Function | Description |
|---------|-------------|
| **Design** | Define sites, buildings, floors; IP address pools; DNS/DHCP servers |
| **Policy** | Define Virtual Networks, SGTs, SGACL matrix, QoS policy |
| **Provision** | Onboard devices, assign fabric roles, push configurations |
| **Assurance** | Monitor health scores, detect issues, root cause analysis |
| **Platform** | REST API, integration with ITSM (ServiceNow), SIEM, IPAM |

### 6.2 Cisco ISE (Identity Services Engine)

ISE provides the policy and identity services that underpin SD-Access:

- **802.1X authentication** (EAP-TLS, PEAP-MSCHAPv2) for wired and wireless
- **MAB (MAC Authentication Bypass)** for non-802.1X devices
- **Device Profiling**: classifies endpoints by OUI, DHCP fingerprint, HTTP User-Agent
- **SGT assignment**: dynamically assigns SGT based on authentication result + policy
- **Guest lifecycle management**: self-service portal, sponsor approval, time-limited access
- **pxGrid**: real-time sharing of context (SGT, endpoint data) with DNA Center and third-party systems

### 6.3 Telemetry Infrastructure

| Protocol | Use Case | Standards |
|---------|---------|-----------|
| gRPC / gNMI | Streaming operational data from IOS-XE/NX-OS | OpenConfig, YANG |
| NETCONF | Configuration management and state retrieval | RFC 6241, RFC 6242 |
| RESTCONF | HTTP-based NETCONF alternative | RFC 8040 |
| NetFlow v9 / IPFIX | Traffic flow visibility | RFC 3954, RFC 7011 |
| SNMP v3 | Legacy device monitoring | RFC 3410 |
| Syslog | Event logging | RFC 5424 |

---

## 7. Integration with Traditional Campus (HLD Mapping)

### 7.1 Migration Approach

SD-Access can be deployed as a **greenfield** (new fabric from scratch) or **brownfield** (overlaid on existing campus) implementation. The companion HLD describes a brownfield-compatible traditional campus that would be the underlay for SD-Access.

**Brownfield integration steps:**

1. Deploy DNA Center and ISE (or integrate existing ISE)
2. Onboard existing campus switches as SD-Access fabric nodes
3. Migrate VLANs to Virtual Networks (one-to-one initial mapping)
4. Enable 802.1X on access ports (already required by SAFE ARD)
5. Deploy SGT assignments via ISE policy (replaces static VLAN-based policy)
6. Enable SGACL enforcement at border nodes
7. Enable assurance and validate closed-loop operation

### 7.2 HLD to SD-Access Component Mapping

| HLD Component | SD-Access Equivalent |
|--------------|---------------------|
| Access switch (Layer 2) | Fabric Edge Node |
| Distribution switch | Intermediate Node (underlay forwarding) |
| Firewall (default gateway) | Fabric Border Node (external connectivity) |
| VLAN | Virtual Network (VN) |
| Inter-VLAN firewall policy | SGT / SGACL + VN routing policy |
| 802.1Q trunk | VXLAN-encapsulated underlay |
| RSTP | ISIS-IS (underlay routing) or OSPF |
| Static IP assignment | LISP-tracked EID + DNA Center IP pool |
| Manual firewall rule | Intent-translated SGACL |
| Periodic audit | Continuous assurance (IBA) |

---

## 8. Architecture Requirements (Quantitative Criteria)

### 8.1 IBN Closed-Loop Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| IBN-01 | Intent ingestion must be available via REST API | 100% of intents programmatically accessible |
| IBN-02 | Intent translation must complete without operator intervention | ≤ 60 seconds for standard intent types |
| IBN-03 | Intent orchestration (config push) must be transactional | Rollback on failure; no partial deployment |
| IBN-04 | Telemetry collection interval (streaming) | ≤ 30 seconds for critical path metrics |
| IBN-05 | Compliance assessment cycle time | ≤ 5 minutes from deviation to detection |
| IBN-06 | Automated remediation for minor deviations | ≤ 10 minutes from detection to correction |
| IBN-07 | SSoT must maintain full intent history | ≥ 12 months retention |
| IBN-08 | All remediation actions must be audit-logged | 100% of automated and manual actions |

### 8.2 Fabric Performance Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| FAB-01 | VXLAN encapsulation overhead | ≤ 50 bytes per frame (MTU must be ≥ 1550 bytes on underlay) |
| FAB-02 | Endpoint mobility re-registration time (LISP) | ≤ 2 seconds |
| FAB-03 | SGT policy enforcement latency | ≤ 1 ms additional per hop |
| FAB-04 | Fabric node failover (dual-homed edge) | ≤ 1 second |

### 8.3 Security and Policy Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| IPOL-01 | All endpoints must receive an SGT at authentication | 100% (no SGT 0 / unknown for production endpoints) |
| IPOL-02 | SGT matrix must be reviewed and validated | Quarterly review cycle |
| IPOL-03 | All policy changes must flow through intent lifecycle | No out-of-band device-level policy changes |
| IPOL-04 | Guest VN must have zero routes to internal VNs | Verified by assurance continuously |
| IPOL-05 | ISE must be deployed in HA pair | Active-passive minimum; active-active preferred |

### 8.4 Scalability Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| ISCAL-01 | Maximum SGTs per deployment | ≤ 65,535 (theoretical); ≤ 256 recommended operational limit |
| ISCAL-02 | Maximum endpoints per fabric | Per DNA Center sizing guide (≥ 25,000 for enterprise appliance) |
| ISCAL-03 | New intent types must be deployable without fabric redesign | Additive only; no service impact |

---

## 9. Compliance Mapping to HLD

### 9.1 HLD to IBN ARD Gap Analysis

| HLD Section | IBN ARD Requirements | Status |
|-------------|---------------------|--------|
| Architecture Overview | IBN-03, IPOL-03 | ❌ HLD is configuration-driven; no intent lifecycle |
| Site Architecture Types | FAB-04, ISCAL-02 | ⚠️ Physical topology compatible; IBN overlay not specified |
| Network Layer Architecture | FAB-01 | ⚠️ MTU not specified in HLD (VXLAN requires ≥ 1550 bytes underlay) |
| Switching Infrastructure | FAB-02, FAB-03 | ⚠️ RSTP present; LISP/VXLAN control plane not mentioned |
| Port Configuration Standards | IPOL-01 | ⚠️ 802.1X mentioned implicitly; SGT assignment not specified |
| Population Types / Segmentation | IPOL-01..04 | ⚠️ VLAN-based (macro only); SGT micro-segmentation absent |
| Firewall Architecture | IPOL-03 | ❌ Policy managed manually; no intent translation |
| Management Networks | IBN-07, IBN-08 | ⚠️ OOB present; no mention of intent audit trail |
| **IBN Closed-Loop Functions** | IBN-01..08 | ❌ Entirely absent from HLD — expected (HLD is pre-IBN) |

### 9.2 Summary: HLD as IBN Underlay

The companion HLD is **well-suited as the physical underlay** for an SD-Access IBN deployment. Its three-tier physical architecture, VLAN segmentation, firewall zoning, and OOB management are all compatible with and complementary to the SD-Access overlay.

The HLD does **not address** the IBN functional layer (intent ingestion, translation, orchestration, assurance, closed-loop). This is expected and appropriate — the HLD is a physical/logical infrastructure document. The IBN layer should be addressed in a separate **IBN Platform Design** document that references both this ARD and the companion SAFE ARD.

---

## 10. References

- Cisco SD-Access Solution Design Guide (CVD): https://www.cisco.com/c/en/us/td/docs/solutions/CVD/Campus/cisco-sda-design-guide.html
- Cisco Campus LAN and WLAN Design Guide (CVD): https://www.cisco.com/c/en/us/td/docs/solutions/CVD/Campus/cisco-campus-lan-wlan-design-guide.html
- Cisco DNA Center (Catalyst Center) Documentation: https://developer.cisco.com/docs/dna-center/
- Cisco TrustSec Design Guide: https://www.cisco.com/c/en/us/solutions/enterprise-networks/trustsec/index.html
- RFC 9315 — Intent-Based Networking (IBN) — IRTF NMRG, October 2022
- RFC 7348 — Virtual eXtensible Local Area Network (VXLAN)
- RFC 6830 — The Locator/ID Separation Protocol (LISP)
- RFC 6241 — Network Configuration Protocol (NETCONF)
- RFC 8040 — RESTCONF Protocol
- RFC 7011 — Specification of the IP Flow Information Export (IPFIX) Protocol
- OpenConfig: https://www.openconfig.net/
- YANG Data Modeling Language — RFC 7950
