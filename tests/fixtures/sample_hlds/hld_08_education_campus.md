# Westbrook University - Education Campus Network

## Overview

Westbrook University is a small private university with 2,500 students, 300 faculty, and 150 administrative staff across a single campus with six buildings: Main Hall (administration), Science Building, Library, Student Center, Dormitory Complex, and Athletics. The network supports distinct populations for students, faculty, research labs, administrative staff, and campus-wide guest access.

The architecture separates academic research traffic from administrative systems using zone-based firewall policies. Research lab VLANs carry high-bandwidth scientific data and must not be impacted by student streaming traffic. The DMZ hosts the university website, learning management system (LMS), library catalog, and a research data repository. Student dormitory WiFi is rate-limited and isolated.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Faculty-Admin | 100 | 10.60.100.0/23 | - | Medium | AF21 | 500Mbps |
| Voice | 110 | 10.60.110.0/24 | - | High | EF | 100Mbps |
| Student-Wired | 120 | 10.60.120.0/22 | - | Low | AF11 | 500Mbps |
| Research-Lab | 130 | 10.60.130.0/24 | - | High | AF41 | 1Gbps |
| Student-WiFi | 140 | 10.60.140.0/21 | - | Low | BE | 1Gbps |
| IoT-Campus | 150 | 10.60.150.0/24 | - | Low | CS1 | 50Mbps |
| Management | 160 | 10.60.160.0/27 | - | High | CS6 | 20Mbps |
| Library-Systems | 165 | 10.60.165.0/25 | - | Medium | AF21 | 200Mbps |
| AV-Classroom | 170 | 10.60.170.0/25 | - | High | AF41 | 300Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| Web-DMZ | 200 | University website and admissions portal | Internet | 2 |
| LMS-DMZ | 210 | Learning management system (Canvas/Moodle) | Internet, Student-WiFi | 2 |
| Library-DMZ | 220 | Library catalog and digital archives | Internet, Faculty-Admin | 1 |
| Research-Repo | 230 | Research data repository and preprint server | Internet, Research-Lab | 1 |
| Email-DMZ | 240 | Mail relay and spam filtering | Internet | 1 |
| Proxy | 260 | Content filter and reverse proxy | Internet | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| wbu-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-westbrook-acc01 | 192.168.100.121 |
| wbu-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-westbrook-acc02 | 192.168.100.122 |
| wbu-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-westbrook-acc03 | 192.168.100.123 |
| wbu-acc-04 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-westbrook-acc04 | 192.168.100.124 |
| wbu-acc-05 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-westbrook-acc05 | 192.168.100.125 |
| wbu-core-01 | Nokia | srlinux | CORE_SWITCH | HQ | clab-westbrook-core01 | 192.168.100.126 |
| wbu-core-02 | Nokia | srlinux | CORE_SWITCH | HQ | clab-westbrook-core02 | 192.168.100.127 |
| wbu-usf-01 | VyOS | vyos | FIREWALL | HQ | clab-westbrook-usf01 | 192.168.100.128 |
| wbu-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-westbrook-dmzfw01 | 192.168.100.129 |
| wbu-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-westbrook-edge01 | 192.168.100.130 |
| wbu-edge-02 | FRR | frr | EDGE_ROUTER | HQ | clab-westbrook-edge02 | 192.168.100.131 |
