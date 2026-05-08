"""
Shared sample data for IBN Closed-Loop test suite.

Provides reusable intent, assessment, incident, and config data structures
used across T4 (Ingestion), T5 (Policy-Config), T8 (Assessment), T9 (Action),
and integration/e2e tests.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Intents (T4 — Agent 1 Ingestion)
# ---------------------------------------------------------------------------

INTENT_GUEST_ISOLATION = {
    "type": "access-policy",
    "subject": "Guest",
    "action": "permit",
    "target": "Internet",
    "statement": "Guest users must only access the internet",
}

INTENT_EXISTING_GUEST = {
    "intentId": "INT-001",
    "subject": "Guest",
    "target": "Internet",
    "action": "permit",
}

INTENT_CONFLICTING_GUEST = {
    "subject": "Guest",
    "target": "Internet",
    "action": "deny",
}

INTENT_EMPLOYEE_DMZ = {
    "subject": "Employee",
    "target": "DMZ",
    "action": "permit",
}

# ---------------------------------------------------------------------------
# Severity classification incidents (T9 — Agent 8 Action)
# ---------------------------------------------------------------------------

INCIDENT_MINOR = {"metric_deviation_pct": 5, "devices_affected": 0}
INCIDENT_SINGLE_INTERFACE = {"devices_affected": 1, "redundancy_active": True}
INCIDENT_MULTI_DEVICE = {"devices_affected": 3, "redundancy_active": False}
INCIDENT_SERVICE_IMPACTING = {"service_impact": True, "business_critical": True}
INCIDENT_MULTIPLE_INTENTS = {"intents_violated": 4}

ACTION_MATRIX = {
    "INFO":     {"action": "LOG",                    "autonomous": True,  "loop": "inner"},
    "LOW":      {"action": "AUTO_REMEDIATE",         "autonomous": True,  "loop": "inner"},
    "MEDIUM":   {"action": "AUTO_REMEDIATE_VERIFY",  "autonomous": True,  "loop": "inner"},
    "HIGH":     {"action": "ESCALATE",               "autonomous": False, "loop": "outer"},
    "CRITICAL": {"action": "ROLLBACK_ESCALATE",      "autonomous": False, "loop": "outer"},
}

# ---------------------------------------------------------------------------
# Drift detection (T8 — Agent 7 Assessment)
# ---------------------------------------------------------------------------

DRIFT_POR_RULE = {"config": "GUEST-TO-USER default-action drop", "element": "FirewallRule FWR-002"}
DRIFT_POR_INTERFACE = {"state": "up"}
DRIFT_POR_VRRP = {"ha_role": "MASTER"}

DRIFT_ASBUILT_RULE = {"config": None}
DRIFT_ASBUILT_INTERFACE = {"state": "down"}
DRIFT_ASBUILT_VRRP = {"ha_role": "BACKUP"}

DEPENDENCY_GRAPH = {
    "FirewallRule-FWR-002": "Policy-POL-001",
    "Policy-POL-001": "Intent-INT-001",
}

DEPENDENCY_GRAPH_MULTI = {
    "FWR-001": "Device-usf-fw-01",
    "FWR-002": "Device-usf-fw-01",
    "FWR-003": "Device-usf-fw-01",
}

# ---------------------------------------------------------------------------
# Config versions for rollback (T9)
# ---------------------------------------------------------------------------

CONFIG_VERSIONS = [
    {"configId": "CFG-001", "version": 1, "compliant": True},
    {"configId": "CFG-002", "version": 2, "compliant": True},
    {"configId": "CFG-003", "version": 3, "compliant": False},
]

# ---------------------------------------------------------------------------
# HLD device inventory
# ---------------------------------------------------------------------------

HLD_FIREWALL_DEVICES = [
    {"hostname": "usf-fw-01", "platform": "vyos", "role": "USF",  "site": "HQ"},
    {"hostname": "usf-fw-02", "platform": "vyos", "role": "USF",  "site": "HQ"},
    {"hostname": "dmzfw-01",  "platform": "vyos", "role": "DMZFW", "site": "HQ"},
    {"hostname": "dmzfw-02",  "platform": "vyos", "role": "DMZFW", "site": "HQ"},
]

HLD_SWITCH_DEVICES = [
    {"hostname": "acc-sw-01", "platform": "eos", "role": "ACCESS",      "site": "HQ"},
    {"hostname": "acc-sw-02", "platform": "eos", "role": "ACCESS",      "site": "HQ"},
    {"hostname": "acc-sw-03", "platform": "eos", "role": "ACCESS",      "site": "HQ"},
    {"hostname": "acc-sw-04", "platform": "eos", "role": "ACCESS",      "site": "HQ"},
    {"hostname": "agg-sw-01", "platform": "eos", "role": "AGGREGATION", "site": "HQ"},
    {"hostname": "agg-sw-02", "platform": "eos", "role": "AGGREGATION", "site": "HQ"},
]

HLD_EDGE_DEVICES = [
    {"hostname": "edge-rt-01", "platform": "eos", "role": "EDGE", "site": "HQ"},
    {"hostname": "edge-rt-02", "platform": "eos", "role": "EDGE", "site": "HQ"},
]

HLD_ALL_DEVICES = HLD_FIREWALL_DEVICES + HLD_SWITCH_DEVICES + HLD_EDGE_DEVICES

# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

HLD_SITES = [
    {"siteId": "SITE-HQ-01",   "name": "Headquarters", "type": "large"},
    {"siteId": "SITE-BRA-01",  "name": "Branch-A",     "type": "medium"},
    {"siteId": "SITE-BRB-01",  "name": "Branch-B",     "type": "small"},
]
