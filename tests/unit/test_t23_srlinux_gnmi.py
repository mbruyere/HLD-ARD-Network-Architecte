"""
T23 — Slice 7a SR Linux gNMI executor + CLI→YANG translator.

The translator is pure-Python and table-driven; we test it exhaustively
against the line shapes the `srl_*.j2` chain produces. The executor
itself is tested via monkey-patched `gNMIclient` — the real live path
is covered by the Slice 7a acceptance flow (commit the HLD, set
IBN_SRLINUX_TRANSPORT=gnmi, confirm config on the running container).
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from ibn.agents._srlinux_yang import (
    parse_line, cli_to_gnmi_updates, UnknownCliLine,
)


# ===========================================================================
# Line-by-line translator coverage
# ===========================================================================


class TestParseLine:

    def test_hostname(self):
        assert parse_line("set / system name host-name DEV-HQ-ACC-01") == (
            "/system/name", {"host-name": "DEV-HQ-ACC-01"}
        )

    def test_system_location_quoted(self):
        assert parse_line(
            'set / system information location "IBN-Lab managed by closed-loop pipeline"'
        ) == ("/system/information", {"location": "IBN-Lab managed by closed-loop pipeline"})

    def test_interface_admin_state(self):
        assert parse_line("set / interface ethernet-1/1 admin-state enable") == (
            "/interface[name=ethernet-1/1]", {"admin-state": "enable"}
        )

    def test_interface_description(self):
        path, val = parse_line(
            'set / interface ethernet-1/1 description "Trunk to access layer (HLD-driven)"'
        )
        assert path == "/interface[name=ethernet-1/1]"
        assert val == {"description": "Trunk to access layer (HLD-driven)"}

    def test_interface_vlan_tagging_true(self):
        assert parse_line("set / interface ethernet-1/1 vlan-tagging true") == (
            "/interface[name=ethernet-1/1]", {"vlan-tagging": True}
        )

    def test_interface_vlan_tagging_false(self):
        assert parse_line("set / interface ethernet-1/1 vlan-tagging false") == (
            "/interface[name=ethernet-1/1]", {"vlan-tagging": False}
        )

    def test_subif_type(self):
        assert parse_line("set / interface ethernet-1/1 subinterface 100 type bridged") == (
            "/interface[name=ethernet-1/1]/subinterface[index=100]", {"type": "bridged"}
        )

    def test_subif_vlan_id(self):
        assert parse_line(
            "set / interface ethernet-1/1 subinterface 100 vlan encap single-tagged vlan-id 100"
        ) == (
            "/interface[name=ethernet-1/1]/subinterface[index=100]/vlan/encap/single-tagged",
            {"vlan-id": 100},
        )

    def test_subif_description(self):
        path, val = parse_line(
            'set / interface ethernet-1/1 subinterface 100 description "Employee (HLD-driven)"'
        )
        assert path == "/interface[name=ethernet-1/1]/subinterface[index=100]"
        assert val == {"description": "Employee (HLD-driven)"}

    def test_network_instance_type(self):
        assert parse_line("set / network-instance vlan-100 type mac-vrf") == (
            "/network-instance[name=vlan-100]", {"type": "mac-vrf"}
        )

    def test_network_instance_interface_ref(self):
        assert parse_line(
            "set / network-instance vlan-100 interface ethernet-1/1.100"
        ) == (
            "/network-instance[name=vlan-100]/interface[name=ethernet-1/1.100]",
            {},
        )

    def test_blank_line_ignored(self):
        assert parse_line("") is None
        assert parse_line("   \n") is None

    def test_comment_ignored(self):
        assert parse_line("# a comment") is None

    def test_unknown_line_raises(self):
        with pytest.raises(UnknownCliLine):
            parse_line("set / something unknown here")


# ===========================================================================
# Full blob merging (multiple leaves per container → one gNMI op)
# ===========================================================================


class TestCliToGnmiUpdates:

    def test_empty(self):
        assert cli_to_gnmi_updates("") == []

    def test_full_chain_merges_per_path(self):
        blob = """
        set / system name host-name DEV-HQ-ACC-01
        set / system information location "IBN-Lab managed by closed-loop pipeline"
        set / interface ethernet-1/1 admin-state enable
        set / interface ethernet-1/1 description "Trunk to access layer (HLD-driven)"
        set / interface ethernet-1/1 vlan-tagging true
        set / interface ethernet-1/1 subinterface 100 type bridged
        set / interface ethernet-1/1 subinterface 100 vlan encap single-tagged vlan-id 100
        set / interface ethernet-1/1 subinterface 100 description "vlan-100 (HLD-driven)"
        set / network-instance vlan-100 type mac-vrf
        set / network-instance vlan-100 interface ethernet-1/1.100
        """
        updates = cli_to_gnmi_updates(blob)
        paths = [p for p, _ in updates]
        # The three interface leaves collapse to ONE (path, value) entry.
        assert paths.count("/interface[name=ethernet-1/1]") == 1
        # Find that merged entry and check all three leaves are present.
        iface = dict(updates)["/interface[name=ethernet-1/1]"]
        assert iface == {
            "admin-state": "enable",
            "description": "Trunk to access layer (HLD-driven)",
            "vlan-tagging": True,
        }
        # Subif merges too
        sub = dict(updates)["/interface[name=ethernet-1/1]/subinterface[index=100]"]
        assert sub == {"type": "bridged", "description": "vlan-100 (HLD-driven)"}
        # Order is preserved (insertion order)
        assert paths[0] == "/system/name"
        assert paths[-1] == "/network-instance[name=vlan-100]/interface[name=ethernet-1/1.100]"


# ===========================================================================
# Executor dispatch + monkey-patched Set call
# ===========================================================================


class TestExecutorDispatch:

    def test_default_dispatch_keeps_cli(self, monkeypatch):
        monkeypatch.delenv("IBN_SRLINUX_TRANSPORT", raising=False)
        from ibn.agents.agent5_orchestration import _resolve_executor, _srlinux_ssh_executor
        assert _resolve_executor("srlinux") is _srlinux_ssh_executor

    def test_gnmi_env_selects_gnmi_executor(self, monkeypatch):
        monkeypatch.setenv("IBN_SRLINUX_TRANSPORT", "gnmi")
        from ibn.agents.agent5_orchestration import _resolve_executor, _srlinux_gnmi_executor
        assert _resolve_executor("srlinux") is _srlinux_gnmi_executor

    def test_gnmi_env_selects_gnmi_verifier(self, monkeypatch):
        monkeypatch.setenv("IBN_SRLINUX_TRANSPORT", "gnmi")
        from ibn.agents.agent5_orchestration import _resolve_verifier, _srlinux_gnmi_verifier
        assert _resolve_verifier("srlinux") is _srlinux_gnmi_verifier

    def test_vyos_unaffected_by_flag(self, monkeypatch):
        monkeypatch.setenv("IBN_SRLINUX_TRANSPORT", "gnmi")
        from ibn.agents.agent5_orchestration import _resolve_executor, _default_ssh_executor
        assert _resolve_executor("vyos") is _default_ssh_executor


class TestGnmiExecutorCall:

    def test_empty_config_is_skipped(self, monkeypatch):
        from ibn.agents.agent5_orchestration import _srlinux_gnmi_executor
        monkeypatch.setattr(
            "ibn.agents.agent5_orchestration._srlinux_mgmt_ip",
            lambda c: "192.0.2.1",
        )
        r = _srlinux_gnmi_executor("DEV-HQ-ACC-01", "  \n# only comments\n")
        assert r["status"] == "skipped"

    def test_set_is_issued_with_translated_updates(self, monkeypatch):
        from ibn.agents import agent5_orchestration as a5

        monkeypatch.setattr(a5, "_srlinux_mgmt_ip", lambda c: "192.0.2.1")

        captured: dict = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                captured["kwargs"] = kw
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def set(self, update=None, delete=None, replace=None):
                captured["update"] = update
                return {"response": [{"op": "UPDATE"} for _ in update]}

        import pygnmi.client as pyc
        monkeypatch.setattr(pyc, "gNMIclient", FakeClient)

        blob = (
            "set / system name host-name DEV-HQ-ACC-01\n"
            "set / interface ethernet-1/1 admin-state enable\n"
            "set / interface ethernet-1/1 vlan-tagging true\n"
        )
        r = a5._srlinux_gnmi_executor("DEV-HQ-ACC-01", blob)
        assert r["status"] == "ok"
        assert r["transport"] == "gnmi"
        # Two merged paths: /system/name, /interface[name=ethernet-1/1]
        assert r["updates"] == 2
        paths = [p for p, _ in captured["update"]]
        assert paths == ["/system/name", "/interface[name=ethernet-1/1]"]
        assert captured["kwargs"]["skip_verify"] is True
