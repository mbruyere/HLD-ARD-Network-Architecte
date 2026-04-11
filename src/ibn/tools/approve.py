"""
Slice 4 — Approval CLI for the IBN closed loop.

When the post-commit hook fires the pipeline and lands on the
approval gate, it writes a pending-plan markdown file in
``.git/ibn-pending-approval/<sha>.md`` and exits without pushing
anything to the lab. The operator reviews the markdown and runs
this CLI to either resume the pipeline (apply the plan) or archive
the changes (reject).

Usage::

    python -m ibn.tools.approve <commit-sha>
    python -m ibn.tools.approve approve <commit-sha>
    python -m ibn.tools.approve reject <commit-sha> --reason "needs security review"
    python -m ibn.tools.approve list

The default subcommand is ``approve`` (one-shot ergonomics for the
common case).

What approve does
-----------------
1. Looks up the MigrationPlan by commit SHA in Neo4j
2. Marks it APPROVED with the operator's username
3. Bulk-transitions the referenced CANDIDATE Intent / Policy /
   FirewallRule / Configuration nodes to POR
4. Calls ``HldCommitPipeline.resume_from_approval(plan_id)`` which
   runs A3 → A5 → A7 against the now-POR artifacts
5. Marks the plan APPLIED on success
6. Removes the pending-plan markdown file from .git/

What reject does
----------------
1. Marks the MigrationPlan REJECTED with the operator's reason
2. Marks the referenced Intent nodes as ``status='REJECTED'`` and
   the Policy nodes as ``modelState='REJECTED'`` (kept in Neo4j for
   audit, but excluded from A3's queries)
3. Removes the pending-plan markdown file from .git/
4. Does NOT touch any device

Both subcommands are idempotent — re-running on an already-APPROVED
or already-REJECTED plan exits cleanly with a status message.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Optional


PENDING_PLAN_DIR = ".git/ibn-pending-approval"


def _connect():
    """Construct the Neo4j + Live-Memory clients from env."""
    from ibn.core.neo4j_client import Neo4jClient
    from ibn.core.live_memory_client import LiveMemoryClient
    neo = Neo4jClient(
        uri      = os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user     = os.environ.get("NEO4J_USER", "neo4j"),
        password = os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    lm = LiveMemoryClient(
        base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
        token=os.environ.get("LIVE_MEMORY_TOKEN", ""),
    )
    return neo, lm


def _resolve_plan(neo, commit_or_plan: str) -> Optional[dict]:
    """Look up a plan by either its commit SHA or its planId.

    The CLI accepts both for ergonomics: the operator can paste the
    commit SHA from `git log` or the planId from the markdown.
    """
    plan = neo.get_migration_plan_by_commit(commit_or_plan)
    if plan:
        return plan
    if commit_or_plan.startswith("PLAN-"):
        return neo.get_migration_plan(commit_or_plan)
    # Maybe the operator passed a short SHA — try a substring match
    pending = neo.list_pending_migration_plans()
    matches = [p for p in pending if commit_or_plan in (p.get("commitSha") or "")]
    if len(matches) == 1:
        return matches[0]
    return None


def _remove_pending_md(commit_sha: str) -> None:
    """Best-effort cleanup of the pending-plan markdown."""
    if not commit_sha:
        return
    p = Path(PENDING_PLAN_DIR) / f"{commit_sha[:8]}.md"
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_approve(args) -> int:
    neo, lm = _connect()
    try:
        plan = _resolve_plan(neo, args.commit)
        if not plan:
            print(f"[approve] no plan found for '{args.commit}'", file=sys.stderr)
            return 2

        plan_id = plan["planId"]
        status = plan.get("status")
        if status == "APPLIED":
            print(f"[approve] plan {plan_id} already APPLIED — nothing to do")
            return 0
        if status == "REJECTED":
            print(
                f"[approve] plan {plan_id} was REJECTED "
                f"({plan.get('rejectedReason', 'no reason recorded')}) — refusing to override",
                file=sys.stderr,
            )
            return 1

        operator = getpass.getuser()
        print(f"[approve] {plan_id} commit={plan.get('commitSha', '?')[:8]} "
              f"severity={plan.get('severity')} blast={plan.get('blastRadius')} → APPROVING as {operator}")

        # 1. Mark APPROVED
        neo.update_migration_plan_status(plan_id, "APPROVED", operator=operator)

        # 2. Transition CANDIDATE → POR
        neo.transition_artifacts_to_por(
            intent_ids = plan.get("intentIds") or [],
            policy_ids = plan.get("policyIds") or [],
            config_ids = plan.get("configIds") or [],
        )

        # 3. Resume A3 → A5 → A7
        from ibn.pipeline.hld_commit import HldCommitPipeline
        pipeline = HldCommitPipeline(neo4j_client=neo, live_memory_client=lm)
        result = pipeline.resume_from_approval(plan_id)

        print()
        print(f"Resume summary for {plan_id}:")
        for stage in result["stage_objects"]:
            print(stage)
        print(f"cycle_complete: {result['cycle_complete']}")

        # 4. Cleanup the pending-plan markdown on success
        if result["cycle_complete"]:
            _remove_pending_md(plan.get("commitSha", ""))

        return 0 if result["cycle_complete"] else 1
    finally:
        neo.close()


def cmd_reject(args) -> int:
    neo, _lm = _connect()
    try:
        plan = _resolve_plan(neo, args.commit)
        if not plan:
            print(f"[reject] no plan found for '{args.commit}'", file=sys.stderr)
            return 2

        plan_id = plan["planId"]
        status = plan.get("status")
        if status == "APPLIED":
            print(
                f"[reject] plan {plan_id} is already APPLIED — refusing to reject "
                f"(use a new HLD edit to undo the change)",
                file=sys.stderr,
            )
            return 1
        if status == "REJECTED":
            print(f"[reject] plan {plan_id} already REJECTED")
            return 0

        operator = getpass.getuser()
        print(f"[reject] {plan_id} → REJECTED by {operator}: {args.reason}")

        neo.update_migration_plan_status(
            plan_id, "REJECTED",
            operator=operator,
            reason=args.reason,
        )
        neo.reject_artifacts(
            intent_ids = plan.get("intentIds") or [],
            policy_ids = plan.get("policyIds") or [],
        )
        _remove_pending_md(plan.get("commitSha", ""))
        return 0
    finally:
        neo.close()


def cmd_list(args) -> int:
    neo, _lm = _connect()
    try:
        plans = neo.list_pending_migration_plans()
        if not plans:
            print("[list] no pending plans")
            return 0
        print(f"[list] {len(plans)} pending plan(s):")
        for p in plans:
            print(
                f"  {p.get('planId'):24} commit={(p.get('commitSha') or '?')[:8]:8} "
                f"severity={p.get('severity'):8} blast={p.get('blastRadius', 0):3}  "
                f"{p.get('summary', '')}"
            )
        return 0
    finally:
        neo.close()


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ibn.tools.approve",
        description="Approve, reject, or list pending IBN migration plans.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    p_approve = sub.add_parser("approve", help="Approve a pending plan and resume the pipeline")
    p_approve.add_argument("commit", help="Commit SHA or plan ID")

    p_reject = sub.add_parser("reject", help="Reject a pending plan")
    p_reject.add_argument("commit", help="Commit SHA or plan ID")
    p_reject.add_argument("--reason", required=True, help="Why this plan is rejected")

    sub.add_parser("list", help="List pending migration plans")

    # Convenience: if the first positional arg looks like a SHA/plan id and
    # there's no subcommand, default to approve.
    args_list = list(argv if argv is not None else sys.argv[1:])
    if args_list and args_list[0] not in ("approve", "reject", "list", "-h", "--help", "-v", "--verbose"):
        args_list = ["approve"] + args_list

    args = parser.parse_args(args_list)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-25s %(levelname)-7s %(message)s",
    )

    if args.cmd == "approve":
        return cmd_approve(args)
    if args.cmd == "reject":
        return cmd_reject(args)
    if args.cmd == "list":
        return cmd_list(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
