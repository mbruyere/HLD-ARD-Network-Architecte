"""
Canned Live-Memory and Graph-Memory content for unit tests.

Provides pre-formatted live_note() content strings and bank file content
used across T3 (Live-Memory), T4 (Ingestion), T7 (Monitoring), T8
(Assessment), T9 (Action), and T11 (Consolidation) tests.
"""

# ---------------------------------------------------------------------------
# Agent 1 — Ingestion notes
# ---------------------------------------------------------------------------

NOTE_INGESTION_SUCCESS = "Intent INT-001 ingested: Guest → permit → Internet"
NOTE_CONFLICT_DETECTED = (
    "CONFLICT: INT-002 (Guest→deny→Internet) conflicts with "
    "INT-001 (Guest→permit→Internet)"
)

# ---------------------------------------------------------------------------
# Agent 3 — Policy→Config notes
# ---------------------------------------------------------------------------

NOTE_CONFIG_RENDERED = (
    "Config rendered for usf-fw-01: 4 templates, 127 lines, "
    "hash=a1b2c3d4. Diff: +12 lines (2 new firewall rules)."
)
NOTE_CONFIG_NO_DIFF = (
    "Config rendered for usf-fw-01: no diff from previous CFG-001. "
    "Skipping deployment."
)

# ---------------------------------------------------------------------------
# Agent 6 — Monitoring notes
# ---------------------------------------------------------------------------

NOTE_TELEMETRY_SNAPSHOT = (
    "Polling cycle complete: 4 devices, 16 interfaces, 0 anomalies"
)
NOTE_ANOMALY_DETECTED = (
    "ANOMALY: usf-fw-01 eth0.140 transitioned DOWN unexpectedly"
)
NOTE_HIGH_CPU = (
    "ALERT: usf-fw-01 CPU utilisation at 92.3% (threshold: 90%)"
)

# ---------------------------------------------------------------------------
# Agent 7 — Assessment notes
# ---------------------------------------------------------------------------

NOTE_DRIFT_DETECTED = (
    "DRIFT: FirewallRule FWR-002 missing on usf-fw-01 "
    "(expected by POL-001)"
)
NOTE_ASSESSMENT_COMPLIANT = (
    "ASSESSMENT: INT-001 → COMPLIANT. "
    "All firewall rules present, interfaces up, VRRP MASTER."
)
NOTE_ASSESSMENT_NONCOMPLIANT = (
    "ASSESSMENT: INT-001 → NON_COMPLIANT. "
    "1 rule missing, 0 extra. Root cause: usf-fw-01 config drift."
)
NOTE_ASSESSMENT_DEGRADED = (
    "ASSESSMENT: INT-001 → DEGRADED. "
    "VRRP role is BACKUP (expected MASTER). Failover may have occurred."
)

# ---------------------------------------------------------------------------
# Agent 8 — Action notes
# ---------------------------------------------------------------------------

NOTE_REMEDIATION_ATTEMPT = (
    "Attempting auto-remediation for INC-001: "
    "re-push CFG-002 to usf-fw-01"
)
NOTE_REMEDIATION_SUCCESS = (
    "Remediation REM-001 SUCCESS: "
    "usf-fw-01 re-assessed as COMPLIANT"
)
NOTE_REMEDIATION_FAILED = (
    "Remediation REM-002 FAILED: "
    "usf-fw-01 still NON_COMPLIANT after re-push. Escalating."
)
NOTE_ESCALATION = (
    "ESCALATION: INC-002 (HIGH severity) — "
    "2 intents non-compliant, remediation failed. "
    "Ticket TKT-001 created, orchestration paused."
)
NOTE_ROLLBACK = (
    "ROLLBACK: Critical incident INC-003 — "
    "rolling back to CFG-001 (last known-good POR). "
    "Ticket TKT-002 created."
)

# ---------------------------------------------------------------------------
# Bank file content  (post-consolidation)
# ---------------------------------------------------------------------------

BANK_REMEDIATION_HISTORY = """\
# Remediation History

## REM-001 (2026-03-15)
Drift detected on usf-fw-01: firewall rule FWR-002 missing.
Caused by: manual SSH session removed rule outside the loop.
Action: Auto-remediate — re-pushed CFG-002.
Result: COMPLIANT after 45 seconds.

Lesson: Disable direct SSH access to firewall management interfaces.

## REM-002 (2026-03-16)
Drift detected on dmzfw-01: extra rule ROGUE-RULE present.
Caused by: operator added rule via console during maintenance window.
Action: Auto-remediate — re-pushed CFG-005.
Result: COMPLIANT after 30 seconds.

Lesson: All changes must go through the intent pipeline.
"""

BANK_DEPLOYMENT_LOG = """\
# Deployment Log

## DEP-001 (2026-03-15T10:30:00Z)
Intent: INT-001 (Guest isolation)
Devices: usf-fw-01, usf-fw-02
Templates: base, policies, nat, ha
Lines pushed: 127 per device
Post-deploy verification: PASS (all rules present, VRRP active)

## DEP-002 (2026-03-15T14:00:00Z)
Intent: INT-002 (DMZ server access)
Devices: dmzfw-01, dmzfw-02
Templates: base, policies, nat, ha
Lines pushed: 98 per device
Post-deploy verification: PASS
"""

BANK_COMPLIANCE_SUMMARY = """\
# Compliance Summary — 2026-03-15

| Intent | Status | Drift Events | Last Check |
|--------|--------|-------------|------------|
| INT-001 | COMPLIANT | 1 (resolved) | 23:45:00Z |
| INT-002 | COMPLIANT | 0 | 23:45:00Z |

Overall compliance: 100%
Inner loop cycles today: 288 (5-min interval)
Remediations: 1 auto (REM-001), 0 escalated
"""

# ---------------------------------------------------------------------------
# Space definitions  (consolidation rules per STEP2)
# ---------------------------------------------------------------------------

SPACE_DEFINITIONS = {
    "ibn-loop-inner": {
        "description": "Inner loop working memory — autonomous remediation",
        "consolidation_rules": {
            "trigger": "note_count",
            "threshold": 20,
            "strategy": "temporal_summary",
            "retain_last_n": 5,
        },
    },
    "ibn-loop-outer": {
        "description": "Outer loop — human-in-the-loop escalations",
        "consolidation_rules": {
            "trigger": "manual",
            "strategy": "decision_log",
        },
    },
    "ibn-candidate-001": {
        "description": "Candidate state for intent INT-001",
        "consolidation_rules": {
            "trigger": "state_transition",
            "strategy": "design_rationale",
        },
    },
    "ibn-por-v1": {
        "description": "Plan-of-Record version 1",
        "consolidation_rules": {
            "trigger": "state_transition",
            "strategy": "approval_record",
        },
    },
    "ibn-deploy-001": {
        "description": "Deployment event for INT-001",
        "consolidation_rules": {
            "trigger": "state_transition",
            "strategy": "deployment_narrative",
        },
    },
}
