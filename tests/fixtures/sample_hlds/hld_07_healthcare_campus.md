# Lakeview Regional Medical Center - Healthcare Campus Network

## Overview

Lakeview Regional Medical Center is a 150-bed community hospital with an attached medical office building and outpatient clinic. The network architecture prioritizes HIPAA compliance, clinical system availability, and strict segmentation between medical device networks, clinical workstations, and public-facing services. Biomedical IoT devices (infusion pumps, patient monitors, imaging systems) are isolated on a dedicated VLAN with restrictive firewall policies.

The campus deploys a robust three-tier architecture with four access switches covering the hospital wings, medical office building, and data center. Dual aggregation switches provide redundant core services, and dual firewalls enforce zone-based segmentation. A comprehensive DMZ supports the patient portal, telehealth gateway, PACS image sharing, and health information exchange (HIE) endpoints. Patient WiFi is completely isolated from clinical networks.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Clinical-Workstation | 100 | 10.50.100.0/22 | - | High | AF31 | 1Gbps |
| Voice | 110 | 10.50.110.0/24 | - | High | EF | 200Mbps |
| Biomedical-IoT | 120 | 10.50.120.0/24 | - | High | AF41 | 500Mbps |
| Video-Telehealth | 130 | 10.50.130.0/24 | - | High | AF41 | 500Mbps |
| Patient-WiFi | 140 | 10.50.140.0/22 | - | Low | BE | 200Mbps |
| Facilities-IoT | 150 | 10.50.150.0/24 | - | Medium | CS1 | 100Mbps |
| Management | 160 | 10.50.160.0/27 | - | High | CS6 | 50Mbps |
| Printer-Label | 170 | 10.50.170.0/25 | - | Low | AF11 | 30Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| Patient-Portal | 200 | MyChart patient portal | Internet | 2 |
| DNS-DMZ | 210 | Healthcare DNS resolution | Internet, Clinical | 1 |
| AD-DMZ | 220 | Clinical Active Directory | Clinical-Workstation | 2 |
| PACS-Share | 230 | Radiology image exchange (DICOMweb) | Internet, Partners | 1 |
| Telehealth-GW | 240 | Telehealth video gateway | Internet | 2 |
| HIE-Exchange | 250 | Health information exchange endpoint | Partners, Internet | 1 |
| Proxy | 260 | Reverse proxy and SSL offload | Internet | 1 |
| Mgmt-DMZ | 270 | Jump host for remote administration | VPN | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| lvm-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-lakeview-acc01 | 192.168.100.121 |
| lvm-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-lakeview-acc02 | 192.168.100.122 |
| lvm-acc-03 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-lakeview-acc03 | 192.168.100.123 |
| lvm-acc-04 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-lakeview-acc04 | 192.168.100.124 |
| lvm-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-lakeview-agg01 | 192.168.100.125 |
| lvm-agg-02 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-lakeview-agg02 | 192.168.100.126 |
| lvm-usf-01 | VyOS | vyos | FIREWALL | HQ | clab-lakeview-usf01 | 192.168.100.127 |
| lvm-dmzfw-01 | VyOS | vyos | FIREWALL | HQ | clab-lakeview-dmzfw01 | 192.168.100.128 |
| lvm-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-lakeview-edge01 | 192.168.100.129 |
| lvm-edge-02 | FRR | frr | EDGE_ROUTER | HQ | clab-lakeview-edge02 | 192.168.100.130 |
