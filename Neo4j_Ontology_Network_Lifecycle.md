# Neo4j Ontology — Network Architecture Lifecycle
## Enterprise Campus Network / IBN Closed-Loop

**Version:** 1.0
**Date:** March 2026
**Scope:** Full lifecycle of an enterprise campus network HLD — from design through deployment, operations, troubleshooting, upgrade, and decommissioning.
**Graph Database:** Neo4j (property graph model)
**Reference Frameworks:** RFC 9315 (IBN), Cisco SAFE, TOGAF, ITIL v4
**Status:** Theoretical — design-only, no live instance

---

## INDEX

1. [Design Philosophy](#1-design-philosophy)
2. [Ontology Layers](#2-ontology-layers)
3. [Node Labels](#3-node-labels)
4. [Relationship Types](#4-relationship-types)
5. [Lifecycle State Machine](#5-lifecycle-state-machine)
6. [Lifecycle Phase Coverage](#6-lifecycle-phase-coverage)
7. [Key Query Patterns](#7-key-query-patterns)
8. [Graph Model Diagram](#8-graph-model-diagram)

---

## 1. Design Philosophy

### 1.1 Why a Graph Model for Network Lifecycle?

Network infrastructure is inherently relational. A device is connected to other devices, carries VLANs, implements policies, belongs to sites, participates in topology layers, has operational state, generates incidents, and evolves through versions. Traditional relational databases and YANG/XML configuration stores capture the *current state* of individual elements but struggle to represent:

- **Dependency chains:** "What services are impacted if this interface fails?"
- **Version lineage:** "What changed between architecture v1.2 and v1.3, and why?"
- **Intent traceability:** "Which physical device implements which declared intent?"
- **Blast radius analysis:** "Which VLANs, segments, and users are affected by this incident?"
- **Zero-downtime upgrade planning:** "What is the safe migration path from topology A to topology B?"

A property graph natively models all of these as first-class traversal operations.

### 1.2 Core Design Principles

**Principle 1 — Lifecycle as a First-Class Citizen**
Every node in the graph carries a `lifecycleState` property and is connected to `LifecyclePhase` and `LifecycleTransition` nodes. The graph is the authoritative record of the full lifecycle history, not just the current state.

**Principle 2 — Multi-Layer Representation**
The ontology models nine distinct layers (physical, logical, topology, design, policy, configuration, change, operations, people). Relationships cross layers to enable traversal from intent to device to incident.

**Principle 3 — Immutability Through Versioning**
Design documents, configurations, and policies are never overwritten — they are versioned. New versions create new nodes connected by `PRECEDED_BY` relationships. This enables full auditability and rollback.

**Principle 4 — RFC 9315 Intent Traceability**
Every policy and configuration must be traceable back to a declared `Intent`, which is in turn traceable to a `BusinessUseCase`. This implements the RFC 9315 closed-loop accountability model.

**Principle 5 — Temporal Accuracy**
All relationships carry `since` and optionally `until` timestamp properties. This allows the graph to answer "what was the network state at time T?" — essential for post-incident analysis.

**Principle 6 — Zero-Downtime Upgrade Support**
Architecture upgrades are modelled as `ArchitectureVersion` nodes with `MigrationPlan` relationships. Devices are connected by `REPLACED_BY` relationships, allowing graph traversal to determine safe cutover sequences.

---

## 2. Ontology Layers

The ontology is organized into nine semantic layers. Higher layers depend on lower layers.

```
Layer 9 ─── PEOPLE & PROCESS        (Operator, Team, Ticket, SLA)
Layer 8 ─── LIFECYCLE MANAGEMENT    (LifecyclePhase, Transition, Commission, Decommission)
Layer 7 ─── CHANGE MANAGEMENT       (ChangeRequest, Approval, DeploymentEvent, MigrationPlan)
Layer 6 ─── INCIDENTS & OPERATIONS  (Incident, Alert, RootCause, Remediation, Diagnostic)
Layer 5 ─── CONFIGURATION & STATE   (Configuration, OperationalState, Telemetry, Assurance)
Layer 4 ─── POLICY & INTENT         (Intent, Policy, FirewallRule, SGT, ComplianceReq)
Layer 3 ─── ARCHITECTURE & DESIGN   (Architecture, HLD, ARD, DesignDecision, BUC)
Layer 2 ─── TOPOLOGY & SEGMENTATION (Topology, Zone, Segment, TopologyLayer, FirewallPair)
Layer 1 ─── INFRASTRUCTURE          (Site, Device, Interface, Link, VLAN, VRF, Subnet)
```

---

## 3. Node Labels

### 3.1 Layer 1 — Infrastructure

#### `Site`
A physical or logical location hosting network infrastructure.

| Property | Type | Description |
|----------|------|-------------|
| `siteId` | String | Unique identifier (e.g., `SITE-PAR-01`) |
| `name` | String | Human-readable name |
| `siteType` | Enum | `LARGE_CAMPUS`, `SMALL_CAMPUS`, `BRANCH`, `DATA_CENTER`, `CLOUD_POP` |
| `address` | String | Physical address |
| `country` | String | ISO country code |
| `lifecycleState` | Enum | See Section 5 |
| `createdAt` | DateTime | First created in graph |

#### `Device`
Any physical or virtual network device.

| Property | Type | Description |
|----------|------|-------------|
| `deviceId` | String | Unique ID (e.g., `DEV-PAR-ACC-01`) |
| `hostname` | String | DNS hostname |
| `vendor` | String | Cisco, Arista, Fortinet, Palo Alto… |
| `model` | String | Hardware model (e.g., `Catalyst 9300`) |
| `os` | String | Operating system (IOS-XE, EOS, FortiOS…) |
| `osVersion` | String | Current running OS version |
| `serialNumber` | String | Hardware serial |
| `deviceRole` | Enum | `ACCESS_SWITCH`, `AGGREGATION_SWITCH`, `CORE_SWITCH`, `USER_FW`, `DMZ_FW`, `ROUTER`, `JUMP_HOST`, `SERVER`, `ISP_STUB` |
| `haRole` | Enum | `STANDALONE`, `ACTIVE`, `PASSIVE`, `ACTIVE_ACTIVE_MEMBER` |
| `lifecycleState` | Enum | See Section 5 |
| `commissionedAt` | DateTime | |
| `decommissionedAt` | DateTime | Null if active |

#### `Interface`
A physical or logical interface on a device.

| Property | Type | Description |
|----------|------|-------------|
| `interfaceId` | String | Unique ID |
| `name` | String | Interface name (e.g., `GigabitEthernet0/1`, `Port-channel10`) |
| `interfaceType` | Enum | `PHYSICAL`, `LAG`, `SUBINTERFACE`, `LOOPBACK`, `TUNNEL`, `SVI`, `MGMT` |
| `speed` | Integer | Speed in Mbps |
| `duplex` | Enum | `FULL`, `HALF`, `AUTO` |
| `mtu` | Integer | MTU in bytes |
| `adminState` | Enum | `UP`, `DOWN`, `SHUTDOWN` |
| `operState` | Enum | `UP`, `DOWN`, `ERROR` |
| `macAddress` | String | |
| `description` | String | Interface description per naming convention |
| `since` | DateTime | When this state was last set |

#### `PhysicalLink`
A physical cable or fiber between two interfaces.

| Property | Type | Description |
|----------|------|-------------|
| `linkId` | String | Unique ID |
| `medium` | Enum | `COPPER`, `FIBER_SM`, `FIBER_MM`, `DAC` |
| `length` | Integer | Cable length in meters |
| `lifecycleState` | Enum | |

#### `LogicalLink`
A logical link: LAG, tunnel, or VPN overlay.

| Property | Type | Description |
|----------|------|-------------|
| `linkId` | String | |
| `linkType` | Enum | `LAG_LACP`, `LAG_STATIC`, `VXLAN_TUNNEL`, `IPSEC_TUNNEL`, `GRE` |
| `adminState` | Enum | |
| `operState` | Enum | |

#### `VLAN`
An 802.1Q VLAN definition.

| Property | Type | Description |
|----------|------|-------------|
| `vlanId` | Integer | 802.1Q VLAN ID (1-4094) |
| `name` | String | VLAN name |
| `description` | String | Population/zone description |
| `vlanGroup` | Enum | `POPULATION`, `DMZ`, `MANAGEMENT`, `TRANSIT`, `NATIVE` |
| `lifecycleState` | Enum | |

#### `VRF`
A Virtual Routing and Forwarding instance.

| Property | Type | Description |
|----------|------|-------------|
| `vrfId` | String | Unique ID |
| `name` | String | VRF name |
| `routeDistinguisher` | String | BGP RD (e.g., `65000:100`) |
| `routeTarget` | String | BGP RT |
| `description` | String | |
| `lifecycleState` | Enum | |

#### `Subnet`
An IP subnet.

| Property | Type | Description |
|----------|------|-------------|
| `subnetId` | String | Unique ID |
| `prefix` | String | CIDR notation (e.g., `10.100.0.0/24`) |
| `addressFamily` | Enum | `IPv4`, `IPv6` |
| `gatewayIp` | String | Default gateway |
| `dhcpEnabled` | Boolean | |
| `purpose` | String | Description |

#### `IPAddress`
An individual IP address assignment.

| Property | Type | Description |
|----------|------|-------------|
| `address` | String | IP address (e.g., `10.100.0.1`) |
| `prefixLength` | Integer | |
| `addressType` | Enum | `GATEWAY`, `HOST`, `LOOPBACK`, `VIP`, `NAT_POOL` |
| `since` | DateTime | When assigned |

#### `IPPool`
An IP address pool for dynamic assignment.

| Property | Type | Description |
|----------|------|-------------|
| `poolId` | String | |
| `prefix` | String | Pool range |
| `purpose` | Enum | `LOOPBACK`, `P2P`, `CAMPUS_USER`, `DMZ`, `MANAGEMENT`, `VPN` |

#### `RoutingDomain`
An OSPF process, BGP instance, or IS-IS process.

| Property | Type | Description |
|----------|------|-------------|
| `domainId` | String | |
| `protocol` | Enum | `OSPF`, `BGP`, `ISIS`, `EIGRP`, `STATIC` |
| `processId` | String | OSPF process ID or BGP AS number |
| `scope` | Enum | `UNDERLAY`, `OVERLAY`, `MANAGEMENT`, `INTERNET` |

---

### 3.2 Layer 2 — Topology & Segmentation

#### `Topology`
A named logical topology (site profile).

| Property | Type | Description |
|----------|------|-------------|
| `topologyId` | String | |
| `name` | String | |
| `model` | Enum | `THREE_TIER`, `TWO_TIER_COLLAPSED`, `LEAF_SPINE`, `ROUTED_ACCESS` |
| `siteType` | Enum | See Site.siteType |

#### `TopologyLayer`
A tier within the topology hierarchy.

| Property | Type | Description |
|----------|------|-------------|
| `layerId` | String | |
| `name` | Enum | `ACCESS`, `DISTRIBUTION`, `CORE`, `INTERNET_EDGE`, `MANAGEMENT` |
| `function` | String | Layer description from HLD |

#### `Zone`
A security zone (enforced at the firewall layer).

| Property | Type | Description |
|----------|------|-------------|
| `zoneId` | String | |
| `name` | String | |
| `type` | Enum | `USER`, `GUEST`, `IOT`, `VOICE`, `DMZ_INFRA`, `DMZ_PUBLISH`, `INTERNET`, `MANAGEMENT`, `TRANSIT` |
| `securityLevel` | Integer | 0 (lowest) to 100 (highest) — Cisco ASA model |
| `defaultPolicy` | Enum | `DENY`, `PERMIT` |
| `lifecycleState` | Enum | |

#### `Segment`
A population segment (user/device group with dedicated VLAN).

| Property | Type | Description |
|----------|------|-------------|
| `segmentId` | String | |
| `name` | String | |
| `population` | Enum | `EMPLOYEE`, `CONTRACTOR`, `GUEST`, `VOICE`, `VIDEO`, `IOT`, `BUILDING_MGMT`, `PRINTER`, `CAMERA`, `SERVER` |
| `qosDscp` | Integer | Default DSCP marking |
| `internetAccess` | Boolean | |
| `internalAccess` | Boolean | |
| `lifecycleState` | Enum | |

#### `FirewallPair`
An HA pair of firewall devices.

| Property | Type | Description |
|----------|------|-------------|
| `pairId` | String | |
| `name` | String | |
| `function` | Enum | `USER_SERVICES`, `DMZ_INTERNET` |
| `haModel` | Enum | `ACTIVE_ACTIVE`, `ACTIVE_PASSIVE` |
| `failoverTime` | Integer | Seconds |
| `virtualIp` | String | Cluster/VIP address |
| `lifecycleState` | Enum | |

---

### 3.3 Layer 3 — Architecture & Design Artifacts

#### `Architecture`
The top-level architecture entity — the singular design that all versions descend from.

| Property | Type | Description |
|----------|------|-------------|
| `archId` | String | |
| `name` | String | |
| `domain` | String | `Enterprise Campus Network` |
| `owner` | String | Architect name/team |
| `createdAt` | DateTime | |

#### `ArchitectureVersion`
A versioned snapshot of the architecture.

| Property | Type | Description |
|----------|------|-------------|
| `versionId` | String | |
| `version` | String | SemVer (e.g., `1.2.0`) |
| `status` | Enum | `DRAFT`, `UNDER_REVIEW`, `APPROVED`, `ACTIVE`, `SUPERSEDED`, `ARCHIVED` |
| `approvedBy` | String | |
| `approvedAt` | DateTime | |
| `changeRationale` | String | Why this version exists |
| `breakingChange` | Boolean | Does this require service impact? |

#### `HLDDocument`
A High-Level Design document.

| Property | Type | Description |
|----------|------|-------------|
| `docId` | String | |
| `title` | String | |
| `version` | String | |
| `filePath` | String | Path to the source document |
| `format` | Enum | `MARKDOWN`, `DOCX`, `PDF` |
| `status` | Enum | `DRAFT`, `REVIEW`, `APPROVED`, `SUPERSEDED` |

#### `ARDDocument`
An Architecture Reference Design document.

| Property | Type | Description |
|----------|------|-------------|
| `docId` | String | |
| `title` | String | |
| `framework` | String | `SAFE`, `CVD`, `TOGAF`, `RFC9315` |
| `version` | String | |
| `filePath` | String | |

#### `DesignDecision`
An individual architectural decision with full rationale (ADR-style).

| Property | Type | Description |
|----------|------|-------------|
| `decisionId` | String | |
| `title` | String | Short title |
| `status` | Enum | `PROPOSED`, `ACCEPTED`, `DEPRECATED`, `SUPERSEDED` |
| `context` | String | Why this decision was needed |
| `decision` | String | What was decided |
| `rationale` | String | Why this option was chosen |
| `consequences` | String | Known trade-offs |
| `alternatives` | String | Options considered and rejected |
| `decidedAt` | DateTime | |

#### `DesignPrinciple`
A high-level guiding principle.

| Property | Type | Description |
|----------|------|-------------|
| `principleId` | String | |
| `name` | String | |
| `statement` | String | Full principle statement |
| `source` | String | `HLD`, `SAFE`, `RFC9315`, `TOGAF`, `Internal` |

#### `BusinessUseCase`
A business use case (BUC) driving architectural choices (from SAFE framework).

| Property | Type | Description |
|----------|------|-------------|
| `bucId` | String | e.g., `BUC-C01` |
| `name` | String | |
| `description` | String | |
| `priority` | Enum | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` |
| `affectedZones` | List[String] | |

#### `ComplianceRequirement`
A quantitative requirement from the ARD that the implementation must satisfy.

| Property | Type | Description |
|----------|------|-------------|
| `reqId` | String | e.g., `AVL-01`, `SEC-03` |
| `category` | Enum | `AVAILABILITY`, `SECURITY`, `SEGMENTATION`, `PERFORMANCE`, `SCALABILITY`, `IBN` |
| `statement` | String | Full requirement text |
| `metric` | String | Target metric (e.g., `≥ 99.99%`) |
| `verificationMethod` | Enum | `AUTOMATED_TEST`, `MANUAL_AUDIT`, `CONTINUOUS_ASSURANCE` |

---

### 3.4 Layer 4 — Policy & Intent

#### `Intent`
An RFC 9315 intent — high-level, declarative, outcome-focused.

| Property | Type | Description |
|----------|------|-------------|
| `intentId` | String | |
| `statement` | String | Human-readable intent (e.g., "Guest devices must not access internal resources") |
| `type` | Enum | `CONNECTIVITY`, `SECURITY`, `PERFORMANCE`, `AVAILABILITY`, `COMPLIANCE` |
| `priority` | Integer | Conflict resolution priority |
| `status` | Enum | `DRAFT`, `ACTIVE`, `VIOLATED`, `SUSPENDED`, `RETIRED` |
| `createdBy` | String | |
| `createdAt` | DateTime | |

#### `IntentTranslation`
The translated machine-readable form of an intent.

| Property | Type | Description |
|----------|------|-------------|
| `translationId` | String | |
| `translatedAt` | DateTime | |
| `translatedBy` | String | Agent or operator |
| `policyType` | Enum | `FIREWALL_RULE`, `SGACL`, `ROUTE_POLICY`, `QOS_POLICY`, `ACL` |
| `translationStatus` | Enum | `PENDING`, `TRANSLATED`, `DEPLOYED`, `FAILED` |

#### `Policy`
A network policy instance (firewall policy, route policy, QoS policy).

| Property | Type | Description |
|----------|------|-------------|
| `policyId` | String | |
| `name` | String | |
| `type` | Enum | `FIREWALL_ZONE_POLICY`, `ROUTE_MAP`, `QOS_POLICY`, `ACL`, `SGACL`, `NAT_RULE` |
| `version` | Integer | Policy version |
| `lifecycleState` | Enum | |
| `lastModified` | DateTime | |

#### `FirewallRule`
An individual rule within a firewall policy.

| Property | Type | Description |
|----------|------|-------------|
| `ruleId` | String | |
| `ruleNumber` | Integer | Rule sequence number |
| `action` | Enum | `PERMIT`, `DENY`, `INSPECT`, `DROP` |
| `protocol` | String | `TCP`, `UDP`, `ICMP`, `ANY` |
| `sourcePort` | String | |
| `destPort` | String | |
| `logging` | Boolean | |
| `businessJustification` | String | BUC reference — traceability to SEC-03 |
| `since` | DateTime | When rule was created |

#### `SecurityGroup`
A TrustSec SGT or logical security group.

| Property | Type | Description |
|----------|------|-------------|
| `groupId` | String | |
| `name` | String | |
| `tag` | Integer | SGT value (0-65535) |
| `description` | String | |

#### `ThreatVector`
An identified threat that architecture decisions mitigate.

| Property | Type | Description |
|----------|------|-------------|
| `threatId` | String | |
| `name` | String | |
| `description` | String | |
| `cvss` | Float | CVSS score if applicable |
| `affectedLayers` | List[String] | |

#### `SecurityCapability`
A security function deployed in the architecture.

| Property | Type | Description |
|----------|------|-------------|
| `capabilityId` | String | |
| `name` | String | e.g., `802.1X`, `IPS`, `URL_FILTERING` |
| `type` | Enum | `PREVENTION`, `DETECTION`, `RESPONSE`, `VISIBILITY` |
| `enforcementLayer` | Enum | `L2`, `L3`, `L4`, `L7` |

---

### 3.5 Layer 5 — Configuration & State

#### `ConfigurationVersion`
A versioned snapshot of a device's configuration.

| Property | Type | Description |
|----------|------|-------------|
| `configId` | String | |
| `capturedAt` | DateTime | When config was captured |
| `capturedBy` | String | |
| `hash` | String | SHA256 of config content |
| `source` | Enum | `MANUAL`, `NETCONF`, `RESTCONF`, `ANSIBLE`, `DNA_CENTER` |
| `diff` | String | Diff from previous version (optional) |
| `approved` | Boolean | Change-approved config |

#### `OperationalState`
Current operational state snapshot of a device or interface.

| Property | Type | Description |
|----------|------|-------------|
| `stateId` | String | |
| `timestamp` | DateTime | |
| `cpuUtil` | Float | CPU utilization % |
| `memUtil` | Float | Memory utilization % |
| `uptime` | Integer | Uptime in seconds |
| `bgpPeers` | Integer | Number of established BGP peers |
| `ospfNeighbors` | Integer | Number of OSPF full neighbors |
| `interfaceCount` | Integer | Total interfaces |
| `interfacesUp` | Integer | Interfaces in UP state |

#### `TelemetryRecord`
A streaming telemetry data point.

| Property | Type | Description |
|----------|------|-------------|
| `recordId` | String | |
| `timestamp` | DateTime | |
| `metric` | String | Metric name (e.g., `interface.in_octets`) |
| `value` | Float | Metric value |
| `unit` | String | |
| `source` | Enum | `GRPC_GNMI`, `SNMP`, `NETFLOW`, `SYSLOG` |

#### `AssuranceResult`
An intent compliance assessment from the IBN assurance plane.

| Property | Type | Description |
|----------|------|-------------|
| `resultId` | String | |
| `timestamp` | DateTime | |
| `compliance` | Enum | `COMPLIANT`, `NON_COMPLIANT`, `DEGRADED`, `UNKNOWN` |
| `score` | Float | 0.0 to 1.0 |
| `details` | String | Human-readable assessment |
| `closedLoopAction` | Enum | `NONE`, `ALERT`, `AUTO_REMEDIATE`, `ESCALATE` |

#### `SSoT`
Single Source of Truth record — the authoritative desired state for an element.

| Property | Type | Description |
|----------|------|-------------|
| `ssotId` | String | |
| `element` | String | Reference to the governed node |
| `desiredState` | String | YANG/JSON serialized desired state |
| `lastUpdated` | DateTime | |
| `updatedBy` | String | |

---

### 3.6 Layer 6 — Incidents & Operations

#### `Incident`
A network incident (service-impacting event).

| Property | Type | Description |
|----------|------|-------------|
| `incidentId` | String | |
| `title` | String | |
| `severity` | Enum | `P1_CRITICAL`, `P2_HIGH`, `P3_MEDIUM`, `P4_LOW` |
| `status` | Enum | `OPEN`, `INVESTIGATING`, `MITIGATED`, `RESOLVED`, `CLOSED` |
| `openedAt` | DateTime | |
| `resolvedAt` | DateTime | |
| `mttr` | Integer | Mean time to resolve (minutes) |
| `affectedServices` | List[String] | |

#### `Alert`
A monitoring system alert.

| Property | Type | Description |
|----------|------|-------------|
| `alertId` | String | |
| `source` | String | Monitoring tool (DNA Center, Solarwinds, Prometheus…) |
| `condition` | String | Alert condition |
| `severity` | Enum | |
| `timestamp` | DateTime | |
| `acknowledged` | Boolean | |

#### `RootCause`
Identified root cause of an incident.

| Property | Type | Description |
|----------|------|-------------|
| `rcaId` | String | |
| `category` | Enum | `HARDWARE_FAILURE`, `SOFTWARE_BUG`, `CONFIGURATION_ERROR`, `DESIGN_FLAW`, `HUMAN_ERROR`, `EXTERNAL`, `CAPACITY` |
| `description` | String | |
| `identifiedAt` | DateTime | |
| `identifiedBy` | String | |

#### `Remediation`
A corrective action applied to resolve an incident.

| Property | Type | Description |
|----------|------|-------------|
| `remediationId` | String | |
| `type` | Enum | `MANUAL`, `AUTOMATED`, `CLOSED_LOOP` |
| `action` | String | Description of action taken |
| `appliedAt` | DateTime | |
| `appliedBy` | String | Operator name or `SYSTEM` |
| `successful` | Boolean | |

#### `DiagnosticProbe`
An active diagnostic test.

| Property | Type | Description |
|----------|------|-------------|
| `probeId` | String | |
| `type` | Enum | `PING`, `TRACEROUTE`, `IPSLA`, `PATHTEST`, `PACKET_CAPTURE` |
| `source` | String | Source device/IP |
| `destination` | String | Destination device/IP |
| `timestamp` | DateTime | |
| `result` | String | |
| `latencyMs` | Float | |
| `packetLoss` | Float | |

---

### 3.7 Layer 7 — Change Management

#### `ChangeRequest`
A formal change request (RFC).

| Property | Type | Description |
|----------|------|-------------|
| `crId` | String | e.g., `CHG-2026-042` |
| `title` | String | |
| `type` | Enum | `STANDARD`, `NORMAL`, `EMERGENCY`, `UPGRADE`, `DECOMMISSION` |
| `risk` | Enum | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `status` | Enum | `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, `IN_PROGRESS`, `COMPLETED`, `ROLLED_BACK` |
| `requestedBy` | String | |
| `requestedAt` | DateTime | |
| `targetVersion` | String | ArchitectureVersion to reach |
| `rollbackProcedure` | String | Rollback steps |
| `testPlan` | String | |

#### `ChangeWindow`
A scheduled maintenance window.

| Property | Type | Description |
|----------|------|-------------|
| `windowId` | String | |
| `start` | DateTime | |
| `end` | DateTime | |
| `recurrence` | String | Cron expression if recurring |
| `type` | Enum | `SCHEDULED`, `EMERGENCY` |
| `impactStatement` | String | |

#### `Approval`
A formal approval record.

| Property | Type | Description |
|----------|------|-------------|
| `approvalId` | String | |
| `decision` | Enum | `APPROVED`, `REJECTED`, `CONDITIONAL` |
| `conditions` | String | Any conditions attached |
| `grantedAt` | DateTime | |

#### `DeploymentEvent`
A record of an actual deployment action.

| Property | Type | Description |
|----------|------|-------------|
| `deployId` | String | |
| `startedAt` | DateTime | |
| `completedAt` | DateTime | |
| `status` | Enum | `STARTED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `ROLLED_BACK` |
| `method` | Enum | `MANUAL`, `ANSIBLE`, `NSO`, `DNA_CENTER`, `NETLAB` |
| `log` | String | Deployment log summary |

#### `MigrationPlan`
A zero-downtime migration/upgrade plan.

| Property | Type | Description |
|----------|------|-------------|
| `planId` | String | |
| `name` | String | |
| `strategy` | Enum | `PARALLEL_RUN`, `ROLLING_UPGRADE`, `BLUE_GREEN`, `CUTOVER` |
| `phases` | Integer | Number of migration phases |
| `estimatedDuration` | Integer | Minutes |
| `serviceImpact` | Enum | `NONE`, `DEGRADED`, `BRIEF_OUTAGE` |
| `rollbackTrigger` | String | Condition that triggers rollback |

---

### 3.8 Layer 8 — Lifecycle Management

#### `LifecyclePhase`
A named phase in the network lifecycle.

| Property | Type | Description |
|----------|------|-------------|
| `phaseId` | String | |
| `name` | Enum | `DESIGN`, `REVIEW`, `APPROVED`, `DEPLOYING`, `ACTIVE`, `DEGRADED`, `MAINTENANCE`, `UPGRADING`, `DECOMMISSIONING`, `DECOMMISSIONED` |
| `description` | String | |

#### `LifecycleTransition`
An event that moves a node from one lifecycle phase to another.

| Property | Type | Description |
|----------|------|-------------|
| `transitionId` | String | |
| `timestamp` | DateTime | |
| `reason` | String | |
| `triggeredBy` | Enum | `HUMAN`, `SYSTEM`, `CLOSED_LOOP` |
| `evidenceRef` | String | Reference to CR, incident, or assurance result |

#### `CommissioningRecord`
Formal record of a device/element being commissioned into service.

| Property | Type | Description |
|----------|------|-------------|
| `recordId` | String | |
| `commissionedAt` | DateTime | |
| `commissionedBy` | String | |
| `acceptanceTestRef` | String | Test report reference |
| `signedOff` | Boolean | |

#### `DecommissioningRecord`
Formal record of a device/element being retired.

| Property | Type | Description |
|----------|------|-------------|
| `recordId` | String | |
| `decommissionedAt` | DateTime | |
| `decommissionedBy` | String | |
| `replacedByDeviceId` | String | Successor device if applicable |
| `dataWiped` | Boolean | |
| `hardwareDisposal` | String | RMA / recycling / storage |

---

### 3.9 Layer 9 — People & Process

#### `Operator`
A network operator, engineer, or architect.

| Property | Type | Description |
|----------|------|-------------|
| `operatorId` | String | |
| `name` | String | |
| `role` | Enum | `NOC_ENGINEER`, `NET_ENGINEER`, `ARCHITECT`, `SECURITY_ENGINEER`, `MANAGER` |
| `email` | String | |

#### `Team`
An organizational team.

| Property | Type | Description |
|----------|------|-------------|
| `teamId` | String | |
| `name` | String | |
| `function` | Enum | `NOC`, `NETOPS`, `SECURITY`, `ARCHITECTURE`, `MANAGEMENT` |

#### `Ticket`
An ITSM ticket (ServiceNow, Jira, etc.).

| Property | Type | Description |
|----------|------|-------------|
| `ticketId` | String | External ticket ID |
| `system` | String | `ServiceNow`, `Jira`, etc. |
| `status` | String | |
| `url` | String | Deep link to ticket |

#### `SLA`
A service level agreement.

| Property | Type | Description |
|----------|------|-------------|
| `slaId` | String | |
| `name` | String | |
| `availabilityTarget` | Float | e.g., `99.99` |
| `mttrTarget` | Integer | Minutes |
| `mtbfTarget` | Integer | Hours |
| `scope` | String | What service/segment this covers |

#### `SLAViolation`
A recorded SLA breach.

| Property | Type | Description |
|----------|------|-------------|
| `violationId` | String | |
| `detectedAt` | DateTime | |
| `duration` | Integer | Minutes of violation |
| `impact` | String | |

---

## 4. Relationship Types

### 4.1 Infrastructure Topology Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `LOCATED_AT` | Device | Site | `since` |
| `HAS_INTERFACE` | Device | Interface | — |
| `CONNECTED_TO` | Interface | Interface | `since`, `until`, `linkType` |
| `MEMBER_OF_LAG` | Interface | LogicalLink | `lagPriority` |
| `CARRIES_VLAN` | Interface | VLAN | `mode: TRUNK/ACCESS`, `since` |
| `DEFINED_ON` | VLAN | Device | `since` |
| `BOUND_TO` | VLAN | VRF | `since` |
| `ASSIGNED_TO` | Subnet | VLAN | — |
| `ASSIGNED_TO` | Subnet | VRF | — |
| `PART_OF_SUBNET` | IPAddress | Subnet | `since`, `until` |
| `ASSIGNED_TO` | IPAddress | Interface | `since`, `until` |
| `DRAWS_FROM` | Subnet | IPPool | — |
| `MEMBER_OF_PAIR` | Device | FirewallPair | `haRole` |
| `MEMBER_OF_STACK` | Device | StackGroup | `stackPriority` |
| `IN_LAYER` | Device | TopologyLayer | `since` |
| `BELONGS_TO_TOPOLOGY` | TopologyLayer | Topology | — |
| `INSTANCE_OF_TOPOLOGY` | Site | Topology | `since` |

### 4.2 Segmentation & Policy Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `MAPPED_TO_VLAN` | Segment | VLAN | — |
| `BELONGS_TO_ZONE` | Segment | Zone | `since` |
| `BELONGS_TO_ZONE` | VLAN | Zone | `since` |
| `PART_OF_VRF` | Zone | VRF | — |
| `HAS_ZONE` | FirewallPair | Zone | `interfaceName` |
| `APPLIED_TO` | Policy | Device | `since` |
| `APPLIED_TO` | Policy | Zone | `direction: INBOUND/OUTBOUND/BOTH` |
| `GOVERNS` | Policy | Segment | — |
| `CONTAINS_RULE` | Policy | FirewallRule | `ruleOrder` |
| `PERMITS_FROM` | FirewallRule | Zone/Segment | — |
| `PERMITS_TO` | FirewallRule | Zone/Segment | — |
| `DENIES_FROM` | FirewallRule | Zone/Segment | — |
| `ASSIGNED_SGT` | Segment | SecurityGroup | — |
| `SGACL_PERMITS` | SecurityGroup | SecurityGroup | `protocol`, `port` |
| `SGACL_DENIES` | SecurityGroup | SecurityGroup | — |
| `PARTICIPATES_IN` | Device | RoutingDomain | `role: ABR/ASBR/INTERNAL` |

### 4.3 Architecture & Design Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `HAS_VERSION` | Architecture | ArchitectureVersion | — |
| `PRECEDED_BY` | ArchitectureVersion | ArchitectureVersion | `changeType: MAJOR/MINOR/PATCH` |
| `BASED_ON_HLD` | ArchitectureVersion | HLDDocument | — |
| `REFERENCES_ARD` | ArchitectureVersion | ARDDocument | — |
| `CONTAINS_DECISION` | ArchitectureVersion | DesignDecision | — |
| `DERIVED_FROM_PRINCIPLE` | DesignDecision | DesignPrinciple | — |
| `JUSTIFIES` | DesignDecision | Device | — |
| `JUSTIFIES` | DesignDecision | VLAN | — |
| `JUSTIFIES` | DesignDecision | Policy | — |
| `JUSTIFIES` | DesignDecision | TopologyLayer | — |
| `SATISFIES` | DesignDecision | ComplianceRequirement | — |
| `DEFINED_IN` | ComplianceRequirement | ARDDocument | — |
| `REQUIRES_CAPABILITY` | BusinessUseCase | SecurityCapability | — |
| `MITIGATED_BY` | ThreatVector | SecurityCapability | — |
| `ENFORCED_BY` | SecurityCapability | Device | `enforcementPoint` |
| `ADDRESSES_THREAT` | BusinessUseCase | ThreatVector | — |
| `IMPLEMENTS_VERSION` | Site | ArchitectureVersion | `since` |

### 4.4 Intent & IBN Relationships (RFC 9315)

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `SATISFIES_BUC` | Intent | BusinessUseCase | — |
| `CONFLICTS_WITH` | Intent | Intent | `conflictType` |
| `TRANSLATED_TO` | Intent | IntentTranslation | `translatedAt` |
| `GENERATES_POLICY` | IntentTranslation | Policy | — |
| `ASSURES` | AssuranceResult | Intent | `compliance` |
| `BASED_ON_TELEMETRY` | AssuranceResult | TelemetryRecord | — |
| `REFERENCES_SSOT` | AssuranceResult | SSoT | — |
| `GOVERNS_ELEMENT` | SSoT | Device | — |
| `TRIGGERED_ACTION` | AssuranceResult | Remediation | `actionType` |
| `COLLECTED_FROM` | TelemetryRecord | Device | `protocol` |
| `COLLECTED_FROM` | TelemetryRecord | Interface | `protocol` |

### 4.5 Configuration & State Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `HAS_CONFIG` | Device | ConfigurationVersion | `isCurrent: Boolean` |
| `PRECEDED_BY` | ConfigurationVersion | ConfigurationVersion | `changedAt` |
| `DEPLOYED_BY` | ConfigurationVersion | DeploymentEvent | — |
| `HAS_STATE` | Device | OperationalState | `timestamp` |
| `HAS_STATE` | Interface | OperationalState | `timestamp` |

### 4.6 Change Management Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `TARGETS_ELEMENT` | ChangeRequest | Device | `changeType` |
| `TARGETS_ELEMENT` | ChangeRequest | VLAN | `changeType` |
| `TARGETS_ELEMENT` | ChangeRequest | Policy | `changeType` |
| `TARGETS_VERSION` | ChangeRequest | ArchitectureVersion | — |
| `HAS_APPROVAL` | ChangeRequest | Approval | — |
| `GRANTED_BY` | Approval | Operator | — |
| `SCHEDULED_IN` | ChangeRequest | ChangeWindow | — |
| `EXECUTES` | DeploymentEvent | ChangeRequest | — |
| `PERFORMED_BY` | DeploymentEvent | Operator | — |
| `RESULTS_IN` | DeploymentEvent | LifecycleTransition | — |
| `HAS_MIGRATION_PLAN` | ChangeRequest | MigrationPlan | — |
| `MIGRATES` | MigrationPlan | Device | `phase: Integer` |
| `REPLACES` | Device | Device | `since`, `migrationPlanId` |
| `ROLLS_BACK` | DeploymentEvent | ChangeRequest | `reason` |

### 4.7 Incident & Troubleshooting Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `TRIGGERED_BY` | Incident | Alert | — |
| `IMPACTS` | Incident | Device | `impactType: SERVICE/PARTIAL/FULL` |
| `IMPACTS` | Incident | Segment | — |
| `IMPACTS` | Incident | Site | — |
| `HAS_ROOT_CAUSE` | Incident | RootCause | — |
| `CAUSED_BY` | RootCause | Device | — |
| `CAUSED_BY` | RootCause | ConfigurationVersion | — |
| `CAUSED_BY` | RootCause | DesignDecision | `designFlaw: Boolean` |
| `RESOLVES` | Remediation | Incident | `resolutionType` |
| `MODIFIES` | Remediation | Device | — |
| `MODIFIES` | Remediation | Policy | — |
| `LINKED_TO_TICKET` | Incident | Ticket | — |
| `VIOLATES` | Incident | SLA | `violationDuration` |
| `GENERATED_BY` | Alert | Device | — |
| `GENERATED_BY` | Alert | Interface | — |
| `RAN_DURING` | DiagnosticProbe | Incident | — |
| `PROBED` | DiagnosticProbe | Device | — |

### 4.8 Lifecycle Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `IN_PHASE` | Device | LifecyclePhase | `since` |
| `IN_PHASE` | VLAN | LifecyclePhase | `since` |
| `IN_PHASE` | Policy | LifecyclePhase | `since` |
| `IN_PHASE` | ArchitectureVersion | LifecyclePhase | `since` |
| `TRANSITIONED_VIA` | LifecyclePhase | LifecycleTransition | — |
| `FROM_PHASE` | LifecycleTransition | LifecyclePhase | — |
| `TO_PHASE` | LifecycleTransition | LifecyclePhase | — |
| `PERFORMED_BY` | LifecycleTransition | Operator | — |
| `COMMISSIONED_BY` | CommissioningRecord | Device | — |
| `AUTHORIZED_BY` | CommissioningRecord | Approval | — |
| `DECOMMISSIONED_BY` | DecommissioningRecord | Device | — |
| `SUCCEEDED_BY` | Device | Device | `since` |

### 4.9 People & Process Relationships

| Relationship | From | To | Key Properties |
|-------------|------|----|---------------|
| `MEMBER_OF` | Operator | Team | `since`, `role` |
| `CREATED` | Operator | DesignDecision | `at` |
| `CREATED` | Operator | Intent | `at` |
| `OWNS` | Team | Site | — |
| `RESPONSIBLE_FOR` | Team | Device | `responsibilityType` |
| `ASSIGNED_TO` | Ticket | Operator | — |
| `ASSIGNED_TO` | Ticket | Team | — |
| `COVERS` | SLA | Segment | — |
| `COVERS` | SLA | Site | — |
| `RECORDS_VIOLATION` | SLAViolation | SLA | — |
| `CAUSED_VIOLATION` | Incident | SLAViolation | — |

---

## 5. Lifecycle State Machine

### 5.1 Universal Lifecycle States

Every infrastructure, design, and policy node carries a `lifecycleState` property. The valid states and transitions are:

```
  ┌─────────┐
  │ PLANNED │ ← Initial state when a node is created in the design phase
  └────┬────┘
       │ DesignDecision created / HLD approved
       ▼
  ┌─────────┐
  │ DESIGNED│ ← Node is specified in HLD/ARD, not yet approved
  └────┬────┘
       │ Architecture review passed
       ▼
  ┌──────────┐
  │ APPROVED │ ← Change approved, ready for deployment
  └────┬─────┘
       │ Deployment started (ChangeRequest IN_PROGRESS)
       ▼
  ┌───────────┐
  │ DEPLOYING │ ← Actively being provisioned
  └─────┬─────┘
        │ Deployment completed, acceptance tests passed
        ▼
  ┌────────┐
  │ ACTIVE │ ←───────────────────────────────────────┐
  └──┬──┬──┘                                          │
     │  │                                             │
     │  │ Alert / fault condition                     │
     │  ▼                                             │
     │  ┌──────────┐     Fault cleared                │
     │  │ DEGRADED │ ──────────────────────────────── ┤
     │  └──────────┘                                  │
     │                                                │
     │ Maintenance window opens                       │
     ▼                                                │
  ┌─────────────┐     Maintenance complete            │
  │ MAINTENANCE │ ────────────────────────────────────┘
  └──────┬──────┘
         │ Architecture upgrade initiated
         ▼
  ┌───────────┐
  │ UPGRADING │ ← MigrationPlan executing (zero-downtime if strategy = ROLLING/BLUE_GREEN)
  └─────┬─────┘
        │ Upgrade complete
        └──► ACTIVE (on new ArchitectureVersion)
             OR
        │ Upgrade fails / rollback
        └──► ACTIVE (on previous ArchitectureVersion via ROLLS_BACK)

  ACTIVE ──► DECOMMISSIONING ──► DECOMMISSIONED
```

### 5.2 Architecture Version Lifecycle

```
DRAFT → UNDER_REVIEW → APPROVED → ACTIVE → SUPERSEDED → ARCHIVED
```

An `ArchitectureVersion` becomes `SUPERSEDED` when a newer version reaches `ACTIVE`. The old version is preserved in the graph with all its nodes and relationships, enabling full historical query.

### 5.3 Intent Lifecycle (RFC 9315)

```
DRAFT → ACTIVE → VIOLATED (assurance detects deviation)
                      ↓
              closed-loop action triggered
                      ↓
               ACTIVE (if remediated) or SUSPENDED (if unresolvable)
ACTIVE → RETIRED (when business use case no longer applies)
```

---

## 6. Lifecycle Phase Coverage

### 6.1 Design Phase

**Key nodes active:** Architecture, ArchitectureVersion (DRAFT/UNDER_REVIEW), HLDDocument, ARDDocument, DesignDecision, DesignPrinciple, BusinessUseCase, ComplianceRequirement, ThreatVector, SecurityCapability, Intent (DRAFT), Topology, Zone, Segment, VLAN, VRF, Subnet (PLANNED)

**Key relationships active:** `HAS_VERSION`, `BASED_ON_HLD`, `REFERENCES_ARD`, `CONTAINS_DECISION`, `DERIVED_FROM_PRINCIPLE`, `JUSTIFIES`, `SATISFIES`, `REQUIRES_CAPABILITY`, `MITIGATED_BY`

**Typical queries:**
- "Show all design decisions that justify the dual-firewall architecture"
- "Which compliance requirements are not yet addressed by any design decision?"
- "What threat vectors are not yet mitigated by a security capability?"

### 6.2 Deployment Phase

**Key nodes active:** Device (DEPLOYING), Interface, PhysicalLink, LogicalLink, VLAN (DEPLOYING), ConfigurationVersion, DeploymentEvent, ChangeRequest, Approval, CommissioningRecord, LifecycleTransition

**Key relationships active:** `EXECUTES`, `PERFORMED_BY`, `RESULTS_IN`, `TARGETS_ELEMENT`, `HAS_APPROVAL`, `COMMISSIONED_BY`, `HAS_CONFIG`

**Typical queries:**
- "Which devices are still in DEPLOYING state and have not yet been commissioned?"
- "Show the full deployment history of device DEV-PAR-ACC-01"
- "Which ChangeRequests have been approved but not yet executed?"

### 6.3 Operating Phase

**Key nodes active:** All infrastructure (ACTIVE), OperationalState, TelemetryRecord, AssuranceResult, Intent (ACTIVE), SSoT, ConfigurationVersion, SLA

**Key relationships active:** `HAS_STATE`, `COLLECTED_FROM`, `ASSURES`, `REFERENCES_SSOT`, `COVERS`

**Typical queries:**
- "Which intents are currently NON_COMPLIANT?"
- "Show all devices where operState is DOWN on at least one interface"
- "What is the current compliance score across all intents for site SITE-PAR-01?"

### 6.4 Troubleshooting Phase

**Key nodes active:** Incident (OPEN/INVESTIGATING), Alert, RootCause, Remediation, DiagnosticProbe, Ticket, SLAViolation

**Key relationships active:** `TRIGGERED_BY`, `IMPACTS`, `HAS_ROOT_CAUSE`, `CAUSED_BY`, `RESOLVES`, `MODIFIES`, `VIOLATES`, `RAN_DURING`

**Key traversals:**
- **Blast radius:** From an Alert on a Device → traverse `IMPACTS` → find all Segments, Sites, SLAs affected
- **Root cause chain:** From RootCause → `CAUSED_BY` ConfigurationVersion → `PRECEDED_BY` ConfigurationVersion → identify when the bad config was introduced
- **Design flaw detection:** RootCause `CAUSED_BY` DesignDecision → flag the decision for review in next ArchitectureVersion

### 6.5 Architecture Upgrade Phase

**Key nodes active:** ArchitectureVersion (APPROVED), MigrationPlan, ChangeRequest (UPGRADE type), Device (UPGRADING), new Device nodes (PLANNED/DEPLOYING)

**Key traversals:**
- **Safe cutover sequence:** MigrationPlan `MIGRATES` Device (with `phase` property) → order deployment by phase, respecting redundancy constraints
- **Parallel run detection:** Old Device and new Device both `IN_LAYER` same TopologyLayer → validate HA before cutover
- **Zero-downtime validation:** Verify that for every Segment, at least one Device carrying its VLAN remains ACTIVE throughout migration phases

**Relationships supporting zero-downtime:**
- `REPLACES` (new Device → old Device, with `migrationPlanId`)
- `SUCCEEDED_BY` (old Device → new Device)
- `PRECEDED_BY` (new ArchitectureVersion → old ArchitectureVersion)

### 6.6 Decommissioning Phase

**Key nodes active:** Device (DECOMMISSIONING → DECOMMISSIONED), DecommissioningRecord, ChangeRequest (DECOMMISSION type), LifecycleTransition

**Key traversals:**
- **Dependency check before decommission:** Device → traverse all `CARRIES_VLAN`, `APPLIES_TO`, `MEMBER_OF_PAIR` → verify no active segment or policy depends solely on this device
- **Orphan detection:** After decommission, find Subnets/IPAddresses with no remaining `ASSIGNED_TO` active interface
- **History preservation:** DECOMMISSIONED devices remain in the graph with all historical relationships, enabling post-mortem and audit queries

---

## 7. Key Query Patterns

### 7.1 Design Phase — Compliance Gap Analysis

```cypher
// Find compliance requirements not satisfied by any design decision
MATCH (r:ComplianceRequirement)
WHERE NOT (r)<-[:SATISFIES]-(:DesignDecision)
RETURN r.reqId, r.category, r.statement
ORDER BY r.category
```

### 7.2 Deployment — Configuration Drift Detection

```cypher
// Find devices whose running config differs from the approved config
MATCH (d:Device)-[:HAS_CONFIG]->(c:ConfigurationVersion)
WHERE c.approved = false
AND d.lifecycleState = 'ACTIVE'
RETURN d.hostname, d.deviceRole, c.capturedAt, c.hash
ORDER BY c.capturedAt DESC
```

### 7.3 Operations — Intent Compliance Dashboard

```cypher
// Show all intents with their current compliance state
MATCH (i:Intent)-[:TRANSLATED_TO]->(:IntentTranslation)-[:GENERATES_POLICY]->(:Policy)-[:APPLIED_TO]->(d:Device)
OPTIONAL MATCH (ar:AssuranceResult)-[:ASSURES]->(i)
WHERE ar.timestamp = max(ar.timestamp)
RETURN i.statement, i.type, ar.compliance, ar.score, collect(d.hostname) AS devices
ORDER BY ar.score ASC
```

### 7.4 Troubleshooting — Blast Radius from Device Failure

```cypher
// Given a failing device, find all impacted segments, sites, and SLAs
MATCH (d:Device {hostname: 'sw-par-acc-01'})
OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v:VLAN)<-[:MAPPED_TO_VLAN]-(s:Segment)
OPTIONAL MATCH (s)<-[:COVERS]-(sla:SLA)
OPTIONAL MATCH (d)-[:LOCATED_AT]->(site:Site)
RETURN d.hostname,
       collect(DISTINCT v.name) AS impactedVLANs,
       collect(DISTINCT s.name) AS impactedSegments,
       collect(DISTINCT sla.name) AS atRiskSLAs,
       site.name AS site
```

### 7.5 Troubleshooting — Root Cause Chain

```cypher
// Trace the config that caused an incident back through version history
MATCH (inc:Incident {incidentId: 'INC-2026-042'})
      -[:HAS_ROOT_CAUSE]->(rca:RootCause)
      -[:CAUSED_BY]->(cfg:ConfigurationVersion)
      -[:PRECEDED_BY*1..5]->(prev:ConfigurationVersion)
RETURN inc.title, rca.category, cfg.capturedAt, cfg.hash,
       collect({version: prev.capturedAt, hash: prev.hash}) AS history
ORDER BY prev.capturedAt DESC
```

### 7.6 Upgrade — Zero-Downtime Migration Validation

```cypher
// For each segment, verify at least 2 active devices will carry its VLAN during migration
MATCH (seg:Segment)-[:MAPPED_TO_VLAN]->(v:VLAN)
MATCH (d:Device)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v)
WHERE d.lifecycleState IN ['ACTIVE', 'DEPLOYING']
WITH seg, v, collect(d) AS devices
WHERE size(devices) < 2
RETURN seg.name, v.name, size(devices) AS activeDeviceCount,
       'WARNING: Single point of failure during migration' AS alert
```

### 7.7 Upgrade — Architecture Version Delta

```cypher
// Show what changed between two architecture versions
MATCH (v2:ArchitectureVersion {version: '2.0.0'})
      -[:PRECEDED_BY]->(v1:ArchitectureVersion {version: '1.0.0'})
MATCH (v2)-[:CONTAINS_DECISION]->(d2:DesignDecision)
WHERE NOT (v1)-[:CONTAINS_DECISION]->(d2)
RETURN d2.decisionId, d2.title, d2.decision, d2.rationale
```

### 7.8 Decommissioning — Dependency Check

```cypher
// Before decommissioning a device, verify no segment solely depends on it
MATCH (d:Device {hostname: 'fw-par-usr-01'})
MATCH (d)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v:VLAN)<-[:MAPPED_TO_VLAN]-(seg:Segment)
WITH seg, v,
     count {
       MATCH (other:Device)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v)
       WHERE other.lifecycleState = 'ACTIVE' AND other.deviceId <> d.deviceId
     } AS otherActiveDevices
WHERE otherActiveDevices = 0
RETURN seg.name, v.name,
       'BLOCKER: No other active device carries this VLAN' AS status
```

### 7.9 Full Lifecycle Audit Trail

```cypher
// Full history of a device from design to current state
MATCH (d:Device {hostname: 'sw-par-acc-01'})
MATCH (d)-[:IN_PHASE]->(phase:LifecyclePhase)
OPTIONAL MATCH (phase)<-[:FROM_PHASE|TO_PHASE]-(t:LifecycleTransition)-[:PERFORMED_BY]->(op:Operator)
RETURN d.hostname, phase.name, t.timestamp, t.reason, op.name
ORDER BY t.timestamp ASC
```

---

## 8. Graph Model Diagram

```
                    ┌─────────────────┐
                    │  Architecture   │
                    └────────┬────────┘
                             │ HAS_VERSION
                    ┌────────▼────────┐      PRECEDED_BY
                    │ArchitectureVer. │◄────────────────┐
                    └──┬─────────┬───┘                  │
          BASED_ON_HLD │         │ REFERENCES_ARD        │
               ┌───────▼┐    ┌──▼──────┐    PRECEDED_BY │
               │  HLD   │    │   ARD   │     (chain)    │
               └───────-┘    └─────────┘                │
                             CONTAINS_DECISION           │
                    ┌────────────────────┐               │
                    │  DesignDecision    │───────────────►┘
                    └────────┬───────────┘
                             │ JUSTIFIES
       ┌─────────────────────┼────────────────────┐
       ▼                     ▼                     ▼
  ┌────────┐           ┌──────────┐          ┌──────────┐
  │ Device │           │   VLAN   │          │  Policy  │
  └──┬─┬───┘           └──┬───────┘          └────┬─────┘
     │ │ LOCATED_AT       │ BOUND_TO              │ CONTAINS_RULE
     │ │      ┌───────┐   │    ┌──────┐           │
     │ │      │ Site  │   ▼    │ VRF  │    ┌──────▼──────┐
     │ │      └───────┘ ┌────┐ └──────┘    │FirewallRule │
     │ │                │Subnet│           └─────────────┘
     │ │                └────┘             (TRANSLATED from Intent)
     │ │ HAS_INTERFACE
     │ ▼
  ┌──────────┐   CONNECTED_TO   ┌──────────┐
  │Interface │◄────────────────►│Interface │
  └──────────┘                  └──────────┘
     │ CARRIES_VLAN
     ▼
  ┌──────────┐
  │   VLAN   │◄──── MAPPED_TO_VLAN ────┌──────────┐
  └──────────┘                         │ Segment  │
                                        └────┬─────┘
                                             │ BELONGS_TO_ZONE
                                        ┌────▼─────┐
                                        │   Zone   │
                                        └──────────┘

  ┌─────────┐  TRIGGERED_BY  ┌────────┐  IMPACTS  ┌─────────┐
  │Incident │◄───────────────│ Alert  │            │ Segment │
  └────┬────┘                └────────┘            └─────────┘
       │ HAS_ROOT_CAUSE          ▲
  ┌────▼────────┐         GENERATED_BY
  │  RootCause  │────────►  Device
  └─────────────┘  CAUSED_BY

  ┌────────────┐  ASSURES  ┌────────┐  TRANSLATED_TO  ┌─────────────────┐
  │AssuranceRes│──────────►│ Intent │◄────────────────│IntentTranslation│
  └────────────┘           └────────┘                  └─────────────────┘
                                                              │ GENERATES_POLICY
                                                         ┌────▼────┐
                                                         │ Policy  │
                                                         └─────────┘
```

---

*This ontology is a living document. It should be versioned alongside the ArchitectureVersion it describes, and updated at each iteration of the network lifecycle.*
