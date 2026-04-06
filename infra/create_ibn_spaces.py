#!/usr/bin/env python3
"""
Create (or verify) the 7 IBN Live-Memory spaces.

Idempotent — 'already exists' responses are treated as success.
Uses LiveMemoryClient with the admin token so space_create is permitted.

Usage:
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k \
    python infra/create_ibn_spaces.py
"""

from __future__ import annotations
import os, sys
sys.path.insert(0, "src")

from ibn.core.live_memory_client import LiveMemoryClient

URL   = os.getenv("LIVE_MEMORY_URL",   "http://localhost:8002")
TOKEN = os.getenv("LIVE_MEMORY_TOKEN", "lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k")

SPACES = [
    {
        "space_id": "ibn-loop-inner",
        "description": "Inner loop: autonomous remediation decisions, drift corrections (Agents 6-8)",
        "owner": "ibn-system",
        "rules": """# IBN Inner Loop — Memory Bank Rules
## Mandatory Bank Files
### active-remediations.md — current open remediation actions (one section per active item)
### drift-analysis.md — running POR vs AS-BUILT drift analysis by type
### remediation-history.md — completed remediations, chronological, max 15 KB
### loop-metrics.md — detection latency, success rate, autonomous vs escalated ratio

## Rules
1. Never lose active remediations until confirmed resolved.
2. Synthesize repeated observations into trends.
3. On complete: move summary to remediation-history.md.
4. Preserve root cause chains for Graph-Memory ingestion.
5. ISO 8601 timestamps throughout.
""",
    },
    {
        "space_id": "ibn-loop-outer",
        "description": "Outer loop: human escalations, operator decisions, compliance reporting (Agents 9-10)",
        "owner": "ibn-system",
        "rules": """# IBN Outer Loop — Memory Bank Rules
## Mandatory Bank Files
### escalation-queue.md — active escalations awaiting human decision
### decision-log.md — operator decisions, APPEND-ONLY (audit trail)
### compliance-summary.md — overall compliance %, open items, trend
### reporting-context.md — context for next human report (replaced each cycle)
### operator-notes.md — human free-form notes, NOT modified by LLM

## Rules
1. decision-log.md is append-only — never remove entries.
2. compliance-summary.md is a single-page executive view.
3. operator-notes.md is human-authored — consolidator must not rewrite it.
""",
    },
    {
        "space_id": "ibn-por-v1",
        "description": "Plan-of-Record v1: HLD baseline campus network, approval audit trail",
        "owner": "ibn-system",
        "rules": """# IBN Plan-of-Record — Memory Bank Rules
## Mandatory Bank Files
### approval-record.md — formal POR approval record (immutable once active)
### design-rationale.md — why decisions were made, HLD section references, trade-offs
### validation-results.md — Campus profile constraint results (PASS/FAIL per constraint)
### change-history.md — POR changes: what, who, why, approval

## Rules
1. approval-record.md entries are append-only.
2. design-rationale.md organised by topic, not chronologically.
3. Always include HLD section references.
4. Primary candidate for Graph-Memory push — preserve causal chains.
""",
    },
    {
        "space_id": "ibn-candidate-bootstrap",
        "description": "Template Candidate space: intent decomposition, policy rendering, What-If validation",
        "owner": "ibn-system",
        "rules": """# IBN Candidate Model — Memory Bank Rules
## Mandatory Bank Files
### policy-decisions.md — intent decomposition, rule details, conflict resolution
### config-rendering.md — affected devices, template versions, config diff summary
### validation-results.md — blast radius, Campus constraints, What-If (APPROVED or BLOCKED)
### rejected-alternatives.md — options not selected (never discard)

## Rules
1. Include Neo4j intentId/policyId references.
2. policy-decisions.md organised by zone pair (source→dest).
3. validation-results.md must state APPROVED or BLOCKED with reasons.
""",
    },
    {
        "space_id": "ibn-deploy-bootstrap",
        "description": "Template Deployment space: per-deployment execution log and verification",
        "owner": "ibn-system",
        "rules": """# IBN Deployment — Memory Bank Rules
## Mandatory Bank Files
### deployment-log.md — step-by-step: devices in order, commands, success/fail, rollback points
### verification-results.md — VERIFIED or FAILED per device, expected vs actual
### jinja2-context.md — template versions, Cypher queries, variable values

## Rules
1. deployment-log.md is chronologically ordered — preserve exact sequence.
2. Never lose per-device success/failure status.
3. Include Neo4j deployId for cross-system traceability.
""",
    },
    {
        "space_id": "ibn-asbuilt-current",
        "description": "Current As-Built: Agent 6 monitoring observations, anomaly watch, telemetry trends",
        "owner": "ibn-system",
        "rules": """# IBN As-Built Observations — Memory Bank Rules
## Mandatory Bank Files
### network-health.md — current health snapshot per device/VLAN (replaced entirely each cycle)
### anomaly-watch.md — sub-incident anomalies: new → watching → resolved/escalated
### telemetry-insights.md — interpretive analysis, correlations, baselines (cumulative)

## Rules
1. network-health.md is a snapshot — replace entirely, do not accumulate.
2. telemetry-insights.md is cumulative — never discard analytical observations.
3. Include metric source (gNMI path, SNMP OID, CLI) for reproducibility.
4. Remove stale anomalies (>24h without update).
""",
    },
    {
        "space_id": "ibn-whatif-bootstrap",
        "description": "Template What-If space: design exploration before Candidate promotion",
        "owner": "ibn-system",
        "rules": """# IBN What-If Exploration — Memory Bank Rules
## Mandatory Bank Files
### exploration-brief.md — what is being explored and why (set once)
### options-analysis.md — options with pros/cons, comparison matrix, selected option marked
### simulation-results.md — blast radius, capacity projections, Cypher query references

## Rules
1. When option selected, mark clearly: ## SELECTED: Option X + rationale.
2. simulation-results.md includes actual Cypher queries for reproducibility.
3. Ephemeral spaces — optimise for clarity over longevity.
""",
    },
]


def main():
    client = LiveMemoryClient(URL, TOKEN)
    print(f"Live-Memory: {URL}\n")

    print("── Creating 7 IBN spaces ─────────────────────────────────")
    for space in SPACES:
        try:
            result = client.space_create(
                space_id=space["space_id"],
                description=space["description"],
                owner=space["owner"],
                rules=space["rules"],
            )
            print(f"  ✓ {space['space_id']}")
        except Exception as e:
            err = str(e).lower()
            if "already exists" in err or "duplicate" in err or "exist" in err:
                print(f"  ~ {space['space_id']}  (already exists)")
            else:
                print(f"  ✗ {space['space_id']}: {e}")

    print("\n── Listing spaces ────────────────────────────────────────")
    try:
        result = client.space_list()
        spaces = result if isinstance(result, list) else result.get("spaces", [result])
        for s in spaces:
            sid = s.get("space_id", s) if isinstance(s, dict) else s
            print(f"  • {sid}")
    except Exception as e:
        print(f"  (could not list spaces: {e})")


if __name__ == "__main__":
    main()
