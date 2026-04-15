"""
HLD-commit pipeline orchestrator — Slice 1.

Reads the diff between two HLD revisions, drives the closed loop:

    A1 (HLD ingest + dialogue)
      → A2 (Intent → Policy/FirewallRule)
        → A4 (Planning — STUB in Slice 1, real in Slice 4)
          → A3 (Policy → VyOS Configuration)
            → A5 (SSH push)
              → A7 (Compliance assessment)

Each step writes to Neo4j with the appropriate model state and emits a
``live_note()`` to the ``ibn-loop-outer`` Live-Memory space so the
consolidation pipeline can ingest the full narrative later.

Invocation
----------

From the post-commit hook (the typical case)::

    python -m ibn.pipeline.hld_commit --commit HEAD

Manual / test mode (compare current working tree against the previous commit)::

    python -m ibn.pipeline.hld_commit --commit HEAD~1..HEAD

Specify a non-default HLD path::

    python -m ibn.pipeline.hld_commit --hld "Enterprise_Campus_Network_HLD (1).md"

CI / non-interactive mode (auto-answer the dialogue with template (a))::

    IBN_DIALOGUE_DEFAULT=a python -m ibn.pipeline.hld_commit --commit HEAD
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ibn.parser.hld_parser import (
    parse_hld,
    parse_hld_file,
    diff_snapshots,
    HldSnapshot,
    ChangeSet,
)


DEFAULT_HLD_PATH = "Enterprise_Campus_Network_HLD (1).md"
OUTER_LOOP_SPACE = "ibn-loop-outer"
CANDIDATE_SPACE  = "ibn-candidate-001"

# Slice 4 — pending plan markdown directory inside .git/
PENDING_PLAN_DIR = ".git/ibn-pending-approval"


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    name:    str
    status:  str          # "ok" | "skipped" | "error"
    summary: str
    payload: dict

    def __str__(self) -> str:
        marker = {"ok": "✓", "skipped": "·", "error": "✗"}[self.status]
        return f"  {marker} {self.name:<22} {self.summary}"


# ---------------------------------------------------------------------------
# Git diff helpers
# ---------------------------------------------------------------------------

def _git_show_at(commit: str, path: str) -> Optional[str]:
    """Return the contents of *path* at the given commit, or None if absent."""
    try:
        out = subprocess.check_output(
            ["git", "show", f"{commit}:{path}"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return None


def _hld_changed_in_commit(commit: str, hld_path: str) -> bool:
    """Return True if *hld_path* appears in the commit's name-only file list."""
    try:
        out = subprocess.check_output(
            ["git", "show", "--name-only", "--pretty=format:", commit],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False
    files = [line.strip() for line in out.decode("utf-8").splitlines() if line.strip()]
    return hld_path in files


def load_snapshots(commit: str, hld_path: str) -> tuple[HldSnapshot, HldSnapshot]:
    """Return (old_snapshot, new_snapshot) for the given commit and path.

    *commit* is the commit at which the change landed. The "new" snapshot
    is the file at that commit; the "old" snapshot is the file at its
    parent. If the file did not exist at the parent, an empty snapshot is
    returned (so every population is treated as added).
    """
    new_text = _git_show_at(commit, hld_path)
    if new_text is None:
        # File doesn't exist at this commit — read from disk as fallback
        # (useful in tests where the working tree is the source)
        new_text = Path(hld_path).read_text(encoding="utf-8")

    old_text = _git_show_at(f"{commit}^", hld_path)
    if old_text is None:
        old_text = ""

    return (
        parse_hld(old_text, source_path=hld_path),
        parse_hld(new_text, source_path=hld_path),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

class HldCommitPipeline:
    """Drive the closed loop end-to-end for a single HLD commit."""

    def __init__(
        self,
        neo4j_client=None,
        live_memory_client=None,
    ):
        # Lazy-init so the module can be imported without infra connections
        # (the post-commit hook benefits from fast startup).
        self._neo4j = neo4j_client
        self._lm    = live_memory_client
        self._log   = logging.getLogger("ibn.pipeline.hld_commit")

    def _ensure_clients(self):
        if self._neo4j is None:
            from ibn.core.neo4j_client import Neo4jClient
            self._neo4j = Neo4jClient(
                uri      = os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                user     = os.environ.get("NEO4J_USER", "neo4j"),
                password = os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
            )
        if self._lm is None:
            from ibn.core.live_memory_client import LiveMemoryClient
            self._lm = LiveMemoryClient(
                base_url = os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
                token    = os.environ.get("LIVE_MEMORY_TOKEN", ""),
            )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        commit: str = "HEAD",
        hld_path: str = DEFAULT_HLD_PATH,
        dialogue_fn=None,
    ) -> dict:
        """Drive the full pipeline for one commit.

        Returns a dict with per-stage results plus a final ``cycle_complete``
        flag. Even when stages are skipped (no diff, no rules), the dict is
        always returned — only fatal errors raise.
        """
        self._ensure_clients()
        self._ensure_outer_space()

        stages: list[StageResult] = []

        # Stage 0 — diff
        old_snap, new_snap = load_snapshots(commit, hld_path)
        changeset = diff_snapshots(old_snap, new_snap)
        stages.append(StageResult(
            name="diff",
            status="skipped" if changeset.is_empty else "ok",
            summary=changeset.summary(),
            payload={"populations_added": [p.vlan for p in changeset.populations_added]},
        ))

        if changeset.is_empty:
            self._note(
                f"HLD commit {commit}: no changes in {hld_path} — pipeline no-op"
            )
            return self._final_result(stages, cycle_complete=True)

        # Stage 1 — A1 ingest + dialogue (population path)
        from ibn.agents.agent1_ingestion import Agent1Ingestion
        a1 = Agent1Ingestion(self._neo4j, self._lm)
        a1_result = a1.ingest_hld_changeset(
            changeset       = changeset,
            source_path     = hld_path,
            candidate_space = CANDIDATE_SPACE,
            dialogue_fn     = dialogue_fn,
        )
        stages.append(StageResult(
            name="A1 ingestion",
            status="ok",
            summary=(
                f"created={len(a1_result['intents_created'])} "
                f"reused={len(a1_result['intents_existing'])}"
            ),
            payload=a1_result,
        ))

        # Stage 1b — A1 device ingest (Slice 3)
        # Reconciles the HLD Device Inventory Table → Neo4j Device nodes.
        # Runs unconditionally so devices_modified rows are picked up too.
        a1_device_result = a1.ingest_hld_devices(
            changeset       = changeset,
            source_path     = hld_path,
            candidate_space = CANDIDATE_SPACE,
        )
        stages.append(StageResult(
            name="A1 device ingest",
            status="ok",
            summary=(
                f"created={len(a1_device_result['devices_created'])} "
                f"updated={len(a1_device_result['devices_updated'])} "
                f"to_retire={len(a1_device_result['devices_to_retire'])}"
            ),
            payload=a1_device_result,
        ))

        # Stage 1c — Provisioning (Slice 3)
        # Spin up containers for new devices, tear down retired ones.
        provisioning_result = self._run_provisioning_stage(
            new_device_entries  = changeset.devices_added,
            retired_device_ids  = a1_device_result["devices_to_retire"],
        )
        prov_failed = any(not r.success for r in provisioning_result["provisioned"])
        stages.append(StageResult(
            name="Provisioning",
            status="error" if prov_failed else "ok",
            summary=(
                f"provisioned={len([r for r in provisioning_result['provisioned'] if r.success])} "
                f"retired={len([r for r in provisioning_result['retired'] if r.success])}"
                + (" (errors above)" if prov_failed else "")
            ),
            payload=provisioning_result,
        ))
        if prov_failed:
            self._note(
                f"HLD commit {commit}: provisioning had failures — pipeline aborted"
            )
            return self._final_result(stages, cycle_complete=False)

        # Split "real intents" (from A1 ingestion — A2 needs to run against
        # these) from "render-only intents" (device-only commits — A3/A5/A7
        # still need to render against existing Neo4j state but A2 has
        # nothing to decompose).
        real_intent_ids = a1_result["intents_created"]
        render_intent_ids = list(real_intent_ids)
        if not real_intent_ids and changeset.devices_added:
            render_intent_ids = [f"INT-DEVICE-PROVISION-{commit[:8]}"]

        if not render_intent_ids:
            self._note(
                f"HLD commit {commit}: nothing for downstream agents to do "
                f"(no new intents, no new devices)"
            )
            return self._final_result(stages, cycle_complete=True)

        # Stage 2 — A2 translate (only for real Intent nodes)
        if real_intent_ids:
            from ibn.agents.agent2_intent_policy import Agent2IntentPolicy
            a2 = Agent2IntentPolicy(self._neo4j, self._lm)
            a2_results = []
            for iid in real_intent_ids:
                r = a2.run(intent_id=iid)
                a2_results.append(r)
            stages.append(StageResult(
                name="A2 translation",
                status="ok",
                summary=(
                    f"{len(a2_results)} policies, "
                    f"{sum(r['ruleCount'] for r in a2_results)} firewall rules"
                ),
                payload={"policies": a2_results},
            ))
        else:
            stages.append(StageResult(
                name="A2 translation",
                status="skipped",
                summary="device-only commit — no intents to decompose",
                payload={},
            ))

        # Keep ``intent_ids`` for downstream stages (A4, A3, A5, A7).
        intent_ids = render_intent_ids

        # Stage 3 — A4 planning (Slice 4 real implementation)
        from ibn.agents.agent4_planning import Agent4Planning
        a4 = Agent4Planning(self._neo4j, self._lm)
        device_ids_for_plan = (
            a1_device_result.get("devices_created", [])
            + a1_device_result.get("devices_updated", [])
            + a1_device_result.get("devices_to_retire", [])
        )
        a4_result = a4.run(
            changeset    = changeset,
            commit_sha   = commit,
            intent_ids   = intent_ids,
            device_ids   = device_ids_for_plan,
            outer_space  = OUTER_LOOP_SPACE,
        )
        stages.append(StageResult(
            name="A4 planning",
            status="ok",
            summary=(
                f"plan={a4_result['planId']} severity={a4_result['severity']} "
                f"blast={a4_result['blastRadius']} devices"
            ),
            payload=a4_result,
        ))

        # Stage 3.5 — Approval gate (Slice 4)
        # If IBN_AUTO_APPROVE is set, bypass entirely (Slice 1-3 behavior).
        # Otherwise write a pending-plan markdown and exit.
        auto_approve = os.environ.get("IBN_AUTO_APPROVE", "").strip() in ("1", "true", "yes")
        if not auto_approve:
            md_path = self._write_pending_plan_md(a4_result, commit, changeset)
            stages.append(StageResult(
                name="Approval gate",
                status="ok",
                summary=f"PENDING — {md_path}",
                payload={"plan_path": md_path, "plan_id": a4_result["planId"]},
            ))
            self._note(
                f"PENDING APPROVAL: plan {a4_result['planId']} for commit {commit}. "
                f"Run `python -m ibn.tools.approve {commit}` to apply, "
                f"`python -m ibn.tools.approve reject {commit} --reason '...'` to reject."
            )
            return self._final_result(
                stages,
                cycle_complete=False,
                awaiting_approval=True,
                pending_plan_path=md_path,
            )

        # Auto-approve path: mark the plan APPLIED before running A3-A5-A7
        # so the audit trail still shows the plan even though no human
        # touched it.
        try:
            self._neo4j.update_migration_plan_status(
                a4_result["planId"], "APPROVED", operator="auto-approve"
            )
            self._neo4j.transition_artifacts_to_por(
                intent_ids = intent_ids,
                policy_ids = a4_result.get("policyIds", []),
                config_ids = a4_result.get("configIds", []),
            )
        except Exception as exc:
            self._log.warning("auto-approve transition failed: %s", exc)

        # Stages 4-6 (A3 render → A5 deploy → A7 assess) run via the
        # shared helper that the resume_from_approval path also uses.
        self._run_render_deploy_assess(
            stages       = stages,
            intent_ids   = intent_ids,
            commit       = commit,
        )
        # Mark the plan APPLIED after the rest of the loop runs
        try:
            self._neo4j.update_migration_plan_status(a4_result["planId"], "APPLIED")
        except Exception as exc:
            self._log.warning("mark APPLIED failed: %s", exc)

        self._note(
            f"HLD commit {commit}: pipeline complete (auto-approved) — "
            f"{len(intent_ids)} new intents flowed end-to-end"
        )
        return self._final_result(stages, cycle_complete=True)

    # ------------------------------------------------------------------
    # Render → deploy → assess helper (shared by run() and resume_from_approval())
    # ------------------------------------------------------------------

    def _run_render_deploy_assess(
        self,
        stages: list,
        intent_ids: list[str],
        commit: str,
    ) -> None:
        """Stages 4-6: A3 render, A5 deploy, A7 assessment.

        Mutates ``stages`` by appending one StageResult per agent. Used
        by both the auto-approve path in run() and the post-approval
        resume path.
        """
        # Stage 4 — A3 render configs
        from ibn.agents.agent3_policy_config import Agent3PolicyConfig
        a3 = Agent3PolicyConfig(self._neo4j, self._lm)
        a3_results = []
        for iid in intent_ids:
            r = a3.run(intent_id=iid, candidate_space=CANDIDATE_SPACE)
            a3_results.append(r)
        rendered_count = sum(
            len([d for d in r.get("devices", []) if "configId" in d])
            for r in a3_results
        )
        stages.append(StageResult(
            name="A3 render",
            status="ok",
            summary=f"{rendered_count} configs rendered",
            payload={"renders": a3_results},
        ))

        # Stage 5 — A5 deploy
        from ibn.agents.agent5_orchestration import Agent5Orchestration
        a5 = Agent5Orchestration(self._neo4j, self._lm)
        a5_results = []
        for r in a3_results:
            iid = r.get("intent_id", "unknown")
            plan = [
                {
                    "deviceId": d["deviceId"],
                    "configId": d["configId"],
                    "content":  d["content"],
                    # Slice 2: pass platform through so A5 can dispatch
                    # to the right vendor executor (vyos / srlinux / …).
                    "platform": d.get("platform"),
                    # Slice 3: pass clabContainer so A5 can use it as the
                    # docker exec target instead of deriving from deviceId.
                    "clabContainer": d.get("clabContainer"),
                }
                for d in r.get("devices", [])
                if "configId" in d
            ]
            if not plan:
                continue
            try:
                a5_results.append(a5.run(intent_id=iid, plan=plan))
            except Exception as exc:
                self._log.error("A5 push failed for intent %s: %s", iid, exc)
                stages.append(StageResult(
                    name="A5 deploy",
                    status="error",
                    summary=f"intent {iid}: {exc}",
                    payload={},
                ))
                self._note(
                    f"HLD pipeline FAILED at A5 for intent {iid}: {exc}"
                )
                return  # helper exits early; caller checks the stages list

        # Slice 2: surface A5's internal status. A5 returns FAILED on
        # rollback without raising, so the previous "always ok" was masking
        # real push failures.
        any_failed = any(r.get("status") == "FAILED" for r in a5_results)
        deployed_count = sum(len(r.get("devices", [])) for r in a5_results if r.get("status") == "ORCHESTRATED")
        skipped_count = sum(len(r.get("skipped", [])) for r in a5_results)
        stages.append(StageResult(
            name="A5 deploy",
            status="error" if any_failed else "ok",
            summary=(
                f"{deployed_count} devices pushed, "
                f"{skipped_count} skipped (empty render)"
                + (f", FAILED on intent(s)" if any_failed else "")
            ),
            payload={"deploys": a5_results},
        ))

        # Stage 6 — A7 assessment
        from ibn.agents.agent7_assessment import Agent7Assessment
        a7 = Agent7Assessment(self._neo4j, self._lm)
        a7_results = []
        for iid in intent_ids:
            try:
                a7_results.append(a7.run(intent_id=iid, assess_space=OUTER_LOOP_SPACE))
            except Exception as exc:
                self._log.warning("A7 assessment soft-failed for %s: %s", iid, exc)
        stages.append(StageResult(
            name="A7 assessment",
            status="ok",
            summary=f"{len(a7_results)} assessments",
            payload={"assessments": a7_results},
        ))

    # ------------------------------------------------------------------
    # Stage helpers
    # ------------------------------------------------------------------

    def _run_provisioning_stage(
        self,
        new_device_entries: list,
        retired_device_ids: list[str],
    ) -> dict:
        """Slice 3 provisioning stage.

        For each newly-added DeviceEntry, spin up the container.
        For each retired device id, tear down the container.
        Returns lists of ProvisionResult / RetireResult objects.
        """
        results = {"provisioned": [], "retired": []}
        if not new_device_entries and not retired_device_ids:
            return results

        from ibn.agents.provisioner import Provisioner
        prov = Provisioner(self._neo4j, self._lm)

        for entry in new_device_entries:
            self._note(
                f"Provisioning new device {entry.device_id} "
                f"({entry.vendor}/{entry.platform}) → {entry.clab_container}"
            )
            r = prov.provision(entry)
            results["provisioned"].append(r)
            if not r.success:
                self._note(
                    f"PROVISION FAILED for {entry.device_id}: {r.error}"
                )

        for did in retired_device_ids:
            self._note(f"Retiring device {did}")
            r = prov.retire(did)
            results["retired"].append(r)
            if not r.success:
                self._note(f"RETIRE FAILED for {did}: {r.error}")

        return results

    # ------------------------------------------------------------------
    # Pending-plan markdown writer (Slice 4)
    # ------------------------------------------------------------------

    def _write_pending_plan_md(self, plan_result: dict, commit: str, changeset) -> str:
        """Write a human-readable pending-plan markdown to .git/ibn-pending-approval/.

        Returns the absolute path to the file. The post-commit hook
        prints this path on stdout so the operator sees it immediately.
        """
        from pathlib import Path

        Path(PENDING_PLAN_DIR).mkdir(parents=True, exist_ok=True)
        sha_short = (commit or "unknown")[:8]
        path = Path(PENDING_PLAN_DIR) / f"{sha_short}.md"

        device_list = "\n".join(f"  - `{d}`" for d in plan_result.get("deviceIds", [])) or "  - (none)"
        intent_list = "\n".join(f"  - `{i}`" for i in plan_result.get("intentIds", [])) or "  - (none)"

        body = f"""# Pending Plan {plan_result['planId']}

**Commit:** `{commit}`
**Severity:** **{plan_result['severity']}**
**Blast radius:** {plan_result['blastRadius']} devices

## Summary
{plan_result['summary']}

## Inverse plan (rollback summary)
{plan_result.get('inverseSummary', '(not generated)')}

## Affected devices
{device_list}

## New intents
{intent_list}

## Changeset detail
- populations added: {len(changeset.populations_added)}
- populations modified: {len(changeset.populations_modified)}
- populations removed: {len(changeset.populations_removed)}
- devices added: {len(changeset.devices_added)}
- devices modified: {len(changeset.devices_modified)}
- devices removed: {len(changeset.devices_removed)}

## To approve
```
python -m ibn.tools.approve {commit}
```

## To reject
```
python -m ibn.tools.approve reject {commit} --reason "describe why"
```
"""
        path.write_text(body, encoding="utf-8")
        return str(path.resolve())

    # ------------------------------------------------------------------
    # Resume from approval (Slice 4)
    # ------------------------------------------------------------------

    def resume_from_approval(self, plan_id: str) -> dict:
        """Run A3 → A5 → A7 against an APPROVED plan's artifacts.

        Used by the approval CLI after the operator runs `ibn approve`.
        Re-derives all state from Neo4j (the CANDIDATE artifacts are
        already there) and runs the back half of the pipeline.

        Side effects:
          - Marks the plan APPLIED on success
          - Returns the same shape as ``run()`` so the CLI can print
            stage results uniformly
        """
        self._ensure_clients()
        self._ensure_outer_space()

        plan = self._neo4j.get_migration_plan(plan_id)
        if not plan:
            raise ValueError(f"MigrationPlan {plan_id} not found")
        if plan.get("status") not in ("APPROVED", "PENDING"):
            # PENDING is allowed because the CLI calls update_status
            # immediately before this. We tolerate either.
            raise ValueError(
                f"Plan {plan_id} status is {plan.get('status')}; "
                f"expected APPROVED or PENDING"
            )

        intent_ids = plan.get("intentIds") or []
        commit = plan.get("commitSha", "unknown")

        stages: list[StageResult] = []
        stages.append(StageResult(
            name="resume",
            status="ok",
            summary=f"plan={plan_id} commit={commit[:8]} intents={len(intent_ids)}",
            payload={"plan": plan},
        ))

        if not intent_ids:
            self._note(
                f"resume_from_approval: plan {plan_id} has no intents — nothing to deploy"
            )
            return self._final_result(stages, cycle_complete=True)

        self._run_render_deploy_assess(
            stages     = stages,
            intent_ids = intent_ids,
            commit     = commit,
        )

        # Mark the plan APPLIED if the back-half succeeded
        any_failed = any(s.status == "error" for s in stages)
        if not any_failed:
            try:
                self._neo4j.update_migration_plan_status(plan_id, "APPLIED")
            except Exception as exc:
                self._log.warning("mark APPLIED failed: %s", exc)

        return self._final_result(stages, cycle_complete=not any_failed)

    # ------------------------------------------------------------------
    # Live-Memory wiring
    # ------------------------------------------------------------------

    def _ensure_outer_space(self):
        try:
            self._lm.space_create(
                space_id    = OUTER_LOOP_SPACE,
                description = "Outer-loop narrative for HLD-driven changes",
                owner       = "ibn-pipeline",
                rules       = "# outer loop\n",
            )
        except Exception:
            pass  # already exists

    def _note(self, content: str) -> None:
        try:
            self._lm.live_note(
                space=OUTER_LOOP_SPACE,
                content=content,
                category="hld-pipeline",
            )
        except Exception as exc:
            self._log.warning("live_note failed: %s", exc)

    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------

    def _final_result(
        self,
        stages: list[StageResult],
        cycle_complete: bool,
        awaiting_approval: bool = False,
        pending_plan_path: Optional[str] = None,
    ) -> dict:
        return {
            "cycle_complete": cycle_complete,
            "awaiting_approval": awaiting_approval,
            "pending_plan_path": pending_plan_path,
            "stages": [
                {
                    "name":    s.name,
                    "status":  s.status,
                    "summary": s.summary,
                }
                for s in stages
            ],
            "stage_objects": stages,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ibn.pipeline.hld_commit",
        description="Drive the IBN closed loop from an HLD git commit.",
    )
    parser.add_argument(
        "--commit", default="HEAD",
        help="Commit SHA whose HLD diff to process (default: HEAD)",
    )
    parser.add_argument(
        "--hld", default=DEFAULT_HLD_PATH,
        help=f"Path to the HLD file (default: {DEFAULT_HLD_PATH!r})",
    )
    parser.add_argument(
        "--require-hld-changed", action="store_true",
        help="Exit cleanly with no work if the HLD wasn't in this commit. "
             "Used by the post-commit hook to filter unrelated commits.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
    )

    if args.require_hld_changed and not _hld_changed_in_commit(args.commit, args.hld):
        print(f"[hld_commit] {args.hld} not changed in {args.commit} — skipping pipeline.")
        return 0

    pipeline = HldCommitPipeline()
    try:
        result = pipeline.run(commit=args.commit, hld_path=args.hld)
    except Exception as exc:
        logging.exception("Pipeline crashed: %s", exc)
        print(f"\n[hld_commit] FATAL: {exc}", file=sys.stderr)
        return 2

    print(f"\nHLD commit {args.commit} pipeline summary:")
    for stage in result["stage_objects"]:
        print(stage)

    return 0 if result["cycle_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
