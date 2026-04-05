#!/usr/bin/env python3
"""
Neo4j SSoT → Jinja2 → VyOS Firewall Configuration Rendering Pipeline
=====================================================================

This script implements the Orchestration Agent's (Agent 5) config rendering
pipeline for firewall devices. It:

  1. Connects to the Neo4j SSoT and executes extraction queries
  2. Builds a structured context (dict) from query results
  3. Renders VyOS configuration through the Jinja2 template chain
  4. Writes per-device config files ready for deployment to NetLab
  5. Records the rendering event back to Neo4j as a DeploymentEvent

Part of the IBN Closed-Loop Architecture.
Reference: RFC 9315 §5.1.3 (Intent Orchestration)

Usage:
    python render_firewall_config.py --neo4j-uri bolt://localhost:7687 \\
                                      --output-dir ./rendered_configs
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from neo4j import GraphDatabase
except ImportError:
    print("ERROR: neo4j driver not installed. Run: pip install neo4j")
    sys.exit(1)

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    print("ERROR: jinja2 not installed. Run: pip install jinja2")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
CYPHER_DIR = SCRIPT_DIR / "cypher"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "rendered_configs"

# Template chain — rendered in order for each device
TEMPLATE_CHAIN = [
    "vyos_firewall_base.j2",
    "vyos_firewall_policies.j2",
    "vyos_nat.j2",
    "vyos_ha.j2",
]

# Cypher query file
CYPHER_FILE = CYPHER_DIR / "extract_firewall_state.cypher"

logger = logging.getLogger("fw-pipeline")


# ---------------------------------------------------------------------------
# Custom Jinja2 Filters
# ---------------------------------------------------------------------------
def ipaddr_prefixlen(cidr: str) -> str:
    """Extract prefix length from CIDR notation. e.g. '10.100.0.0/24' → '24'"""
    if cidr and "/" in str(cidr):
        return str(cidr).split("/")[1]
    return "24"  # default


def truncate_filter(s: str, length: int = 80) -> str:
    """Truncate string to given length."""
    s = str(s)
    if len(s) > length:
        return s[: length - 3] + "..."
    return s


# ---------------------------------------------------------------------------
# Neo4j Query Executor
# ---------------------------------------------------------------------------
class SSoTExtractor:
    """Extracts firewall configuration state from the Neo4j SSoT."""

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Connected to Neo4j at {uri}")

    def close(self):
        self.driver.close()

    def _run_query(self, query: str) -> list[dict]:
        """Execute a single Cypher query and return results as list of dicts."""
        with self.driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def extract_all(self) -> dict[str, Any]:
        """
        Execute all extraction queries and return the full context.

        Parses the multi-query Cypher file, splits on comment headers,
        and executes each query independently.
        """
        queries = self._parse_cypher_file()
        context = {}

        query_map = {
            "QUERY 1": "firewalls",
            "QUERY 2": "zones",
            "QUERY 3": "segments",
            "QUERY 4": "policies",
            "QUERY 5": "intents",
            "QUERY 6": "fw_interfaces",
            "QUERY 7": "nat_rules",
            "QUERY 8": "fw_transit",
        }

        for label, query_text in queries.items():
            var_name = None
            for key, name in query_map.items():
                if key in label:
                    var_name = name
                    break

            if var_name:
                logger.info(f"Executing {label} → {var_name}")
                results = self._run_query(query_text)
                # QUERY 8 (fw_transit) returns a single row
                if var_name == "fw_transit" and results:
                    context[var_name] = results[0]
                else:
                    context[var_name] = results
                logger.info(f"  → {len(results)} record(s)")

        return context

    def _parse_cypher_file(self) -> dict[str, str]:
        """Parse the multi-query Cypher file into individual queries."""
        cypher_text = CYPHER_FILE.read_text()
        queries = {}
        current_label = None
        current_lines = []

        for line in cypher_text.splitlines():
            # Detect query header comments
            if line.startswith("// QUERY"):
                if current_label and current_lines:
                    queries[current_label] = "\n".join(current_lines).strip()
                current_label = line.lstrip("/ ").strip()
                current_lines = []
            elif current_label is not None:
                # Skip comment lines within a query section
                if line.startswith("// ---") or line.startswith("// Returns:") or line.startswith("// Template"):
                    continue
                if not line.startswith("//"):
                    current_lines.append(line)

        # Last query
        if current_label and current_lines:
            queries[current_label] = "\n".join(current_lines).strip()

        return queries

    def record_rendering_event(
        self, device_id: str, config_hash: str, snapshot_id: str
    ):
        """Write a DeploymentEvent node back to the SSoT for audit."""
        query = """
        MERGE (de:DeploymentEvent {eventId: $event_id})
        SET de.timestamp    = datetime(),
            de.status       = 'RENDERED',
            de.configHash   = $config_hash,
            de.snapshotId   = $snapshot_id,
            de.renderedBy   = 'OrchestrationAgent'
        WITH de
        MATCH (d:Device {deviceId: $device_id})
        MERGE (de)-[:TARGETS]->(d)
        """
        event_id = f"DEPLOY-{device_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        with self.driver.session() as session:
            session.run(
                query,
                event_id=event_id,
                device_id=device_id,
                config_hash=config_hash,
                snapshot_id=snapshot_id,
            )
        logger.info(f"Recorded DeploymentEvent {event_id} for {device_id}")


# ---------------------------------------------------------------------------
# Jinja2 Renderer
# ---------------------------------------------------------------------------
class ConfigRenderer:
    """Renders VyOS configuration from Jinja2 templates with SSoT context."""

    def __init__(self, template_dir: Path = TEMPLATE_DIR):
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        # Register custom filters
        self.env.filters["ipaddr_prefixlen"] = ipaddr_prefixlen
        self.env.filters["truncate"] = truncate_filter

    def render_device(
        self, device: dict, context: dict, template_chain: list[str]
    ) -> str:
        """
        Render the full configuration for a single firewall device.

        Concatenates output from each template in the chain.
        """
        render_meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ssot_snapshot_id": f"SNAP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "intents": context.get("intents", []),
            "syslog_server": "192.168.100.10",
        }

        # Build per-device context
        device_context = {
            "device": device,
            "render_meta": render_meta,
            **context,
        }

        config_parts = []
        for template_name in template_chain:
            try:
                template = self.env.get_template(template_name)
                rendered = template.render(**device_context)
                config_parts.append(rendered)
            except Exception as e:
                logger.error(
                    f"Error rendering {template_name} for {device['hostname']}: {e}"
                )
                config_parts.append(
                    f"! ERROR: Failed to render {template_name}: {e}"
                )

        return "\n\n".join(config_parts)


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------
class FirewallPipeline:
    """
    Full pipeline: Neo4j SSoT → Jinja2 Rendering → Config Files.

    This is invoked by the Orchestration Agent (Agent 5) when:
      - A new Configuration node appears in Neo4j (status = READY)
      - The Compliance Action Agent triggers re-orchestration
      - A manual rendering is requested
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        output_dir: Path,
    ):
        self.extractor = SSoTExtractor(neo4j_uri, neo4j_user, neo4j_password)
        self.renderer = ConfigRenderer()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Path]:
        """
        Execute the full rendering pipeline.

        Returns list of rendered config file paths.
        """
        logger.info("=" * 70)
        logger.info("Firewall Configuration Rendering Pipeline — START")
        logger.info("=" * 70)

        # Step 1: Extract state from Neo4j SSoT
        logger.info("Step 1: Extracting firewall state from Neo4j SSoT...")
        context = self.extractor.extract_all()

        firewalls = context.get("firewalls", [])
        if not firewalls:
            logger.warning("No active firewall devices found in SSoT. Aborting.")
            return []

        logger.info(f"Found {len(firewalls)} firewall device(s)")

        # Step 2: Enrich device context with interface mappings
        logger.info("Step 2: Enriching device context...")
        devices = self._enrich_devices(firewalls, context)

        # Step 3: Render configuration for each device
        logger.info("Step 3: Rendering configurations...")
        output_files = []

        for device in devices:
            hostname = device["hostname"]
            logger.info(f"  Rendering {hostname} ({device['device_role']})...")

            config_text = self.renderer.render_device(
                device, context, TEMPLATE_CHAIN
            )

            # Write config file
            config_path = self.output_dir / f"{hostname}.conf"
            config_path.write_text(config_text)
            output_files.append(config_path)
            logger.info(f"  → Written: {config_path}")

            # Step 4: Record rendering event in SSoT
            import hashlib

            config_hash = hashlib.sha256(config_text.encode()).hexdigest()[:16]
            try:
                self.extractor.record_rendering_event(
                    device["device_id"],
                    config_hash,
                    f"SNAP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                )
            except Exception as e:
                logger.warning(f"  Could not record deployment event: {e}")

        logger.info("=" * 70)
        logger.info(
            f"Pipeline COMPLETE — {len(output_files)} config(s) rendered"
        )
        logger.info("=" * 70)

        self.extractor.close()
        return output_files

    def _enrich_devices(
        self, firewalls: list[dict], context: dict
    ) -> list[dict]:
        """
        Enrich raw firewall records with additional context needed by templates.

        Adds: uplink_interface, transit_interface, ha_interface, mgmt_interface,
              transit_ip, ha_peer_ip, mgmt_ip mappings.
        """
        enriched = []
        for fw in firewalls:
            device = dict(fw)  # copy

            # Default interface mappings (can be overridden by Neo4j data)
            device.setdefault("uplink_interface", "eth0")
            device.setdefault("transit_interface", "eth1")
            device.setdefault("ha_interface", "eth2")
            device.setdefault("mgmt_interface", "eth3")

            # Transit IP: derive from pair membership
            # USF1 → .1, USF2 → .2 on transit subnet
            if "transit_ip" not in device:
                if device["device_id"].endswith("-01"):
                    device["transit_ip"] = "10.255.254.1"
                else:
                    device["transit_ip"] = "10.255.254.2"

            # HA peer IP: the other member's HA interface address
            if "ha_peer_ip" not in device:
                peer_suffix = "02" if device["device_id"].endswith("-01") else "01"
                peer_id = device["device_id"][:-2] + peer_suffix
                # Find peer in firewalls list
                for other in firewalls:
                    if other["device_id"] == peer_id:
                        device["ha_peer_ip"] = f"10.255.255.{2 if peer_suffix == '02' else 1}"
                        break
                device.setdefault("ha_peer_ip", "10.255.255.2")

            # Internet interface (DMZFW only)
            if device["device_role"] == "DMZ_FW":
                device.setdefault("internet_interface", "eth3")

            enriched.append(device)

        return enriched


# ---------------------------------------------------------------------------
# Standalone / Dry-Run Mode
# ---------------------------------------------------------------------------
def dry_run(output_dir: Path):
    """
    Run the pipeline with mock data (no Neo4j connection required).
    Useful for testing templates and validating output format.
    """
    logger.info("DRY RUN MODE — using mock SSoT data")

    mock_context = {
        "firewalls": [
            {
                "device_id": "DEV-HQ-USF-01",
                "hostname": "fw-hq-usr-01",
                "vendor": "VyOS",
                "model": "VyOS 1.4",
                "device_role": "USER_FW",
                "ha_role": "ACTIVE_ACTIVE_MEMBER",
                "os": "VyOS",
                "os_version": "1.4.0",
                "pair_id": "FWPAIR-HQ-USF",
                "pair_name": "HQ User Services Firewall Pair",
                "pair_function": "USER_SERVICES",
                "ha_model": "ACTIVE_ACTIVE",
                "failover_time": 0,
                "virtual_ip": None,
                "site_id": "SITE-PAR-01",
                "site_name": "Paris HQ Campus",
            },
            {
                "device_id": "DEV-HQ-DMZFW-01",
                "hostname": "fw-hq-dmz-01",
                "vendor": "VyOS",
                "model": "VyOS 1.4",
                "device_role": "DMZ_FW",
                "ha_role": "ACTIVE_ACTIVE_MEMBER",
                "os": "VyOS",
                "os_version": "1.4.0",
                "pair_id": "FWPAIR-HQ-DMZ",
                "pair_name": "HQ DMZ/Internet Firewall Pair",
                "pair_function": "DMZ_INTERNET",
                "ha_model": "ACTIVE_ACTIVE",
                "failover_time": 0,
                "virtual_ip": None,
                "site_id": "SITE-PAR-01",
                "site_name": "Paris HQ Campus",
            },
        ],
        "zones": [
            {"zone_id": "ZONE-USER", "zone_name": "User", "zone_type": "USER", "security_level": 80, "default_policy": "DENY"},
            {"zone_id": "ZONE-GUEST", "zone_name": "Guest", "zone_type": "GUEST", "security_level": 10, "default_policy": "DENY"},
            {"zone_id": "ZONE-IOT", "zone_name": "IoT", "zone_type": "IOT", "security_level": 20, "default_policy": "DENY"},
            {"zone_id": "ZONE-DMZ-INFRA", "zone_name": "DMZ Infrastructure", "zone_type": "DMZ_INFRA", "security_level": 50, "default_policy": "DENY"},
            {"zone_id": "ZONE-DMZ-PUBLISH", "zone_name": "DMZ Publishing", "zone_type": "DMZ_PUBLISH", "security_level": 30, "default_policy": "DENY"},
            {"zone_id": "ZONE-INTERNET", "zone_name": "Internet", "zone_type": "INTERNET", "security_level": 0, "default_policy": "DENY"},
            {"zone_id": "ZONE-MGMT", "zone_name": "Management", "zone_type": "MANAGEMENT", "security_level": 100, "default_policy": "DENY"},
        ],
        "segments": [
            {"segment_id": "SEG-EMP", "segment_name": "Employee", "population": "EMPLOYEE", "qos_dscp": 0, "internet_access": True, "internal_access": True, "vlan_id": 100, "vlan_name": "employee", "subnet_prefix": "10.100.0.0/24", "gateway_ip": "10.100.0.1", "zone_id": "ZONE-USER", "zone_name": "User", "zone_type": "USER"},
            {"segment_id": "SEG-VOICE", "segment_name": "Voice", "population": "VOICE", "qos_dscp": 46, "internet_access": False, "internal_access": True, "vlan_id": 110, "vlan_name": "voice", "subnet_prefix": "10.100.10.0/24", "gateway_ip": "10.100.10.1", "zone_id": "ZONE-USER", "zone_name": "User", "zone_type": "USER"},
            {"segment_id": "SEG-BMS", "segment_name": "Building Management", "population": "BUILDING_MGMT", "qos_dscp": 0, "internet_access": False, "internal_access": False, "vlan_id": 120, "vlan_name": "bms", "subnet_prefix": "10.100.20.0/24", "gateway_ip": "10.100.20.1", "zone_id": "ZONE-IOT", "zone_name": "IoT", "zone_type": "IOT"},
            {"segment_id": "SEG-VIDEO", "segment_name": "Video Collaboration", "population": "VIDEO", "qos_dscp": 34, "internet_access": True, "internal_access": True, "vlan_id": 130, "vlan_name": "video", "subnet_prefix": "10.100.30.0/24", "gateway_ip": "10.100.30.1", "zone_id": "ZONE-USER", "zone_name": "User", "zone_type": "USER"},
            {"segment_id": "SEG-GUEST", "segment_name": "Guest", "population": "GUEST", "qos_dscp": 0, "internet_access": True, "internal_access": False, "vlan_id": 140, "vlan_name": "guest", "subnet_prefix": "10.100.40.0/24", "gateway_ip": "10.100.40.1", "zone_id": "ZONE-GUEST", "zone_name": "Guest", "zone_type": "GUEST"},
            {"segment_id": "SEG-IOT", "segment_name": "Operational Technology", "population": "IOT", "qos_dscp": 0, "internet_access": False, "internal_access": False, "vlan_id": 160, "vlan_name": "iot", "subnet_prefix": "10.100.60.0/24", "gateway_ip": "10.100.60.1", "zone_id": "ZONE-IOT", "zone_name": "IoT", "zone_type": "IOT"},
        ],
        "policies": [
            {"policy_id": "POL-USF-GUEST-DENY", "policy_name": "Guest Zone Isolation", "policy_type": "FIREWALL_ZONE_POLICY", "target_device_id": "DEV-HQ-USF-01", "target_hostname": "fw-hq-usr-01", "target_device_role": "USER_FW", "rule_id": "FR-001", "rule_number": 10, "action": "DROP", "protocol": "ANY", "source_port": None, "dest_port": None, "logging": True, "justification": "INT-001: Guest isolation", "source_zone": "Guest", "source_zone_type": "GUEST", "dest_zone": "User", "dest_zone_type": "USER"},
            {"policy_id": "POL-USF-GUEST-DENY", "policy_name": "Guest Zone Isolation", "policy_type": "FIREWALL_ZONE_POLICY", "target_device_id": "DEV-HQ-USF-01", "target_hostname": "fw-hq-usr-01", "target_device_role": "USER_FW", "rule_id": "FR-002", "rule_number": 20, "action": "DROP", "protocol": "ANY", "source_port": None, "dest_port": None, "logging": True, "justification": "INT-001: Guest isolation", "source_zone": "Guest", "source_zone_type": "GUEST", "dest_zone": "DMZ Infrastructure", "dest_zone_type": "DMZ_INFRA"},
            {"policy_id": "POL-USF-EMP-DNS", "policy_name": "Employee DNS Access", "policy_type": "FIREWALL_ZONE_POLICY", "target_device_id": "DEV-HQ-USF-01", "target_hostname": "fw-hq-usr-01", "target_device_role": "USER_FW", "rule_id": "FR-010", "rule_number": 10, "action": "ACCEPT", "protocol": "UDP", "source_port": None, "dest_port": "53", "logging": False, "justification": "All users: DNS resolution", "source_zone": "User", "source_zone_type": "USER", "dest_zone": "DMZ Infrastructure", "dest_zone_type": "DMZ_INFRA"},
            {"policy_id": "POL-USF-EMP-DNS", "policy_name": "Employee DNS Access", "policy_type": "FIREWALL_ZONE_POLICY", "target_device_id": "DEV-HQ-USF-01", "target_hostname": "fw-hq-usr-01", "target_device_role": "USER_FW", "rule_id": "FR-011", "rule_number": 20, "action": "ACCEPT", "protocol": "TCP", "source_port": None, "dest_port": "53", "logging": False, "justification": "All users: DNS resolution (TCP)", "source_zone": "User", "source_zone_type": "USER", "dest_zone": "DMZ Infrastructure", "dest_zone_type": "DMZ_INFRA"},
        ],
        "intents": [
            {"intent_id": "INT-001", "intent_statement": "Guest devices must not access any internal resource or segment", "intent_type": "SECURITY", "priority": 1, "policy_id": "POL-USF-GUEST-DENY", "policy_name": "Guest Zone Isolation", "translation_id": "ITRANS-001", "translated_at": "2025-12-10"},
        ],
        "fw_interfaces": [
            {"device_id": "DEV-HQ-USF-01", "hostname": "fw-hq-usr-01", "device_role": "USER_FW", "interface_id": "IF-USF1-E0V100", "interface_name": "eth0.100", "interface_type": "SUBINTERFACE", "description": "Employee VLAN", "admin_state": "UP", "vlan_id": 100, "vlan_name": "employee", "subnet_prefix": "10.100.0.0/24", "gateway_ip": "10.100.0.1", "connected_to_device": "agg1", "connected_to_interface": "eth5"},
            {"device_id": "DEV-HQ-USF-01", "hostname": "fw-hq-usr-01", "device_role": "USER_FW", "interface_id": "IF-USF1-E0V110", "interface_name": "eth0.110", "interface_type": "SUBINTERFACE", "description": "Voice VLAN", "admin_state": "UP", "vlan_id": 110, "vlan_name": "voice", "subnet_prefix": "10.100.10.0/24", "gateway_ip": "10.100.10.1", "connected_to_device": "agg1", "connected_to_interface": "eth5"},
            {"device_id": "DEV-HQ-USF-01", "hostname": "fw-hq-usr-01", "device_role": "USER_FW", "interface_id": "IF-USF1-E0V130", "interface_name": "eth0.130", "interface_type": "SUBINTERFACE", "description": "Video VLAN", "admin_state": "UP", "vlan_id": 130, "vlan_name": "video", "subnet_prefix": "10.100.30.0/24", "gateway_ip": "10.100.30.1", "connected_to_device": "agg1", "connected_to_interface": "eth5"},
            {"device_id": "DEV-HQ-USF-01", "hostname": "fw-hq-usr-01", "device_role": "USER_FW", "interface_id": "IF-USF1-E0V140", "interface_name": "eth0.140", "interface_type": "SUBINTERFACE", "description": "Guest VLAN", "admin_state": "UP", "vlan_id": 140, "vlan_name": "guest", "subnet_prefix": "10.100.40.0/24", "gateway_ip": "10.100.40.1", "connected_to_device": "agg1", "connected_to_interface": "eth5"},
            {"device_id": "DEV-HQ-DMZFW-01", "hostname": "fw-hq-dmz-01", "device_role": "DMZ_FW", "interface_id": "IF-DMZFW1-E0V200", "interface_name": "eth0.200", "interface_type": "SUBINTERFACE", "description": "DNS DMZ", "admin_state": "UP", "vlan_id": 200, "vlan_name": "dmz_dns", "subnet_prefix": "10.200.0.0/24", "gateway_ip": "10.200.0.1", "connected_to_device": "agg1", "connected_to_interface": "eth7"},
            {"device_id": "DEV-HQ-DMZFW-01", "hostname": "fw-hq-dmz-01", "device_role": "DMZ_FW", "interface_id": "IF-DMZFW1-E0V210", "interface_name": "eth0.210", "interface_type": "SUBINTERFACE", "description": "AD DMZ", "admin_state": "UP", "vlan_id": 210, "vlan_name": "dmz_ad", "subnet_prefix": "10.200.10.0/24", "gateway_ip": "10.200.10.1", "connected_to_device": "agg1", "connected_to_interface": "eth7"},
            {"device_id": "DEV-HQ-DMZFW-01", "hostname": "fw-hq-dmz-01", "device_role": "DMZ_FW", "interface_id": "IF-DMZFW1-E0V250", "interface_name": "eth0.250", "interface_type": "SUBINTERFACE", "description": "Publishing DMZ", "admin_state": "UP", "vlan_id": 250, "vlan_name": "dmz_publish", "subnet_prefix": "10.200.50.0/24", "gateway_ip": "10.200.50.1", "connected_to_device": "agg1", "connected_to_interface": "eth7"},
        ],
        "nat_rules": [],
        "fw_transit": {
            "vlan_id": 300,
            "vlan_name": "fw_interlink",
            "transit_prefix": "10.255.254.0/30",
            "transit_gateway": "10.255.254.1",
        },
    }

    renderer = ConfigRenderer()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Enrich mock devices
    for fw in mock_context["firewalls"]:
        fw["uplink_interface"] = "eth0"
        fw["transit_interface"] = "eth1"
        fw["ha_interface"] = "eth2"
        fw["mgmt_interface"] = "eth3"
        if fw["device_id"].endswith("-01"):
            fw["transit_ip"] = "10.255.254.1"
            fw["ha_peer_ip"] = "10.255.255.2"
        else:
            fw["transit_ip"] = "10.255.254.2"
            fw["ha_peer_ip"] = "10.255.255.1"
        if fw["device_role"] == "DMZ_FW":
            fw["internet_interface"] = "eth3"

    for fw in mock_context["firewalls"]:
        hostname = fw["hostname"]
        logger.info(f"Rendering {hostname} (dry run)...")
        config_text = renderer.render_device(fw, mock_context, TEMPLATE_CHAIN)
        config_path = output_dir / f"{hostname}.conf"
        config_path.write_text(config_text)
        logger.info(f"  → Written: {config_path}")

    logger.info(f"Dry run complete — configs in {output_dir}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Neo4j SSoT → Jinja2 → VyOS Firewall Config Pipeline"
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j connection URI",
    )
    parser.add_argument("--neo4j-user", default="neo4j", help="Neo4j username")
    parser.add_argument(
        "--neo4j-password", default="password", help="Neo4j password"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for rendered configs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run with mock data (no Neo4j required)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.dry_run:
        dry_run(args.output_dir)
    else:
        pipeline = FirewallPipeline(
            args.neo4j_uri, args.neo4j_user, args.neo4j_password, args.output_dir
        )
        pipeline.run()


if __name__ == "__main__":
    main()
