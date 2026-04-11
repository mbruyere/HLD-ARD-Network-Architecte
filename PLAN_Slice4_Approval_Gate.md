# Slice 4 — Agent 4 Planning + Human Approval Gate

Date: 2026-04-11
Status: **DRAFT — about to execute (operator approved 1.2.3.)**
Predecessors: [PLAN_Slice3_Device_Provisioning.md](PLAN_Slice3_Device_Provisioning.md), [FIX_NOTES_Slice3_Device_Provisioning.md](FIX_NOTES_Slice3_Device_Provisioning.md)

## Goal of this slice

Slices 1-3 made the closed loop **automatic**: every HLD commit
auto-flows through ingest → translate → render → push → assess,
including spinning up new containers. That works for trusted edits
on a development lab. **For real network changes, you want a human
approval step between "this is what would change" and "actually
change it."**

Slice 4 makes Agent 4 (Planning) real and adds a **human approval
gate** between the `CANDIDATE` and `POR` model states. The flow
becomes:

1. Operator edits the HLD, runs `git commit` (Slice 1 hook)
2. Pipeline runs A1 (ingest) and A2 (translate) — produces
   `CANDIDATE` Intents/Policies/Configs in Neo4j
3. **A4 Planning** computes the change set: blast radius (which
   devices touched), impact severity (info / warning / risk),
   inverse plan (rollback steps), and writes a `MigrationPlan` (L7)
   node summarizing it
4. **Approval gate** stops the pipeline. The MigrationPlan is
   surfaced to the operator via:
   - The git commit message (the hook prints a one-line summary
     to stdout)
   - A `.git/ibn-pending-approval/<commit>.md` markdown file with
     the full plan
   - A Live-Memory `ibn-loop-outer` note
5. Operator reviews and either:
   - **Approves**: runs `python -m ibn.tools.approve <commit>` (or
     `ibn approve <commit>` if we add a wrapper). The pending plan
     is moved to `POR`, the rest of the pipeline resumes (A3 → A5
     → A7) automatically.
   - **Rejects**: runs `ibn reject <commit> --reason "..."`. The
     CANDIDATE artifacts are marked `REJECTED`, the pending plan
     is moved to a rejection log, and the original What-If state
     is preserved for audit.
6. If approved, A3-A5-A7 run as before, the `Configuration` and
   `DeploymentEvent` nodes get the `POR`/`DEPLOYED` model state, and
   the new HLD becomes the new "as built."

## Vision alignment

This is **RFC 9315 §6 outer loop, literally**. The outer loop in the
RFC is the human-in-the-loop check that bounds what the autonomous
inner loop can do. Slice 4 makes that boundary a real git workflow:

- **What-If state** = the CANDIDATE Intents/Policies/Configurations
  from Slice 1+2+3, untouched by the operator
- **Plan-of-Record (POR)** = the operator's approval transitions the
  CANDIDATE artifacts into POR via Cypher batch update
- **Inner loop autonomy** = once at POR, A3-A5-A7 run automatically
  without further operator intervention (this is exactly what Slices
  1-3 already do, just gated now)

The operator still uses `git commit` as the primary input. The
approval workflow uses the same commit SHA as the correlation key
between "what was committed" and "what was approved."

## In scope for Slice 4

| # | Component | New / Modified | Description |
|---|---|---|---|
| 1 | A4 Planning agent | new | `src/ibn/agents/agent4_planning.py`. Reads CANDIDATE artifacts in Neo4j, computes blast radius (device count + LifecycleEvent count), classifies severity, generates a `MigrationPlan` (L7) node with the full audit data. |
| 2 | `MigrationPlan` data model | new | Dataclass for L7. Properties: `planId, intentIds, policyIds, configIds, deviceIds, blastRadius, severity, summary, inverseSummary, status (PENDING/APPROVED/REJECTED), createdAt, approvedAt, rejectedAt, rejectedReason`. |
| 3 | Neo4jClient writers | new | `create_migration_plan`, `approve_migration_plan(plan_id, operator_id)`, `reject_migration_plan(plan_id, reason)`, `get_migration_plan(plan_id)`, `get_pending_plans()`. |
| 4 | Pipeline orchestrator | modified | New stage between A2 and A3 (or between Provisioning and A3 in the Slice 3 layout): `A4 Planning + Approval Gate`. If `IBN_AUTO_APPROVE=1` is set (or the operator passes `--auto-approve`), the gate is bypassed (Slice 1-3 default behavior). Otherwise the pipeline writes the pending plan and exits with `cycle_complete=False, awaiting_approval=True`. |
| 5 | Approval CLI tool | new | `src/ibn/tools/approve.py` with `python -m ibn.tools.approve <commit>` and `... reject <commit> --reason ...`. Resumes the pipeline from the gate point — runs A3-A5-A7 against the Neo4j artifacts that were transitioned to POR. |
| 6 | Pending-plan markdown writer | new | When the gate fires, writes `.git/ibn-pending-approval/<commit>.md` with the full plan: blast radius, devices touched, configurations rendered, severity, inverse summary, and the exact `ibn approve <commit>` / `ibn reject <commit>` commands. |
| 7 | Hook update | modified | The post-commit hook now prints the pending-plan markdown path (and the approve/reject one-liners) on stdout immediately after returning, so the operator sees them before the terminal scrolls. |
| 8 | Resume mechanism | new | Approval CLI re-loads the orchestrator's state from Neo4j (the CANDIDATE artifacts) and runs A3-A5-A7 with `IBN_RESUME_FROM_APPROVAL=1` to skip the gate and the earlier stages. |
| 9 | Acceptance test | new | `tests/unit/test_t21_approval_gate.py` (mocked, fast) + `tests/integration/test_slice4_approval.py` (live, lightweight). Asserts: (a) gate fires for a normal commit, (b) plan markdown gets written, (c) `approve` transitions CANDIDATE → POR and the rest of the pipeline runs, (d) `reject` marks plan REJECTED and leaves POR untouched. |
| 10 | CLAUDE.md update | modified | Mark Slice 4 in implementation status; document the new operator workflow. |
| 11 | Commit + write FIX_NOTES_Slice4 | — | Standard convention. |

## Out of scope for Slice 4 (deferred)

| Item | Slice |
|---|---|
| GitHub PR-based approval (vs. CLI command) | **5** |
| Web UI for plan review | **6** |
| Multi-operator approval (require N-of-M signoffs) | **6** |
| Real blast radius graph traversal (trace dependencies through L1-L9) | **6** — Slice 4 ships a simpler "device count + severity heuristic" |
| Slack/email notifications when a plan is pending | **6** |
| Time-based auto-approval ("approve if no rejection within 24h") | **6** |

## Architecture — what Slice 4 adds

```
                Enterprise_Campus_Network_HLD (1).md
                          │  git commit
                          ▼
                .git/hooks/post-commit
                          │
                          ▼
            ibn.pipeline.hld_commit  (Slice 1+2+3+4)
                          │
        ┌─────────────────┴──────────────────┐
        ▼                                    ▼
   A1 ingest (population + devices)     [other agents]
        │
        ▼
   A2 translate
        │
        ▼
   Provisioning  (Slice 3)
        │
        ▼
   A4 Planning  ── NEW IN SLICE 4 ──
   • compute blast radius
   • classify severity
   • generate MigrationPlan (L7)
   • write inverse summary
        │
        ▼
   Approval Gate ── NEW IN SLICE 4 ──
   if IBN_AUTO_APPROVE:           if NOT IBN_AUTO_APPROVE:
      pass through                   write pending-plan markdown
                                     write Live-Memory note
                                     return cycle_complete=False
                                     pipeline EXITS HERE
                                              │
                                              ▼
                                     operator reviews
                                              │
                                ┌─────────────┴──────────────┐
                                ▼                            ▼
                          ibn approve <sha>         ibn reject <sha> --reason
                                │                            │
                                ▼                            ▼
                          plan.status=APPROVED         plan.status=REJECTED
                          CANDIDATE→POR transition     CANDIDATE→REJECTED
                          resume A3-A5-A7              archive, no push
                                │
                                ▼
                          A3 render / A5 push / A7 assess
                          (existing Slice 1-3 logic, unchanged)
```

## Data flow walkthrough

Operator adds a row to the HLD population table:

```diff
+ | Lab Demo Pop | 195 | 5-10 | 2-5 | Standard | AF21 | 1 Mbps |
```

Pipeline behavior:

1. Hook fires.
2. A1 ingestion creates `INT-HLD-195` (CANDIDATE).
3. A1 device ingest: no device changes → no-op.
4. A2 translation: creates `POL-INT-HLD-195` + 5 FirewallRules (CANDIDATE).
5. Provisioning: no device changes → no-op.
6. **A4 Planning runs** (NEW). Reads the CANDIDATE artifacts:
   - 1 new Intent
   - 1 new Policy
   - 5 new FirewallRules
   - Devices that would be touched (firewalls + the SR Linux switch): 5
   - Severity classification: `LOW` (single VLAN add, no removals)
   - Inverse summary: "delete VLAN 195, delete firewall rules, delete intent"
   - Writes `MigrationPlan PLAN-<commit>` (L7) with status=PENDING
7. **Approval gate fires.** Writes `.git/ibn-pending-approval/<sha>.md`:

   ```markdown
   # Pending Plan PLAN-c968f18

   ## Summary
   +1 population (VLAN 195 'Lab Demo Pop'), +1 policy, +5 firewall rules

   ## Blast radius
   5 devices: clab-ibnlab-usf1, usf2, dmzfw1, dmzfw2, acc-sw-01

   ## Severity: LOW

   ## Inverse plan
   On rollback: delete VLAN 195, drop firewall rules, mark intent RETIRED

   ## To approve
   ```
   ibn approve c968f18
   ```

   ## To reject
   ```
   ibn reject c968f18 --reason "needs security review"
   ```
   ```

   Hook stdout prints:
   ```
   [ibn-hook] PENDING APPROVAL: plan PLAN-c968f18 written to .git/ibn-pending-approval/c968f18.md
   [ibn-hook] Run `ibn approve c968f18` or `ibn reject c968f18 --reason ...`
   ```

8. **Pipeline EXITS** at this point. No A3, no A5, no A7 yet. The
   running infra is unchanged. The CANDIDATE artifacts sit in Neo4j
   waiting for the operator's decision.

9. Operator reviews the markdown, decides to approve:
   ```bash
   python -m ibn.tools.approve c968f18
   ```

10. Approve CLI:
    - Loads `MigrationPlan PLAN-c968f18`
    - Marks `status=APPROVED`, sets `approvedAt`, `approvedBy=$USER`
    - Transitions all CANDIDATE artifacts referenced in the plan to POR
      (via a single Cypher MATCH ... SET batch)
    - Runs `HldCommitPipeline.resume_from_approval(plan_id)` which
      runs A3 → A5 → A7 against the now-POR artifacts

11. Live SR Linux switch receives the new VLAN config via the same
    Slice 2 push path. Audit trail in Neo4j now shows the full
    PENDING → APPROVED → DEPLOYED → AS_BUILT chain.

If the operator had run `ibn reject c968f18 --reason "needs security review"`:
- `MigrationPlan.status=REJECTED, rejectedReason=...`
- CANDIDATE artifacts marked `REJECTED` (but kept in Neo4j for audit)
- No A3-A5-A7
- Live infra unchanged
- The HLD edit stays in git history but does not become reality

## Why this isn't a "branch and merge" workflow yet

Real production GitOps uses branches + PRs + merges:
- Operator works on a feature branch
- Opens a PR
- CI runs A4 + posts the plan as a PR comment
- Reviewer approves the PR → merge to `main`
- Post-merge hook runs A3-A5-A7

Slice 4 ships the **single-branch** version of this workflow because:

1. The git hook story (Slice 1) already uses a single-branch model
2. PR-based workflows require either GitHub Actions or a local CI
   runner — both of which would slow Slice 4 down significantly
3. The CLI-based approve/reject is a strict superset of "merge to main"
   in terms of what it has to do (transition Cypher state + resume the
   pipeline). PR-based is just a prettier UI on top.

**Slice 5** will add the GitHub PR-based wrapper. The approval logic
itself is identical — just a different trigger.

## Severity classification (Slice 4 heuristic)

A4 ships a deliberately simple classifier:

| Conditions | Severity |
|---|---|
| `devices_added > 0` (new physical/virtual hardware) | **HIGH** |
| `devices_removed > 0` (decommissioning) | **HIGH** |
| `populations_removed > 0` (a VLAN goes away) | **MEDIUM** |
| Otherwise — single population add or modify | **LOW** |
| No changes (no-op pipeline) | **INFO** |

Slice 6 will replace this with a real graph-traversal blast radius
that walks the SSoT relationships and computes:
- How many endpoints are in each affected VLAN
- Which DMZ services depend on them
- Which agents would have to re-render
- The expected cycle time of the rollback

For Slice 4 the heuristic is enough — it gives the operator a useful
flag (HIGH = think twice) without pretending to be more accurate than
it is.

## Resume mechanism

The approval CLI needs to "pick up" the pipeline at the gate. Two
options were considered:

**(a) Persist the orchestrator state to disk** at the gate, replay
on approve. Complex (need to serialize Python state, version it, etc.).

**(b) Re-derive everything from Neo4j** at approve time. The CANDIDATE
artifacts are already in the database. The approve CLI just needs to
know which plan to operate on. **This is what we'll ship.** It's
simpler, idempotent, and resilient to crashes between commit and approve.

Concretely: the approve CLI calls
`HldCommitPipeline.resume_from_approval(plan_id)` which:

1. Loads the MigrationPlan from Neo4j
2. Reads the list of intent_ids and device_ids it references
3. Skips A1, A2, Provisioning, A4, gate (already done)
4. Runs A3 with the intent_ids → renders configs
5. Runs A5 with the rendered configs → pushes
6. Runs A7 → assesses
7. Marks the MigrationPlan `status=APPLIED, appliedAt=now`

## Work breakdown — execution order

1. **MigrationPlan dataclass** in `models.py` + `MigrationPlanStatus` enum
2. **Neo4jClient writers** for migration plan CRUD
3. **Agent 4 Planning** in `src/ibn/agents/agent4_planning.py` —
   reads CANDIDATE artifacts, computes severity, writes plan
4. **Pipeline orchestrator** — new gate stage between A2/Provisioning
   and A3, with `IBN_AUTO_APPROVE` env var for bypass
5. **Pending-plan markdown writer** — `_write_pending_plan_md(plan)`
   helper that creates the markdown file in `.git/ibn-pending-approval/`
6. **Approval CLI** — `src/ibn/tools/approve.py` with `approve` and
   `reject` subcommands
7. **resume_from_approval()** method on the orchestrator — runs A3-A5-A7
8. **Hook update** — print the pending-plan path after pipeline exits
   on `awaiting_approval=True`
9. **Unit tests** — `tests/unit/test_t21_approval_gate.py`
10. **Integration smoke test** — `tests/integration/test_slice4_approval.py`
    (lightweight: no clab deploy, just HLD population edits)
11. **Update existing acceptance tests** that assume auto-approval —
    they'll need to set `IBN_AUTO_APPROVE=1` to keep working
12. **CLAUDE.md** + commit + FIX_NOTES

## Acceptance criteria

Slice 4 is **done** when:

1. Editing the HLD population table and committing produces a
   pending-plan markdown file in `.git/ibn-pending-approval/`,
   the pipeline exits with `cycle_complete=False, awaiting_approval=True`,
   and **no config is pushed to any device**.
2. Running `python -m ibn.tools.approve <commit>` transitions the
   CANDIDATE artifacts to POR, runs A3-A5-A7 against the live SR
   Linux switch, and returns success.
3. Running `python -m ibn.tools.reject <commit> --reason ...` marks
   the plan REJECTED and leaves the live infra untouched.
4. Setting `IBN_AUTO_APPROVE=1` in the environment bypasses the gate
   entirely, preserving the Slice 1-3 auto-flow behavior for tests
   that depend on it.
5. Slice 1, 2, and 3 acceptance tests still pass (with
   `IBN_AUTO_APPROVE=1` set as part of their env).
6. Slice 4 acceptance test passes.
7. Slice 4 documented in `FIX_NOTES_Slice4_Approval_Gate.md`.

## Decisions deferred to later slices

| Item | Slice |
|---|---|
| Real graph-traversal blast radius (not just device count) | **6** |
| GitHub PR-based approval workflow | **5** |
| Web UI / dashboard for pending plans | **6** |
| Multi-operator quorum approval | **6** |
| Auto-approve based on time / past success rate | **6** |
| Notification (Slack / email) on pending | **6** |

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| Existing Slice 1-3 acceptance tests assume auto-flow and will start failing the moment the gate is added | Add `IBN_AUTO_APPROVE=1` to the test env in conftest.py for the integration suite. Document the flag in the CLAUDE.md test instructions. |
| Operator forgets to approve → CANDIDATE artifacts pile up in Neo4j | Approve CLI surfaces a "pending plans" subcommand: `ibn list-pending`. Slice 6 will add a dashboard or stale-plan reaper. |
| The same HLD line edited twice in two commits creates two pending plans for the same intent | A4 detects this: if a CANDIDATE Intent already has a PENDING plan, the new commit's plan REPLACES it (and marks the old plan SUPERSEDED). |
| `ibn approve` runs against a stale Neo4j (the operator manually deleted the CANDIDATE artifacts) | Approve fails loud with "plan references missing artifacts; cannot resume." The operator has to re-commit the HLD. |
| Approve CLI hits the same memory pressure that killed the live integration test in Slice 3 | Approve runs A3-A5-A7 in the same process as the operator's terminal, not as a background job. The operator sees the output directly. If memory is tight, the operator can free up infra before approving. |
| User confuses "git commit" with "approve" — commits but doesn't approve, expects deployment | Hook stdout makes the pending state explicit. The pending-plan markdown is named `<commit>.md` so the operator sees it in their working tree. |

## Open questions for the operator

None — all four "1.2.3." pre-approvals and the Slice 4 plan above
form a complete spec. Proceeding with execution.
