"""
Containerlab topology YAML mutation helpers — Slice 3.

Pure functions that read, modify, and write a containerlab topology
file. The HLD-driven Provisioner uses these to add or remove nodes
on the fly when the operator edits the Device Inventory Table.

Comment preservation
--------------------
We use stdlib PyYAML which round-trips structure but **drops comments**.
That's acceptable for ``clab-ibnlab-switches.yml`` which is operator-
maintained. If a future slice needs comment-preserving edits we can
swap to ``ruamel.yaml`` — the public API of this module is designed to
allow that swap without changing callers.

Default kind/image map
----------------------
Maps a (vendor, platform) tuple to the right containerlab ``kind:`` and
``image:`` fields. This is the same dispatch the Slice 2 vendor table
uses for rendering, just on the lab-infra side. Adding a vendor in a
later slice is a one-line change here plus a corresponding entry in
A3's ``_TEMPLATE_CHAINS`` and A5's ``_VENDOR_EXECUTORS``.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


# ---------------------------------------------------------------------------
# Vendor → containerlab kind/image dispatch
# ---------------------------------------------------------------------------

# Each entry: (vendor.lower(), platform.lower()) → {kind, image, type?}
# Slice 3 ships only the SR Linux row; Slice 6 will add Cisco / Arista / FRR.
_KIND_MAP: dict[tuple[str, str], dict] = {
    ("nokia", "srlinux"): {
        "kind": "nokia_srlinux",
        "image": "ghcr.io/nokia/srlinux:latest",
        "type": "ixrd2l",
    },
    ("vyos", "vyos"): {
        "kind": "linux",
        "image": "ghcr.io/sysoleg/vyos-container:latest",
    },
    # Slice 5 — FRRouting for edge routers. Built locally because Docker
    # Hub's frrouting/frr image is amd64-only; see infra/frr-image/Dockerfile.
    # Must run privileged for the netlink socket used by zebra.
    ("frr", "frr"): {
        "kind": "linux",
        "image": "ibn-frr:local",
    },
}


class UnsupportedPlatformError(ValueError):
    """Raised when (vendor, platform) has no clab kind/image mapping yet."""


def kind_image_for(vendor: str, platform: str) -> dict:
    """Look up the containerlab kind/image for a vendor+platform pair.

    Raises UnsupportedPlatformError if the pair isn't in ``_KIND_MAP``.
    Future slices add rows; the rest of the pipeline is platform-agnostic
    so growing this table is the only place a new vendor needs touching
    on the lab-infra side.
    """
    key = (vendor.lower(), platform.lower())
    if key not in _KIND_MAP:
        raise UnsupportedPlatformError(
            f"No clab kind/image mapping for vendor={vendor!r} platform={platform!r}. "
            f"Add an entry to ibn.core.clab_yaml._KIND_MAP."
        )
    return dict(_KIND_MAP[key])


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def load_topology(path: str | Path) -> dict:
    """Load a containerlab topology YAML into a Python dict.

    Returns an empty topology shell if the file is missing — the caller
    can immediately call ``add_node()`` and ``save_topology()`` to
    bootstrap a new lab.
    """
    p = Path(path)
    if not p.exists():
        return {
            "name":  p.stem,
            "prefix": "clab",
            "mgmt": {
                "network": "netlab_mgmt",
                "ipv4-subnet": "192.168.100.0/24",
            },
            "topology": {"nodes": {}},
        }
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("topology", {}).setdefault("nodes", {})
    return data


def save_topology(path: str | Path, data: dict) -> None:
    """Write a topology dict back to YAML, preserving structural ordering."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# Node mutation
# ---------------------------------------------------------------------------

def add_node(
    topology: dict,
    node_name: str,
    vendor: str,
    platform: str,
    mgmt_ipv4: Optional[str] = None,
) -> dict:
    """Add (or update) a node in a containerlab topology dict.

    Idempotent: re-adding a node with the same parameters produces an
    identical YAML on the next save. Returns the node dict that was
    actually written.
    """
    nodes = topology.setdefault("topology", {}).setdefault("nodes", {})
    spec = kind_image_for(vendor, platform)
    if mgmt_ipv4:
        spec["mgmt-ipv4"] = mgmt_ipv4
    nodes[node_name] = spec
    return spec


def remove_node(topology: dict, node_name: str) -> bool:
    """Remove a node from the topology. Returns True if anything was removed."""
    nodes = topology.get("topology", {}).get("nodes", {})
    if node_name not in nodes:
        return False
    del nodes[node_name]
    return True


def list_nodes(topology: dict) -> list[str]:
    """Return all node names currently in the topology."""
    return list(topology.get("topology", {}).get("nodes", {}).keys())


def has_node(topology: dict, node_name: str) -> bool:
    return node_name in topology.get("topology", {}).get("nodes", {})


# ---------------------------------------------------------------------------
# Management IP allocation
# ---------------------------------------------------------------------------

def used_mgmt_ips(topology: dict) -> set[str]:
    """Return the set of mgmt-ipv4 addresses currently in the topology."""
    used = set()
    for spec in topology.get("topology", {}).get("nodes", {}).values():
        if isinstance(spec, dict) and "mgmt-ipv4" in spec:
            used.add(spec["mgmt-ipv4"])
    return used


def next_free_mgmt_ip(
    topology: dict,
    subnet: Optional[str] = None,
    skip: Iterable[str] = (),
) -> str:
    """Allocate the next free management IP from the topology's mgmt subnet.

    The starting offset is 121 (so we don't collide with the firewall
    range 101-110 used by netlab) and we skip the network/broadcast
    addresses plus anything in ``skip`` or already used.
    """
    if subnet is None:
        subnet = topology.get("mgmt", {}).get("ipv4-subnet", "192.168.100.0/24")
    net = ipaddress.IPv4Network(subnet, strict=False)
    used = used_mgmt_ips(topology) | set(skip)
    for host in net.hosts():
        if host.compressed in used:
            continue
        # Reserve the low range (.1-.120) for the netlab firewall lab
        if int(host) - int(net.network_address) < 121:
            continue
        return host.compressed
    raise RuntimeError(f"No free management IP available in {subnet}")
