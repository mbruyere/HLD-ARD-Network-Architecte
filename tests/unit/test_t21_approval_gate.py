"""
T21 — Slice 4 approval gate unit tests.

Pure unit-level coverage of:
  - Agent 4 severity classifier + summary builders
  - MigrationPlan dataclass shape
  - Pipeline orchestrator gate behavior with mocked Neo4j (auto-approve
    bypass + gate fires when flag absent)
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from ibn.agents.agent4_planning import (
    classify_severity, build_summary, build_inverse_summary,
)
from ibn.parser.hld_parser import (
    parse_hld, ChangeSet, PopulationEntry, DeviceEntry,
)
from ibn.core.models import (
    MigrationPlan, MigrationPlanStatus, PlanSeverity,
)


# ===========================================================================
# Severity classifier
# ===========================================================================


class TestSeverityClassifier:

    def test_no_changes_is_info(self):
        cs = ChangeSet()
        assert classify_severity(cs) == PlanSeverity.INFO

    def test_single_population_add_is_low(self):
        cs = ChangeSet()
        cs.populations_added.append(PopulationEntry(
            name="X", vlan=199, large_site="1", small_site="1",
            qos_priority="Standard", dscp="AF21", bandwidth="1 Mbps",
        ))
        assert classify_severity(cs) == PlanSeverity.LOW

    def test_population_remove_is_medium(self):
        cs = ChangeSet()
        cs.populations_removed.append(PopulationEntry(
            name="X", vlan=199, large_site="1", small_site="1",
            qos_priority="Standard", dscp="AF21", bandwidth="1 Mbps",
        ))
        assert classify_severity(cs) == PlanSeverity.MEDIUM

    def test_device_add_is_high(self):
        cs = ChangeSet()
        cs.devices_added.append(DeviceEntry(
            device_id="x", vendor="V", platform="p", role="ACCESS_SWITCH",
            site="HQ", clab_container="x", mgmt_ipv4="1.1.1.1",
        ))
        assert classify_severity(cs) == PlanSeverity.HIGH

    def test_device_remove_is_high(self):
        cs = ChangeSet()
        cs.devices_removed.append(DeviceEntry(
            device_id="x", vendor="V", platform="p", role="ACCESS_SWITCH",
            site="HQ", clab_container="x", mgmt_ipv4="1.1.1.1",
        ))
        assert classify_severity(cs) == PlanSeverity.HIGH


class TestSummaryBuilders:

    def test_summary_handles_empty(self):
        assert build_summary(ChangeSet()) == "no changes"

    def test_summary_lists_changes(self):
        cs = ChangeSet()
        cs.populations_added.append(PopulationEntry(
            name="A", vlan=1, large_site="1", small_site="1",
            qos_priority="x", dscp="x", bandwidth="x",
        ))
        cs.devices_added.append(DeviceEntry(
            device_id="d", vendor="V", platform="p", role="r",
            site="s", clab_container="c", mgmt_ipv4="1.1.1.1",
        ))
        s = build_summary(cs)
        assert "+1 populations" in s
        assert "+1 devices" in s

    def test_inverse_summary_handles_empty(self):
        assert build_inverse_summary(ChangeSet()) == "no rollback needed (no-op change)"

    def test_inverse_summary_describes_population_add(self):
        cs = ChangeSet()
        cs.populations_added.append(PopulationEntry(
            name="A", vlan=199, large_site="1", small_site="1",
            qos_priority="x", dscp="x", bandwidth="x",
        ))
        text = build_inverse_summary(cs)
        assert "delete VLAN 199" in text

    def test_inverse_summary_describes_device_add(self):
        cs = ChangeSet()
        cs.devices_added.append(DeviceEntry(
            device_id="acc-sw-99", vendor="V", platform="p", role="r",
            site="s", clab_container="c", mgmt_ipv4="1.1.1.1",
        ))
        text = build_inverse_summary(cs)
        assert "retire device acc-sw-99" in text


# ===========================================================================
# MigrationPlan dataclass shape
# ===========================================================================


class TestMigrationPlanDataclass:

    def test_default_status_is_pending(self):
        plan = MigrationPlan(
            planId="PLAN-1", commitSha="abc", intentIds=[], policyIds=[],
            configIds=[], deviceIds=[], blastRadius=0,
            severity=PlanSeverity.LOW, summary="x", inverseSummary="y",
        )
        assert plan.status == MigrationPlanStatus.PENDING

    def test_severity_is_typed_enum(self):
        plan = MigrationPlan(
            planId="PLAN-1", commitSha="abc", intentIds=[], policyIds=[],
            configIds=[], deviceIds=[], blastRadius=0,
            severity=PlanSeverity.HIGH, summary="x", inverseSummary="y",
        )
        assert plan.severity is PlanSeverity.HIGH


# ===========================================================================
# Orchestrator approval gate behavior
# ===========================================================================


class TestOrchestratorApprovalGate:
    """Drive HldCommitPipeline.run() with a synthetic diff and assert
    the gate behavior depending on IBN_AUTO_APPROVE."""

    def _make_pipeline_with_mocks(self):
        from ibn.pipeline.hld_commit import HldCommitPipeline
        neo = MagicMock()
        neo.create_intent.return_value = {}
        neo.get_intent_by_origin.return_value = None
        neo.create_vlan.return_value = {}
        neo.get_device.return_value = None
        neo.create_device.return_value = {}
        neo.create_policy.return_value = {}
        neo.create_firewall_rule.return_value = {}
        neo.update_intent_status.return_value = None
        # A4 needs migration plan + intent lookups
        neo.run_query.return_value = [{"pids": [], "cids": []}]
        neo.get_migration_plan_by_commit.return_value = None
        neo.create_migration_plan.return_value = {}
        neo.update_migration_plan_status.return_value = None
        neo.transition_artifacts_to_por.return_value = None

        lm = MagicMock()
        lm.live_note.return_value = {}
        lm.space_create.return_value = {}

        return HldCommitPipeline(neo4j_client=neo, live_memory_client=lm)

    def test_gate_fires_when_auto_approve_off(self, monkeypatch, tmp_path):
        """With IBN_AUTO_APPROVE absent, the pipeline should EXIT at the gate."""
        import ibn.pipeline.hld_commit as hc

        monkeypatch.delenv("IBN_AUTO_APPROVE", raising=False)
        monkeypatch.chdir(tmp_path)
        # Need a fake .git directory so the markdown writer doesn't choke
        (tmp_path / ".git").mkdir()

        # Synthesize a population-only diff
        old_text = (
            "### Population Summary Table\n\n"
            "| Population | VLAN | Large Site Count | Small Site Count | QoS Priority | DSCP | Bandwidth |\n"
            "|------------|------|------------------|------------------|--------------|------|-----------|\n"
            "| A | 100 | 1 | 1 | Standard | AF21 | 1 Mbps |\n"
        )
        new_text = old_text + "| B | 199 | 1 | 1 | Standard | AF21 | 1 Mbps |\n"

        def fake_loader(commit, hld_path):
            return parse_hld(old_text, source_path=hld_path), parse_hld(new_text, source_path=hld_path)
        monkeypatch.setattr(hc, "load_snapshots", fake_loader)

        # Patch out the agents that touch real Neo4j so we don't need
        # the full agent dependency tree mocked.
        monkeypatch.setattr(
            "ibn.agents.agent1_ingestion.Agent1Ingestion.ingest_hld_changeset",
            lambda self, **kw: {
                "intents_created": ["INT-HLD-199"],
                "intents_existing": [],
                "dialogue_transcript": [],
                "changeset_summary": "+1 populations",
            },
        )
        monkeypatch.setattr(
            "ibn.agents.agent1_ingestion.Agent1Ingestion.ingest_hld_devices",
            lambda self, **kw: {
                "devices_created": [],
                "devices_updated": [],
                "devices_to_retire": [],
            },
        )
        monkeypatch.setattr(
            "ibn.agents.agent2_intent_policy.Agent2IntentPolicy.run",
            lambda self, **kw: {
                "id": "POL-1", "policyId": "POL-1", "intentId": kw.get("intent_id"),
                "ruleIds": [], "ruleCount": 0,
            },
        )

        pipeline = self._make_pipeline_with_mocks()
        result = pipeline.run(commit="abc12345", hld_path="HLD.md", dialogue_fn=lambda p, c: "a")

        assert result["cycle_complete"] is False
        assert result["awaiting_approval"] is True
        assert result["pending_plan_path"] is not None
        assert any(s.name == "Approval gate" for s in result["stage_objects"])

        # Markdown file should exist
        from pathlib import Path
        md_files = list(Path(".git/ibn-pending-approval").glob("*.md"))
        assert len(md_files) >= 1
        body = md_files[0].read_text()
        assert "PLAN-" in body
        assert "ibn.tools.approve" in body

    def test_auto_approve_bypasses_gate(self, monkeypatch, tmp_path):
        """With IBN_AUTO_APPROVE=1 the pipeline should NOT pause."""
        import ibn.pipeline.hld_commit as hc

        monkeypatch.setenv("IBN_AUTO_APPROVE", "1")
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        old_text = (
            "### Population Summary Table\n\n"
            "| Population | VLAN | Large Site Count | Small Site Count | QoS Priority | DSCP | Bandwidth |\n"
            "|------------|------|------------------|------------------|--------------|------|-----------|\n"
            "| A | 100 | 1 | 1 | Standard | AF21 | 1 Mbps |\n"
        )
        new_text = old_text + "| B | 199 | 1 | 1 | Standard | AF21 | 1 Mbps |\n"

        def fake_loader(commit, hld_path):
            return parse_hld(old_text, source_path=hld_path), parse_hld(new_text, source_path=hld_path)
        monkeypatch.setattr(hc, "load_snapshots", fake_loader)

        # Stub all the agents — including A3/A5/A7 which the auto-approve
        # path runs through
        monkeypatch.setattr(
            "ibn.agents.agent1_ingestion.Agent1Ingestion.ingest_hld_changeset",
            lambda self, **kw: {
                "intents_created": ["INT-HLD-199"], "intents_existing": [],
                "dialogue_transcript": [], "changeset_summary": "+1 populations",
            },
        )
        monkeypatch.setattr(
            "ibn.agents.agent1_ingestion.Agent1Ingestion.ingest_hld_devices",
            lambda self, **kw: {"devices_created": [], "devices_updated": [], "devices_to_retire": []},
        )
        monkeypatch.setattr(
            "ibn.agents.agent2_intent_policy.Agent2IntentPolicy.run",
            lambda self, **kw: {"id": "POL-1", "policyId": "POL-1",
                                "intentId": kw.get("intent_id"), "ruleIds": [], "ruleCount": 0},
        )
        monkeypatch.setattr(
            "ibn.agents.agent3_policy_config.Agent3PolicyConfig.run",
            lambda self, **kw: {"devices": [], "intent_id": kw.get("intent_id")},
        )
        # A5 isn't called when there are no devices to push, so no patch needed
        monkeypatch.setattr(
            "ibn.agents.agent7_assessment.Agent7Assessment.run",
            lambda self, **kw: {"assessments": []},
        )

        pipeline = self._make_pipeline_with_mocks()
        result = pipeline.run(commit="def67890", hld_path="HLD.md", dialogue_fn=lambda p, c: "a")

        assert result["cycle_complete"] is True
        assert result["awaiting_approval"] is False
        # No "Approval gate" stage when auto-approved
        gate_stages = [s for s in result["stage_objects"] if s.name == "Approval gate"]
        assert len(gate_stages) == 0
        # A4 still ran
        a4_stages = [s for s in result["stage_objects"] if s.name == "A4 planning"]
        assert len(a4_stages) == 1
