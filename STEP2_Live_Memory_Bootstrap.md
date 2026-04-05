# Step 2 — Live-Memory Working Memory Bootstrap

**Goal:** Deploy Live-Memory (Tier 2), create the 7 foundational IBN spaces with domain-specific consolidation rules, validate the `live_note()` → `bank_consolidate()` pipeline, and prepare the Graph Bridge connection to Graph-Memory (Tier 3).

**Prerequisites:** Docker, Docker Compose, S3-compatible storage (MinIO for local dev or Cloud Temple S3), an OpenAI-compatible LLM API endpoint. Step 1 (Neo4j) does not need to be complete — Live-Memory is independent of Neo4j.

---

## Step 2.1 — Deploy Live-Memory

Clone the repository and configure the environment.

```bash
git clone https://github.com/Cloud-Temple/live-memory.git
cd live-memory
cp .env.example .env
```

Edit `.env` with your infrastructure:

```bash
# ─── MCP Server ───
MCP_SERVER_NAME=IBN Live Memory
MCP_SERVER_PORT=8002
MCP_SERVER_DEBUG=true          # Enable for Phase 1 development

# ─── Authentication ───
ADMIN_BOOTSTRAP_KEY=$(openssl rand -hex 32)   # Generate a strong key

# ─── S3 Storage ───
# Option A: Cloud Temple S3
S3_ENDPOINT_URL=https://your-endpoint.s3.fr1.cloud-temple.com
S3_ACCESS_KEY_ID=YOUR_KEY
S3_SECRET_ACCESS_KEY=YOUR_SECRET
S3_BUCKET_NAME=ibn-live-memory
S3_REGION_NAME=fr1

# Option B: Local MinIO for development
# S3_ENDPOINT_URL=http://minio:9000
# S3_ACCESS_KEY_ID=minioadmin
# S3_SECRET_ACCESS_KEY=minioadmin
# S3_BUCKET_NAME=ibn-live-memory
# S3_REGION_NAME=us-east-1

# ─── LLM for Consolidation ───
LLMAAS_API_URL=https://api.ai.cloud-temple.com/v1
LLMAAS_API_KEY=YOUR_LLM_KEY
LLMAAS_MODEL=qwen3-2507:235b
LLMAAS_MAX_TOKENS=100000
LLMAAS_TEMPERATURE=0.3

# ─── Consolidation ───
CONSOLIDATION_TIMEOUT=600
CONSOLIDATION_MAX_NOTES=500

# ─── WAF (dev mode) ───
SITE_ADDRESS=:8080
WAF_PORT=8080
```

**If using local MinIO for development**, add a MinIO service to `docker-compose.yml`:

```yaml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio-data:/data

volumes:
  minio-data:
```

Then create the bucket:

```bash
# Start MinIO first
docker compose up -d minio

# Create the bucket
docker run --rm --network host \
  minio/mc alias set local http://localhost:9000 minioadmin minioadmin && \
  minio/mc mb local/ibn-live-memory
```

**Start Live-Memory:**

```bash
docker compose up -d
```

**Validation:**

```bash
# Health check
curl -s http://localhost:8080/health | python -m json.tool

# Expected: {"status": "healthy", ...}

# Web dashboard
# Open http://localhost:8080/live in a browser
```

---

## Step 2.2 — Create Admin and Agent Tokens

Live-Memory uses Bearer tokens scoped to specific spaces. We need:
- 1 admin token (for space management)
- 1 write token per agent group (for `live_note()`)
- 1 read token for the human operator

```bash
ADMIN_KEY="your-bootstrap-key-from-env"
LM_URL="http://localhost:8080"

# ─── Create Admin Token ───
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "admin_create_token",
      "arguments": {
        "name": "ibn-admin",
        "permissions": "admin",
        "space_ids": ""
      }
    },
    "id": 1
  }' | python -m json.tool

# Save the returned token value as IBN_ADMIN_TOKEN
```

```bash
# ─── Create Agent Write Token (all ibn-* spaces) ───
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "admin_create_token",
      "arguments": {
        "name": "ibn-agents",
        "permissions": "write",
        "space_ids": ""
      }
    },
    "id": 2
  }' | python -m json.tool

# Save as IBN_AGENT_TOKEN

# ─── Create Human Operator Read Token ───
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "admin_create_token",
      "arguments": {
        "name": "ibn-operator",
        "permissions": "read",
        "space_ids": ""
      }
    },
    "id": 3
  }' | python -m json.tool

# Save as IBN_OPERATOR_TOKEN
```

---

## Step 2.3 — Create the 7 IBN Spaces

Each space gets **domain-specific consolidation rules** tailored to its role in the closed loop. The rules are immutable after creation — they tell the LLM consolidator how to structure the bank files.

We create spaces in this order:
1. Two **cross-cutting** spaces (long-lived, created once)
2. Five **model-state template** spaces (pattern for dynamic creation)

### 2.3.1 — Space: `ibn-loop-inner` (Inner Loop Coordination)

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-loop-inner",
        "description": "Inner loop coordination: autonomous remediation decisions, re-orchestration triggers, drift corrections",
        "owner": "ibn-system",
        "rules": "# IBN Inner Loop — Memory Bank Rules\n\n## Purpose\nThis space captures the autonomous inner loop of the IBN closed-loop architecture (RFC 9315 §6). Agents 6 (Monitoring), 7 (Assessment), and 8 (Action) write here. The inner loop operates without human intervention.\n\n## Mandatory Bank Files\n\n### 1. active-remediations.md\n**Role:** Current open remediation actions and their status.\n- One section per active remediation, keyed by remediation ID\n- Each section: severity, action taken (LOG/RE_ORCHESTRATE/RE_PLAN), affected devices, affected intents, timestamp\n- Remove completed remediations (move summary to remediation-history.md)\n- Target size: <8 KB\n\n### 2. drift-analysis.md\n**Role:** Running analysis of detected drift between POR and AS-BUILT.\n- Organized by drift type (policy drift, config drift, state drift)\n- Each entry: what drifted, when detected, root cause hypothesis, resolution status\n- Synthesize recurring patterns into summary sections\n- Replace entries when drift is resolved\n\n### 3. remediation-history.md\n**Role:** Completed remediation journal — what was fixed and how.\n- Chronological, grouped by week\n- Each entry: drift detected → root cause → action taken → outcome → time-to-resolve\n- This file grows over time — it is the inner loop institutional memory\n- Max 15 KB; archive older entries by summarizing into monthly digests\n\n### 4. loop-metrics.md\n**Role:** Inner loop performance metrics.\n- Detection-to-remediation latency (avg, p95)\n- Remediation success rate\n- Most common drift types (top 5)\n- Autonomous vs escalated ratio\n- Updated on each consolidation cycle\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| observation   | drift-analysis.md |\n| decision      | active-remediations.md |\n| progress      | remediation-history.md |\n| issue         | active-remediations.md |\n| insight       | drift-analysis.md or loop-metrics.md |\n| todo          | active-remediations.md |\n| question      | drift-analysis.md |\n\n## Consolidation Rules\n1. Never lose information about an active remediation until it is confirmed resolved.\n2. Synthesize repeated observations into trend summaries — do not duplicate raw notes.\n3. active-remediations.md is the entry point — agents read this first to understand current state.\n4. When a remediation completes, move its summary to remediation-history.md and remove from active-remediations.md.\n5. Keep loop-metrics.md updated with computed statistics on every consolidation.\n6. Preserve root cause analysis chains — these are critical for Graph-Memory ingestion.\n7. Use ISO 8601 timestamps throughout."
      }
    },
    "id": 10
  }' | python -m json.tool
```

### 2.3.2 — Space: `ibn-loop-outer` (Outer Loop Coordination)

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-loop-outer",
        "description": "Outer loop coordination: escalations to human operator, reporting context, human decisions",
        "owner": "ibn-system",
        "rules": "# IBN Outer Loop — Memory Bank Rules\n\n## Purpose\nThis space captures the human-in-the-loop outer loop (RFC 9315 §6). Agents 9 (Abstraction), 10 (Reporting), and the Human Operator write here. Escalations from Agent 8 land here.\n\n## Mandatory Bank Files\n\n### 1. escalation-queue.md\n**Role:** Active escalations awaiting human decision.\n- One section per escalation, keyed by ticket ID\n- Each section: severity, source agent, affected intents, recommended action, timestamp, SLA deadline\n- Remove resolved escalations (move to decision-log.md)\n- This is the first file the human operator reads\n- Target size: <5 KB\n\n### 2. decision-log.md\n**Role:** Record of human operator decisions on escalated issues.\n- Chronological entries\n- Each entry: escalation reference, decision taken, rationale, who decided, outcome\n- This file is critical governance evidence — never lose decision records\n- Pushed to Graph-Memory for long-term knowledge persistence\n\n### 3. compliance-summary.md\n**Role:** Current compliance posture for the human operator.\n- Overall compliance percentage\n- Open non-compliant items by severity\n- Trend (improving/degrading/stable) with week-over-week comparison\n- Top 3 risk areas\n- Updated by Agent 9 (Abstraction) on every consolidation\n\n### 4. reporting-context.md\n**Role:** Context and data gathered for the next human-facing report.\n- Key metrics, notable events, trend analysis\n- Agent 10 (Reporting) reads this to generate dashboards and summaries\n- Replaces completely on each report cycle\n\n### 5. operator-notes.md\n**Role:** Free-form notes from the human operator.\n- The operator can annotate decisions, flag concerns, set priorities\n- Agents read this to understand human intent that is not captured as formal Intent nodes\n- Never modified by the LLM consolidator — only appended to\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| decision      | decision-log.md |\n| observation   | compliance-summary.md or reporting-context.md |\n| progress      | decision-log.md |\n| issue         | escalation-queue.md |\n| insight       | compliance-summary.md |\n| todo          | escalation-queue.md |\n| question      | escalation-queue.md |\n\n## Consolidation Rules\n1. escalation-queue.md is the operator entry point — keep it concise and actionable.\n2. NEVER remove or modify entries in decision-log.md — only append. This is an audit trail.\n3. compliance-summary.md should be a single-page executive view — synthesize, do not dump raw data.\n4. operator-notes.md is human-authored — the consolidator must NEVER rewrite or synthesize it.\n5. When an escalation is resolved, move it from escalation-queue.md to decision-log.md with the resolution.\n6. Use ISO 8601 timestamps throughout.\n7. Tag all entries with the model state version (POR version) they relate to."
      }
    },
    "id": 11
  }' | python -m json.tool
```

### 2.3.3 — Space: `ibn-por-v1` (Plan-of-Record — first version)

This is the first model-state space. We create one for POR v1 (the HLD baseline seeded in Step 1).

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-por-v1",
        "description": "Plan-of-Record v1 — HLD baseline campus network. Approval audit trail and governance evidence.",
        "owner": "ibn-system",
        "rules": "# IBN Plan-of-Record — Memory Bank Rules\n\n## Purpose\nThis space documents the approved Plan-of-Record (POR) for the campus network. It captures why specific design decisions were approved, who approved them, and the governance evidence trail. This is the most important space for audit and compliance.\n\n## Mandatory Bank Files\n\n### 1. approval-record.md\n**Role:** Formal record of POR approval.\n- Approval authority, date, conditions\n- Scope of what was approved (sites, VLANs, firewall pairs, policies)\n- Any constraints or exceptions noted during approval\n- Immutable once POR is active — do not modify\n\n### 2. design-rationale.md\n**Role:** Why the POR design was chosen over alternatives.\n- Key design decisions with justification\n- Trade-offs considered and rejected alternatives\n- HLD references (section numbers) for traceability\n- Organized by topic: topology, segmentation, firewall model, VLAN scheme\n\n### 3. validation-results.md\n**Role:** Results of Campus profile constraint validation.\n- Each constraint: pass/fail, details, timestamp\n- Schema version validated against\n- Agent 4 (Planning) validation output\n\n### 4. change-history.md\n**Role:** Chronological record of changes to the POR.\n- Each entry: what changed, who requested, who approved, rationale\n- Links to the Candidate space that originated the change\n- This file grows over the POR lifetime\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| decision      | approval-record.md or design-rationale.md |\n| observation   | validation-results.md |\n| progress      | change-history.md |\n| insight       | design-rationale.md |\n| issue         | validation-results.md |\n\n## Consolidation Rules\n1. approval-record.md entries are append-only — never rewrite or summarize approval records.\n2. design-rationale.md should be structured by topic, not chronologically.\n3. Always include HLD section references when documenting design decisions.\n4. validation-results.md should clearly distinguish PASS from FAIL constraints.\n5. change-history.md entries must include: date, source (which Candidate), requester, approver.\n6. This space is a primary candidate for Graph-Memory push — preserve causal chains."
      }
    },
    "id": 12
  }' | python -m json.tool
```

### 2.3.4 — Space: `ibn-candidate-bootstrap` (Candidate Template)

This serves as the template for candidate spaces. In practice, each new Candidate model gets a new space (`ibn-candidate-{id}`).

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-candidate-bootstrap",
        "description": "Template Candidate space — clone rules for each new Candidate model instance.",
        "owner": "ibn-system",
        "rules": "# IBN Candidate Model — Memory Bank Rules\n\n## Purpose\nThis space captures the translation process: intent decomposition into policies, config rendering decisions, and validation results for a proposed change. Agents 1-4 write here.\n\n## Mandatory Bank Files\n\n### 1. policy-decisions.md\n**Role:** How the intent was decomposed into policies and firewall rules.\n- Intent reference (intentId from Neo4j)\n- Each policy rule: source zone, dest zone, action, justification\n- Conflict resolution notes (if rules overlapped with existing POR)\n- SGT assignments and DSCP markings\n\n### 2. config-rendering.md\n**Role:** Configuration generation context.\n- Which devices are affected\n- Jinja2 template versions used\n- Config diff summary (what changed vs POR baseline)\n- Any rendering issues or workarounds\n\n### 3. validation-results.md\n**Role:** Pre-approval validation by Agent 4 (Planning).\n- Blast radius analysis: devices, interfaces, VLANs affected\n- Campus profile constraint check: pass/fail per constraint\n- What-If simulation results (if performed)\n- Risk assessment: LOW / MEDIUM / HIGH / CRITICAL\n\n### 4. rejected-alternatives.md\n**Role:** Options considered but not selected.\n- Each alternative: description, why rejected, who rejected\n- Preserves institutional memory of what was tried\n- Important for Graph-Memory — prevents re-exploring failed options\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| decision      | policy-decisions.md |\n| observation   | config-rendering.md or validation-results.md |\n| progress      | config-rendering.md |\n| issue         | validation-results.md |\n| insight       | rejected-alternatives.md |\n| question      | validation-results.md |\n\n## Consolidation Rules\n1. Always include the Neo4j intentId and policyId references for traceability.\n2. policy-decisions.md should be organized by zone pair (source→dest), not chronologically.\n3. Preserve conflict resolution chains — these explain WHY a rule looks the way it does.\n4. validation-results.md must clearly state APPROVED or BLOCKED with reasons.\n5. rejected-alternatives.md is critical for learning — never discard alternative analysis.\n6. Keep config-rendering.md focused on diffs, not full configs."
      }
    },
    "id": 13
  }' | python -m json.tool
```

### 2.3.5 — Space: `ibn-deploy-bootstrap` (Deployment Template)

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-deploy-bootstrap",
        "description": "Template Deployment space — clone rules for each DeploymentEvent.",
        "owner": "ibn-system",
        "rules": "# IBN Deployment — Memory Bank Rules\n\n## Purpose\nThis space documents a specific deployment event: what was pushed to NetLab, how it went, and the post-deploy verification. Agent 5 (Orchestration) is the primary writer.\n\n## Mandatory Bank Files\n\n### 1. deployment-log.md\n**Role:** Step-by-step deployment execution record.\n- Deployment event ID (from Neo4j DeploymentEvent node)\n- Devices targeted, in deployment order\n- Per-device: commands pushed, SSH session duration, success/failure\n- Rollback points saved\n- Total deployment time\n\n### 2. verification-results.md\n**Role:** Post-deployment verification.\n- Per-device: expected vs actual state comparison\n- Rules confirmed count vs total\n- Any discrepancies found\n- Verification method (CLI poll, gNMI, SNMP)\n\n### 3. jinja2-context.md\n**Role:** Rendering context used for this deployment.\n- Template versions (vyos_firewall_base.j2, vyos_firewall_policies.j2, etc.)\n- Neo4j Cypher queries executed for context extraction\n- Variable values fed to templates\n- Intent traceability header content\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| progress      | deployment-log.md |\n| observation   | verification-results.md |\n| decision      | deployment-log.md |\n| issue         | deployment-log.md or verification-results.md |\n| insight       | jinja2-context.md |\n\n## Consolidation Rules\n1. deployment-log.md must be chronologically ordered — preserve the exact sequence.\n2. Never lose per-device success/failure status.\n3. verification-results.md should clearly state VERIFIED or FAILED per device.\n4. Include Neo4j deployId references for cross-system traceability.\n5. jinja2-context.md is reference material — keep it factual, no synthesis needed."
      }
    },
    "id": 14
  }' | python -m json.tool
```

### 2.3.6 — Space: `ibn-asbuilt-current` (As-Built — Current Snapshot)

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-asbuilt-current",
        "description": "Current As-Built observations — monitoring telemetry interpretation, anomaly narratives.",
        "owner": "ibn-system",
        "rules": "# IBN As-Built Observations — Memory Bank Rules\n\n## Purpose\nThis space captures Agent 6 (Monitoring) observations about the running network. It holds the human-readable interpretation of telemetry — what the numbers mean, trends forming, anomalies detected but not yet triggering incidents.\n\n## Mandatory Bank Files\n\n### 1. network-health.md\n**Role:** Current network health summary.\n- Per-device: status (UP/DOWN/DEGRADED), key metrics, last seen\n- Per-VLAN: utilization, broadcast storm indicators\n- Overall health score\n- Updated on every consolidation\n- Target size: <8 KB — this is the monitoring dashboard\n\n### 2. anomaly-watch.md\n**Role:** Anomalies detected but not yet incident-level.\n- Each anomaly: metric, threshold proximity, duration, affected scope\n- Trend direction (worsening/stable/improving)\n- Remove anomalies that return to normal\n- Escalate to ibn-loop-inner when threshold is crossed\n\n### 3. telemetry-insights.md\n**Role:** Interpretive analysis of telemetry patterns.\n- Correlations between metrics (e.g., latency spike on VLAN 110 correlates with peak hours)\n- Capacity trends (growth rate, time-to-exhaustion estimates)\n- Performance baselines by time-of-day\n- This is the richest file for Graph-Memory — preserves analytical reasoning\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| observation   | network-health.md or anomaly-watch.md |\n| insight       | telemetry-insights.md |\n| issue         | anomaly-watch.md |\n| progress      | network-health.md |\n| decision      | anomaly-watch.md |\n\n## Consolidation Rules\n1. network-health.md should be a snapshot — replace entirely on each consolidation, do not accumulate history.\n2. anomaly-watch.md entries have a lifecycle: new → watching → resolved OR escalated. Track the state.\n3. telemetry-insights.md is cumulative — synthesize but never discard analytical observations.\n4. Always include the timestamp and the metric source (gNMI path, SNMP OID, CLI command) for reproducibility.\n5. Remove stale anomalies (>24h without update) from anomaly-watch.md.\n6. Correlations in telemetry-insights.md should reference specific VLAN tags, device hostnames, and interface names."
      }
    },
    "id": 15
  }' | python -m json.tool
```

### 2.3.7 — Space: `ibn-whatif-bootstrap` (What-If Template)

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_create",
      "arguments": {
        "space_id": "ibn-whatif-bootstrap",
        "description": "Template What-If space — clone rules for each exploration session.",
        "owner": "ibn-system",
        "rules": "# IBN What-If Exploration — Memory Bank Rules\n\n## Purpose\nThis space captures design exploration by Agent 4 (Planning) and the Human Operator. Multiple options are evaluated before one is promoted to Candidate. These spaces are ephemeral.\n\n## Mandatory Bank Files\n\n### 1. exploration-brief.md\n**Role:** What question is being explored and why.\n- Trigger: what prompted this What-If (capacity concern, new intent, incident response)\n- Scope: which parts of the network are under consideration\n- Constraints: budget, timeline, compatibility requirements\n- Created once, rarely modified\n\n### 2. options-analysis.md\n**Role:** Options evaluated with pros/cons.\n- One section per option\n- Each: description, impact (devices/VLANs/rules affected), risk level, estimated effort\n- Comparison matrix at the top\n- Mark the selected option clearly when decision is made\n\n### 3. simulation-results.md\n**Role:** Results of What-If graph queries and impact analysis.\n- Blast radius calculations\n- Capacity projections\n- Failure scenario outcomes\n- Neo4j query references used\n\n## Consolidation Mapping\n| Note Category | Target File |\n|---------------|-------------|\n| observation   | simulation-results.md |\n| decision      | options-analysis.md |\n| insight       | options-analysis.md |\n| question      | exploration-brief.md |\n| progress      | simulation-results.md |\n\n## Consolidation Rules\n1. exploration-brief.md is set once — the consolidator should only append clarifications.\n2. options-analysis.md should maintain a clear structure: one section per option, comparison matrix updated.\n3. When an option is selected, mark it prominently (## SELECTED: Option X) with rationale.\n4. simulation-results.md should include the actual Cypher queries used for reproducibility.\n5. These spaces are ephemeral — optimize for clarity over longevity."
      }
    },
    "id": 16
  }' | python -m json.tool
```

---

## Step 2.4 — Validate: List All Spaces

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "space_list",
      "arguments": {}
    },
    "id": 20
  }' | python -m json.tool
```

**Expected:** 7 spaces listed:
1. `ibn-loop-inner`
2. `ibn-loop-outer`
3. `ibn-por-v1`
4. `ibn-candidate-bootstrap`
5. `ibn-deploy-bootstrap`
6. `ibn-asbuilt-current`
7. `ibn-whatif-bootstrap`

---

## Step 2.5 — Test the Pipeline: live_note() → bank_consolidate()

Write a few test notes to `ibn-loop-inner`, then trigger consolidation to verify the full pipeline.

```bash
TOKEN=$IBN_AGENT_TOKEN

# ─── Write test notes (simulating Agent 7 observations) ───
for i in 1 2 3; do
  curl -s -X POST "$LM_URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{
      \"jsonrpc\": \"2.0\",
      \"method\": \"tools/call\",
      \"params\": {
        \"name\": \"live_note\",
        \"arguments\": {
          \"space_id\": \"ibn-loop-inner\",
          \"category\": \"observation\",
          \"content\": \"Test observation #$i: POR vs AS-BUILT comparison on fw-hq-usr-01 shows VLAN 100 ACL rule count matches (12/12). No drift detected on this device.\",
          \"tags\": \"test,agent7,compliance\"
        }
      },
      \"id\": $((30 + i))
    }" | python -m json.tool
done

# ─── Write a decision note (simulating Agent 8) ───
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "live_note",
      "arguments": {
        "space_id": "ibn-loop-inner",
        "category": "decision",
        "content": "Test decision: All 4 access switches and 2 USF firewalls show full compliance. No remediation needed this cycle. Inner loop cycle time: 45s.",
        "tags": "test,agent8,compliant"
      }
    },
    "id": 35
  }' | python -m json.tool
```

**Read back the notes:**

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "live_read",
      "arguments": {
        "space_id": "ibn-loop-inner",
        "limit": 10
      }
    },
    "id": 36
  }' | python -m json.tool
```

**Expected:** 4 notes returned with YAML front-matter and timestamps.

**Trigger consolidation:**

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IBN_ADMIN_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "bank_consolidate",
      "arguments": {
        "space_id": "ibn-loop-inner"
      }
    },
    "id": 37
  }' | python -m json.tool
```

**This may take 30–60 seconds** (LLM processing). When complete, read the bank:

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "bank_read_all",
      "arguments": {
        "space_id": "ibn-loop-inner"
      }
    },
    "id": 38
  }' | python -m json.tool
```

**Expected:** Bank files created matching the rules:
- `active-remediations.md` — should note "no active remediations"
- `drift-analysis.md` — should note "no drift detected"
- `remediation-history.md` — should note "no completed remediations yet"
- `loop-metrics.md` — should capture the 45s cycle time metric

**Verify the live notes were consumed** (deleted after consolidation):

```bash
curl -s -X POST "$LM_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "live_read",
      "arguments": {
        "space_id": "ibn-loop-inner",
        "limit": 10
      }
    },
    "id": 39
  }' | python -m json.tool
```

**Expected:** 0 notes — all consumed by consolidation.

---

## Step 2.6 — Verify via Web Dashboard

Open http://localhost:8080/live in your browser.

You should see:
- All 7 spaces listed on the dashboard
- `ibn-loop-inner` showing bank files with content
- Timeline tab showing the consolidated notes (now archived in bank)
- Bank tab showing the 4 Markdown files with structured content

---

## Step 2.7 — What You've Built

| Component | Status |
|-----------|--------|
| Live-Memory MCP server | Running on :8080 (WAF) → :8002 (MCP) |
| S3 storage backend | Connected and operational |
| LLM consolidation | Validated end-to-end |
| 7 IBN spaces | Created with domain-specific rules |
| Token security | Admin + Agent + Operator tokens provisioned |
| Pipeline test | `live_note()` → `bank_consolidate()` → `bank_read_all()` verified |

The **3 template spaces** (`ibn-candidate-bootstrap`, `ibn-deploy-bootstrap`, `ibn-whatif-bootstrap`) serve as rule templates. When an agent needs a new Candidate or Deployment space, it reads the template's rules via `space_rules()` and creates a new space with those rules and a unique ID.

---

## Next Steps

1. **Step 3 — Deploy Graph-Memory (Tier 3)** → Set up Graph-Memory with Qdrant, create the `ibn-lifecycle` memory with custom ontology, configure the Graph Bridge from Live-Memory
2. **Step 4 — Agent 1 (Ingestion) prototype** → Accept structured intent, validate against Neo4j SSoT, create Intent node in L4, emit `live_note()` to appropriate space
3. **Step 5 — Connect the dots** → Wire the event bus so Neo4j model state transitions trigger Live-Memory consolidation automatically
