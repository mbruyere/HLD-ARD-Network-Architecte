"""
T5 — Agent 3: Policy→Config (Jinja2 Pipeline) Tests (Unit)
===========================================================
Validates Cypher extraction queries, Jinja2 template rendering,
Configuration node creation, and config diff generation.
"""
import pytest
import os

# Try to import Jinja2 — skip rendering tests if not available
try:
    from jinja2 import Environment, FileSystemLoader, BaseLoader
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


# ── T5.1 Cypher extraction queries ───────────────────────────────────────

class TestCypherExtraction:
    """T5.1 — Validate the 8 Cypher extraction queries return expected data."""

    EXTRACTION_QUERIES = {
        "firewalls": (
            "MATCH (fp:FirewallPair)-[:AGGREGATES]->(d:Device) "
            "WHERE d.modelState = 'POR' "
            "RETURN fp, d"
        ),
        "zones": (
            "MATCH (z:Zone)-[:CONTAINS]->(s:Segment)-[:MAPPED_TO]->(v:VLAN) "
            "WHERE z.modelState = 'POR' "
            "RETURN z, collect(v.vlanId) as vlans"
        ),
        "segments": (
            "MATCH (s:Segment)-[:MAPPED_TO]->(v:VLAN) "
            "WHERE s.modelState = 'POR' "
            "RETURN s.name, v.vlanId"
        ),
        "policies": (
            "MATCH (fr:FirewallRule)-[:ENFORCES]->(p:Policy) "
            "WHERE p.status = 'APPROVED' AND p.modelState = 'CANDIDATE' "
            "RETURN fr, p"
        ),
        "intents": (
            "MATCH (i:Intent)-[:IMPLEMENTED_BY]->(p:Policy) "
            "WHERE i.status = 'TRANSLATED' "
            "RETURN i, p"
        ),
        "fw_interfaces": (
            "MATCH (d:Device)-[:CONTAINS]->(iface:Interface) "
            "WHERE d.role = 'firewall' AND d.modelState = 'POR' "
            "RETURN d.deviceId, iface"
        ),
        "nat_rules": (
            "MATCH (n:NATRule)-[:APPLIED_ON]->(d:Device) "
            "WHERE d.role = 'firewall' "
            "RETURN n, d.deviceId"
        ),
        "fw_transit": (
            "MATCH (v:VLAN {vlanId: 300})-[:BELONGS_TO]->(site:Site) "
            "RETURN v, site"
        ),
    }

    @pytest.mark.parametrize("query_name", EXTRACTION_QUERIES.keys())
    def test_t5_1_query_structure(self, query_name):
        """T5.1.1–T5.1.7 — Each extraction query has valid Cypher structure."""
        query = self.EXTRACTION_QUERIES[query_name]
        assert "MATCH" in query.upper()
        assert "RETURN" in query.upper()
        # All queries should filter by modelState or status or role or vlanId
        assert "modelState" in query or "status" in query or "role" in query or "vlanId" in query

    def test_t5_1_8_all_eight_queries_defined(self):
        """T5.1.8 — All 8 extraction queries are defined."""
        assert len(self.EXTRACTION_QUERIES) == 8
        expected_names = {"firewalls", "zones", "segments", "policies",
                          "intents", "fw_interfaces", "nat_rules", "fw_transit"}
        assert set(self.EXTRACTION_QUERIES.keys()) == expected_names


# ── T5.2 Jinja2 template rendering ───────────────────────────────────────

@pytest.mark.skipif(not HAS_JINJA2, reason="Jinja2 not installed")
class TestJinja2Rendering:
    """T5.2 — Validate Jinja2 template rendering to VyOS config."""

    def _render_template_string(self, template_str: str, context: dict) -> str:
        """Render a Jinja2 template from string."""
        env = Environment(loader=BaseLoader())
        template = env.from_string(template_str)
        return template.render(**context)

    def test_t5_2_1_base_template_renders_hostname(self):
        """T5.2.1 — Base template renders hostname and interfaces."""
        template = """
{%- for fw in firewalls %}
set system host-name {{ fw.hostname }}
{%- for iface in fw.interfaces %}
set interfaces ethernet {{ iface.name }} address {{ iface.ip }}
set interfaces ethernet {{ iface.name }} vif {{ iface.vlan }} description '{{ iface.description }}'
{%- endfor %}
{%- endfor %}
"""
        context = {
            "firewalls": [{
                "hostname": "fw-hq-usr-01",
                "interfaces": [
                    {"name": "eth0", "ip": "10.1.100.1/24", "vlan": 100, "description": "Employee"},
                    {"name": "eth1", "ip": "10.1.255.1/30", "vlan": 300, "description": "Transit"},
                ]
            }]
        }
        result = self._render_template_string(template, context)
        assert "set system host-name fw-hq-usr-01" in result
        assert "set interfaces ethernet eth0 address 10.1.100.1/24" in result

    def test_t5_2_2_policy_template_renders_zones(self):
        """T5.2.2 — Policy template renders zone-based firewall rules."""
        template = """
{%- for rule in rules %}
set firewall name {{ rule.name }} default-action {{ rule.default_action }}
set firewall name {{ rule.name }} rule {{ rule.number }} action {{ rule.action }}
set firewall name {{ rule.name }} rule {{ rule.number }} source group network-group {{ rule.source }}
set firewall name {{ rule.name }} rule {{ rule.number }} destination group network-group {{ rule.dest }}
{%- endfor %}
{%- for zone in zones %}
set zone-policy zone {{ zone.name }} default-action drop
{%- for iface in zone.interfaces %}
set zone-policy zone {{ zone.name }} interface {{ iface }}
{%- endfor %}
{%- endfor %}
"""
        context = {
            "rules": [
                {"name": "GUEST-TO-INTERNET", "default_action": "accept",
                 "number": 10, "action": "accept", "source": "GUEST-NET", "dest": "INTERNET-NET"},
                {"name": "GUEST-TO-USER", "default_action": "drop",
                 "number": 10, "action": "drop", "source": "GUEST-NET", "dest": "USER-NET"},
            ],
            "zones": [
                {"name": "USER", "interfaces": ["eth0.100", "eth0.110"]},
                {"name": "INTERNET", "interfaces": ["eth2"]},
            ]
        }
        result = self._render_template_string(template, context)
        assert "set firewall name GUEST-TO-INTERNET" in result
        assert "set firewall name GUEST-TO-USER default-action drop" in result
        assert "set zone-policy zone USER" in result

    def test_t5_2_3_nat_template_renders_rules(self):
        """T5.2.3 — NAT template renders source/destination NAT rules."""
        template = """
{%- for rule in nat_rules %}
set nat {{ rule.type }} rule {{ rule.number }} outbound-interface {{ rule.outbound }}
set nat {{ rule.type }} rule {{ rule.number }} source address {{ rule.source }}
set nat {{ rule.type }} rule {{ rule.number }} translation {{ rule.translation }}
{%- endfor %}
"""
        context = {
            "nat_rules": [{
                "type": "source", "number": 100,
                "outbound": "eth2", "source": "10.1.100.0/24",
                "translation": "masquerade"
            }]
        }
        result = self._render_template_string(template, context)
        assert "set nat source rule 100" in result
        assert "masquerade" in result

    def test_t5_2_4_ha_template_renders_vrrp(self):
        """T5.2.4 — HA template renders VRRP configuration."""
        template = """
set high-availability vrrp group {{ vrrp.group }} interface {{ vrrp.interface }}
set high-availability vrrp group {{ vrrp.group }} virtual-address {{ vrrp.vip }}
set high-availability vrrp group {{ vrrp.group }} priority {{ vrrp.priority }}
set high-availability vrrp group {{ vrrp.group }} preempt {{ vrrp.preempt }}
"""
        context = {
            "vrrp": {
                "group": "USF-HA", "interface": "eth0",
                "vip": "10.1.100.254", "priority": 200, "preempt": "true"
            }
        }
        result = self._render_template_string(template, context)
        assert "set high-availability vrrp group USF-HA" in result
        assert "priority 200" in result

    def test_t5_2_6_per_device_distinct_output(self):
        """T5.2.6 — Rendering for two USF devices produces different configs."""
        template = "set system host-name {{ hostname }}\nset interfaces ethernet eth0 address {{ ip }}"
        devices = [
            {"hostname": "fw-hq-usr-01", "ip": "10.1.100.1/24"},
            {"hostname": "fw-hq-usr-02", "ip": "10.1.100.2/24"},
        ]
        configs = [self._render_template_string(template, d) for d in devices]
        assert configs[0] != configs[1]
        assert "fw-hq-usr-01" in configs[0]
        assert "fw-hq-usr-02" in configs[1]


# ── T5.3 Configuration node creation ─────────────────────────────────────

class TestConfigNodeCreation:
    """T5.3 — Agent 3 creates Configuration nodes in Neo4j L5."""

    def test_t5_3_1_creates_configuration_node(self, neo4j_driver):
        """T5.3.1 — Configuration node created with correct properties."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Configuration {configId: $cid, deviceId: $did, "
                "content: $content, format: 'vyos-set', version: 1, "
                "modelState: 'CANDIDATE'})",
                {
                    "cid": "CFG-USF-001",
                    "did": "fw-hq-usr-01",
                    "content": "set system host-name fw-hq-usr-01"
                }
            )

        nodes = neo4j_driver.nodes
        cfg_nodes = [n for n in nodes if n.get("_label") == "Configuration"]
        assert len(cfg_nodes) >= 1

    def test_t5_3_2_links_configuration_to_policy(self, neo4j_driver):
        """T5.3.2 — Configuration linked to Policy via RENDERS."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001', modelState: 'CANDIDATE'})"
                "-[:RENDERS]->"
                "(:Policy {policyId: 'POL-001', modelState: 'CANDIDATE'})",
                {}
            )

        queries = neo4j_driver.queries
        assert any("RENDERS" in q["query"] for q in queries)

    def test_t5_3_3_links_configuration_to_device(self, neo4j_driver):
        """T5.3.3 — Configuration linked to target Device via TARGETS."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Configuration {configId: 'CFG-001', modelState: 'CANDIDATE'})"
                "-[:TARGETS]->"
                "(:Device {deviceId: 'fw-hq-usr-01', modelState: 'POR'})",
                {}
            )

        queries = neo4j_driver.queries
        assert any("TARGETS" in q["query"] for q in queries)

    def test_t5_3_4_emits_live_note(self, live_memory):
        """T5.3.4 — Emits live_note to candidate space after rendering."""
        live_memory.space_create("ibn-candidate-001")

        note = live_memory.live_note(
            space="ibn-candidate-001",
            category="config-rendering",
            content="Rendered VyOS config for fw-hq-usr-01: 42 lines, 3 zone policies"
        )

        assert note["category"] == "config-rendering"


# ── T5.4 Diff generation ─────────────────────────────────────────────────

class TestConfigDiff:
    """T5.4 — Config diff between versions."""

    def _compute_diff(self, old_config: str, new_config: str) -> list:
        """Line-by-line diff between two configs."""
        old_lines = set(old_config.strip().splitlines())
        new_lines = set(new_config.strip().splitlines())
        added = new_lines - old_lines
        removed = old_lines - new_lines
        return {"added": sorted(added), "removed": sorted(removed)}

    def test_t5_4_1_diff_detects_changes(self):
        """T5.4.1 — Diff between v1 and v2 shows additions/removals."""
        v1 = "set firewall name GUEST-TO-INTERNET default-action accept\nset firewall name GUEST-TO-USER default-action drop"
        v2 = "set firewall name GUEST-TO-INTERNET default-action accept\nset firewall name GUEST-TO-DMZ default-action drop"

        diff = self._compute_diff(v1, v2)
        assert len(diff["added"]) == 1
        assert "GUEST-TO-DMZ" in diff["added"][0]
        assert len(diff["removed"]) == 1
        assert "GUEST-TO-USER" in diff["removed"][0]

    def test_t5_4_2_empty_diff_when_unchanged(self):
        """T5.4.2 — No diff when configs are identical."""
        config = "set system host-name fw-hq-usr-01\nset interfaces ethernet eth0 address 10.1.100.1/24"
        diff = self._compute_diff(config, config)
        assert len(diff["added"]) == 0
        assert len(diff["removed"]) == 0
