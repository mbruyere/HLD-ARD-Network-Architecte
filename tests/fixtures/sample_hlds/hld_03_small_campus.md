# Greenfield Insurance - Small Campus Network

## Overview

Greenfield Insurance operates a single campus with approximately 200 employees across two buildings connected by fiber. The network supports the full range of population VLANs including employee, voice, printer, video conferencing, guest wireless, IoT sensors, and network management. Three access switches are distributed across floors, feeding into a central aggregation switch.

A pair of VyOS firewalls in active-standby configuration protect the DMZ zone which hosts public-facing web services, DNS, and an Active Directory federation proxy. The aggregation layer provides inter-VLAN routing for internal traffic while the firewalls handle north-south traffic flows.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | 10.10.100.0/22 | - | Medium | AF21 | 500Mbps |
| Voice | 110 | 10.10.110.0/24 | - | High | EF | 100Mbps |
| Printer | 120 | 10.10.120.0/25 | - | Low | AF11 | 20Mbps |
| Video | 130 | 10.10.130.0/24 | - | High | AF41 | 200Mbps |
| Guest | 140 | 10.10.140.0/24 | - | Low | BE | 100Mbps |
| IoT | 150 | 10.10.150.0/24 | - | Low | CS1 | 50Mbps |
| Management | 160 | 10.10.160.0/27 | - | High | CS6 | 20Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| DMZ-Web | 200 | Customer portal and quoting engine | Internet | 2 |
| DNS-DMZ | 210 | External DNS resolution | Internet | 1 |
| AD-DMZ | 220 | AD Federation Services proxy | Employee, Internet | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| gfi-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-greenfield-acc01 | 192.168.100.121 |
| gfi-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-greenfield-acc02 | 192.168.100.122 |
| gfi-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-greenfield-acc03 | 192.168.100.123 |
| gfi-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-greenfield-agg01 | 192.168.100.124 |
| gfi-usf-01 | VyOS | vyos | FIREWALL | HQ | clab-greenfield-usf01 | 192.168.100.125 |
| gfi-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-greenfield-dmzfw01 | 192.168.100.126 |
