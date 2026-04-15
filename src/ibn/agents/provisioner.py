"""
Provisioner — A5 submodule for HLD-driven device lifecycle (Slice 3).

When the HLD's Device Inventory Table changes, the orchestrator calls
the Provisioner to reconcile the live containerlab topology against
the desired state. The Provisioner:

  1. Mutates the right containerlab YAML on disk
  2. Runs ``containerlab deploy`` (or ``destroy``) for the affected node
  3. Polls until the container is healthy
  4. Writes a LifecycleEvent (L8) capturing the transition
  5. Updates the Device's lifecycleState in Neo4j

Why a submodule and not a new agent
-----------------------------------
RFC 9315 §5.1.3 places "deploy" with Agent 5. Container provisioning
is the same job as config push at a different layer of abstraction
(make reality match the model). Adding A11 would split coordination
unnecessarily. We house this as ``ibn.agents.provisioner`` and the
orchestrator calls it explicitly between A2 and A3.

Lab path conventions
--------------------
The active containerlab topology lives at::

    <repo>/clab-ibnlab-switches.yml          ← source-of-truth (gitted)

But containerlab needs to deploy from a path the OS can chown
(``/home`` is on 9p which fails). The Provisioner copies to ``/tmp``
before each deploy, exactly like ``~/start-ibn-lab.sh`` does for the
firewall lab. After deploy, the ``/tmp`` copy is the *running* state;
the repo copy stays in sync because the Provisioner mirrors mutations
both ways.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ibn.core.clab_yaml import (
    load_topology, save_topology, add_node, remove_node,
    list_nodes, has_node, next_free_mgmt_ip,
    UnsupportedPlatformError,
)
from ibn.core.models import (
    Device, LifecycleEvent, DeviceLifecycleState, ModelState,
)


logger = logging.getLogger("ibn.provisioner")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProvisionResult:
    device_id:    str
    container:    str
    success:      bool
    state:        str          # final lifecycleState
    error:        Optional[str] = None
    duration_ms:  int = 0


@dataclass
class RetireResult:
    device_id:    str
    container:    str
    success:      bool
    error:        Optional[str] = None


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------

class Provisioner:
    """Reconcile containerlab topology against the Neo4j Device list."""

    # Source-of-truth path inside the repo (gitted, gitignored mutations
    # are not allowed — the orchestrator commits the YAML alongside the
    # HLD when applicable, future Slice 4).
    DEFAULT_REPO_TOPOLOGY = "clab-ibnlab-switches.yml"

    # Working path containerlab actually deploys from (must be off /home
    # because of the 9p chown issue documented in start-ibn-lab.sh).
    DEFAULT_WORK_TOPOLOGY = "/tmp/clab-ibnlab-switches.yml"

    def __init__(
        self,
        neo4j,
        live_memory,
        repo_topology_path: Optional[str] = None,
        work_topology_path: Optional[str] = None,
        clab_binary: str = "containerlab",
        clab_use_sudo: bool = True,
    ):
        self._neo4j = neo4j
        self._lm = live_memory
        self._repo_path = Path(repo_topology_path or self.DEFAULT_REPO_TOPOLOGY)
        self._work_path = Path(work_topology_path or self.DEFAULT_WORK_TOPOLOGY)
        self._clab = clab_binary
        self._sudo = clab_use_sudo
        self._log = logger

    # ------------------------------------------------------------------
    # Public: provision / retire
    # ------------------------------------------------------------------

    def provision(self, device_entry, deploy_space: str = "ibn-deploy-001") -> ProvisionResult:
        """Spin up (or adopt) the container for an HLD device entry.

        ``device_entry`` is a ``DeviceEntry`` from the HLD parser.

        Slice 4.5 — **Adopt path**: if the target container is already
        running (e.g. it was provisioned out-of-band by netlab for the
        firewall lab), skip the clab deploy entirely, mark the Device
        ACTIVE, and write an `ADOPTED` LifecycleEvent. This lets the
        HLD Device Inventory Table reflect containers the loop didn't
        spin up itself.

        Otherwise the standard flow runs:
          1. Add the node to the topology YAML (idempotent)
          2. Run `clab deploy` from the work path
          3. Poll `docker ps` for the container
          4. Write a LifecycleEvent + update Device.lifecycleState
        """
        start = time.monotonic()
        container = device_entry.clab_container
        device_id = device_entry.device_id

        # Slice 4.5 — adopt path: already running, no clab deploy needed.
        if self._container_running(container):
            self._log.info(
                "Provisioner: container %s already running — adopting (no deploy)",
                container,
            )
            self._safe_lifecycle_update(device_id, DeviceLifecycleState.ACTIVE.value)
            event = LifecycleEvent(
                eventId   = f"EVT-ADOPT-{uuid.uuid4().hex[:8].upper()}",
                deviceId  = device_id,
                eventType = "ADOPTED",
                fromState = DeviceLifecycleState.PLANNED.value,
                toState   = DeviceLifecycleState.ACTIVE.value,
                payload   = f"container={container} (externally provisioned)",
            )
            self._safe_create_event(event)
            self._note(
                deploy_space,
                f"Provisioner: adopted existing container {container} for {device_id}",
                "adopt-result",
            )
            return ProvisionResult(
                device_id   = device_id,
                container   = container,
                success     = True,
                state       = DeviceLifecycleState.ACTIVE.value,
                duration_ms = int((time.monotonic() - start) * 1000),
            )

        # Step 1: ensure topology has this node
        try:
            self._add_node_to_topology(device_entry)
        except UnsupportedPlatformError as exc:
            return self._provision_failure(
                device_id, container, f"unsupported platform: {exc}", start, deploy_space,
            )

        # Step 2: deploy
        try:
            self._clab_deploy()
        except subprocess.CalledProcessError as exc:
            return self._provision_failure(
                device_id, container,
                f"clab deploy failed (rc={exc.returncode}): "
                f"{(exc.stderr or b'').decode(errors='replace')[:400]}",
                start, deploy_space,
            )
        except FileNotFoundError as exc:
            return self._provision_failure(
                device_id, container, f"clab binary not found: {exc}",
                start, deploy_space,
            )

        # Step 3: wait for the container to appear
        if not self._wait_for_container(container, timeout=120):
            return self._provision_failure(
                device_id, container,
                "container did not appear in `docker ps` within 120s",
                start, deploy_space,
            )

        # Step 4: success — update lifecycleState + write event
        # The bolt connection may have gone idle during the long clab
        # deploy. Retry once on ServiceUnavailable.
        self._safe_lifecycle_update(device_id, DeviceLifecycleState.PROVISIONED.value)
        event = LifecycleEvent(
            eventId   = f"EVT-PROV-{uuid.uuid4().hex[:8].upper()}",
            deviceId  = device_id,
            eventType = "PROVISIONED",
            fromState = DeviceLifecycleState.PLANNED.value,
            toState   = DeviceLifecycleState.PROVISIONED.value,
            payload   = f"container={container} mgmt={device_entry.mgmt_ipv4}",
        )
        self._safe_create_event(event)

        self._note(
            deploy_space,
            f"Provisioner: {device_id} → container {container} is up "
            f"(took {int((time.monotonic() - start) * 1000)}ms)",
            "provision-result",
        )

        return ProvisionResult(
            device_id   = device_id,
            container   = container,
            success     = True,
            state       = DeviceLifecycleState.PROVISIONED.value,
            duration_ms = int((time.monotonic() - start) * 1000),
        )

    def retire(self, device_id: str, deploy_space: str = "ibn-deploy-001") -> RetireResult:
        """Tear down the container for an HLD-removed device.

        Steps:
          1. Look up the Device.clabContainer in Neo4j
          2. Remove the node from the topology YAML
          3. Run `clab deploy --reconfigure` to apply the new (smaller) topology
             — this is how containerlab handles "node removed from topology",
             which destroys the container that's no longer in the spec
          4. Mark the Neo4j Device as RETIRED, write LifecycleEvent
        """
        existing = self._neo4j.get_device(device_id)
        if not existing:
            return RetireResult(
                device_id=device_id, container="",
                success=False, error="device not found in Neo4j",
            )
        container = existing.get("clabContainer", "")

        # Step 1: remove from topology YAML so future deploys don't recreate it
        topo = load_topology(self._repo_path)
        node_name = container.replace("clab-ibnlab-switches-", "")
        removed = remove_node(topo, node_name)
        if not removed:
            self._log.info(
                "Provisioner.retire: node %s not in topology — already removed",
                node_name,
            )
        save_topology(self._repo_path, topo)
        shutil.copy(self._repo_path, self._work_path)

        # Step 2: tear down the container directly. clab deploy --reconfigure
        # does NOT auto-prune nodes that have been removed from the topology
        # YAML — it only deploys what's currently in the file. So we have
        # to docker rm -f the orphan ourselves. This is simpler, faster,
        # and doesn't disrupt the other containers in the same lab.
        if self._container_exists(container):
            try:
                self._docker_rm_force(container)
            except subprocess.CalledProcessError as exc:
                return RetireResult(
                    device_id=device_id, container=container,
                    success=False,
                    error=(
                        f"docker rm -f failed (rc={exc.returncode}): "
                        f"{(exc.stderr or b'').decode(errors='replace')[:400]}"
                    ),
                )

        # Step 4: mark Neo4j retired + write event
        self._safe_lifecycle_update(device_id, DeviceLifecycleState.RETIRED.value)
        event = LifecycleEvent(
            eventId   = f"EVT-RTRD-{uuid.uuid4().hex[:8].upper()}",
            deviceId  = device_id,
            eventType = "RETIRED",
            fromState = existing.get("lifecycleState"),
            toState   = DeviceLifecycleState.RETIRED.value,
            payload   = f"container={container} (removed from topology)",
        )
        self._safe_create_event(event)

        self._note(
            deploy_space,
            f"Provisioner: {device_id} → container {container} retired",
            "retire-result",
        )

        return RetireResult(
            device_id=device_id, container=container, success=True,
        )

    # ------------------------------------------------------------------
    # Topology helpers
    # ------------------------------------------------------------------

    def _add_node_to_topology(self, device_entry) -> None:
        """Mutate the topology YAML to include the new node, then mirror to /tmp."""
        topo = load_topology(self._repo_path)
        node_name = device_entry.clab_container.replace("clab-ibnlab-switches-", "")
        if has_node(topo, node_name):
            self._log.info("Provisioner: node %s already in topology", node_name)
        else:
            add_node(
                topo, node_name,
                vendor=device_entry.vendor,
                platform=device_entry.platform,
                mgmt_ipv4=device_entry.mgmt_ipv4 or next_free_mgmt_ip(topo),
            )
            save_topology(self._repo_path, topo)
        shutil.copy(self._repo_path, self._work_path)

    # ------------------------------------------------------------------
    # Containerlab CLI shell-out
    # ------------------------------------------------------------------

    def _clab_deploy(self) -> None:
        """Run `containerlab deploy --reconfigure` from the work path."""
        cmd = []
        if self._sudo:
            cmd.append("sudo")
            cmd.append("-n")  # non-interactive — fail fast if no passwordless sudo
        cmd += [self._clab, "deploy", "-t", str(self._work_path), "--reconfigure"]
        self._log.info("Provisioner: %s", " ".join(cmd))
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=300,
        )

    def _docker_rm_force(self, container: str) -> None:
        cmd = ["sudo", "-n", "docker", "rm", "-f", container] if self._sudo else \
              ["docker", "rm", "-f", container]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)

    # ------------------------------------------------------------------
    # Container probes
    # ------------------------------------------------------------------

    def _container_exists(self, container: str) -> bool:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                timeout=10,
            )
            return container in out.decode().splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _container_running(self, container: str) -> bool:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--format", "{{.Names}}"],
                timeout=10,
            )
            return container in out.decode().splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _wait_for_container(self, container: str, timeout: int = 120) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._container_running(container):
                return True
            time.sleep(2)
        return False

    # ------------------------------------------------------------------
    # Failure helper
    # ------------------------------------------------------------------

    def _provision_failure(
        self,
        device_id: str,
        container: str,
        error: str,
        start_mono: float,
        deploy_space: str,
    ) -> ProvisionResult:
        # Write a failure LifecycleEvent so the audit trail is complete
        event = LifecycleEvent(
            eventId      = f"EVT-PFAIL-{uuid.uuid4().hex[:8].upper()}",
            deviceId     = device_id,
            eventType    = "PROVISION_FAILED",
            fromState    = DeviceLifecycleState.PLANNED.value,
            toState      = DeviceLifecycleState.PLANNED.value,
            errorMessage = error,
        )
        try:
            self._neo4j.create_lifecycle_event(event)
        except Exception as exc:
            self._log.warning("create_lifecycle_event failed: %s", exc)
        self._note(
            deploy_space,
            f"Provisioner FAILED for {device_id}: {error}",
            "provision-failure",
        )
        return ProvisionResult(
            device_id   = device_id,
            container   = container,
            success     = False,
            state       = DeviceLifecycleState.PLANNED.value,
            error       = error,
            duration_ms = int((time.monotonic() - start_mono) * 1000),
        )

    def _note(self, space: str, content: str, category: str) -> None:
        try:
            self._lm.live_note(space=space, content=content, category=category)
        except Exception as exc:
            self._log.warning("live_note failed: %s", exc)

    # ------------------------------------------------------------------
    # Resilient Neo4j writes (the bolt connection can go idle during a
    # multi-minute clab deploy; retry once on transient errors).
    # ------------------------------------------------------------------

    def _safe_lifecycle_update(self, device_id: str, new_state: str) -> None:
        for attempt in (1, 2):
            try:
                self._neo4j.update_device_lifecycle(device_id, new_state)
                return
            except Exception as exc:
                self._log.warning(
                    "update_device_lifecycle attempt %d failed: %s", attempt, exc
                )
                if attempt == 2:
                    return
                time.sleep(0.5)

    def _safe_create_event(self, event: LifecycleEvent) -> None:
        for attempt in (1, 2):
            try:
                self._neo4j.create_lifecycle_event(event)
                return
            except Exception as exc:
                self._log.warning(
                    "create_lifecycle_event attempt %d failed: %s", attempt, exc
                )
                if attempt == 2:
                    return
                time.sleep(0.5)
