"""
NetLab Topology Generator — Agent 5 helper

Generates a netlab.tools-compatible ``topology.yml`` from Neo4j POR state.

The generator queries Neo4j for:
- Sites (L1) with modelState=POR
- Devices (L1) with their platform, role, and site membership
- VLANs (L1) and their site assignments
- Links (L1 PhysicalLinks) between devices

Output is a YAML dict that can be saved directly as a netlab topology file.

Usage::

    from ibn.agents.netlab_topology import NetLabTopologyGenerator
    from ibn.core.neo4j_client import Neo4jClient

    client = Neo4jClient.from_env()
    gen = NetLabTopologyGenerator(client)
    topo = gen.generate(site_id="site-hq")
    gen.save(topo, "topology_site_hq.yml")
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional

from ibn.core.neo4j_client import Neo4jClient


# NetLab device type mapping — IBN platform → netlab device keyword
PLATFORM_MAP = {
    "vyos":   "vyos",
    "eos":    "eos",
    "iosxe":  "csr",
    "iosxr":  "xrd",
    "nxos":   "nxos",
    "linux":  "linux",
}

# NetLab device role → image defaults (informational — netlab resolves images)
ROLE_GROUP_MAP = {
    "FIREWALL":   "firewalls",
    "SWITCH":     "switches",
    "ROUTER":     "routers",
    "ACCESS":     "access",
    "AGGREGATION":"aggregation",
    "EDGE":       "edge",
}


class NetLabTopologyGenerator:
    """Generates netlab topology YAML from Neo4j POR state."""

    def __init__(self, neo4j: Neo4jClient):
        self._neo4j = neo4j

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, site_id: str, provider: str = "clab") -> dict:
        """
        Build the full topology dict for a given site.

        Args:
            site_id: The Neo4j siteId (e.g. "site-hq").
            provider: NetLab provider — "clab" (containerlab) or "libvirt".

        Returns:
            Dict matching netlab topology YAML schema.
        """
        devices = self._fetch_devices(site_id)
        vlans = self._fetch_vlans(site_id)
        links = self._fetch_links(site_id)

        topo = {
            "provider": provider,
            "defaults": {
                "device": "eos",
                "pool": "campus_pool",
            },
            "addressing": self._addressing_block(),
            "groups": self._build_groups(devices),
            "nodes": self._build_nodes(devices),
            "vlans": self._build_vlans(vlans),
            "links": self._build_links(links, devices),
        }
        return topo

    def save(self, topology: dict, path: str | Path) -> Path:
        """Write the topology dict to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            yaml.dump(topology, f, default_flow_style=False, sort_keys=False)
        return p

    # ------------------------------------------------------------------
    # Neo4j queries
    # ------------------------------------------------------------------

    def _fetch_devices(self, site_id: str) -> list[dict]:
        """Return all POR devices for a site."""
        rows = self._neo4j.run_query(
            """
            MATCH (s:Site {siteId: $siteId})-[:CONTAINS]->(d:Device)
            WHERE d.modelState IN ['POR', 'DEPLOYED']
            RETURN d.deviceId   AS deviceId,
                   d.hostname   AS hostname,
                   d.platform   AS platform,
                   d.deviceRole AS role,
                   d.siteId     AS siteId
            ORDER BY d.deviceRole, d.hostname
            """,
            siteId=site_id,
        )
        return rows

    def _fetch_vlans(self, site_id: str) -> list[dict]:
        """Return all POR VLANs for a site (via CONTAINS relationship)."""
        rows = self._neo4j.run_query(
            """
            MATCH (s:Site {siteId: $siteId})-[:CONTAINS]->(v:VLAN)
            WHERE v.modelState IN ['POR', 'DEPLOYED', 'AS_BUILT']
            RETURN v.vlanId   AS vlanId,
                   v.name     AS name,
                   v.category AS category
            ORDER BY v.vlanId
            """,
            siteId=site_id,
        )
        # Fallback: if fewer than 5 VLANs found via site relationship,
        # supplement with all POR VLANs (handles incomplete CONTAINS edges)
        if len(rows) < 5:
            extra = self._neo4j.run_query(
                """
                MATCH (v:VLAN)
                WHERE v.modelState IN ['POR', 'DEPLOYED', 'AS_BUILT']
                RETURN v.vlanId   AS vlanId,
                       v.name     AS name,
                       v.category AS category
                ORDER BY v.vlanId
                """
            )
            # Merge, deduplicating by vlanId
            existing_ids = {r["vlanId"] for r in rows}
            rows = rows + [r for r in extra if r["vlanId"] not in existing_ids]
        return rows

    def _fetch_links(self, site_id: str) -> list[dict]:
        """Return all physical links between devices in the site."""
        rows = self._neo4j.run_query(
            """
            MATCH (a:Device)-[l:PHYSICALLY_CONNECTED_TO]->(b:Device)
            WHERE a.siteId = $siteId AND b.siteId = $siteId
              AND a.modelState IN ['POR', 'DEPLOYED']
              AND b.modelState IN ['POR', 'DEPLOYED']
            RETURN a.hostname        AS srcDevice,
                   l.srcInterface   AS srcIf,
                   b.hostname        AS dstDevice,
                   l.dstInterface   AS dstIf,
                   l.linkType       AS linkType
            """,
            siteId=site_id,
        )
        return rows

    # ------------------------------------------------------------------
    # Topology builders
    # ------------------------------------------------------------------

    @staticmethod
    def _addressing_block() -> dict:
        return {
            "mgmt":        {"ipv4": "192.168.100.0/24", "prefix": 24},
            "loopback":    {"ipv4": "10.255.0.0/24",   "prefix": 32},
            "campus_pool": {"ipv4": "10.100.0.0/16",   "prefix": 24},
            "dmz_pool":    {"ipv4": "10.200.0.0/16",   "prefix": 24},
            "p2p":         {"ipv4": "10.255.255.0/24", "prefix": 30},
        }

    @staticmethod
    def _build_groups(devices: list[dict]) -> dict:
        groups: dict[str, dict] = {}
        for d in devices:
            role = (d.get("role") or "SWITCH").upper()
            group = ROLE_GROUP_MAP.get(role, "devices")
            groups.setdefault(group, {"members": []})
            hostname = d.get("hostname") or d.get("deviceId", "unknown")
            if hostname not in groups[group]["members"]:
                groups[group]["members"].append(hostname)
        return groups

    @staticmethod
    def _build_nodes(devices: list[dict]) -> dict:
        nodes: dict[str, dict] = {}
        for d in devices:
            hostname = d.get("hostname") or d.get("deviceId", "unknown")
            platform = (d.get("platform") or "eos").lower()
            node: dict = {
                "device": PLATFORM_MAP.get(platform, platform),
            }
            nodes[hostname] = node
        return nodes

    @staticmethod
    def _build_vlans(vlans: list[dict]) -> dict:
        result: dict[str, dict] = {}
        for v in vlans:
            name = (v.get("name") or f"vlan{v.get('vlanId', 0)}").replace(" ", "-").lower()
            entry: dict = {"id": v.get("vlanId")}
            if v.get("subnet"):
                entry["prefix"] = v["subnet"]
            result[name] = entry
        return result

    @staticmethod
    def _build_links(links: list[dict], devices: list[dict]) -> list[dict]:
        # Build set of known hostnames to validate endpoints
        known = {d.get("hostname") or d.get("deviceId") for d in devices}
        result: list[dict] = []
        seen: set[frozenset] = set()

        for lnk in links:
            src = lnk.get("srcDevice")
            dst = lnk.get("dstDevice")
            if not src or not dst:
                continue
            # Deduplicate bidirectional links
            key = frozenset([src, dst])
            if key in seen:
                continue
            seen.add(key)

            endpoints: list = []
            if lnk.get("srcIf"):
                endpoints.append(f"{src}:{lnk['srcIf']}")
            else:
                endpoints.append(src)
            if lnk.get("dstIf"):
                endpoints.append(f"{dst}:{lnk['dstIf']}")
            else:
                endpoints.append(dst)

            entry: dict = {"endpoints": endpoints}
            if lnk.get("linkType"):
                entry["type"] = lnk["linkType"].lower()
            result.append(entry)

        return result
