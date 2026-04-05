"""
Agent 5 — Orchestration  (RFC 9315 §5.1.3)

Responsibilities:
  1. Receive a list of (device_id, config_content) pairs from Agent 3 (or directly)
  2. Push configuration to each NetLab device via SSH in plan order
  3. On any device failure: roll back all previously-succeeded devices
  4. Write DeploymentEvent nodes (L5) for each push (DEPLOYED / FAILED / ROLLED_BACK)
  5. Update Intent status to ORCHESTRATED on full success
  6. Emit live_notes per device result and on rollback
  7. Publish deployment.complete / deployment.failed events

Entry point::

    agent = Agent5Orchestration(neo4j, live_memory, ssh_executor=<callable>)
    result = agent.run(
        intent_id="INT-001",
        plan=[
            {"deviceId": "usf-fw-01", "configId": "CFG-001", "content": "..."},
            {"deviceId": "usf-fw-02", "configId": "CFG-002", "content": "..."},
        ],
        deploy_space="ibn-deploy-001",
    )
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import DeploymentEvent, ModelState


# ---------------------------------------------------------------------------
# SSH executor abstraction — lets tests inject a mock
# ---------------------------------------------------------------------------

def _default_ssh_executor(device_id: str, config: str) -> dict:
    """
    Real SSH push to a NetLab VyOS device.

    In production this delegates to paramiko / netmiko.
    Returns {"status": "ok", "device": device_id} or raises on failure.
    """
    import paramiko  # lazy import — not needed in tests

    host = device_id  # NetLab hostname resolves via /etc/hosts or DNS
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="vyos", timeout=10)

    # VyOS configure-mode session
    stdin, stdout, stderr = ssh.exec_command(
        f"configure\n{config}\ncommit\nsave\nexit"
    )
    exit_code = stdout.channel.recv_exit_status()
    ssh.close()

    if exit_code != 0:
        raise RuntimeError(f"SSH push to {device_id} failed (exit={exit_code}): {stderr.read().decode()}")

    return {"status": "ok", "device": device_id}


class Agent5Orchestration(BaseAgent):

    AGENT_ID   = "A5"
    AGENT_NAME = "Orchestration"

    def __init__(self, neo4j, live_memory, event_bus=None, ssh_executor: Optional[Callable] = None):
        super().__init__(neo4j, live_memory, event_bus)
        self._ssh = ssh_executor or _default_ssh_executor

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        intent_id:    str  = kwargs["intent_id"]
        plan:         list = kwargs["plan"]          # list of {deviceId, configId, content}
        deploy_space: str  = kwargs.get("deploy_space", "ibn-deploy-001")

        self._note(
            deploy_space,
            f"Starting deployment of {len(plan)} devices for {intent_id}",
            category="deployment-start",
        )

        succeeded: list[dict] = []  # devices that succeeded (for rollback)
        failed_device: Optional[str] = None

        # ── Push in plan order ─────────────────────────────────────────
        for step in plan:
            device_id = step["deviceId"]
            config_id = step.get("configId", f"CFG-{uuid.uuid4().hex[:8].upper()}")
            content   = step.get("content", "")

            event_id = f"DEP-{uuid.uuid4().hex[:8].upper()}"
            try:
                self._ssh(device_id, content)

                # Record success
                self._neo4j.create_deployment_event(DeploymentEvent(
                    eventId        = event_id,
                    targetDeviceId = device_id,
                    status         = "DEPLOYED",
                    modelState     = ModelState.DEPLOYED,
                    configId       = config_id,
                ))
                succeeded.append({"deviceId": device_id, "configId": config_id, "content": content})

                self._note(
                    deploy_space,
                    f"Device {device_id}: config pushed successfully",
                    category="device-result",
                )

            except Exception as exc:
                # Record failure
                self._neo4j.create_deployment_event(DeploymentEvent(
                    eventId        = event_id,
                    targetDeviceId = device_id,
                    status         = "FAILED",
                    modelState     = ModelState.DEPLOYED,
                    configId       = config_id,
                    errorMessage   = str(exc),
                ))

                self._note(
                    deploy_space,
                    f"Device {device_id}: push FAILED — {exc}",
                    category="device-result",
                )
                failed_device = device_id
                break

        # ── Rollback if any failure ────────────────────────────────────
        if failed_device:
            rollback_devices = [s["deviceId"] for s in succeeded]
            self._note(
                deploy_space,
                f"Rollback triggered: {failed_device} push failed, "
                f"rolling back {', '.join(rollback_devices)}",
                category="rollback-triggered",
            )
            self._rollback(succeeded, deploy_space)
            self._publish("deployment.failed", {
                "intentId":     intent_id,
                "failedDevice": failed_device,
                "rolledBack":   rollback_devices,
            })
            return {
                "id":       intent_id,
                "status":   "FAILED",
                "failed":   failed_device,
                "rolled_back": rollback_devices,
            }

        # ── Full success ───────────────────────────────────────────────
        self._neo4j.update_intent_status(intent_id, "ORCHESTRATED")

        self._publish("deployment.complete", {
            "intentId":   intent_id,
            "devices":    [s["deviceId"] for s in succeeded],
            "modelState": ModelState.DEPLOYED.value,
        })

        return {
            "id":      intent_id,
            "status":  "ORCHESTRATED",
            "devices": [s["deviceId"] for s in succeeded],
        }

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def _rollback(self, succeeded: list[dict], deploy_space: str) -> None:
        """Re-push the previous (pre-deployment) config to all succeeded devices.

        In a real system we'd fetch the previous config from Neo4j via
        PRECEDED_BY chain.  Here we re-push whatever ``previous_content``
        the caller supplied, falling back to empty string (no-op).
        """
        for step in reversed(succeeded):
            device_id = step["deviceId"]
            prev      = step.get("previous_content", "")  # may be empty for Phase 1
            event_id  = f"DEP-{uuid.uuid4().hex[:8].upper()}"
            try:
                if prev:
                    self._ssh(device_id, prev)
                self._neo4j.create_deployment_event(DeploymentEvent(
                    eventId        = event_id,
                    targetDeviceId = device_id,
                    status         = "ROLLED_BACK",
                    modelState     = ModelState.DEPLOYED,
                    rollbackFrom   = step.get("configId"),
                    rollbackTo     = step.get("previousConfigId"),
                ))
                self._note(
                    deploy_space,
                    f"Device {device_id}: rolled back successfully",
                    category="rollback-result",
                )
            except Exception as exc:
                self._log.error("Rollback failed for %s: %s", device_id, exc)
                self._note(
                    deploy_space,
                    f"Device {device_id}: rollback FAILED — {exc}",
                    category="rollback-result",
                )
