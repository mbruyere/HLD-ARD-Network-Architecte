"""
Agent 4 — Planning  (RFC 9315 §5.1.2 / §6 outer-loop boundary)

Slice 4 scope: read the CANDIDATE artifacts produced by A1+A2+
Provisioning for one HLD commit, classify the change severity, write
a MigrationPlan (L7) node summarizing the blast radius and inverse
plan. The orchestrator's approval gate then reads this plan and
either bypasses (auto-approve) or pauses the pipeline waiting for
operator signoff.

This agent does NOT reach into the lab. It's a pure SSoT-driven
analyzer: input is the changeset + Neo4j, output is one MigrationPlan
node.

Severity classifier
-------------------
Slice 4 ships a deliberately simple heuristic:

  - HIGH:    devices_added > 0 OR devices_removed > 0
  - MEDIUM:  populations_removed > 0
  - LOW:     populations_added > 0 OR populations_modified > 0
  - INFO:    no changes

Slice 6 will replace this with a real graph-traversal blast radius
that walks the SSoT relationships and computes endpoint counts,
DMZ-service dependencies, and rollback time estimates.

Inverse plan
------------
Slice 4 generates a one-line human description of what the rollback
would do. It does NOT generate executable inverse Cypher — that's a
Slice 6 enhancement that depends on the real graph-traversal
analyzer.
"""
from __future__ import annotations

import uuid
from typing import Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import (
    MigrationPlan, MigrationPlanStatus, PlanSeverity,
)


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------

def classify_severity(changeset) -> PlanSeverity:
    """Slice 4 heuristic: see module docstring for the rules."""
    if changeset.devices_added or changeset.devices_removed:
        return PlanSeverity.HIGH
    if changeset.populations_removed or changeset.dmz_removed:
        return PlanSeverity.MEDIUM
    if (
        changeset.populations_added
        or changeset.populations_modified
        or changeset.dmz_added
        or changeset.dmz_modified
        or changeset.devices_modified
    ):
        return PlanSeverity.LOW
    return PlanSeverity.INFO


# ---------------------------------------------------------------------------
# Plan summary helpers
# ---------------------------------------------------------------------------

def build_summary(changeset) -> str:
    """One-line operator-facing description of the change."""
    parts = []
    if changeset.populations_added:
        parts.append(f"+{len(changeset.populations_added)} populations")
    if changeset.populations_modified:
        parts.append(f"~{len(changeset.populations_modified)} populations")
    if changeset.populations_removed:
        parts.append(f"-{len(changeset.populations_removed)} populations")
    if changeset.dmz_added:
        parts.append(f"+{len(changeset.dmz_added)} dmz")
    if changeset.devices_added:
        parts.append(f"+{len(changeset.devices_added)} devices")
    if changeset.devices_modified:
        parts.append(f"~{len(changeset.devices_modified)} devices")
    if changeset.devices_removed:
        parts.append(f"-{len(changeset.devices_removed)} devices")
    return ", ".join(parts) if parts else "no changes"


def build_inverse_summary(changeset) -> str:
    """One-line description of the rollback operation.

    This is human-readable text, not executable Cypher. The operator
    reads it as part of the approval review to understand what
    "reject + revert HLD" would do.
    """
    parts = []
    if changeset.populations_added:
        vlans = [str(p.vlan) for p in changeset.populations_added]
        parts.append(f"delete VLAN {', '.join(vlans)}")
    if changeset.populations_removed:
        vlans = [str(p.vlan) for p in changeset.populations_removed]
        parts.append(f"restore VLAN {', '.join(vlans)}")
    if changeset.devices_added:
        ids = [d.device_id for d in changeset.devices_added]
        parts.append(f"retire device {', '.join(ids)}")
    if changeset.devices_removed:
        ids = [d.device_id for d in changeset.devices_removed]
        parts.append(f"re-provision device {', '.join(ids)}")
    if changeset.populations_modified or changeset.devices_modified:
        parts.append("revert property changes")
    if not parts:
        return "no rollback needed (no-op change)"
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Agent 4
# ---------------------------------------------------------------------------

class Agent4Planning(BaseAgent):
    """Generate a MigrationPlan summarizing what's about to change."""

    AGENT_ID   = "A4"
    AGENT_NAME = "Planning"

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        changeset    = kwargs["changeset"]
        commit_sha   = kwargs["commit_sha"]
        intent_ids:  list[str] = kwargs.get("intent_ids", []) or []
        device_ids:  list[str] = kwargs.get("device_ids", []) or []
        outer_space: str       = kwargs.get("outer_space", "ibn-loop-outer")

        # Compute the plan
        severity = classify_severity(changeset)
        summary = build_summary(changeset)
        inverse = build_inverse_summary(changeset)

        # Look up the policies + configs the orchestrator just produced
        # so the resume path knows what to transition. We query Neo4j
        # rather than asking the caller because the orchestrator hasn't
        # always tracked these IDs explicitly.
        policy_ids: list[str] = []
        config_ids: list[str] = []
        if intent_ids:
            rows = self._neo4j.run_query(
                """
                MATCH (i:Intent) WHERE i.intentId IN $ids
                OPTIONAL MATCH (i)-[:DECOMPOSED_INTO]->(p:Policy)
                OPTIONAL MATCH (c:Configuration {intentId: i.intentId})
                RETURN collect(DISTINCT p.policyId) AS pids,
                       collect(DISTINCT c.configId) AS cids
                """,
                ids=intent_ids,
            )
            if rows:
                row = rows[0]
                policy_ids = [p for p in (row.get("pids") or []) if p]
                config_ids = [c for c in (row.get("cids") or []) if c]

        # Blast radius: distinct devices touched by either the
        # configurations or the device-add/remove set
        device_set = set(device_ids)
        if config_ids:
            rows = self._neo4j.run_query(
                """
                MATCH (c:Configuration)-[:APPLIES_TO]->(d:Device)
                WHERE c.configId IN $ids
                RETURN collect(DISTINCT d.deviceId) AS dids
                """,
                ids=config_ids,
            )
            if rows:
                device_set.update(d for d in (rows[0].get("dids") or []) if d)
        # Also include devices coming from the changeset directly
        for entry in (changeset.devices_added or []) + (changeset.devices_removed or []):
            device_set.add(entry.device_id)

        plan = MigrationPlan(
            planId         = f"PLAN-{commit_sha[:8] if commit_sha else uuid.uuid4().hex[:8]}",
            commitSha      = commit_sha,
            intentIds      = list(intent_ids),
            policyIds      = list(policy_ids),
            configIds      = list(config_ids),
            deviceIds      = sorted(device_set),
            blastRadius    = len(device_set),
            severity       = severity,
            summary        = summary,
            inverseSummary = inverse,
            status         = MigrationPlanStatus.PENDING,
        )

        # Mark any older PENDING plan for the same commit as SUPERSEDED
        existing = self._neo4j.get_migration_plan_by_commit(commit_sha)
        if existing and existing.get("planId") != plan.planId and existing.get("status") == "PENDING":
            try:
                self._neo4j.update_migration_plan_status(
                    existing["planId"], "SUPERSEDED",
                )
                self._note(
                    outer_space,
                    f"A4: superseded prior plan {existing['planId']} for commit {commit_sha}",
                    "plan-superseded",
                )
            except Exception as exc:
                self._log.warning("supersede prior plan failed: %s", exc)

        self._neo4j.create_migration_plan(plan)

        self._note(
            outer_space,
            (
                f"A4: plan {plan.planId} (severity={severity.value}, "
                f"blast={plan.blastRadius} devices) — {summary}"
            ),
            "plan-created",
        )

        self._publish("plan.created", {
            "planId":   plan.planId,
            "commitSha": commit_sha,
            "severity": severity.value,
            "blastRadius": plan.blastRadius,
            "summary":  summary,
        })

        return {
            "id":         plan.planId,
            "planId":     plan.planId,
            "severity":   severity.value,
            "blastRadius": plan.blastRadius,
            "summary":    summary,
            "inverseSummary": inverse,
            "intentIds":  list(intent_ids),
            "policyIds":  list(policy_ids),
            "configIds":  list(config_ids),
            "deviceIds":  sorted(device_set),
        }
