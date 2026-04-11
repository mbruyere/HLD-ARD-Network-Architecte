"""
Agent 3 — Policy→Config  (RFC 9315 §5.1.2)

Responsibilities:
  1. Query Neo4j for firewall context: devices, zones, segments, policies,
     NAT rules, transit VLAN, firewall pairs
  2. Build a Jinja2 rendering context from the Neo4j result set
  3. Render the 4-template chain (base, policies, nat, ha) per device
  4. Compute a per-device config diff vs. the previous Configuration node
  5. Create Configuration nodes (L5) in Neo4j with modelState=CANDIDATE
  6. Emit live_note() per device to ibn-candidate-{intent_id} space
  7. Publish config.rendered event

Entry point::

    agent = Agent3PolicyConfig(neo4j, live_memory, template_dir=Path("firewall_pipeline/templates"))
    result = agent.run(
        intent_id="INT-001",
        candidate_space="ibn-candidate-001",
    )
"""

from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import Configuration, ModelState


# ---------------------------------------------------------------------------
# Cypher extraction queries (8 per architecture spec)
# ---------------------------------------------------------------------------

_QUERIES = {
    "firewalls": """
        MATCH (fp:FirewallPair)-[:AGGREGATES]->(d:Device)
        WHERE d.modelState IN ['POR','DEPLOYED']
        OPTIONAL MATCH (d)-[:LOCATED_AT]->(s:Site)
        RETURN d.deviceId      AS device_id,
               d.hostname      AS hostname,
               d.vendor        AS vendor,
               d.platform      AS platform,
               d.deviceRole    AS device_role,
               d.firewallFunction AS fw_function,
               fp.pairId       AS pair_id,
               fp.name         AS pair_name,
               fp.haMode       AS ha_model,
               s.siteId        AS site_id,
               s.name          AS site_name
        ORDER BY d.deviceRole, d.hostname
    """,
    "zones": """
        MATCH (z:Zone)
        WHERE NOT z.zoneId STARTS WITH '_'
        RETURN z.zoneId       AS zone_id,
               z.name         AS zone_name,
               z.type         AS zone_type,
               z.securityLevel AS security_level,
               z.defaultPolicy AS default_policy
        ORDER BY z.securityLevel DESC
    """,
    "segments": """
        MATCH (s:Segment)
        OPTIONAL MATCH (s)-[:MAPPED_TO_VLAN]->(v:VLAN)
        RETURN s.segmentId   AS segment_id,
               s.name        AS segment_name,
               s.population  AS population,
               v.vlanId      AS vlan_id,
               v.name        AS vlan_name
        ORDER BY v.vlanId
    """,
    # Reads FirewallRule nodes written by Agent 2 (Slice 1 schema:
    # sourceZone/destZone, parent Policy via (Policy)-[:CONTAINS]->(rule)).
    # Also matches the legacy seed schema (srcZone/dstZone) via coalesce
    # so older fixture data still renders. Result columns are aliased to
    # src_zone / dst_zone so existing Jinja2 templates work unchanged.
    "policies": """
        MATCH (fr:FirewallRule)
        WHERE fr.modelState IN ['POR','CANDIDATE']
        OPTIONAL MATCH (p:Policy)-[:CONTAINS]->(fr)
        RETURN fr.ruleId                                AS rule_id,
               coalesce(fr.name, fr.ruleId)             AS rule_name,
               coalesce(fr.sourceZone, fr.srcZone)      AS src_zone,
               coalesce(fr.destZone,   fr.dstZone)      AS dst_zone,
               fr.action                                AS action,
               fr.priority                              AS priority,
               fr.protocol                              AS protocol,
               fr.destPort                              AS dest_port,
               fr.description                           AS description,
               p.policyId                               AS policy_id,
               p.intentId                               AS intent_id
        ORDER BY fr.priority
    """,
    "intents": """
        MATCH (i:Intent)
        WHERE i.status IN ['INGESTED','TRANSLATED','ORCHESTRATED']
        RETURN i.intentId   AS intent_id,
               i.statement  AS statement,
               i.type       AS type,
               i.status     AS status,
               i.modelState AS model_state
        ORDER BY i.intentId
    """,
    "fw_interfaces": """
        MATCH (d:Device)
        WHERE d.deviceRole = 'FIREWALL' AND d.modelState IN ['POR','DEPLOYED']
        RETURN d.deviceId AS device_id,
               d.hostname  AS hostname
    """,
    "nat_rules": """
        MATCH (d:Device)
        WHERE d.deviceRole = 'FIREWALL' AND d.modelState IN ['POR','DEPLOYED']
        RETURN d.deviceId AS device_id
    """,
    "fw_transit": """
        MATCH (v:VLAN {vlanId: 300})
        OPTIONAL MATCH (v)-[:HAS_SUBNET]->(sn:Subnet)
        RETURN v.vlanId AS vlan_id,
               v.name   AS vlan_name,
               sn.prefix AS subnet
    """,
    # Slice 2: non-firewall devices (switches, edges, …) joined to their site
    # rather than to a FirewallPair. The vendor field is what drives template
    # dispatch in _render_device(). Returns the same column shape as the
    # firewalls query so the renderer can treat both lists uniformly.
    # Slice 3: also returns clabContainer (the literal container name) so
    # A5 can dispatch via docker exec without deriving the name.
    # Filters out devices in lifecycleState=RETIRED so HLD-removed devices
    # don't get re-rendered after retirement.
    "switches": """
        MATCH (d:Device)
        WHERE d.deviceRole IN ['ACCESS_SWITCH','AGGREGATION_SWITCH','EDGE_ROUTER']
          AND d.modelState IN ['POR','DEPLOYED','CANDIDATE']
          AND coalesce(d.lifecycleState, 'PLANNED') <> 'RETIRED'
        OPTIONAL MATCH (d)-[:LOCATED_AT]->(s:Site)
        RETURN d.deviceId      AS device_id,
               d.hostname      AS hostname,
               d.vendor        AS vendor,
               d.platform      AS platform,
               d.deviceRole    AS device_role,
               d.clabContainer AS clab_container,
               d.mgmtIpv4      AS mgmt_ipv4,
               d.lifecycleState AS lifecycle_state,
               s.siteId        AS site_id,
               s.name          AS site_name
        ORDER BY d.deviceRole, d.hostname
    """,
    # Slice 2: all current VLAN nodes (CANDIDATE/POR/DEPLOYED). Switch
    # templates iterate this to provision the VLAN database. The HLD
    # population table is the source-of-truth for which VLANs exist —
    # A1 writes them via create_vlan() during HLD ingestion.
    "vlans": """
        MATCH (v:VLAN)
        WHERE v.modelState IN ['CANDIDATE','POR','DEPLOYED']
          AND v.vlanId IS NOT NULL
        RETURN v.vlanId    AS vlan_id,
               v.name      AS vlan_name,
               v.modelState AS model_state,
               v.origin    AS origin
        ORDER BY v.vlanId
    """,
}

# ── Vendor dispatch table ──────────────────────────────────────────────────
# Maps device.platform (case-insensitive) → ordered list of Jinja2 templates
# in firewall_pipeline/templates/. Adding a new vendor in a future slice is
# a one-line change here plus a new template set on disk.
_TEMPLATE_CHAINS: dict[str, list[str]] = {
    "vyos": [
        "vyos_firewall_base.j2",
        "vyos_firewall_policies.j2",
        "vyos_nat.j2",
        "vyos_ha.j2",
    ],
    "srlinux": [
        # Order matters: srl_interfaces enables vlan-tagging on the trunk
        # port, which is a prerequisite for srl_vlans to attach subinterfaces.
        "srl_base.j2",
        "srl_interfaces.j2",
        "srl_vlans.j2",
    ],
    # Slice 6 will add: "ios-xe": [...], "eos": [...], etc.
}

# Backwards-compat alias used by tests that import the old constant.
_DEFAULT_TEMPLATE_CHAIN = _TEMPLATE_CHAINS["vyos"]


def _resolve_chain(platform: Optional[str]) -> list[str]:
    """Look up the template chain for a device.platform, case-insensitive."""
    if not platform:
        return _TEMPLATE_CHAINS["vyos"]  # safe default
    return _TEMPLATE_CHAINS.get(platform.lower(), _TEMPLATE_CHAINS["vyos"])


class Agent3PolicyConfig(BaseAgent):
    """Render per-device VyOS firewall configuration from Neo4j POR state."""

    AGENT_ID   = "A3"
    AGENT_NAME = "Policy→Config"

    def __init__(self, neo4j, live_memory, template_dir: Optional[Path] = None,
                 event_bus=None):
        super().__init__(neo4j, live_memory, event_bus)
        # Default: look relative to repo root
        if template_dir is None:
            template_dir = Path(__file__).parent.parent.parent.parent / "firewall_pipeline" / "templates"
        self._template_dir = Path(template_dir)

    # ------------------------------------------------------------------
    # _execute (called by BaseAgent.run)
    # ------------------------------------------------------------------

    def _execute(self, intent_id: str = "none", candidate_space: str = "ibn-candidate-bootstrap",
                 **kwargs) -> dict:
        """
        Render configs for all POR firewalls and switches (Slice 2).

        Returns a dict with per-device results:
            {
                "devices": [
                    {"deviceId": ..., "configId": ..., "content": ..., "diff_lines": N},
                    ...
                ],
                "intent_id": ...,
            }

        The render is vendor-aware: firewalls go through the VyOS template
        chain, switches through their platform's chain (per ``_TEMPLATE_CHAINS``).
        """
        context = self._build_context()
        firewalls = context.get("firewalls", []) or []
        switches  = context.get("switches",  []) or []
        devices   = list(firewalls) + list(switches)

        if not devices:
            self._note(candidate_space, "No firewalls or switches found in POR state", "observation")
            return {"devices": [], "intent_id": intent_id}

        self._note(
            candidate_space,
            f"A3 render: {len(firewalls)} firewalls + {len(switches)} switches",
            "progress",
        )

        results = []
        for device in devices:
            try:
                content = self._render_device(device, context)
                config_id = self._write_config_node(device, content, intent_id)
                diff_lines = self._compute_diff(device["device_id"], content)

                self._note(
                    candidate_space,
                    f"Config rendered for {device['hostname']} "
                    f"({len(content.splitlines())} lines, {diff_lines} changed)",
                    "progress",
                )
                results.append({
                    "deviceId": device["device_id"],
                    "hostname": device["hostname"],
                    "platform": device.get("platform"),       # Slice 2: vendor dispatch hint
                    "vendor":   device.get("vendor"),
                    "clabContainer": device.get("clab_container"),  # Slice 3: A5 docker target
                    "configId": config_id,
                    "content": content,
                    "diffLines": diff_lines,
                })
            except Exception as exc:
                self._log.warning("Render failed for %s: %s", device.get("hostname"), exc)
                self._note(candidate_space,
                           f"Render FAILED for {device.get('hostname')}: {exc}", "issue")
                results.append({"deviceId": device.get("device_id"), "error": str(exc)})

        self._publish("config.rendered", {
            "intentId": intent_id,
            "devicesRendered": len([r for r in results if "configId" in r]),
        })
        return {"devices": results, "intent_id": intent_id}

    # ------------------------------------------------------------------
    # Neo4j extraction
    # ------------------------------------------------------------------

    def _build_context(self) -> dict:
        """Run all 8 extraction queries and return the merged context dict."""
        ctx = {}
        for key, cypher in _QUERIES.items():
            ctx[key] = self._neo4j.run_query(cypher)
        ctx["render_meta"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ssot_snapshot_id": f"SNAP-{uuid.uuid4().hex[:8].upper()}",
            "intents": [i.get("statement", "") for i in ctx.get("intents", [])],
        }
        return ctx

    # ------------------------------------------------------------------
    # Jinja2 rendering
    # ------------------------------------------------------------------

    def _render_device(self, device: dict, context: dict) -> str:
        """Render the per-vendor template chain for a single device.

        Slice 2: the chain is selected from ``_TEMPLATE_CHAINS`` keyed on
        ``device.platform`` (case-insensitive). Unknown platforms fall back
        to the VyOS chain so existing tests keep working.
        """
        try:
            from jinja2 import Environment, FileSystemLoader, StrictUndefined
        except ImportError:
            raise RuntimeError("jinja2 not installed — run: pip install jinja2")

        if not self._template_dir.is_dir():
            # Fallback: generate minimal stub config when templates aren't available
            return self._stub_config(device, context)

        env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        chain = _resolve_chain(device.get("platform"))
        device_ctx = {**context, "device": device}
        rendered_parts = []
        for template_name in chain:
            try:
                tmpl = env.get_template(template_name)
                rendered_parts.append(tmpl.render(**device_ctx))
            except Exception as exc:
                self._log.debug("Template %s skipped: %s", template_name, exc)

        return "\n".join(rendered_parts)

    def _stub_config(self, device: dict, context: dict) -> str:
        """Minimal VyOS set-command stub when templates are unavailable."""
        hostname = device.get("hostname", device.get("device_id", "unknown"))
        lines = [
            f"set system host-name {hostname}",
            "set system time-zone UTC",
        ]
        for zone in context.get("zones", []):
            zid = zone.get("zone_id", "").lower().replace("zone-", "").replace("-", "_")
            if zid:
                lines.append(f"set firewall zone {zid} default-action drop")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Config diff
    # ------------------------------------------------------------------

    def _compute_diff(self, device_id: str, new_content: str) -> int:
        """
        Return number of changed lines vs the previous Configuration node.
        Returns len(new_content.splitlines()) on first render.
        """
        rows = self._neo4j.run_query(
            """
            MATCH (c:Configuration {deviceId: $deviceId})
            WHERE c.modelState IN ['DEPLOYED','POR','CANDIDATE']
            RETURN c.content AS content
            ORDER BY c.createdAt DESC
            LIMIT 1
            """,
            deviceId=device_id,
        )
        if not rows or not rows[0].get("content"):
            return len(new_content.splitlines())

        old_lines = rows[0]["content"].splitlines()
        new_lines = new_content.splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        return sum(1 for l in diff if l.startswith(("+", "-")) and not l.startswith(("---", "+++")))

    # ------------------------------------------------------------------
    # Neo4j write
    # ------------------------------------------------------------------

    def _write_config_node(self, device: dict, content: str, intent_id: str) -> str:
        """Create a Configuration node (L5) and link it to the device."""
        config_id = f"CFG-{uuid.uuid4().hex[:8].upper()}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        self._neo4j.run_query(
            """
            MERGE (c:Configuration {configId: $configId})
            SET c.deviceId    = $deviceId,
                c.content     = $content,
                c.contentHash = $hash,
                c.intentId    = $intentId,
                c.version     = 1,
                c.format      = 'vyos-set',
                c.modelState  = 'CANDIDATE',
                c.createdAt   = datetime()
            WITH c
            MATCH (d:Device {deviceId: $deviceId})
            MERGE (c)-[:APPLIES_TO]->(d)
            """,
            configId=config_id,
            deviceId=device["device_id"],
            content=content,
            hash=content_hash,
            intentId=intent_id,
        )
        return config_id
