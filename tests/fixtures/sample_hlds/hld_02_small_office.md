# Meridian Legal Partners - Small Office Network

## Overview

Meridian Legal Partners is a 40-person law firm occupying a single floor in a downtown office building. The network supports employee workstations, VoIP desk phones, a dedicated printer VLAN, a guest wireless network, and a management VLAN for network devices. Two access switches serve the east and west wings of the office floor.

A small DMZ hosts an externally accessible document portal and a DNS relay for split-horizon resolution. A single VyOS firewall provides inter-VLAN routing, NAT, and stateful packet inspection.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | - | 10.1.100.0/24 | Medium | AF21 | 200Mbps |
| Voice | 110 | - | 10.1.110.0/24 | High | EF | 50Mbps |
| Printer | 120 | - | 10.1.120.0/25 | Low | AF11 | 10Mbps |
| Guest | 140 | - | 10.1.140.0/24 | Low | BE | 50Mbps |
| Management | 160 | - | 10.1.160.0/27 | High | CS6 | 10Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| DMZ-Portal | 200 | Document sharing portal | Internet | 1 |
| DNS-DMZ | 210 | Split-horizon DNS relay | Employee, Internet | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| mrd-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-meridian-acc01 | 192.168.100.121 |
| mrd-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-meridian-acc02 | 192.168.100.122 |
| mrd-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-meridian-fw01 | 192.168.100.123 |
