# Orion Architecture Group - Dual Site Network

## Overview

Orion Architecture Group operates two locations: a headquarters office with 120 staff and a satellite design studio (BR-A) with 30 staff. Both sites share a common VLAN numbering scheme and are connected via a site-to-site VPN tunnel over public Internet. Each site has independent Internet egress and firewall services.

The HQ site uses a two-tier access/firewall topology with two access switches, while BR-A operates with a single access switch. Both sites support employee, voice, guest, printer, and management VLANs. A small DMZ at HQ hosts the firm's project portfolio website and a VPN concentrator endpoint. BR-A has no local DMZ services.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | 10.30.100.0/24 | 10.31.100.0/24 | Medium | AF21 | 300Mbps |
| Voice | 110 | 10.30.110.0/24 | 10.31.110.0/25 | High | EF | 100Mbps |
| Printer | 120 | 10.30.120.0/25 | 10.31.120.0/26 | Low | AF11 | 20Mbps |
| Guest | 140 | 10.30.140.0/24 | 10.31.140.0/24 | Low | BE | 50Mbps |
| Management | 160 | 10.30.160.0/27 | 10.31.160.0/28 | High | CS6 | 10Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| DMZ-Web | 200 | Project portfolio website | Internet | 1 |
| VPN-DMZ | 250 | Site-to-site VPN concentrator | BR-A, Internet | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| ori-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-orion-acc01 | 192.168.100.121 |
| ori-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-orion-acc02 | 192.168.100.122 |
| ori-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-orion-fw01 | 192.168.100.123 |
| ori-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-orion-edge01 | 192.168.100.124 |
| ori-br-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-A | clab-orion-bracc01 | 192.168.100.125 |
| ori-br-fw-01 | VyOS | vyos | FIREWALL | BR-A | clab-orion-brfw01 | 192.168.100.126 |
