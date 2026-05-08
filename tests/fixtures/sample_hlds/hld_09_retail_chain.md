# BrightMart Retail - Retail Chain Network

## Overview

BrightMart Retail operates a corporate headquarters and three branch retail stores. The HQ houses 80 corporate staff including IT, merchandising, and supply chain teams. Each branch store has 15-25 staff with point-of-sale (POS) terminals, inventory scanners, digital signage, and customer WiFi. PCI-DSS compliance requires strict isolation of POS traffic from all other network segments.

Branch stores use a simplified two-tier architecture with a single access switch and firewall. The HQ site adds an aggregation switch and edge router for WAN connectivity. A minimal DMZ at HQ hosts the e-commerce web frontend and an inventory API endpoint. Branch stores have no local DMZ. All POS traffic is encrypted and tunneled to the HQ payment processing gateway.

### Population Summary Table

| Name | VLAN | Large Site | Small Site | QoS Priority | DSCP | Bandwidth |
|---|---|---|---|---|---|---|
| Corporate | 100 | 10.70.100.0/24 | - | Medium | AF21 | 300Mbps |
| Voice | 110 | 10.70.110.0/25 | 10.71.110.0/26 | High | EF | 50Mbps |
| POS-Terminal | 120 | 10.70.120.0/25 | 10.71.120.0/26 | High | AF31 | 100Mbps |
| Customer-WiFi | 140 | 10.70.140.0/24 | 10.71.140.0/24 | Low | BE | 100Mbps |
| Digital-Signage | 150 | 10.70.150.0/26 | 10.71.150.0/27 | Low | CS1 | 50Mbps |
| Management | 160 | 10.70.160.0/27 | 10.71.160.0/28 | High | CS6 | 10Mbps |

### DMZ Summary Table

| Zone | VLAN | Purpose | Access From | Device Count |
|---|---|---|---|---|
| E-Commerce | 200 | Online storefront and order API | Internet | 2 |
| Inventory-API | 210 | Inventory sync endpoint for branches | BR-A, BR-B, BR-C | 1 |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IPv4 |
|---|---|---|---|---|---|---|
| bm-acc-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-brightmart-acc01 | 192.168.100.121 |
| bm-acc-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-brightmart-acc02 | 192.168.100.122 |
| bm-agg-01 | Nokia | srlinux | AGGREGATION_SWITCH | HQ | clab-brightmart-agg01 | 192.168.100.123 |
| bm-fw-01 | VyOS | vyos | FIREWALL | HQ | clab-brightmart-fw01 | 192.168.100.124 |
| bm-edge-01 | FRR | frr | EDGE_ROUTER | HQ | clab-brightmart-edge01 | 192.168.100.125 |
| bm-bra-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-A | clab-brightmart-braacc01 | 192.168.100.126 |
| bm-bra-fw-01 | VyOS | vyos | FIREWALL | BR-A | clab-brightmart-brafw01 | 192.168.100.127 |
| bm-brb-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-B | clab-brightmart-brbacc01 | 192.168.100.128 |
| bm-brb-fw-01 | VyOS | vyos | FIREWALL | BR-B | clab-brightmart-brbfw01 | 192.168.100.129 |
| bm-brc-acc-01 | Nokia | srlinux | ACCESS_SWITCH | BR-C | clab-brightmart-brcacc01 | 192.168.100.130 |
| bm-brc-fw-01 | VyOS | vyos | FIREWALL | BR-C | clab-brightmart-brcfw01 | 192.168.100.131 |
