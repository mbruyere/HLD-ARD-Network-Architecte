# Slice 4 — Agent 4 Planning + Human Approval Gate

Date: 2026-04-11
Plan reference: [PLAN_Slice4_Approval_Gate.md](PLAN_Slice4_Approval_Gate.md)
Predecessors: [FIX_NOTES_Slice3_Device_Provisioning.md](FIX_NOTES_Slice3_Device_Provisioning.md), [FIX_NOTES_Slice2_Multi_Vendor.md](FIX_NOTES_Slice2_Multi_Vendor.md)

## What shipped

Slices 1-3 made every HLD commit auto-flow through ingest →
translate → render → push. Slice 4 makes Agent 4 (Planning) real and
adds a **human approval gate** between the `CANDIDATE` and `POR`
model states. The default behaviour is now:

1. Operator edits the HLD, runs `git commit` (existing Slice 1 hook)
2. Pipeline runs A1 + A2 + Provisioning + **A4 Planning** — produces
   a `MigrationPlan` (L7) summarizing blast radius, severity, and
   inverse plan
3. Pipeline writes a pending-plan markdown file to
   `.git/ibn-pending-approval/<sha>.md` and **EXITS** with
   `cycle_complete=False, awaiting_approval=True`
4. Operator reads the markdown, decides:
   - **Approve:** `python -m ibn.tools.approve <sha>` — bulk-transitions
     CANDIDATE artifacts to POR, runs A3-A5-A7 against the live lab,
     marks the plan APPLIED
   - **Reject:** `python -m ibn.tools.approve reject <sha> --reason ...`
     — marks artifacts REJECTED, archives the plan, leaves the lab
     untouched
5. The full audit trail (PENDING → APPROVED → APPLIED) is queryable
   in Neo4j

This is **RFC 9315 §6 outer-loop, literally**. The inner loop
(autonomous A3-A5-A7) is preserved unchanged; we just gate its entry
on a human signoff.

The Slice 1-3 auto-flow behavior is preserved when `IBN_AUTO_APPROVE=1`
is set, which the existing integration tests now use to keep their
expectations valid.

## New components

| File | Purpose |
|---|---|
| [src/ibn/agents/agent4_planning.py](src/ibn/agents/agent4_planning.py) | New `Agent4Planning` agent. Reads CANDIDATE artifacts in Neo4j, classifies severity (heuristic), generates summary + inverse summary, writes a `MigrationPlan` (L7) node with status PENDING. |
| [src/ibn/tools/approve.py](src/ibn/tools/approve.py) | New CLI: `approve <sha>`, `reject <sha> --reason ...`, `list`. Resolves plans by commit SHA or planId. Approve resumes the pipeline; reject archives. Both idempotent on repeated runs. |
| [tests/unit/test_t21_approval_gate.py](tests/unit/test_t21_approval_gate.py) | 14 unit tests covering: severity classifier (5), summary builders (5), MigrationPlan dataclass (2), orchestrator gate behavior with/without `IBN_AUTO_APPROVE` (2). |

## Modified components

| File | Change |
|---|---|
| [src/ibn/core/models.py](src/ibn/core/models.py) | Added `MigrationPlan` dataclass (L7), `MigrationPlanStatus` enum (PENDING/APPROVED/APPLIED/REJECTED/SUPERSEDED), `PlanSeverity` enum (INFO/LOW/MEDIUM/HIGH/CRITICAL). |
| [src/ibn/core/neo4j_client.py](src/ibn/core/neo4j_client.py) | New writers: `create_migration_plan`, `get_migration_plan`, `get_migration_plan_by_commit`, `list_pending_migration_plans`, `update_migration_plan_status`, `transition_artifacts_to_por`, `reject_artifacts`. All idempotent on entity IDs. |
| [src/ibn/pipeline/hld_commit.py](src/ibn/pipeline/hld_commit.py) | Replaced the Slice 1 A4 stub with the real Agent 4 invocation. Added an explicit "Approval gate" stage that exits when `IBN_AUTO_APPROVE` is unset. Added `_write_pending_plan_md()` for the operator-visible markdown. Added `resume_from_approval(plan_id)` method that re-runs A3-A5-A7 against an APPROVED plan. Refactored A3-A5-A7 into `_run_render_deploy_assess()` so both `run()` and `resume_from_approval()` share it. `_final_result()` now returns `awaiting_approval` and `pending_plan_path` keys. |
| [infra/hooks/post-commit](infra/hooks/post-commit) | Now reads `IBN_AUTO_APPROVE` from `.env` so the operator can persist the auto-flow setting if desired. Prints the approval workflow hint on stdout right after the "running in background" message, including the path to the pending-plan markdown and the exact `ibn approve` command to run. |
| [tests/integration/test_slice1_hld_pipeline.py](tests/integration/test_slice1_hld_pipeline.py) | Added module-level `os.environ["IBN_AUTO_APPROVE"] = "1"` so the Slice 1 auto-flow assertions still hold. |
| [tests/integration/test_slice2_multi_vendor.py](tests/integration/test_slice2_multi_vendor.py) | Same — Slice 2 tests assert auto-flow behavior. |

## End-to-end demo

```bash
# 1. Edit the HLD population table
$EDITOR "Enterprise_Campus_Network_HLD (1).md"
#   ↑ add VLAN 195 'Lab Demo Pop'

# 2. Commit
git commit -am "Add Lab Demo population"
# → [ibn-hook] HLD changed in c0ffee — closed-loop pipeline running in background
# → [ibn-hook] tail -f .git/ibn-hld-pipeline.log to follow
# → [ibn-hook] After A4 planning the pipeline will pause for human approval.
# → [ibn-hook] Look for: .git/ibn-pending-approval/c0ffee.md
# → [ibn-hook] Then run:  python -m ibn.tools.approve c0ffee

# 3. Wait a few seconds, then read the plan
cat .git/ibn-pending-approval/c0ffee.md
#   # Pending Plan PLAN-c0ffee
#
#   **Commit:** `c0ffee...`
#   **Severity:** **LOW**
#   **Blast radius:** 5 devices
#
#   ## Summary
#   +1 populations
#
#   ## Inverse plan (rollback summary)
#   delete VLAN 195
#
#   ## Affected devices
#     - `clab-ibnlab-switches-acc-sw-01`
#     - ...
#
#   ## To approve
#   python -m ibn.tools.approve c0ffee
#
#   ## To reject
#   python -m ibn.tools.approve reject c0ffee --reason "..."

# 4. Approve
python -m ibn.tools.approve c0ffee
#   [approve] PLAN-c0ffee commit=c0ffee severity=LOW blast=5 → APPROVING as ubuntu
#
#   Resume summary for PLAN-c0ffee:
#     ✓ resume                 plan=PLAN-c0ffee commit=c0ffee intents=1
#     ✓ A3 render              13 configs rendered
#     ✓ A5 deploy              1 devices pushed, 12 skipped (empty render)
#     ✓ A7 assessment          1 assessments
#   cycle_complete: True

# 5. Verify in Neo4j
docker exec ibn-neo4j cypher-shell -u neo4j -p ibn-closed-loop-2026 \
  "MATCH (mp:MigrationPlan {commitSha: 'c0ffee...'}) RETURN mp.status, mp.approvedBy, mp.appliedAt"
#   APPLIED, ubuntu, 2026-04-11T...
```

## Test results

| Suite | Result |
|---|---|
| `tests/unit/test_t21_approval_gate.py` (Slice 4 unit) | **14/14 pass** |
| `tests/unit/test_t20_provisioner.py` (Slice 3 unit regression) | 18/18 pass |
| `tests/unit/test_hld_parser.py` (parser regression) | 12/12 pass |
| `tests/integration/test_slice1_hld_pipeline.py` (Slice 1, with IBN_AUTO_APPROVE) | 4/4 pass |
| `tests/integration/test_slice2_multi_vendor.py` (Slice 2, with IBN_AUTO_APPROVE) | 5/5 pass |
| `tests/integration/test_slice3_provisioning.py` (Slice 3 smoke) | 3/3 pass |
| `tests/unit/test_t4_agent1_ingestion.py` (A1 regression) | 12/12 pass |
| `tests/unit/test_t5_agent3_policy_config.py` (A3 regression) | 20/20 pass |
| `tests/unit/test_t6_agent5_orchestration.py` (A5 regression) | 12/12 pass |

**100/100 across all touched suites — no regressions.**

## Architectural decisions made during execution

1. **`IBN_AUTO_APPROVE` env var as the bypass mechanism.** The plan
   called for either a flag or a CLI option. Env var won because it
   composes cleanly with the post-commit hook (which can read it from
   `.env`) and with pytest (each test file sets it at module import
   time). It's also discoverable: the hook prints whether it's enabled
   on every fire.

2. **`resume_from_approval()` as a separate method on `HldCommitPipeline`.**
   The plan suggested re-deriving state from Neo4j; this is exactly
   what the method does. It calls the same `_run_render_deploy_assess()`
   helper as the auto-approve path, so there's only one A3-A5-A7
   implementation in the codebase.

3. **A4 reads policy/config IDs from Neo4j**, not from the orchestrator's
   in-memory state. This is so the resume path (which has no in-memory
   state from the original commit) gets the same view of the world.

4. **Pending plans are markdown files in `.git/ibn-pending-approval/`,
   not git-tracked.** They're operator notes, not source-of-truth.
   The source-of-truth is the `MigrationPlan` node in Neo4j. The
   markdown is convenience UX for the operator's terminal. On approve
   the markdown is removed (the operator doesn't need it any more);
   on reject it's also removed (the rejection reason is in Neo4j).

5. **Approve subcommand is the default** when the first positional arg
   is a SHA — `python -m ibn.tools.approve abc123` is equivalent to
   `python -m ibn.tools.approve approve abc123`. This matches the
   common case (the operator just wants to approve) without forcing
   them to type the subcommand.

6. **SUPERSEDED status for repeat commits.** If the operator commits
   the same HLD diff twice (or amends), A4 detects the existing PENDING
   plan and marks it SUPERSEDED before creating the new one. The audit
   trail keeps both rows.

7. **Severity classifier is intentionally simple** (5 buckets, no
   graph traversal). The plan deferred real blast-radius analysis to
   Slice 6. The current heuristic gives the operator a useful flag
   (HIGH = think twice) without pretending to know more than it does.

## Known limitations (deferred)

1. **No GitHub PR-based approval workflow.** Slice 5 will add a
   GitHub Actions wrapper that runs A4 in CI and posts the plan as a
   PR comment, with merge = approve.

2. **Severity classifier is heuristic.** Slice 6 will replace it with
   a real graph-traversal blast radius that walks SSoT relationships.

3. **No multi-operator quorum approval.** Slice 6 will add N-of-M
   signoff support.

4. **No notification on pending.** The operator has to know to look at
   `.git/ibn-pending-approval/` or run `ibn approve list`. Slice 6 may
   add Slack / email integration.

5. **Approval CLI runs the resume in the operator's terminal**, not
   detached. This is intentional for Slice 4 (the operator wants to
   see the result), but means a long A5 push blocks the terminal.
   Could be moved to a background mode in a later slice.

6. **The full live integration test for Slice 4** (commit + verify
   gate fires + approve + verify lab updated + reject + verify
   archived) was NOT added to CI for the same memory-pressure reason
   as Slice 3 — it would need a clab deploy spike to verify the back
   half. The unit tests cover the gate logic; the live verification
   path is documented in the demo above.

## Schema evolution

- New L7 entity: `MigrationPlan` with properties `planId, commitSha,
  intentIds, policyIds, configIds, deviceIds, blastRadius, severity,
  summary, inverseSummary, status, createdAt, approvedAt, approvedBy,
  appliedAt, rejectedAt, rejectedBy, rejectedReason`. List properties
  are stored natively as Neo4j arrays (the resume path reads them as
  Python lists).
- No new relationships in this slice. The plan references artifacts
  by id list, not by direct edges. Slice 6 may upgrade to relationship
  edges if it needs traversal queries.

## Followups

- **Wire IBN_AUTO_APPROVE into the conftest.py default** for the
  integration suite (currently each test file sets it at module load).
- **Add a `resume_in_background` mode** to the approval CLI so the
  operator's terminal doesn't block on long pushes.
- **Replace `_remove_pending_md` with an "archive to .git/ibn-archived/"
  flow** so the audit trail of past plans is browsable on disk (Neo4j
  is the SSoT, but a flat-file archive is convenient for grep).
- **Update CLAUDE.md Implementation Status** for Slice 4.
- **Document the approval workflow in STEP4_HLD_Driven_Loop_Bootstrap.md**
  alongside the post-commit hook installation.
