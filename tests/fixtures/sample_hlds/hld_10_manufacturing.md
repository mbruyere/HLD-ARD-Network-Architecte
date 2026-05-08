# Ironworks Precision Manufacturing - Manufacturing Plant Network

## Overview

Ironworks Precision Manufacturing operates a single-site industrial facility with corporate offices, a production floor, and a quality control laboratory. The network architecture follows the Purdue Model (ISA-95/IEC 62443) with strict segmentation between IT and OT (Operational Technology) zones. SCADA systems, PLCs, and industrial IoT sensors operate on dedicated VLANs with unidirectional firewall policies preventing any traffic originating from the corporate network from reaching the OT zone.

The facility employs 180 people: 50 in corporate offices, 110 on the production floor, and 20 in the QC lab. A data diode architecture enforces one-way data flow from OT to IT for monitoring dashboards. The DMZ between IT and OT zones hosts a historian server that aggregates production data, an MES (Manufacturing Execution System) gateway, and a secure remote access jump host for vendor maintenance. Guest WiFi is available only in the lobby and break room, completely air-gapped from OT networks.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Corporate-IT | 100 | 10.80.100.0/24 | - | Medium | AF21 | 500Mbps |
| Voice | 110 | 10.80.110.0/25 | - | High | EF | 50Mbps |
| SCADA-Control | 120 | 10.80.120.0/24 | - | High | CS5 | 200Mbps |
| HMI-Operator | 130 | 10.80.130.0/25 | - | High | AF41 | 300Mbps |
| Guest-Lobby | 140 | 10.80.140.0/25 | - | Low | BE | 50Mbps |
| Industrial-IoT | 150 | 10.80.150.0/23 | - | Medium | CS3 | 500Mbps |
| Management | 160 | 10.80.160.0/27 | - | High | CS6 | 20Mbps |
| QC-Lab | 165 | 10.80.165.0/25 | - | Medium | AF21 | 200Mbps |
| Safety-Systems | 170 | 10.80.170.0/26 | - | High | CS7 | 100Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| Historian-DMZ | 200 | Production data historian (OSIsoft PI) | Corporate-IT, SCADA-Control | 2 |
| MES-Gateway | 210 | Manufacturing execution system interface | Corporate-IT, HMI-Operator | 1 |
| Remote-Access | 220 | Vendor maintenance jump host | VPN, Internet | 1 |
| Patch-Staging | 230 | OT patch validation and deployment | Management | 1 |
| SIEM-Collector | 240 | Security event aggregation from OT zone | SCADA-Control, Industrial-IoT | 1 |
| Proxy | 260 | Outbound web proxy for corporate IT | Corporate-IT | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| iw-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ironworks-acc01 | 192.168.100.121 |
| iw-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ironworks-acc02 | 192.168.100.122 |
| iw-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ironworks-acc03 | 192.168.100.123 |
| iw-ot-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ironworks-otacc01 | 192.168.100.124 |
| iw-ot-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ironworks-otacc02 | 192.168.100.125 |
| iw-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-ironworks-agg01 | 192.168.100.126 |
| iw-agg-02 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-ironworks-agg02 | 192.168.100.127 |
| iw-it-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-ironworks-itfw01 | 192.168.100.128 |
| iw-ot-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-ironworks-otfw01 | 192.168.100.129 |
| iw-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-ironworks-dmzfw01 | 192.168.100.130 |
| iw-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-ironworks-edge01 | 192.168.100.131 |
