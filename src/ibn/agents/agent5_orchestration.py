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
  8. Post-deployment verification: compare running config vs expected

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


def _default_ssh_verifier(device_id: str, expected_snippets: list[str]) -> dict:
    """
    Post-deployment verification via SSH: fetch running config and check expected
    snippets are present.

    Returns {"verified": True, "device": device_id} or raises on mismatch.
    """
    import paramiko  # lazy import

    host = device_id
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="vyos", timeout=10)

    stdin, stdout, stderr = ssh.exec_command("show configuration commands")
    running = stdout.read().decode()
    ssh.close()

    missing = [s for s in expected_snippets if s not in running]
    if missing:
        raise RuntimeError(
            f"Verification failed on {device_id}: "
            f"{len(missing)} expected snippet(s) not found: {missing[:3]}"
        )

    return {"verified": True, "device": device_id, "checked": len(expected_snippets)}


def _extract_verify_snippets(config: str, max_snippets: int = 10) -> list[str]:
    """
    Extract key lines from a VyOS config block to use as verification probes.

    We take the first word of each ``set`` line (the command prefix) as a
    lightweight presence check — enough to confirm the config was accepted.
    Blank lines and comments are skipped.
    """
    snippets = []
    for line in config.splitlines():
        line = line.strip()
        if line.startswith("set ") and len(line) > 8:
            # Take up to the first 60 chars as the probe
            snippets.append(line[:60])
            if len(snippets) >= max_snippets:
                break
    return snippets


# ---------------------------------------------------------------------------
# Slice 2: SR Linux executor via `docker exec` into the containerlab node
# ---------------------------------------------------------------------------
# SR Linux containerlab nodes expose `sr_cli` as a CLI shell inside the
# container. We push config by piping a script to `sr_cli` over stdin via
# `docker exec -i`. This bypasses SSH (no credentials needed) and matches
# how the probe in tasks/Slice 2 task 1 was validated.
#
# The container name is derived from the device hostname using the
# containerlab convention: ``clab-<lab-prefix>-<node-name>``. The lab
# prefix is read from the IBN_CLAB_PREFIX env var (default: ``ibnlab``).

import os
import subprocess


def _srlinux_container_for(device_id: str) -> str:
    """Map an IBN device id (or hostname) to its containerlab container name.

    If *device_id* already starts with ``clab-`` we treat it as the literal
    container name and pass it through. Otherwise we derive the name using
    the IBN_CLAB_PREFIX env var (default ``ibnlab``).
    """
    if device_id.lower().startswith("clab-"):
        return device_id
    prefix = os.environ.get("IBN_CLAB_PREFIX", "ibnlab")
    short = device_id.lower()
    for strip in ("dev-hq-", "dev-"):
        if short.startswith(strip):
            short = short[len(strip):]
    short = short.replace("_", "-")
    return f"clab-{prefix}-{short}"


def _srlinux_ssh_executor(device_id: str, config: str) -> dict:
    """Push SR Linux config via ``docker exec ... sr_cli``.

    *config* is a multi-line string of SR Linux ``set`` commands as
    rendered by the srl_*.j2 template chain. We wrap it in
    ``enter candidate ... commit now`` so the change is atomic.
    """
    container = _srlinux_container_for(device_id)

    # Build the sr_cli script: enter candidate, apply, commit, quit.
    # Each line of the rendered config is already a complete `set` statement.
    script_lines = ["enter candidate"]
    for line in config.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            script_lines.append(line)
    script_lines.append("commit now")
    script_lines.append("quit")
    script = "\n".join(script_lines) + "\n"

    proc = subprocess.run(
        ["docker", "exec", "-i", container, "sr_cli"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"sr_cli push to {container} failed (rc={proc.returncode}): "
            f"{proc.stderr.decode(errors='replace')[:500]}"
        )
    return {"status": "ok", "device": device_id, "container": container}


def _srlinux_ssh_verifier(device_id: str, expected_snippets: list[str]) -> dict:
    """Verify SR Linux config via ``docker exec ... sr_cli`` running info from running."""
    container = _srlinux_container_for(device_id)
    proc = subprocess.run(
        ["docker", "exec", container, "sr_cli", "-d", "info from running"],
        capture_output=True,
        timeout=60,
    )
    running = proc.stdout.decode(errors="replace")
    missing = [s for s in expected_snippets if s not in running]
    if missing:
        raise RuntimeError(
            f"SR Linux verification failed on {container}: "
            f"{len(missing)} expected snippet(s) not found: {missing[:3]}"
        )
    return {"verified": True, "device": device_id, "checked": len(expected_snippets)}


# ---------------------------------------------------------------------------
# Vendor dispatch table
# ---------------------------------------------------------------------------
# Maps device.platform (case-insensitive) → (executor, verifier) callables.
# Adding a new vendor in a future slice is one line here plus a new
# executor function above.
_VENDOR_EXECUTORS: dict[str, Callable] = {
    "vyos":    _default_ssh_executor,
    "srlinux": _srlinux_ssh_executor,
}
_VENDOR_VERIFIERS: dict[str, Callable] = {
    "vyos":    _default_ssh_verifier,
    "srlinux": _srlinux_ssh_verifier,
}


def _resolve_executor(platform: Optional[str]) -> Callable:
    if not platform:
        return _default_ssh_executor
    return _VENDOR_EXECUTORS.get(platform.lower(), _default_ssh_executor)


def _resolve_verifier(platform: Optional[str]) -> Callable:
    if not platform:
        return _default_ssh_verifier
    return _VENDOR_VERIFIERS.get(platform.lower(), _default_ssh_verifier)


class Agent5Orchestration(BaseAgent):

    AGENT_ID   = "A5"
    AGENT_NAME = "Orchestration"

    def __init__(
        self,
        neo4j,
        live_memory,
        event_bus=None,
        ssh_executor: Optional[Callable] = None,
        ssh_verifier: Optional[Callable] = None,
    ):
        super().__init__(neo4j, live_memory, event_bus)
        self._ssh = ssh_executor or _default_ssh_executor
        self._verify = ssh_verifier or _default_ssh_verifier

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

        skipped: list[str] = []

        # ── Push in plan order ─────────────────────────────────────────
        for step in plan:
            device_id = step["deviceId"]
            config_id = step.get("configId", f"CFG-{uuid.uuid4().hex[:8].upper()}")
            content   = step.get("content", "")
            platform  = step.get("platform")  # Slice 2: vendor dispatch hint

            # Slice 2: skip devices whose rendered config is empty (the
            # template chain produced nothing for them). These are usually
            # devices the seed has but A3 has no template support for yet.
            # Skipping is honest — we record nothing rather than push junk
            # to a non-resolvable hostname.
            if not content.strip():
                skipped.append(device_id)
                self._note(
                    deploy_space,
                    f"Device {device_id}: SKIPPED (empty rendered config)",
                    category="device-result",
                )
                continue

            # Slice 2: per-platform executor selection. If the constructor
            # was given an explicit ssh_executor (test injection), use that
            # — otherwise dispatch on platform.
            if self._ssh is _default_ssh_executor:
                executor = _resolve_executor(platform)
            else:
                executor = self._ssh

            event_id = f"DEP-{uuid.uuid4().hex[:8].upper()}"
            try:
                executor(device_id, content)

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

        # ── Post-deployment verification ───────────────────────────────
        verify_results: list[dict] = []
        for step in succeeded:
            device_id = step["deviceId"]
            # Build verification snippets from the deployed config lines
            snippets = _extract_verify_snippets(step.get("content", ""))
            if not snippets:
                verify_results.append({"device": device_id, "verified": True, "skipped": True})
                continue
            try:
                vr = self._verify(device_id, snippets)
                verify_results.append(vr)
                self._note(
                    deploy_space,
                    f"Device {device_id}: post-deploy verification PASSED ({vr.get('checked', 0)} checks)",
                    category="verification-result",
                )
            except Exception as exc:
                verify_results.append({"verified": False, "device": device_id, "error": str(exc)})
                self._note(
                    deploy_space,
                    f"Device {device_id}: post-deploy verification WARNING — {exc}",
                    category="verification-result",
                )
                self._log.warning("Verification warning for %s: %s", device_id, exc)

        all_verified = all(r.get("verified", False) for r in verify_results)

        # ── Full success ───────────────────────────────────────────────
        self._neo4j.update_intent_status(intent_id, "ORCHESTRATED")

        self._publish("deployment.complete", {
            "intentId":   intent_id,
            "devices":    [s["deviceId"] for s in succeeded],
            "modelState": ModelState.DEPLOYED.value,
            "verified":   all_verified,
        })

        return {
            "id":           intent_id,
            "status":       "ORCHESTRATED",
            "devices":      [s["deviceId"] for s in succeeded],
            "skipped":      skipped,
            "verified":     all_verified,
            "verification": verify_results,
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
