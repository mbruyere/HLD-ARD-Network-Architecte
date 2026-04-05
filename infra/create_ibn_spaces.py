#!/usr/bin/env python3
"""Create the 7 IBN Live-Memory spaces with domain-specific consolidation rules."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/opt/live-memory/scripts")
from cli.client import MCPClient

MCP_URL = "http://localhost:8002"
ADMIN_TOKEN = "lm_ta1e2GaW4UifCGSgURYd14VEGKxHNTskEQLZPkKA-0k"

SPACES = [
    {
        "space_id": "ibn-loop-inner",
        "description": "Inner loop coordination: autonomous remediation decisions, re-orchestration triggers, drift corrections",
        "owner": "ibn-system",
        "rules": """# IBN Inner Loop — Memory Bank Rules

## Purpose
Captures the autonomous inner loop (RFC 9315 §6). Agents 6 (Monitoring), 7 (Assessment), 8 (Action) write here.

## Mandatory Bank Files

### 1. active-remediations.md
Current open remediation actions. One section per active remediation (severity, action, affected devices/intents, timestamp). Remove completed ones.

### 2. drift-analysis.md
Running drift analysis (POR vs AS-BUILT). By drift type. Synthesize recurring patterns.

### 3. remediation-history.md
Completed remediation journal. Chronological, grouped by week. Max 15 KB — archive older entries monthly.

### 4. loop-metrics.md
Inner loop performance: detection-to-remediation latency, success rate, top-5 drift types, autonomous vs escalated ratio.

## Consolidation Rules
1. Never lose info about active remediations until confirmed resolved.
2. Synthesize repeated observations into trends — no raw note duplication.
3. active-remediations.md is the agent entry point.
4. On remediation complete: move summary to remediation-history.md.
5. Preserve root cause chains for Graph-Memory ingestion.
6. Use ISO 8601 timestamps throughout.
""",
    },
    {
        "space_id": "ibn-loop-outer",
        "description": "Outer loop coordination: escalations to human operator, reporting context, human decisions",
        "owner": "ibn-system",
        "rules": """# IBN Outer Loop — Memory Bank Rules

## Purpose
Captures the human-in-the-loop outer loop (RFC 9315 §6). Agents 9, 10 and Human Operator write here.

## Mandatory Bank Files

### 1. escalation-queue.md
Active escalations awaiting human decision. One section per escalation (severity, source, recommended action, SLA deadline). Operator entry point.

### 2. decision-log.md
Record of human operator decisions. Append-only — critical governance evidence. Pushed to Graph-Memory.

### 3. compliance-summary.md
Current compliance posture: overall %, open items by severity, trend, top-3 risks. Updated by Agent 9.

### 4. reporting-context.md
Context for next human-facing report. Agent 10 reads this. Replaced completely each report cycle.

### 5. operator-notes.md
Free-form human operator notes. NEVER modified by LLM consolidator — append only.

## Consolidation Rules
1. escalation-queue.md must be concise and actionable.
2. NEVER remove/modify decision-log.md entries — append only (audit trail).
3. compliance-summary.md is a single-page executive view.
4. operator-notes.md is human-authored — consolidator must not rewrite it.
5. Use ISO 8601 timestamps and tag entries with POR version.
""",
    },
    {
        "space_id": "ibn-por-v1",
        "description": "Plan-of-Record v1 — HLD baseline campus network. Approval audit trail and governance evidence.",
        "owner": "ibn-system",
        "rules": """# IBN Plan-of-Record — Memory Bank Rules

## Purpose
Documents the approved POR for the campus network. Captures why decisions were approved, governance evidence.

## Mandatory Bank Files

### 1. approval-record.md
Formal POR approval record. Approval authority, date, scope, conditions. Immutable once active.

### 2. design-rationale.md
Why the POR design was chosen. Key decisions, trade-offs, rejected alternatives, HLD section references. By topic.

### 3. validation-results.md
Campus profile constraint validation results. Each constraint: pass/fail, details, timestamp, schema version.

### 4. change-history.md
Chronological record of POR changes. What changed, who requested, who approved, rationale, Candidate space link.

## Consolidation Rules
1. approval-record.md entries are append-only.
2. design-rationale.md is structured by topic, not chronologically.
3. Always include HLD section references for design decisions.
4. validation-results.md clearly distinguishes PASS from FAIL.
5. Primary candidate for Graph-Memory push — preserve causal chains.
""",
    },
    {
        "space_id": "ibn-candidate-bootstrap",
        "description": "Template Candidate space — clone rules for each new Candidate model instance.",
        "owner": "ibn-system",
        "rules": """# IBN Candidate Model — Memory Bank Rules

## Purpose
Captures translation process: intent decomposition, policy rendering, validation. Agents 1-4 write here.

## Mandatory Bank Files

### 1. policy-decisions.md
Intent decomposition into policies and firewall rules. Intent reference, rule details, conflict resolution, SGT/DSCP.

### 2. config-rendering.md
Configuration generation context. Affected devices, Jinja2 template versions, config diff summary, rendering issues.

### 3. validation-results.md
Pre-approval validation (Agent 4). Blast radius, Campus profile constraints, What-If results, risk level.

### 4. rejected-alternatives.md
Options considered but not selected. Critical for Graph-Memory — prevents re-exploring failed options.

## Consolidation Rules
1. Always include Neo4j intentId and policyId references.
2. policy-decisions.md organized by zone pair (source→dest).
3. Preserve conflict resolution chains.
4. validation-results.md must state APPROVED or BLOCKED with reasons.
5. rejected-alternatives.md is never discarded.
""",
    },
    {
        "space_id": "ibn-deploy-bootstrap",
        "description": "Template Deployment space — clone rules for each DeploymentEvent.",
        "owner": "ibn-system",
        "rules": """# IBN Deployment — Memory Bank Rules

## Purpose
Documents a specific deployment event. Agent 5 (Orchestration) is primary writer.

## Mandatory Bank Files

### 1. deployment-log.md
Step-by-step execution: deployment event ID, devices targeted in order, per-device commands/success/failure, rollback points, total time.

### 2. verification-results.md
Post-deployment verification: expected vs actual state, rules confirmed count, discrepancies, verification method.

### 3. jinja2-context.md
Rendering context: template versions, Cypher queries executed, variable values, intent traceability header.

## Consolidation Rules
1. deployment-log.md is chronologically ordered — preserve exact sequence.
2. Never lose per-device success/failure status.
3. verification-results.md states VERIFIED or FAILED per device.
4. Include Neo4j deployId references for cross-system traceability.
""",
    },
    {
        "space_id": "ibn-asbuilt-current",
        "description": "Current As-Built observations — monitoring telemetry interpretation, anomaly narratives.",
        "owner": "ibn-system",
        "rules": """# IBN As-Built Observations — Memory Bank Rules

## Purpose
Captures Agent 6 (Monitoring) observations. Human-readable telemetry interpretation, trends, anomalies.

## Mandatory Bank Files

### 1. network-health.md
Current health snapshot: per-device status, per-VLAN utilization, overall health score. Replaced entirely each consolidation. Max 8 KB.

### 2. anomaly-watch.md
Anomalies detected but not yet incident-level. Metric, threshold proximity, duration, scope, trend. Escalate to ibn-loop-inner when threshold crossed.

### 3. telemetry-insights.md
Interpretive analysis: metric correlations, capacity trends, performance baselines by time-of-day. Cumulative — richest for Graph-Memory.

## Consolidation Rules
1. network-health.md is a snapshot — replace entirely, do not accumulate.
2. anomaly-watch.md entries: new → watching → resolved OR escalated.
3. telemetry-insights.md is cumulative — never discard analytical observations.
4. Include metric source (gNMI path, SNMP OID, CLI) for reproducibility.
5. Remove stale anomalies (>24h without update).
""",
    },
    {
        "space_id": "ibn-whatif-bootstrap",
        "description": "Template What-If space — clone rules for each exploration session.",
        "owner": "ibn-system",
        "rules": """# IBN What-If Exploration — Memory Bank Rules

## Purpose
Captures design exploration by Agent 4 and Human Operator. Multiple options evaluated before promotion to Candidate. Ephemeral spaces.

## Mandatory Bank Files

### 1. exploration-brief.md
What is being explored and why. Trigger, scope, constraints. Created once, rarely modified.

### 2. options-analysis.md
Options evaluated with pros/cons. One section per option, comparison matrix at top. Mark selected option clearly.

### 3. simulation-results.md
What-If graph query results. Blast radius calculations, capacity projections, failure scenarios, Neo4j query references.

## Consolidation Rules
1. exploration-brief.md is set once — only append clarifications.
2. options-analysis.md: one section per option, comparison matrix updated.
3. When option selected, mark prominently (## SELECTED: Option X) with rationale.
4. simulation-results.md includes actual Cypher queries for reproducibility.
5. Optimize for clarity over longevity — these are ephemeral spaces.
""",
    },
]


async def main():
    client = MCPClient(MCP_URL, ADMIN_TOKEN)
    print("Creating 7 IBN spaces...\n")
    for space in SPACES:
        try:
            result = await client.call_tool("space_create", space)
            print(f"  ✓ {space['space_id']}")
        except Exception as e:
            err = str(e)
            if "already exists" in err.lower() or "duplicate" in err.lower() or "exist" in err.lower():
                print(f"  ~ {space['space_id']} (already exists)")
            else:
                print(f"  ✗ {space['space_id']}: {e}")

    print("\nListing spaces...")
    spaces = await client.call_tool("space_list", {})
    print(spaces)


if __name__ == "__main__":
    asyncio.run(main())
