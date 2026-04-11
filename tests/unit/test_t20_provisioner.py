"""
T20 — Slice 3 Provisioner unit tests.

Two layers of coverage:

1. **Provisioner pure-logic tests** — clab YAML mutation, container
   name resolution, kind/image dispatch. These touch no infra.

2. **Orchestrator wiring test** — drives ``HldCommitPipeline`` with
   a synthetic HLD diff against a fake Neo4j + Live-Memory and a
   monkey-patched Provisioner that records what would have been
   provisioned/retired. Asserts the orchestrator calls the right
   methods in the right order with the right device entries.

The full live integration test (real clab deploy + retire) lives in
tests/integration/test_slice3_provisioning.py with a memory-pressure
caveat. This file is the fast, hermetic counterpart that runs in
CI and on small hosts.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ibn.parser.hld_parser import (
    parse_hld, parse_device_inventory, diff_snapshots, DeviceEntry,
)
from ibn.core.clab_yaml import (
    load_topology, save_topology, add_node, remove_node,
    has_node, list_nodes, kind_image_for, next_free_mgmt_ip,
    UnsupportedPlatformError,
)
from ibn.agents.provisioner import Provisioner, ProvisionResult, RetireResult


HLD_FIXTURE = """\
# Test HLD

### Population Summary Table

| Population | VLAN | Large Site Count | Small Site Count | QoS Priority | DSCP | Bandwidth |
|------------|------|------------------|------------------|--------------|------|-----------|
| Test Pop | 100 | 1 | 1 | Standard | AF21 | 1 Mbps |

### Device Inventory Table

| Device ID | Vendor | Platform | Role | Site | Container | Mgmt IP |
|-----------|--------|----------|------|------|-----------|---------|
| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 | 192.168.100.121 |
"""


# ===========================================================================
# 1. HLD parser — device inventory path
# ===========================================================================


class TestParseDeviceInventory:

    def test_parses_minimal_table(self):
        rows = parse_device_inventory(HLD_FIXTURE)
        assert len(rows) == 1
        r = rows[0]
        assert r.device_id == "acc-sw-01"
        assert r.vendor == "Nokia"
        assert r.platform == "srlinux"
        assert r.role == "ACCESS_SWITCH"
        assert r.site == "HQ"
        assert r.clab_container == "clab-ibnlab-switches-acc-sw-01"
        assert r.mgmt_ipv4 == "192.168.100.121"
        assert r.line_number > 0

    def test_returns_empty_when_table_missing(self):
        no_table = "# Empty doc\n\nJust prose, no inventory table.\n"
        assert parse_device_inventory(no_table) == []

    def test_skips_rows_with_too_few_columns(self):
        bad = HLD_FIXTURE.replace(
            "| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 | 192.168.100.121 |",
            "| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH |",
        )
        assert parse_device_inventory(bad) == []


class TestDiffDeviceInventory:

    def test_no_op_when_unchanged(self):
        snap = parse_hld(HLD_FIXTURE)
        cs = diff_snapshots(snap, snap)
        assert cs.is_empty
        assert not cs.devices_added
        assert not cs.devices_modified
        assert not cs.devices_removed

    def test_detects_added_device(self):
        old = parse_hld(HLD_FIXTURE)
        new_text = HLD_FIXTURE.replace(
            "| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 | 192.168.100.121 |",
            (
                "| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 | 192.168.100.121 |\n"
                "| acc-sw-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-02 | 192.168.100.122 |"
            ),
        )
        new = parse_hld(new_text)
        cs = diff_snapshots(old, new)
        assert len(cs.devices_added) == 1
        assert cs.devices_added[0].device_id == "acc-sw-02"
        assert cs.devices_added[0].mgmt_ipv4 == "192.168.100.122"
        assert "+1 devices" in cs.summary()

    def test_detects_removed_device(self):
        old = parse_hld(HLD_FIXTURE)
        new_text = HLD_FIXTURE.replace(
            "| acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 | 192.168.100.121 |\n",
            "",
        )
        new = parse_hld(new_text)
        cs = diff_snapshots(old, new)
        assert len(cs.devices_removed) == 1
        assert cs.devices_removed[0].device_id == "acc-sw-01"

    def test_detects_modified_device_when_property_changes(self):
        old = parse_hld(HLD_FIXTURE)
        new_text = HLD_FIXTURE.replace(
            "192.168.100.121",
            "192.168.100.130",
        )
        new = parse_hld(new_text)
        cs = diff_snapshots(old, new)
        assert len(cs.devices_modified) == 1
        assert cs.devices_modified[0].mgmt_ipv4 == "192.168.100.130"


# ===========================================================================
# 2. clab YAML mutation
# ===========================================================================


class TestClabYaml:

    def test_kind_image_for_srlinux(self):
        spec = kind_image_for("Nokia", "srlinux")
        assert spec["kind"] == "nokia_srlinux"
        assert "srlinux" in spec["image"]

    def test_kind_image_for_unknown_raises(self):
        with pytest.raises(UnsupportedPlatformError):
            kind_image_for("AcmeCorp", "fakeOS")

    def test_load_save_roundtrip(self, tmp_path):
        path = tmp_path / "topo.yml"
        path.write_text(
            "name: probe\n"
            "topology:\n"
            "  nodes:\n"
            "    a:\n"
            "      kind: linux\n"
        )
        topo = load_topology(path)
        assert "a" in topo["topology"]["nodes"]
        save_topology(path, topo)
        topo2 = load_topology(path)
        assert topo == topo2

    def test_add_node_idempotent(self, tmp_path):
        topo = {"topology": {"nodes": {}}}
        add_node(topo, "n1", "Nokia", "srlinux", "10.0.0.1")
        assert has_node(topo, "n1")
        # Re-add — should not duplicate or fail
        add_node(topo, "n1", "Nokia", "srlinux", "10.0.0.1")
        assert list_nodes(topo) == ["n1"]

    def test_remove_node_returns_true_when_removed(self):
        topo = {"topology": {"nodes": {"n1": {}}}}
        assert remove_node(topo, "n1") is True
        assert "n1" not in topo["topology"]["nodes"]

    def test_remove_node_returns_false_when_absent(self):
        topo = {"topology": {"nodes": {}}}
        assert remove_node(topo, "ghost") is False

    def test_next_free_mgmt_ip_skips_used(self):
        topo = {
            "mgmt": {"ipv4-subnet": "192.168.100.0/24"},
            "topology": {"nodes": {
                "a": {"mgmt-ipv4": "192.168.100.121"},
                "b": {"mgmt-ipv4": "192.168.100.122"},
            }},
        }
        assert next_free_mgmt_ip(topo) == "192.168.100.123"

    def test_next_free_mgmt_ip_starts_at_121(self):
        topo = {
            "mgmt": {"ipv4-subnet": "192.168.100.0/24"},
            "topology": {"nodes": {}},
        }
        # Range 1-120 reserved for the netlab firewall lab
        assert next_free_mgmt_ip(topo) == "192.168.100.121"


# ===========================================================================
# 3. Orchestrator → Provisioner wiring (mocked Provisioner)
# ===========================================================================


@pytest.fixture
def mock_provisioner_module(monkeypatch):
    """Replace the real Provisioner with a mock that records calls.

    Returns the mock instance so tests can inspect ``provision`` and
    ``retire`` invocations.
    """
    import ibn.pipeline.hld_commit as hc

    mock_instance = MagicMock(spec=Provisioner)
    mock_instance.provision = MagicMock(
        side_effect=lambda entry, deploy_space="ibn-deploy-001": ProvisionResult(
            device_id=entry.device_id,
            container=entry.clab_container,
            success=True,
            state="PROVISIONED",
        )
    )
    mock_instance.retire = MagicMock(
        side_effect=lambda did, deploy_space="ibn-deploy-001": RetireResult(
            device_id=did,
            container=f"clab-ibnlab-switches-{did}",
            success=True,
        )
    )

    # Patch the Provisioner constructor inside hld_commit's module so any
    # `from ibn.agents.provisioner import Provisioner` lookup at function-
    # call time gets our mock.
    import ibn.agents.provisioner as prov_mod
    monkeypatch.setattr(prov_mod, "Provisioner", lambda neo, lm: mock_instance)

    return mock_instance


class TestOrchestratorProvisioningStage:
    """Drive HldCommitPipeline._run_provisioning_stage with a mock Provisioner.

    These tests instantiate HldCommitPipeline with mock Neo4j / Live-Memory
    so the real clients aren't created in __init__. We then call the helper
    directly with a synthetic device list.
    """

    def _make_pipeline(self):
        from ibn.pipeline.hld_commit import HldCommitPipeline
        p = HldCommitPipeline(
            neo4j_client       = MagicMock(),
            live_memory_client = MagicMock(),
        )
        return p

    def test_provision_stage_calls_provisioner_for_added_device(
        self, mock_provisioner_module
    ):
        pipeline = self._make_pipeline()
        entry = DeviceEntry(
            device_id="acc-sw-99", vendor="Nokia", platform="srlinux",
            role="ACCESS_SWITCH", site="HQ",
            clab_container="clab-ibnlab-switches-acc-sw-99",
            mgmt_ipv4="192.168.100.199",
            line_number=42,
        )
        result = pipeline._run_provisioning_stage(
            new_device_entries=[entry],
            retired_device_ids=[],
        )
        assert mock_provisioner_module.provision.call_count == 1
        provisioned = result["provisioned"]
        assert len(provisioned) == 1
        assert provisioned[0].device_id == "acc-sw-99"
        assert provisioned[0].success is True

    def test_provision_stage_calls_retire_for_removed_device(
        self, mock_provisioner_module
    ):
        pipeline = self._make_pipeline()
        result = pipeline._run_provisioning_stage(
            new_device_entries=[],
            retired_device_ids=["acc-sw-99"],
        )
        assert mock_provisioner_module.retire.call_count == 1
        retired = result["retired"]
        assert len(retired) == 1
        assert retired[0].device_id == "acc-sw-99"
        assert retired[0].success is True

    def test_provision_stage_no_op_when_no_changes(self, mock_provisioner_module):
        pipeline = self._make_pipeline()
        result = pipeline._run_provisioning_stage(
            new_device_entries=[],
            retired_device_ids=[],
        )
        assert mock_provisioner_module.provision.call_count == 0
        assert mock_provisioner_module.retire.call_count == 0
        assert result == {"provisioned": [], "retired": []}
