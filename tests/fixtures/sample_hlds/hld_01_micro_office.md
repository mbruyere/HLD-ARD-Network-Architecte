# Apex Consulting Group - Micro Office Network

## Overview

Apex Consulting Group operates a single micro office with 15 employees in a shared coworking floor. The network requires basic segmentation between employee workstations, VoIP phones, and a guest wireless network. No DMZ is required as all services are cloud-hosted. A single managed switch and firewall provide adequate infrastructure for this deployment.

The design prioritizes simplicity and cost-effectiveness while maintaining proper network segmentation and QoS for voice traffic.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Employee | 100 | - | 10.1.100.0/24 | Medium | AF21 | 100Mbps |
| Voice | 110 | - | 10.1.110.0/24 | High | EF | 50Mbps |
| Guest | 140 | - | 10.1.140.0/24 | Low | BE | 25Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| apex-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-apex-acc01 | 192.168.100.121 |
| apex-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-apex-fw01 | 192.168.100.122 |
