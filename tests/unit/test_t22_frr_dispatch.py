"""
T22 — Slice 5 FRR vendor dispatch + template rendering.

Fast unit-level coverage: FRR is in the clab kind map, A3 resolves
its template chain, A5 resolves its executor, and the FRR Jinja2
chain renders cleanly against a synthetic device + VLAN list.

The full live test (actually deploy an ibn-frr:local container + push
config via vtysh) is covered by the Slice 5 acceptance flow — a
committed HLD Device Inventory Table edit triggers it through the
Slice 4 approval gate.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ibn.core.clab_yaml import kind_image_for, UnsupportedPlatformError
from ibn.agents.agent3_policy_config import (
    _TEMPLATE_CHAINS, _resolve_chain,
)
from ibn.agents.agent5_orchestration import (
    _VENDOR_EXECUTORS, _VENDOR_VERIFIERS,
    _resolve_executor, _resolve_verifier,
    _frr_executor, _frr_verifier,
)


# ===========================================================================
# clab kind dispatch
# ===========================================================================


class TestFrrKindImage:

    def test_frr_has_kind_image(self):
        spec = kind_image_for("FRR", "frr")
        assert spec["kind"] == "linux"
        assert "frr" in spec["image"].lower()

    def test_frr_case_insensitive(self):
        upper = kind_image_for("FRR", "FRR")
        lower = kind_image_for("frr", "frr")
        assert upper == lower


# ===========================================================================
# A3 template chain dispatch
# ===========================================================================


class TestFrrTemplateChain:

    def test_frr_in_chains(self):
        assert "frr" in _TEMPLATE_CHAINS

    def test_resolve_chain_frr(self):
        chain = _resolve_chain("frr")
        # Must include at least base + routing, order matters: base before routing
        assert "frr_base.j2" in chain
        assert "frr_routing.j2" in chain
        assert chain.index("frr_base.j2") < chain.index("frr_routing.j2")

    def test_resolve_chain_case_insensitive(self):
        assert _resolve_chain("FRR") == _resolve_chain("frr")

    def test_resolve_chain_unknown_falls_back_to_vyos(self):
        """Unknown platforms fall back to the VyOS chain (existing contract)."""
        chain = _resolve_chain("no-such-platform")
        assert chain == _TEMPLATE_CHAINS["vyos"]


# ===========================================================================
# A5 executor dispatch
# ===========================================================================


class TestFrrExecutorDispatch:

    def test_frr_executor_registered(self):
        assert "frr" in _VENDOR_EXECUTORS
        assert _VENDOR_EXECUTORS["frr"] is _frr_executor

    def test_frr_verifier_registered(self):
        assert "frr" in _VENDOR_VERIFIERS
        assert _VENDOR_VERIFIERS["frr"] is _frr_verifier

    def test_resolve_executor_frr(self):
        assert _resolve_executor("frr") is _frr_executor

    def test_resolve_executor_case_insensitive(self):
        assert _resolve_executor("FRR") is _frr_executor
        assert _resolve_executor("Frr") is _frr_executor

    def test_resolve_verifier_frr(self):
        assert _resolve_verifier("frr") is _frr_verifier


# ===========================================================================
# FRR executor wire format (no container required)
# ===========================================================================
# The executor shells out to `docker exec -i <container> vtysh`. We
# patch subprocess.run to capture what would be piped to vtysh.


class TestFrrExecutorWireFormat:

    def test_executor_wraps_config_in_enable_config_end_write(self, monkeypatch):
        captured = {}

        def fake_run(cmd, input=None, capture_output=False, timeout=None):
            captured["cmd"] = cmd
            captured["input"] = input.decode("utf-8") if input else ""
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        import subprocess
        monkeypatch.setattr(subprocess, "run", fake_run)

        rendered = (
            "hostname edge-01\n"
            "router bgp 65001\n"
            " bgp router-id 10.0.0.1\n"
            "exit\n"
        )
        result = _frr_executor("clab-ibnlab-switches-edge-01", rendered)
        assert result["status"] == "ok"
        assert result["container"] == "clab-ibnlab-switches-edge-01"

        # Wire format: enable, configure terminal, <lines>, end, write memory
        sent = captured["input"]
        lines = sent.splitlines()
        assert lines[0] == "enable"
        assert lines[1] == "configure terminal"
        assert "hostname edge-01" in lines
        assert "router bgp 65001" in lines
        assert "end" in lines
        assert "write memory" in lines
        # order: enable before configure before end before write memory
        assert lines.index("end") < lines.index("write memory")
        assert lines.index("configure terminal") < lines.index("end")

    def test_executor_skips_blank_and_comment_lines(self, monkeypatch):
        captured = {}
        def fake_run(cmd, input=None, capture_output=False, timeout=None):
            captured["input"] = input.decode("utf-8") if input else ""
            r = MagicMock(); r.returncode = 0; r.stderr = b""
            return r
        import subprocess
        monkeypatch.setattr(subprocess, "run", fake_run)

        rendered = (
            "hostname foo\n"
            "\n"
            "# this is a comment\n"
            "router ospf\n"
        )
        _frr_executor("clab-ibnlab-switches-edge-01", rendered)
        sent_lines = captured["input"].splitlines()
        assert "# this is a comment" not in sent_lines
        assert "hostname foo" in sent_lines
        assert "router ospf" in sent_lines

    def test_executor_raises_on_nonzero_returncode(self, monkeypatch):
        def fake_run(cmd, input=None, capture_output=False, timeout=None):
            r = MagicMock()
            r.returncode = 1
            r.stderr = b"vtysh parse error"
            return r
        import subprocess
        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="vtysh push.*failed"):
            _frr_executor("clab-probe", "hostname x\n")


# ===========================================================================
# FRR Jinja2 template rendering
# ===========================================================================


class TestFrrTemplates:
    """Render the three FRR templates against a synthetic context and
    assert the output has the right shape — no containers needed."""

    def _env(self):
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
        root = Path(__file__).resolve().parents[2]
        return Environment(
            loader=FileSystemLoader(str(root / "firewall_pipeline" / "templates")),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def test_frr_base_renders_hostname(self):
        env = self._env()
        device = {"hostname": "edge-01", "device_id": "DEV-HQ-EDGE-01",
                  "mgmt_ipv4": "192.168.100.125"}
        out = env.get_template("frr_base.j2").render(device=device)
        assert "hostname edge-01" in out

    def test_frr_interfaces_iterates_vlans(self):
        env = self._env()
        device = {"hostname": "edge-01", "device_id": "DEV-HQ-EDGE-01",
                  "mgmt_ipv4": "192.168.100.125"}
        vlans = [
            {"vlan_id": 100, "vlan_name": "employee"},
            {"vlan_id": 140, "vlan_name": "guest"},
        ]
        out = env.get_template("frr_interfaces.j2").render(device=device, vlans=vlans)
        assert "interface eth0" in out
        assert "interface eth0.100" in out
        assert "interface eth0.140" in out
        assert "employee" in out

    def test_frr_routing_emits_bgp_stub(self):
        env = self._env()
        device = {"hostname": "edge-01", "device_id": "DEV-HQ-EDGE-01",
                  "mgmt_ipv4": "192.168.100.125"}
        out = env.get_template("frr_routing.j2").render(device=device)
        assert "router bgp" in out
        assert "router ospf" in out
        assert "bgp router-id 192.168.100.125" in out

    def test_frr_routing_handles_missing_mgmt_ip(self):
        env = self._env()
        device = {"hostname": "edge-02", "device_id": "DEV-HQ-EDGE-02",
                  "mgmt_ipv4": None}
        out = env.get_template("frr_routing.j2").render(device=device)
        # Falls back to a deterministic 10.0.0.x router-id
        assert "bgp router-id 10.0.0." in out
