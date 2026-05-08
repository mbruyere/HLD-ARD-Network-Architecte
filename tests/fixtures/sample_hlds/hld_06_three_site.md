# Pinnacle Logistics - Three Site Network

## Overview

Pinnacle Logistics operates a headquarters distribution center and two regional branch warehouses. The HQ site houses 250 employees including corporate IT, operations management, and a call center. Branch-A is a mid-size regional warehouse with 60 staff, and Branch-B is a smaller fulfillment center with 25 staff. All sites connect via MPLS WAN with Internet backup.

HQ runs the full complement of seven population VLANs and a comprehensive DMZ for logistics applications. Branch-A supports five VLANs with no local DMZ. Branch-B operates a minimal three-VLAN deployment. Each site has independent firewall and Internet egress. HQ additionally deploys an aggregation layer and edge routers for dual ISP connectivity.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | 10.40.100.0/22 | 10.41.100.0/24 | Medium | AF21 | 500Mbps |
| Voice | 110 | 10.40.110.0/24 | 10.41.110.0/25 | High | EF | 150Mbps |
| Printer | 120 | 10.40.120.0/25 | 10.41.120.0/26 | Low | AF11 | 30Mbps |
| Video | 130 | 10.40.130.0/24 | - | High | AF41 | 200Mbps |
| Guest | 140 | 10.40.140.0/24 | 10.41.140.0/25 | Low | BE | 100Mbps |
| IoT | 150 | 10.40.150.0/24 | 10.41.150.0/25 | Low | CS1 | 80Mbps |
| Management | 160 | 10.40.160.0/27 | 10.41.160.0/28 | High | CS6 | 20Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| DMZ-Servers | 200 | Warehouse management system (WMS) | Internet, Employee | 3 |
| DNS-DMZ | 210 | DNS resolution for all sites | Internet | 1 |
| AD-DMZ | 220 | Active Directory for multi-site auth | Employee, VPN | 2 |
| File-DMZ | 230 | EDI file transfer gateway | Internet, Partners | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| pnl-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-pinnacle-acc01 | 192.168.100.121 |
| pnl-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-pinnacle-acc02 | 192.168.100.122 |
| pnl-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-pinnacle-acc03 | 192.168.100.123 |
| pnl-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-pinnacle-agg01 | 192.168.100.124 |
| pnl-usf-01 | VyOS | vyos | FIREWALL | HQ | clab-pinnacle-usf01 | 192.168.100.125 |
| pnl-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-pinnacle-dmzfw01 | 192.168.100.126 |
| pnl-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-pinnacle-edge01 | 192.168.100.127 |
| pnl-bra-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-A | clab-pinnacle-braacc01 | 192.168.100.128 |
| pnl-bra-fw-01 | VyOS | vyos | FIREWALL | BR-A | clab-pinnacle-brafw01 | 192.168.100.129 |
| pnl-brb-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-B | clab-pinnacle-brbacc01 | 192.168.100.130 |
| pnl-brb-fw-01 | VyOS | vyos | FIREWALL | BR-B | clab-pinnacle-brbfw01 | 192.168.100.131 |
