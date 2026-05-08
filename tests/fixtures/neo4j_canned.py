"""
Canned Neo4j query results for unit tests.

These dicts simulate the rows returned by ``session.run()`` for the Cypher
queries used by each agent.  Keyed by a short query identifier that matches
the agent's internal ``_QUERIES`` dict.
"""

# ---------------------------------------------------------------------------
# Agent 3 — Policy→Config  (8 extraction queries)
# ---------------------------------------------------------------------------

FIREWALLS = [
    {
        "device_id": "usf-fw-01",
        "hostname": "fw-hq-usr-01",
        "vendor": "vyos",
        "platform": "vyos-1.4",
        "device_role": "FIREWALL",
        "fw_function": "USF",
        "pair_id": "FP-USF-HQ",
        "site_id": "SITE-HQ-01",
    },
    {
        "device_id": "usf-fw-02",
        "hostname": "fw-hq-usr-02",
        "vendor": "vyos",
        "platform": "vyos-1.4",
        "device_role": "FIREWALL",
        "fw_function": "USF",
        "pair_id": "FP-USF-HQ",
        "site_id": "SITE-HQ-01",
    },
    {
        "device_id": "dmzfw-01",
        "hostname": "fw-hq-dmz-01",
        "vendor": "vyos",
        "platform": "vyos-1.4",
        "device_role": "FIREWALL",
        "fw_function": "DMZFW",
        "pair_id": "FP-DMZFW-HQ",
        "site_id": "SITE-HQ-01",
    },
    {
        "device_id": "dmzfw-02",
        "hostname": "fw-hq-dmz-02",
        "vendor": "vyos",
        "platform": "vyos-1.4",
        "device_role": "FIREWALL",
        "fw_function": "DMZFW",
        "pair_id": "FP-DMZFW-HQ",
        "site_id": "SITE-HQ-01",
    },
]

ZONES = [
    {"zone_id": "USER",      "zone_name": "USER",      "vlans": [100, 110, 120, 130]},
    {"zone_id": "GUEST",     "zone_name": "GUEST",     "vlans": [140]},
    {"zone_id": "IOT",       "zone_name": "IOT",       "vlans": [150]},
    {"zone_id": "MGMT",      "zone_name": "MGMT",      "vlans": [160]},
    {"zone_id": "DMZ_INFRA", "zone_name": "DMZ_INFRA", "vlans": [200, 210, 220, 230, 240, 250, 260, 270]},
    {"zone_id": "INTERNET",  "zone_name": "INTERNET",  "vlans": []},
]

SEGMENTS = [
    {"segment_name": "Employee",   "vlan_id": 100},
    {"segment_name": "Voice",      "vlan_id": 110},
    {"segment_name": "Printer",    "vlan_id": 120},
    {"segment_name": "Video",      "vlan_id": 130},
    {"segment_name": "Guest",      "vlan_id": 140},
    {"segment_name": "IoT",        "vlan_id": 150},
    {"segment_name": "Management", "vlan_id": 160},
]

POLICIES = [
    {
        "rule_id": "FWR-001",
        "rule_name": "GUEST-TO-INTERNET",
        "default_action": "accept",
        "number": 10,
        "action": "accept",
        "source": "10.1.140.0/24",
        "destination": "0.0.0.0/0",
        "protocol": "any",
        "policy_id": "POL-001",
    },
    {
        "rule_id": "FWR-002",
        "rule_name": "GUEST-TO-USER",
        "default_action": "drop",
        "number": 10,
        "action": "drop",
        "source": "10.1.140.0/24",
        "destination": "10.1.100.0/16",
        "protocol": "any",
        "policy_id": "POL-001",
    },
]

INTENTS = [
    {
        "intent_id": "INT-001",
        "statement": "Guest users must only access the internet",
        "status": "TRANSLATED",
        "policy_id": "POL-001",
    },
]

FW_INTERFACES = [
    {"device_id": "usf-fw-01", "iface_name": "eth0",   "ip": "10.1.100.1/24",  "vlan": 100, "description": "Employee"},
    {"device_id": "usf-fw-01", "iface_name": "eth0.110","ip": "10.1.110.1/24",  "vlan": 110, "description": "Voice"},
    {"device_id": "usf-fw-01", "iface_name": "eth0.140","ip": "10.1.140.1/24",  "vlan": 140, "description": "Guest"},
    {"device_id": "usf-fw-01", "iface_name": "eth1",   "ip": "10.1.255.1/30",  "vlan": 300, "description": "Transit"},
    {"device_id": "usf-fw-01", "iface_name": "eth2",   "ip": "203.0.113.1/30", "vlan": None, "description": "Internet-uplink"},
    {"device_id": "usf-fw-02", "iface_name": "eth0",   "ip": "10.1.100.2/24",  "vlan": 100, "description": "Employee"},
    {"device_id": "usf-fw-02", "iface_name": "eth1",   "ip": "10.1.255.5/30",  "vlan": 300, "description": "Transit"},
    {"device_id": "usf-fw-02", "iface_name": "eth2",   "ip": "203.0.113.5/30", "vlan": None, "description": "Internet-uplink"},
]

NAT_RULES = [
    {
        "nat_type": "source",
        "number": 100,
        "outbound": "eth2",
        "source": "10.1.100.0/24",
        "translation": "masquerade",
        "device_id": "usf-fw-01",
    },
    {
        "nat_type": "source",
        "number": 100,
        "outbound": "eth2",
        "source": "10.1.100.0/24",
        "translation": "masquerade",
        "device_id": "usf-fw-02",
    },
]

FW_TRANSIT = [
    {"vlan_id": 300, "vlan_name": "Transit", "site_id": "SITE-HQ-01"},
]

# ---------------------------------------------------------------------------
# Agent 7 — Assessment  (compliance queries)
# ---------------------------------------------------------------------------

ACTIVE_INTENTS = [
    {
        "intentId": "INT-001",
        "statement": "Guest users must only access the internet",
        "status": "ACTIVE",
        "modelState": "POR",
        "complianceStatus": "COMPLIANT",
    },
]

POR_CONFIGURATIONS = [
    {
        "configId": "CFG-001",
        "deviceId": "usf-fw-01",
        "intentId": "INT-001",
        "content": (
            "set firewall name GUEST-TO-INTERNET default-action accept\n"
            "set firewall name GUEST-TO-USER default-action drop"
        ),
        "modelState": "POR",
        "version": 1,
    },
]

ASBUILT_OPERATIONAL_STATE = [
    {
        "deviceId": "usf-fw-01",
        "hostname": "fw-hq-usr-01",
        "config_hash": "abc123",
        "interfaces_up": 5,
        "interfaces_total": 5,
        "vrrp_state": "MASTER",
        "modelState": "AS_BUILT",
    },
]

# ---------------------------------------------------------------------------
# Agent 8 — Action  (rollback chain queries)
# ---------------------------------------------------------------------------

PRECEDED_BY_CHAIN = [
    {"configId": "CFG-003", "version": 3, "modelState": "DEPLOYED", "preceded_by": "CFG-002"},
    {"configId": "CFG-002", "version": 2, "modelState": "POR",      "preceded_by": "CFG-001"},
    {"configId": "CFG-001", "version": 1, "modelState": "POR",      "preceded_by": None},
]

# ---------------------------------------------------------------------------
# Schema / constraints (T1)
# ---------------------------------------------------------------------------

EXPECTED_CONSTRAINTS = [
    {"name": "intent_id_unique",   "label": "Intent",        "property": "intentId"},
    {"name": "device_id_unique",   "label": "Device",        "property": "deviceId"},
    {"name": "site_id_unique",     "label": "Site",          "property": "siteId"},
    {"name": "vlan_id_unique",     "label": "VLAN",          "property": "vlanId"},
    {"name": "policy_id_unique",   "label": "Policy",        "property": "policyId"},
    {"name": "config_id_unique",   "label": "Configuration", "property": "configId"},
    {"name": "fw_rule_id_unique",  "label": "FirewallRule",  "property": "ruleId"},
    {"name": "interface_id_unique","label": "Interface",      "property": "interfaceId"},
]

# ---------------------------------------------------------------------------
# HLD seed data for T2 — Neo4j node creation
# ---------------------------------------------------------------------------

SEED_SITES = [
    {"siteId": "SITE-HQ-01",  "name": "Headquarters", "type": "large",  "modelState": "POR"},
    {"siteId": "SITE-BRA-01", "name": "Branch-A",     "type": "medium", "modelState": "POR"},
    {"siteId": "SITE-BRB-01", "name": "Branch-B",     "type": "small",  "modelState": "POR"},
]

SEED_VLANS = [
    {"vlanId": 100, "name": "Employee",      "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 110, "name": "Voice",         "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 120, "name": "Printer",       "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 130, "name": "Video",         "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 140, "name": "Guest",         "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 150, "name": "IoT",           "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 160, "name": "Management",    "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 200, "name": "DMZ-Servers",   "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 210, "name": "DNS-DMZ",       "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 220, "name": "AD-DMZ",        "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 230, "name": "File-DMZ",      "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 240, "name": "PBX-DMZ",       "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 250, "name": "Publish",       "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 260, "name": "Proxy",         "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 270, "name": "Management-DMZ","siteId": "SITE-HQ-01", "modelState": "POR"},
    {"vlanId": 300, "name": "Transit",       "siteId": "SITE-HQ-01", "modelState": "POR"},
]

SEED_DEVICES = [
    {"deviceId": "usf-fw-01", "hostname": "fw-hq-usr-01", "vendor": "vyos", "deviceRole": "FIREWALL", "firewallFunction": "USF",  "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "usf-fw-02", "hostname": "fw-hq-usr-02", "vendor": "vyos", "deviceRole": "FIREWALL", "firewallFunction": "USF",  "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "dmzfw-01",  "hostname": "fw-hq-dmz-01", "vendor": "vyos", "deviceRole": "FIREWALL", "firewallFunction": "DMZFW","siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "dmzfw-02",  "hostname": "fw-hq-dmz-02", "vendor": "vyos", "deviceRole": "FIREWALL", "firewallFunction": "DMZFW","siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "acc-sw-01", "hostname": "acc-sw-01",     "vendor": "eos",  "deviceRole": "ACCESS",   "firewallFunction": None,   "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "acc-sw-02", "hostname": "acc-sw-02",     "vendor": "eos",  "deviceRole": "ACCESS",   "firewallFunction": None,   "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "agg-sw-01", "hostname": "agg-sw-01",     "vendor": "eos",  "deviceRole": "AGGREGATION","firewallFunction": None, "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"deviceId": "agg-sw-02", "hostname": "agg-sw-02",     "vendor": "eos",  "deviceRole": "AGGREGATION","firewallFunction": None, "siteId": "SITE-HQ-01", "modelState": "POR"},
]

SEED_ZONES = [
    {"zoneId": "USER",      "name": "User Zone",     "modelState": "POR"},
    {"zoneId": "GUEST",     "name": "Guest Zone",    "modelState": "POR"},
    {"zoneId": "IOT",       "name": "IoT Zone",      "modelState": "POR"},
    {"zoneId": "DMZ_INFRA", "name": "DMZ Zone",      "modelState": "POR"},
    {"zoneId": "INTERNET",  "name": "Internet Zone",  "modelState": "POR"},
    {"zoneId": "MGMT",      "name": "Management Zone","modelState": "POR"},
]

SEED_SEGMENTS = [
    {"segmentId": "SEG-EMP",  "name": "Employee",   "zoneId": "USER",  "vlanId": 100, "modelState": "POR"},
    {"segmentId": "SEG-VOI",  "name": "Voice",      "zoneId": "USER",  "vlanId": 110, "modelState": "POR"},
    {"segmentId": "SEG-PRT",  "name": "Printer",    "zoneId": "USER",  "vlanId": 120, "modelState": "POR"},
    {"segmentId": "SEG-VID",  "name": "Video",      "zoneId": "USER",  "vlanId": 130, "modelState": "POR"},
    {"segmentId": "SEG-GST",  "name": "Guest",      "zoneId": "GUEST", "vlanId": 140, "modelState": "POR"},
    {"segmentId": "SEG-IOT",  "name": "IoT",        "zoneId": "IOT",   "vlanId": 150, "modelState": "POR"},
    {"segmentId": "SEG-MGT",  "name": "Management", "zoneId": "MGMT",  "vlanId": 160, "modelState": "POR"},
]

SEED_FIREWALL_PAIRS = [
    {"pairId": "FP-USF-HQ",   "name": "USF HA Pair",   "function": "USF",  "members": ["usf-fw-01", "usf-fw-02"], "siteId": "SITE-HQ-01", "modelState": "POR"},
    {"pairId": "FP-DMZFW-HQ", "name": "DMZFW HA Pair", "function": "DMZFW","members": ["dmzfw-01", "dmzfw-02"],   "siteId": "SITE-HQ-01", "modelState": "POR"},
]
