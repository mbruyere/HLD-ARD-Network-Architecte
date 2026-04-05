# Cisco SAFE Secure Campus — Architecture Reference Design (ARD)
## Synthesized Reference Document

**Framework:** Cisco SAFE (Secure Architecture For Enterprise)
**Document Type:** Architecture Reference Design
**Domain:** Enterprise Campus Network
**Source Basis:** Cisco SAFE Secure Campus Architecture Guide (Design Zone Security)
**Version:** 1.0 (synthesized March 2026)
**Classification:** Reference Use

---

## INDEX

1. [SAFE Framework Overview](#1-safe-framework-overview)
2. [Campus Place in the SAFE Architecture](#2-campus-place-in-the-safe-architecture)
3. [Business Use Cases](#3-business-use-cases)
4. [Threats and Capabilities Model](#4-threats-and-capabilities-model)
5. [Secure Campus Architecture Design](#5-secure-campus-architecture-design)
6. [Segmentation Architecture](#6-segmentation-architecture)
7. [Security Capabilities by Domain](#7-security-capabilities-by-domain)
8. [Architecture Requirements (Quantitative Criteria)](#8-architecture-requirements-quantitative-criteria)
9. [Compliance Mapping to HLD](#9-compliance-mapping-to-hld)
10. [References](#10-references)

---

## 1. SAFE Framework Overview

### 1.1 What is SAFE

SAFE (Secure Architecture For Enterprise) is Cisco's security reference architecture framework. It provides a structured, use-case-driven methodology for designing secure enterprise networks by decomposing the network into **Places in the Network (PINs)** and defining the security capabilities required at each PIN.

SAFE's design approach is:
- **Business-driven:** Architecture is anchored to business use cases (BUCs), not device lists.
- **Threat-informed:** Each design decision maps to a specific threat vector.
- **Capability-based:** Security is expressed as capabilities (e.g., segmentation, visibility, threat defense) rather than product names.
- **Vendor-prescriptive at the capability layer, vendor-agnostic at the framework layer.**

### 1.2 SAFE Design Methodology

The SAFE design process follows five steps:

1. **Identify Business Use Cases (BUCs):** What must the network enable?
2. **Identify Threat Vectors:** What threats apply to each BUC?
3. **Map Security Capabilities:** What capabilities mitigate each threat?
4. **Apply Capabilities to PINs:** Where in the network are capabilities enforced?
5. **Validate the Design:** Does the implemented architecture satisfy the BUCs and mitigate the threats?

### 1.3 SAFE Places in the Network (PINs)

SAFE defines seven canonical PINs for enterprise networks:

| PIN | Description |
|-----|-------------|
| **Campus** | Primary user workspace: offices, buildings, floors |
| **Branch** | Remote sites connected to campus via WAN/SD-WAN |
| **Data Center** | Application hosting and storage infrastructure |
| **WAN Edge** | Connectivity to branch, cloud, and partner networks |
| **Internet Edge** | Secure internet access and external publishing |
| **Cloud** | IaaS/SaaS/PaaS workloads |
| **Management** | Out-of-band management and security operations |

This ARD focuses on the **Campus PIN** and its interactions with the Internet Edge and Management PINs.

---

## 2. Campus Place in the SAFE Architecture

### 2.1 Campus Zones

The SAFE Campus PIN is subdivided into functional **security zones**:

| Zone | Function | Security Posture |
|------|----------|-----------------|
| **User Zone** | End-user devices: PCs, laptops, phones | Authenticated, segmented by population/role |
| **Server Zone** | Local application servers, print, file services | Restricted access, policy-controlled |
| **Guest Zone** | Internet-only access for visitors/contractors | Isolated, no access to internal resources |
| **IoT Zone** | Building management, printers, cameras, sensors | Isolated, restricted outbound only |
| **Voice Zone** | IP telephony infrastructure | QoS-prioritized, isolated from data |
| **Management Zone** | Out-of-band management devices and jump hosts | Strictly controlled, audit-logged |

### 2.2 Campus Architecture Tiers

SAFE's campus architecture aligns with the classical three-tier hierarchical model:

```
[Access Layer]       → End-user / device connectivity, first QoS marking
      ↓
[Distribution Layer] → VLAN aggregation, redundancy, policy enforcement
      ↓
[Core / Firewall]    → Inter-zone routing, Layer 3 gateway, stateful inspection
      ↓
[Internet Edge]      → Internet access, DMZ, external publishing
```

For smaller campus sites, the Access and Distribution layers collapse into a two-tier model, but the security zone structure remains identical.

### 2.3 Campus to Internet Edge Boundary

The boundary between the Campus PIN and the Internet Edge PIN is where:
- Stateful firewall inspection separates internal zones from DMZ and internet-facing services
- NAT/PAT policies are applied
- Internet-bound traffic is filtered for threats (URL filtering, malware inspection, DLP)
- Published services (HTTPS, mail, DNS) are exposed via reverse proxy or direct DMZ hosting

---

## 3. Business Use Cases

SAFE defines Business Use Cases (BUCs) as the primary driver of architecture decisions. For the campus environment, the core BUCs are:

| BUC ID | Business Use Case | Affected Zones |
|--------|------------------|---------------|
| BUC-C01 | Secure employee network access | User Zone |
| BUC-C02 | Guest internet access | Guest Zone |
| BUC-C03 | Contractor / third-party access | User Zone (segmented) |
| BUC-C04 | IoT / building systems connectivity | IoT Zone |
| BUC-C05 | IP telephony and unified communications | Voice Zone |
| BUC-C06 | Secure access to data center applications | User Zone → DC |
| BUC-C07 | Internet access for all user populations | Campus → Internet Edge |
| BUC-C08 | Out-of-band management of network infrastructure | Management Zone |
| BUC-C09 | Inter-site connectivity for branch/remote users | VPN / WAN Edge |
| BUC-C10 | Public service publishing (web, DNS, mail) | Internet Edge / DMZ |

---

## 4. Threats and Capabilities Model

### 4.1 Campus Threat Vectors

| Threat Vector | Description | Affected BUCs |
|--------------|-------------|---------------|
| Unauthorized Access | Unauthenticated or improperly authorized users gaining network access | BUC-C01, C02, C03 |
| Lateral Movement | Attacker moving between segments after initial compromise | All BUCs |
| Man-in-the-Middle | Traffic interception on LAN segments | BUC-C01, C05, C06 |
| Denial of Service | Flooding campus infrastructure to disrupt services | All BUCs |
| Data Exfiltration | Sensitive data leaving the network via covert channels | BUC-C01, C06, C07 |
| Rogue Device | Unauthorized device connecting to campus network | BUC-C01, C04 |
| Malware/Ransomware | Malicious code executed on campus endpoints | BUC-C01, C06 |
| Insider Threat | Legitimate user abusing network access | BUC-C01, C03, C06 |

### 4.2 Required Security Capabilities

| Capability | Function | Campus Location |
|-----------|----------|-----------------|
| **Network Access Control (NAC)** | Authenticate and authorize devices at access layer | Access switches, 802.1X |
| **Network Segmentation** | Enforce zone isolation via VLANs and firewall policy | Distribution + Firewall |
| **Stateful Firewall** | Inspect and control inter-zone traffic | Core/Firewall layer |
| **Intrusion Prevention (IPS)** | Detect and block known attack signatures | Firewall / inline sensor |
| **DNS Security** | Block malicious domains, prevent DNS exfiltration | Internet Edge |
| **URL Filtering** | Control web access by category and reputation | Internet Edge |
| **Malware Defense** | File inspection on ingress/egress | Internet Edge, Endpoints |
| **Encrypted Traffic Analytics (ETA)** | Detect threats in encrypted flows without decryption | Core / Internet Edge |
| **Network Behavior Analytics** | Baseline and alert on anomalous traffic patterns | Visibility infrastructure |
| **Security Information & Event Mgmt (SIEM)** | Aggregate and correlate logs and events | Management Zone |
| **Privileged Access Management (PAM)** | Control and audit admin access to infrastructure | Management Zone |

---

## 5. Secure Campus Architecture Design

### 5.1 Access Layer Design Requirements

- All access ports must authenticate via **802.1X** (EAP-TLS preferred; MAB as fallback for non-802.1X devices)
- Access ports must enforce **VLAN assignment** based on authentication result (dynamic VLAN assignment via RADIUS)
- Access ports must apply **QoS marking** at ingress (DSCP trust boundary at edge)
- Access ports must support **BPDU Guard** and **Root Guard** on all user-facing ports
- Access ports must implement **Dynamic ARP Inspection (DAI)** and **DHCP Snooping**
- Access switches must support **port security** or **IP Source Guard** to prevent address spoofing

### 5.2 Distribution Layer Design Requirements

- Distribution switches aggregate access VLANs via **802.1Q trunking**
- Distribution must implement **RSTP (802.1w)** or **MSTP (802.1s)** for loop prevention
- Distribution must provide **redundant uplinks** to the firewall pair (active-active or active-passive per site size)
- Distribution switches should not perform Layer 3 routing — routing is centralized at the firewall layer
- Inter-distribution traffic must be **hair-pinned through the firewall** for policy enforcement

### 5.3 Firewall / Core Layer Design Requirements

- Firewalls must act as **Layer 3 default gateways** for all campus VLANs and DMZ subnets
- Firewalls must implement **stateful inspection** on all inter-zone traffic flows
- Firewall policy must enforce **default-deny** between all security zones
- Explicit permit rules must reference a **Business Use Case** (traceability requirement)
- Firewalls must synchronize **session state** in HA pairs for seamless failover
- Firewall pairs must support **clustering or active-active** HA at large sites
- Firewalls must log **all permit and deny decisions** to the SIEM

### 5.4 Internet Edge Design Requirements

- Internet edge must implement separate logical paths for:
  - **User internet browsing** (inspected, filtered)
  - **Site-to-site VPN termination** (IPsec/IKEv2)
  - **Published service access** (reverse proxy / DMZ)
- Internet links must be **multi-homed** for redundancy (minimum 2 ISP links at small sites, 3 at large)
- Inbound traffic to published services must pass through a **DMZ reverse proxy or WAF**
- All internet-bound traffic must traverse **URL filtering and malware inspection**
- **DNS sinkholes** must be deployed for known-malicious domain blocking

---

## 6. Segmentation Architecture

### 6.1 VLAN Segmentation Model

SAFE recommends population-based segmentation. Each distinct user or device population receives a dedicated VLAN and subnet:

| Segment | Zone | Default Route | Inter-zone Policy |
|---------|------|--------------|-------------------|
| Employees | User | Firewall | Permit to DC apps; deny to other user zones |
| Contractors | User (restricted) | Firewall | Internet only + specific app access |
| Guests | Guest | Firewall | Internet only; deny all internal |
| Voice | Voice | Firewall | Voice gateway + CUCM only |
| IoT / Building | IoT | Firewall | Specific controller IPs only |
| Servers (local) | Server | Firewall | Permit from specific user zones only |
| Management (OOB) | Management | Mgmt firewall | Jump host access only |

### 6.2 Macro-Segmentation vs. Micro-Segmentation

**Macro-segmentation** (enforced at this layer):
- Implemented via VLANs and firewall zone policies
- Separates major population groups and functional zones
- Coarse-grained: VLAN = population

**Micro-segmentation** (IBN/SD-Access layer — see companion ARD):
- Implemented via Security Group Tags (SGTs) or VXLAN/EVPN group policies
- Allows user/device-level policies independent of VLAN
- Fine-grained: policy follows the identity, not the port

---

## 7. Security Capabilities by Domain

### 7.1 Capability Heat Map

| Security Capability | Access | Distribution | Firewall/Core | Internet Edge | Management |
|--------------------|--------|-------------|--------------|--------------|------------|
| 802.1X / NAC | ● | | | | |
| DHCP Snooping / DAI | ● | | | | |
| QoS Marking | ● | ● | | | |
| VLAN Segmentation | ● | ● | | | |
| Stateful Firewall | | | ● | ● | |
| IPS | | | ● | ● | |
| URL Filtering | | | | ● | |
| DNS Security | | | | ● | |
| Malware Defense | | | | ● | |
| PAM / Jump Host | | | | | ● |
| SIEM / Logging | ● | ● | ● | ● | ● |
| Encrypted Traffic Analytics | | | ● | ● | |

● = Primary enforcement point

---

## 8. Architecture Requirements (Quantitative Criteria)

These requirements are the measurable compliance criteria that any implementation must satisfy. They are derived from the SAFE Secure Campus framework and align with the HLD's design intent.

### 8.1 Availability Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| AVL-01 | Campus network availability (large site) | ≥ 99.99% (< 53 min/year downtime) |
| AVL-02 | Campus network availability (small site) | ≥ 99.9% (< 8.7 hr/year downtime) |
| AVL-03 | Firewall failover time (large site, active-active) | < 1 second (session preservation) |
| AVL-04 | Firewall failover time (small site, active-passive) | ≤ 10 seconds |
| AVL-05 | Access layer redundancy convergence (RSTP) | ≤ 2 seconds |
| AVL-06 | Internet link failover time | ≤ 60 seconds |

### 8.2 Security Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| SEC-01 | All access ports must enforce 802.1X | 100% of user-facing ports |
| SEC-02 | Inter-zone firewall policy must default-deny | All zones (no implicit permit) |
| SEC-03 | All firewall permit rules must be documented and traceable to a BUC | 100% of rules |
| SEC-04 | All firewall events must be logged to SIEM | 100% of permit and deny events |
| SEC-05 | DNS security must block known-malicious domains | Sinkhole active for all egress DNS |
| SEC-06 | All internet-bound traffic must pass URL filtering | 100% of internet-bound flows |
| SEC-07 | Privileged administrative access must use jump host | 100% of admin sessions |
| SEC-08 | All admin sessions must be audit-logged | 100% of sessions, ≥ 90-day retention |

### 8.3 Segmentation Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| SEG-01 | Each distinct user/device population must have a dedicated VLAN | 1:1 VLAN-to-population mapping |
| SEG-02 | Guest zone must have no route to any internal subnet | Zero routes to RFC1918 space |
| SEG-03 | IoT zone must have no lateral access to user zones | Default-deny; permit only to specific controllers |
| SEG-04 | Voice zone must be isolated from data traffic | Dedicated VLAN; QoS-marked DSCP EF (46) |
| SEG-05 | Management zone must be reachable only via designated jump hosts | No direct access from production VLANs |

### 8.4 Performance Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| PERF-01 | Voice traffic end-to-end delay (campus to gateway) | ≤ 150 ms one-way |
| PERF-02 | Voice traffic jitter | ≤ 30 ms |
| PERF-03 | Voice packet loss | ≤ 1% |
| PERF-04 | Business-critical application traffic prioritization | DSCP AF41 or higher |
| PERF-05 | Management traffic prioritization | DSCP CS2 or higher |

### 8.5 Scalability Requirements

| Requirement ID | Requirement | Target Metric |
|---------------|-------------|--------------|
| SCAL-01 | Architecture must support addition of new population VLANs without redesign | VLAN + firewall rule addition only |
| SCAL-02 | Architecture must support new sites without core redesign | VPN mesh expansion only |
| SCAL-03 | New DMZ services must be deployable without production impact | Dedicated DMZ zone addition |

---

## 9. Compliance Mapping to HLD

The following table maps each HLD section to the relevant SAFE ARD requirement IDs, identifying where the HLD satisfies the ARD and where gaps exist.

| HLD Section | ARD Requirements | Status |
|-------------|-----------------|--------|
| Architecture Overview / Design Principles | SEC-02, SEC-03, SCAL-01 | ✅ Addressed |
| Large Site Three-Tier Architecture | AVL-01, AVL-03, AVL-05 | ✅ Addressed |
| Small Site Two-Tier Architecture | AVL-02, AVL-04, AVL-05 | ✅ Addressed |
| Switching Infrastructure (RSTP, trunking) | AVL-05, SEG-01 | ✅ Addressed |
| Port Configuration Standards | SEC-01, PERF-01..05 | ⚠️ QoS addressed; 802.1X not mentioned |
| Population Types / VLAN Segmentation | SEG-01..05 | ✅ Addressed |
| Firewall Architecture | SEC-02, SEC-03, AVL-03/04 | ⚠️ Policy traceability (SEC-03) not addressed |
| DMZ Architecture | SEC-06, SEG-03 | ✅ Addressed |
| Internet Connectivity | AVL-06, SEC-05, SEC-06 | ⚠️ DNS security and URL filtering not specified |
| Inter-Site VPN | AVL-06, SCAL-02 | ✅ Addressed |
| Management Networks | SEC-07, SEC-08, SEG-05 | ✅ Addressed |
| **Security Capabilities (802.1X, NAC, IPS, SIEM)** | SEC-01, SEC-04, SEC-07, SEC-08 | ❌ Not present in HLD — significant gap |

### 9.1 Key Gaps Identified

The HLD covers the **structural and connectivity** requirements well. The principal gaps relative to the SAFE ARD are:

1. **No security capability specification** — The HLD does not mention 802.1X/NAC, IPS, URL filtering, DNS security, or SIEM. These are required capabilities in SAFE.
2. **Firewall rule traceability** — The HLD defines zones but does not mandate that firewall rules be traceable to Business Use Cases (SEC-03).
3. **Wireless not in scope** — The HLD explicitly excludes wireless, but SAFE requires NAC to cover wireless access as well.
4. **No threat model** — The HLD has no threat vector analysis; SAFE requires this as the justification for every architectural choice.

---

## 10. References

- Cisco SAFE Secure Campus Architecture Guide (Design Zone Security): https://www.cisco.com/c/en/us/solutions/collateral/enterprise/design-zone-security/safe-secure-campus-architecture-guide.pdf
- Cisco SAFE Secure Internet Architecture Guide: https://www.cisco.com/c/en/us/solutions/collateral/enterprise/design-zone-security/safe-secure-internet-architecture-guide.pdf
- Cisco SAFE Architecture Toolkit: https://www.cisco.com/c/dam/en/us/solutions/collateral/enterprise/design-zone-security/safe-architecture-toolkit.pdf
- Cisco Campus LAN and WLAN Design Guide (CVD): https://www.cisco.com/c/en/us/td/docs/solutions/CVD/Campus/cisco-campus-lan-wlan-design-guide.html
- RFC 1918 — Address Allocation for Private Internets
- IEEE 802.1X — Port-Based Network Access Control
- IEEE 802.1Q — Virtual LANs
- RFC 2697 / 2698 — QoS Metering (srTCM / trTCM)
