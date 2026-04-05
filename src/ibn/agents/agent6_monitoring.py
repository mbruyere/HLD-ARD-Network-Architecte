"""
Agent 6 — Monitoring  (RFC 9315 §5.2.1)

Responsibilities:
  1. Poll each NetLab device via SSH CLI (VyOS show commands)
  2. Parse interface states, firewall hit counts, VRRP HA state, routing table
  3. Write Telemetry nodes (L5, modelState=AS_BUILT) for each metric
  4. Upsert OperationalState per device (L5, modelState=AS_BUILT)
  5. Raise Alert nodes (L6) when metrics exceed configured thresholds
  6. Emit live_notes per polling cycle and on anomaly
  7. Publish telemetry.collected / alert.raised events

Entry point::

    agent = Agent6Monitoring(neo4j, live_memory, ssh_collector=<callable>)
    result = agent.run(
        devices=["usf-fw-01", "usf-fw-02", "dmzfw-01", "dmzfw-02"],
        asbuilt_space="ibn-asbuilt-current",
    )
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import (
    Alert, ModelState, OperationalState, Severity, Telemetry,
)


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "cpu_utilization":    90.0,   # %
    "memory_utilization": 85.0,   # %
    "interface_down":     1,      # any down interface triggers MEDIUM
}

SEVERITY_MAP = {
    "cpu_utilization":    Severity.MEDIUM,
    "memory_utilization": Severity.MEDIUM,
    "interface_down":     Severity.HIGH,
}


# ---------------------------------------------------------------------------
# VyOS CLI parsers (module-level — used by both agent and tests)
# ---------------------------------------------------------------------------

def parse_interfaces(output: str) -> list[dict]:
    """Parse ``show interfaces`` VyOS text output."""
    interfaces = []
    lines = output.strip().splitlines()
    # Skip header lines (first 3 lines)
    for line in lines[3:]:
        parts = line.split()
        if len(parts) >= 3:
            interfaces.append({
                "name":        parts[0],
                "ip":          parts[1] if "/" in parts[1] else None,
                "state":       parts[2],
                "description": " ".join(parts[3:]) if len(parts) > 3 else "",
            })
    return interfaces


def parse_vrrp(output: str) -> list[dict]:
    """Parse ``show vrrp`` VyOS text output."""
    groups = []
    lines = output.strip().splitlines()
    for line in lines[2:]:   # skip two header lines
        parts = line.split()
        if len(parts) >= 6:
            groups.append({
                "name":      parts[0],
                "interface": parts[1],
                "vrid":      int(parts[2]),
                "state":     parts[3],
                "priority":  int(parts[4]),
                "vip":       parts[5],
            })
    return groups


def parse_firewall_hits(output: str) -> list[dict]:
    """Parse ``show firewall`` VyOS text output."""
    rules = []
    lines = output.strip().splitlines()
    for line in lines[2:]:  # skip two header lines
        parts = line.split()
        if len(parts) >= 6:
            try:
                rules.append({
                    "rule":    int(parts[0]),
                    "action":  parts[1],
                    "source":  parts[2],
                    "dest":    parts[3],
                    "proto":   parts[4],
                    "hits":    int(parts[5]),
                })
            except (ValueError, IndexError):
                continue
    return rules


def parse_routes(output: str) -> list[dict]:
    """Parse ``show ip route`` VyOS text output."""
    routes = []
    for line in output.strip().splitlines()[1:]:
        if ">" in line:
            parts = line.split()
            # prefix may be at index 0 or 1 depending on whether code+flags are there
            for part in parts:
                if "/" in part:
                    routes.append({"prefix": part})
                    break
    return routes


# ---------------------------------------------------------------------------
# Default SSH collector
# ---------------------------------------------------------------------------

def _default_ssh_collector(device_id: str) -> dict:
    """
    Collect telemetry from a VyOS device over SSH.
    Returns a dict with parsed outputs.
    """
    import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(device_id, username="vyos", timeout=10)

    def _run(cmd: str) -> str:
        _, stdout, _ = ssh.exec_command(cmd)
        return stdout.read().decode()

    raw = {
        "interfaces": _run("show interfaces"),
        "vrrp":       _run("show vrrp"),
        "firewall":   _run("show firewall"),
        "routes":     _run("show ip route"),
        "version":    _run("show version"),
    }
    ssh.close()

    return {
        "hostname":   device_id,
        "interfaces": parse_interfaces(raw["interfaces"]),
        "vrrp":       parse_vrrp(raw["vrrp"]),
        "firewall":   parse_firewall_hits(raw["firewall"]),
        "routes":     parse_routes(raw["routes"]),
        # CPU/mem not available from CLI in this simplified model
        "cpu":        0.0,
        "memory":     0.0,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent6Monitoring(BaseAgent):

    AGENT_ID   = "A6"
    AGENT_NAME = "Monitoring"

    def __init__(self, neo4j, live_memory, event_bus=None, ssh_collector: Optional[Callable] = None):
        super().__init__(neo4j, live_memory, event_bus)
        self._collect = ssh_collector or _default_ssh_collector

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        devices:       list[str] = kwargs["devices"]
        asbuilt_space: str       = kwargs.get("asbuilt_space", "ibn-asbuilt-current")

        total_anomalies = 0
        results: list[dict] = []

        for device_id in devices:
            try:
                data = self._collect(device_id)
            except Exception as exc:
                self._log.error("SSH collect failed for %s: %s", device_id, exc)
                self._note(
                    asbuilt_space,
                    f"ANOMALY: SSH collection failed for {device_id} — {exc}",
                    category="anomaly-detected",
                )
                total_anomalies += 1
                continue

            anomalies = self._process_device(device_id, data, asbuilt_space)
            total_anomalies += len(anomalies)
            results.append({"device": device_id, "anomalies": anomalies})

        # Summary note
        self._note(
            asbuilt_space,
            f"Polling cycle complete: {len(devices)} devices, {total_anomalies} anomalies",
            category="telemetry-snapshot",
        )

        self._publish("telemetry.collected", {
            "devices":    len(devices),
            "anomalies":  total_anomalies,
        })

        return {
            "id":        "monitoring-cycle",
            "devices":   len(devices),
            "anomalies": total_anomalies,
            "results":   results,
        }

    # ------------------------------------------------------------------
    # Per-device processing
    # ------------------------------------------------------------------

    def _process_device(self, device_id: str, data: dict, asbuilt_space: str) -> list[str]:
        """Write telemetry/state to Neo4j and return list of anomaly descriptions."""
        anomalies: list[str] = []

        # ── Interface states ───────────────────────────────────────────
        for iface in data.get("interfaces", []):
            state = iface.get("state", "")
            metric_value = "up" if "u/u" in state else "down"

            self._neo4j.create_telemetry(Telemetry(
                deviceId      = device_id,
                metric        = "interface_state",
                value         = metric_value,
                interfaceName = iface["name"],
                modelState    = ModelState.AS_BUILT,
            ))

            if metric_value == "down":
                desc = f"{device_id} {iface['name']} transitioned DOWN unexpectedly"
                anomalies.append(desc)
                self._note(
                    asbuilt_space,
                    f"ANOMALY: {desc}",
                    category="anomaly-detected",
                )
                self._raise_alert(
                    device_id = device_id,
                    metric    = "interface_down",
                    value     = 1.0,
                    threshold = 1.0,
                    severity  = Severity.HIGH,
                )

        # ── CPU & memory ───────────────────────────────────────────────
        cpu = float(data.get("cpu", 0.0))
        mem = float(data.get("memory", 0.0))

        self._neo4j.upsert_operational_state(OperationalState(
            deviceId          = device_id,
            operState         = "running",
            cpuUtilization    = cpu,
            memoryUtilization = mem,
            modelState        = ModelState.AS_BUILT,
        ))

        if cpu > THRESHOLDS["cpu_utilization"]:
            desc = f"{device_id} CPU {cpu:.1f}% exceeds threshold {THRESHOLDS['cpu_utilization']}%"
            anomalies.append(desc)
            self._note(
                asbuilt_space,
                f"ANOMALY: {desc}",
                category="anomaly-detected",
            )
            self._raise_alert(
                device_id = device_id,
                metric    = "cpu_utilization",
                value     = cpu,
                threshold = THRESHOLDS["cpu_utilization"],
                severity  = Severity.MEDIUM,
            )

        if mem > THRESHOLDS["memory_utilization"]:
            desc = f"{device_id} memory {mem:.1f}% exceeds threshold {THRESHOLDS['memory_utilization']}%"
            anomalies.append(desc)
            self._note(
                asbuilt_space,
                f"ANOMALY: {desc}",
                category="anomaly-detected",
            )
            self._raise_alert(
                device_id = device_id,
                metric    = "memory_utilization",
                value     = mem,
                threshold = THRESHOLDS["memory_utilization"],
                severity  = Severity.MEDIUM,
            )

        # ── VRRP HA ────────────────────────────────────────────────────
        for group in data.get("vrrp", []):
            self._neo4j.create_telemetry(Telemetry(
                deviceId  = device_id,
                metric    = "vrrp_state",
                value     = group["state"],
                modelState= ModelState.AS_BUILT,
            ))

        return anomalies

    # ------------------------------------------------------------------
    # Alert helper
    # ------------------------------------------------------------------

    def _raise_alert(
        self,
        device_id: str,
        metric:    str,
        value:     float,
        threshold: float,
        severity:  Severity,
    ) -> None:
        alert = Alert(
            alertId   = f"ALT-{uuid.uuid4().hex[:8].upper()}",
            severity  = severity,
            metric    = metric,
            value     = value,
            threshold = threshold,
            deviceId  = device_id,
            modelState= ModelState.AS_BUILT,
        )
        self._neo4j.create_alert(alert)
        self._publish("alert.raised", {
            "alertId":  alert.alertId,
            "severity": severity.value,
            "metric":   metric,
            "device":   device_id,
        })
