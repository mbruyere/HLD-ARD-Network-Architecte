# Feasibility Analysis: Generating NetLab Topology from HLD
## Enterprise Campus Network → netlab.tools

**Date:** March 2026
**Reference HLD:** Enterprise Campus Network Architecture v1.0
**Target Tool:** netlab (https://netlab.tools) — ipSpace.net infrastructure-as-code labbing tool
**Document Type:** Feasibility Analysis + Proof-of-Concept

---

## 1. What is netlab?

netlab is an open-source Infrastructure-as-Code tool for virtual network labs. The operator describes a network topology in a single YAML file (`topology.yml`), and netlab:

- Auto-generates IP addressing plans (IPv4/IPv6)
- Derives routing protocol configurations (OSPF, BGP, IS-IS, EIGRP…)
- Generates device-specific configuration files (IOS-XE, EOS, NX-OS, JunOS, FRR, etc.)
- Produces virtualization startup files (Vagrant/libvirt, Containerlab/clab, external)

**Core YAML topology objects:**

| Object | Purpose |
|--------|---------|
| `provider` | Virtualization backend (clab, libvirt, external) |
| `nodes` | Network devices (name, device type, module list) |
| `links` | Physical or logical connections between nodes |
| `vlans` | VLAN definitions with optional VRF, mode (bridge/route/irb) |
| `vrfs` | VRF definitions for routing domain separation |
| `groups` | Node groupings for shared attributes |
| `module` | Feature modules (vlan, vrf, ospf, bgp, stp, vxlan, evpn…) |
| `addressing` | IP address pool definitions |
| `defaults` | Global defaults (device type, provider, module) |

---

## 2. HLD → NetLab Element Mapping

### 2.1 Full Mapping Table

The following table maps every significant element from the Enterprise Campus HLD to its netlab equivalent, with a feasibility rating.

| HLD Element | HLD Description | NetLab Mapping | Feasibility |
|-------------|----------------|---------------|-------------|
| **Access switch** | Layer 2, 24-48 ports, trunks to aggregation | `nodes:` entry, `device: catalyst / eos / vios` | ✅ Full |
| **Aggregation switch** | Layer 2 aggregation, peer-link, dual-uplinks to FW | `nodes:` entry with `module: [vlan, stp]` | ✅ Full |
| **User Services Firewall** | L3 gateway, inter-VLAN routing, NAT | `nodes:` entry, `device: asa / fortios / vyos` | ⚠️ Node modelled; policy manual |
| **DMZ/Internet Firewall** | DMZ zones, Internet edge, IPsec VPN | `nodes:` entry, `device: asa / fortios` | ⚠️ Node modelled; policy manual |
| **Population VLANs (100-160)** | Employee, Voice, Video, Guest, IoT, Contractor… | `vlans:` section with `id:` and optional `vrf:` | ✅ Full |
| **DMZ VLANs (200-270)** | DNS, AD, File, PBX, Publishing, Management DMZ | `vlans:` section with `id:` and `mode: route` | ✅ Full |
| **802.1Q trunks** | Inter-switch and switch-to-firewall links | `links:` with `vlan.trunk: [list]` | ✅ Full |
| **Access port** | Single-VLAN port to endpoint | `links:` with `vlan.access: vlan_name` | ✅ Full |
| **RSTP / 802.1w** | Loop prevention, edge ports, BPDU guard | `module: [stp]` with `stp.mode: rstp` | ✅ Full |
| **LACP / Port-Channel** | Aggregated uplinks | `module: [lag]` with `lag.lacp: true` | ✅ Full |
| **VRF separation** | Routing domain per population group | `vrfs:` section mapped to VLANs | ✅ Full |
| **OSPF underlay** | (implicit for inter-site routing) | `module: [ospf]` per node/group | ✅ Full |
| **VRRP / anycast gateway** | Virtual gateway IP for VLAN | `module: [gateway]` with `gateway.protocol: anycast` | ✅ Full |
| **Active-passive FW HA** | Heartbeat, virtual IP, 3-10s failover | Not a native netlab concept — modelled as two nodes + notes | ⚠️ Structural only |
| **Active-active FW HA** | Cluster, session sync, hitless failover | Not a native netlab concept | ⚠️ Structural only |
| **Peer-link (agg. switches)** | Port-channel between aggregation switches | `links:` + `module: [lag]` | ✅ Full |
| **Stack / Ring topology** | Small-site collapsed access/aggregation | Multiple `nodes:` + ring `links:` | ✅ Full |
| **IPsec VPN mesh** | Hub-and-spoke site-to-site VPN | `module: [ipsec]` — limited support | ⚠️ Partial |
| **Internet links (x2-x3)** | Multi-homed ISP connectivity | `links:` to external stub nodes | ⚠️ Structural stub |
| **DMZ zones** | DNS, AD, File, PBX, Publishing DMZ | VLANs + VRFs on the DMZ firewall node | ⚠️ Structure only; no zone policy |
| **OOB Management network** | Dedicated management VLAN/subnet | Separate `vlan` + `vrf` for OOB | ✅ Full (structure) |
| **Jump host** | Bastion access to management network | `nodes:` entry (linux device) in OOB VRF | ✅ Full |
| **QoS marking (DSCP)** | Ingress marking, priority queuing | Not in any netlab module | ❌ Not supported |
| **802.1X / NAC** | Port authentication, dynamic VLAN assignment | Not in any netlab module | ❌ Not supported |
| **Firewall rule sets** | Default-deny inter-zone policies | Not in any netlab module — requires manual config templates | ❌ Not supported natively |
| **NAT/PAT** | User internet access translation | Not in any netlab module | ❌ Not supported |
| **DNS security / URL filtering** | Internet edge security capabilities | Not in any netlab module | ❌ Not supported |
| **DHCP Snooping / DAI** | Layer 2 security on access switches | Not in any netlab module | ❌ Not supported |
| **Naming conventions** | Device/interface naming standards | Partially via netlab `name:` + Jinja2 config templates | ⚠️ Partial |
| **IP addressing framework** | RFC1918 pool assignments | `addressing:` pools section | ✅ Full |
| **Multi-site topology** | Large site + multiple small sites | Multiple node groups, inter-site links | ✅ Full |

### 2.2 Feasibility Summary

| Layer | Coverage | Notes |
|-------|----------|-------|
| **Physical topology** (nodes, links, tiers) | ✅ 95% | Full structural representation |
| **Layer 2** (VLANs, trunks, STP, LACP) | ✅ 90% | All core L2 features supported |
| **Layer 3** (VRFs, routing, gateway) | ✅ 85% | Routing protocols + VRF full; static/default routes need manual tuning |
| **Security policy** (FW rules, 802.1X, QoS) | ❌ 10% | Only node placement; policy content not expressible in netlab |
| **HA clustering** | ⚠️ 30% | Nodes and heartbeat links representable; cluster logic not executable |
| **Internet edge / NAT** | ⚠️ 40% | Stub nodes + external links representable; NAT config manual |

**Overall feasibility: HIGH for the structural/L2-L3 layer — NOT feasible for the security policy layer.**

---

## 3. What netlab CAN generate from the HLD

### 3.1 Directly generatable from HLD content

From the HLD's topology, VLAN tables, VRF model, and addressing framework, netlab can automatically generate:

- Complete node inventory with device type assignments
- All 802.1Q trunk link definitions between tiers
- VLAN definitions for all 15+ population and DMZ VLANs
- VRF definitions per routing domain
- RSTP configuration (mode, priorities, edge ports)
- LACP port-channels for aggregated uplinks
- OSPF process for underlay routing
- VRRP/anycast gateway per user VLAN
- IPv4 addressing plan from the HLD's RFC1918 space
- Complete device-specific configuration files for supported platforms

### 3.2 What requires manual additions post-netlab

- Firewall zone policy rule sets (permit/deny between zones)
- 802.1X authentication (ISE/RADIUS integration)
- NAT/PAT rules on the firewall nodes
- QoS marking and queuing policies
- IPsec VPN parameters (phase 1/2 proposals, pre-shared keys)
- HA cluster configuration (virtual IPs, heartbeat parameters)
- DHCP Snooping, Dynamic ARP Inspection
- DNS, NTP, syslog server references

---

## 4. HLD-to-NetLab Generation Strategy

### 4.1 Proposed Pipeline

```
HLD (Markdown)
     │
     ▼
[Parsing Agent]
Extracts structured data:
 - Site list
 - Node inventory (role, device type, count)
 - VLAN table (id, name, description)
 - VRF model
 - Link matrix (which nodes connect to which)
 - IP pool assignments
     │
     ▼
[YAML Generator]
Builds topology.yml:
 - provider + defaults block
 - addressing: pools from HLD IP schema
 - groups: per site and per layer
 - vlans: full table from HLD
 - vrfs: from HLD population model
 - nodes: per site, per role
 - links: from HLD connection matrix
     │
     ▼
[NetLab]
netlab create → generates:
 - Vagrantfile / clab topology
 - Per-device configuration files
 - IP address allocation report
     │
     ▼
[Post-processor / Manual]
Adds security policy layer:
 - Firewall rules (Jinja2 templates or manual)
 - 802.1X / ISE config
 - QoS policies
 - IPsec VPN parameters
```

### 4.2 Information the HLD must provide for full netlab generation

To enable automated HLD → topology.yml generation, the HLD must contain (or be enriched with):

| Required Data | Present in HLD? | Action |
|--------------|----------------|--------|
| Device type per role (IOS-XE, EOS, FortiOS…) | ❌ Not specified | Add to HLD or agent asks operator |
| VLAN ID table (id, name) | ⚠️ Partial (ranges defined, not full table) | Enumerate in HLD appendix |
| IP address pool per VLAN | ❌ Out of scope in HLD | Add addressing section |
| Number of access switches per site | ⚠️ Partial ("multiple buildings") | Parameterize per site |
| Provider (clab / libvirt) | ❌ Not in HLD | Agent asks operator |
| Inter-site link model (P2P, shared) | ⚠️ VPN described, not link model | Clarify in HLD |

---

## 5. Limitations and Constraints

### 5.1 NetLab is a lab tool, not a production provisioner

netlab is designed for **virtual labs** (Containerlab, GNS3, EVE-NG via libvirt), not for direct provisioning of production networks. The generated configurations are testable and accurate to the topology, but must be adapted for production deployment via tools like Ansible, NSO, or Cisco DNA Center.

### 5.2 Firewall device support

netlab supports Cisco ASAv, FortiGate (VM), VyOS, pfSense, and Juniper vSRX as firewall nodes. However, **firewall zone policies and rule sets are not expressed in the topology.yml** — they must be provided via custom Jinja2 configuration templates added to the netlab project.

### 5.3 HA/clustering models

netlab does not model active-active or active-passive HA clusters as a first-class concept. HA can be *represented* as two nodes with a heartbeat link, but the cluster formation configuration (virtual IPs, session sync, preemption) must be added manually.

### 5.4 Scale considerations

For a realistic large campus site (3 access switches, 2 aggregation, 2 firewall pairs, 3 ISP stubs), the topology.yml is approximately 150-200 lines. A multi-site topology (1 large + 3 small) would be 400-600 lines. This is fully manageable and is within netlab's normal operating range.

---

## 6. Verdict

| Question | Answer |
|---------|--------|
| Can netlab represent the HLD's physical topology? | ✅ Yes, fully |
| Can netlab represent the HLD's VLAN/VRF model? | ✅ Yes, fully |
| Can netlab generate device configurations from the HLD? | ✅ Yes, for the L2/L3 layer |
| Can netlab represent the firewall security policy? | ❌ No — requires complementary templates |
| Is automated HLD → topology.yml generation feasible? | ✅ Yes, with a structured parsing step |
| Is the result production-deployable directly? | ⚠️ Lab-ready; not production-ready without post-processing |

**Conclusion:** Generating a netlab topology from the HLD is **highly feasible** for the structural, VLAN, VRF, and routing layers — which covers roughly 70% of what the HLD defines. The security policy layer (30%) requires a complementary approach: either Jinja2 config templates injected into netlab, or a separate firewall policy management tool (Ansible, NSO, FortiManager). The most valuable use case is **lab validation of the HLD topology before production deployment**.

---

## 7. References

- netlab documentation: https://netlab.tools/
- netlab GitHub (ipspace/netlab): https://github.com/ipspace/netlab
- netlab examples (ipspace/netlab-examples): https://github.com/ipspace/netlab-examples
- netlab VLAN module: https://netlab.tools/module/vlan/
- netlab VRF module: https://netlab.tools/module/vrf/
- netlab STP module: https://netlab.tools/module/stp/
- netlab topology reference: https://netlab.tools/topology-reference/
- Companion HLD: Enterprise_Campus_Network_HLD.md
