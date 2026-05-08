# Cascade Financial Services - Medium Campus Network

## Overview

Cascade Financial Services operates a medium-sized campus with approximately 500 employees across a four-building headquarters complex. The network implements a traditional three-tier architecture with access, aggregation, and edge layers. Four access switches serve individual buildings, two aggregation switches provide redundant core connectivity, and two edge routers connect to dual ISP uplinks.

The security architecture features dual firewall pairs: a User Services Firewall (USF) pair handling population-to-population traffic and a DMZ Firewall (DMZFW) pair protecting the extensive DMZ zone. Five DMZ zones support externally accessible services including web applications, DNS, Active Directory, file sharing, and a reverse proxy tier. Transit VLAN 300 interconnects the USF and DMZFW pairs.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | 10.20.100.0/22 | - | Medium | AF21 | 1Gbps |
| Voice | 110 | 10.20.110.0/24 | - | High | EF | 200Mbps |
| Printer | 120 | 10.20.120.0/25 | - | Low | AF11 | 50Mbps |
| Video | 130 | 10.20.130.0/24 | - | High | AF41 | 500Mbps |
| Guest | 140 | 10.20.140.0/23 | - | Low | BE | 200Mbps |
| IoT | 150 | 10.20.150.0/24 | - | Low | CS1 | 100Mbps |
| Management | 160 | 10.20.160.0/27 | - | High | CS6 | 50Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| DMZ-Servers | 200 | Web application servers | Internet | 4 |
| DNS-DMZ | 210 | Authoritative and recursive DNS | Internet, Employee | 2 |
| AD-DMZ | 220 | Active Directory domain controllers | Employee, VPN | 2 |
| File-DMZ | 230 | Secure file transfer gateway | Internet, Employee | 1 |
| Proxy | 260 | Reverse proxy and WAF | Internet | 2 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| csf-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-cascade-acc01 | 192.168.100.121 |
| csf-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-cascade-acc02 | 192.168.100.122 |
| csf-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-cascade-acc03 | 192.168.100.123 |
| csf-acc-04 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-cascade-acc04 | 192.168.100.124 |
| csf-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-cascade-agg01 | 192.168.100.125 |
| csf-agg-02 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-cascade-agg02 | 192.168.100.126 |
| csf-usf-01 | VyOS | vyos | FIREWALL | HQ | clab-cascade-usf01 | 192.168.100.127 |
| csf-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-cascade-dmzfw01 | 192.168.100.128 |
| csf-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-cascade-edge01 | 192.168.100.129 |
| csf-edge-02 | FRR | frr | EDGE_ROUTER | HQ | clab-cascade-edge02 | 192.168.100.130 |
