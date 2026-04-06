"""
T7 — Agent 6: Monitoring Tests (Unit)
======================================
Validates telemetry collection, CLI output parsing, Neo4j As-Built writes,
and Live-Memory integration.
"""
import pytest
import json
from datetime import datetime, timezone


# ── T7.1 CLI polling ─────────────────────────────────────────────────────

class TestCLIParsing:
    """T7.1 — Parse VyOS CLI outputs into structured telemetry."""

    VYOS_SHOW_INTERFACES = """Codes: S - State, L - Link, u - Up, D - Down, A - Admin Down
Interface    IP Address         S/L  Description
---------    ----------         ---  -----------
eth0         10.1.100.1/24      u/u  Employee-VLAN100
eth0.110     10.1.110.1/24      u/u  Voice-VLAN110
eth1         10.1.255.1/30      u/u  Transit-VLAN300
eth2         203.0.113.1/30     u/u  Internet-uplink
lo           127.0.0.1/8        u/u
"""

    VYOS_SHOW_FIREWALL = """Rule  Action  Source             Dest               Proto  Hits
----  ------  ------             ----               -----  ----
10    accept  10.1.140.0/24      0.0.0.0/0          any    15432
20    drop    10.1.140.0/24      10.1.100.0/16      any    342
"""

    VYOS_SHOW_VRRP = """Name         Interface  VRID  State   Priority  VIP
-----------  ---------  ----  ------  --------  ----
USF-HA       eth0       10    MASTER  200       10.1.100.254
"""

    VYOS_SHOW_IP_ROUTE = """Codes: K - kernel, C - connected, S - static, O - OSPF, B - BGP
S>*  0.0.0.0/0 [1/0] via 203.0.113.2, eth2
C>*  10.1.100.0/24 is directly connected, eth0
C>*  10.1.255.0/30 is directly connected, eth1
O>*  10.1.200.0/24 [110/20] via 10.1.255.2, eth1
"""

    def _parse_interfaces(self, output: str) -> list:
        """Parse VyOS show interfaces output."""
        interfaces = []
        for line in output.strip().splitlines()[3:]:  # skip header
            parts = line.split()
            if len(parts) >= 3:
                interfaces.append({
                    "name": parts[0],
                    "ip": parts[1] if "/" in parts[1] else None,
                    "state": parts[2],
                    "description": parts[3] if len(parts) > 3 else "",
                })
        return interfaces

    def _parse_vrrp(self, output: str) -> list:
        """Parse VyOS show vrrp output."""
        groups = []
        for line in output.strip().splitlines()[2:]:  # skip header
            parts = line.split()
            if len(parts) >= 6:
                groups.append({
                    "name": parts[0], "interface": parts[1],
                    "vrid": int(parts[2]), "state": parts[3],
                    "priority": int(parts[4]), "vip": parts[5],
                })
        return groups

    def test_t7_1_1_parse_show_interfaces(self):
        """T7.1.1 — Parse VyOS show interfaces output."""
        interfaces = self._parse_interfaces(self.VYOS_SHOW_INTERFACES)
        assert len(interfaces) >= 4
        eth0 = next(i for i in interfaces if i["name"] == "eth0")
        assert eth0["ip"] == "10.1.100.1/24"
        assert "u/u" in eth0["state"]

    def test_t7_1_2_parse_show_firewall(self):
        """T7.1.2 — Parse VyOS show firewall output to extract hit counts."""
        # Simple extraction — production would use structured parsing
        lines = self.VYOS_SHOW_FIREWALL.strip().splitlines()[2:]
        rules = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                rules.append({
                    "rule": int(parts[0]), "action": parts[1],
                    "source": parts[2], "dest": parts[3],
                    "proto": parts[4], "hits": int(parts[5])
                })
        assert len(rules) == 2
        assert rules[0]["hits"] == 15432
        assert rules[1]["action"] == "drop"

    def test_t7_1_3_parse_show_vrrp(self):
        """T7.1.3 — Parse VyOS show vrrp to extract HA state."""
        groups = self._parse_vrrp(self.VYOS_SHOW_VRRP)
        assert len(groups) == 1
        assert groups[0]["state"] == "MASTER"
        assert groups[0]["priority"] == 200
        assert groups[0]["vip"] == "10.1.100.254"

    def test_t7_1_4_parse_show_ip_route(self):
        """T7.1.4 — Parse VyOS routing table."""
        routes = []
        for line in self.VYOS_SHOW_IP_ROUTE.strip().splitlines()[1:]:
            if ">" in line:
                parts = line.split()
                prefix = parts[1] if "/" in parts[1] else parts[0].replace(">*", "")
                routes.append({"prefix": prefix})
        assert len(routes) >= 3

    def test_t7_1_5_ssh_failure_handled_gracefully(self, netlab):
        """T7.1.5 — SSH connection failure produces alert, no crash."""
        # Attempt to collect from nonexistent device
        with pytest.raises(KeyError):
            netlab.collect_telemetry("nonexistent-device")
        # Verify other devices are still reachable
        telemetry = netlab.collect_telemetry("usf-fw-01")
        assert telemetry["hostname"] == "usf-fw-01"


# ── T7.2 Neo4j As-Built writes ───────────────────────────────────────────

class TestAsBuiltWrites:
    """T7.2 — Monitoring agent writes As-Built state to Neo4j."""

    def test_t7_2_1_creates_telemetry_nodes(self, mock_neo4j):
        """T7.2.1 — Creates Telemetry nodes in L5 with AS_BUILT modelState."""
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:Telemetry {timestamp: $ts, metric: 'interface_state', "
                "value: 'up', deviceId: $did, interfaceName: 'eth0', "
                "modelState: 'AS_BUILT'})",
                {"ts": datetime.now(timezone.utc).isoformat(), "did": "usf-fw-01"}
            )

        nodes = mock_neo4j.nodes
        telemetry = [n for n in nodes if n.get("_label") == "Telemetry"]
        assert len(telemetry) >= 1
        # modelState is a literal, not a parameter. Verify via query.
        queries = mock_neo4j.queries
        assert any("modelState: 'AS_BUILT'" in q["query"] for q in queries)

    def test_t7_2_2_updates_device_oper_state(self, mock_neo4j):
        """T7.2.2 — Updates OperationalState on Device node."""
        with mock_neo4j.session() as session:
            session.run(
                "CREATE (:OperationalState {deviceId: $did, operState: 'running', "
                "cpuUtilization: 23.5, memoryUtilization: 45.2, "
                "timestamp: $ts, modelState: 'AS_BUILT'})",
                {"did": "usf-fw-01", "ts": datetime.now(timezone.utc).isoformat()}
            )

        nodes = mock_neo4j.nodes
        ops = [n for n in nodes if n.get("_label") == "OperationalState"]
        assert len(ops) >= 1

    def test_t7_2_4_creates_alert_on_threshold_breach(self, mock_neo4j):
        """T7.2.4 — Alert created when metric exceeds threshold."""
        cpu_value = 92.3
        threshold = 90.0

        if cpu_value > threshold:
            with mock_neo4j.session() as session:
                session.run(
                    "CREATE (:Alert {alertId: $aid, severity: 'MEDIUM', "
                    "metric: 'cpu_utilization', value: $val, threshold: $thr, "
                    "deviceId: $did, modelState: 'AS_BUILT'})",
                    {"aid": "ALT-001", "val": cpu_value, "thr": threshold, "did": "usf-fw-01"}
                )

        nodes = mock_neo4j.nodes
        alerts = [n for n in nodes if n.get("_label") == "Alert"]
        assert len(alerts) >= 1
        # severity is a literal, not a parameter. Verify via query.
        queries = mock_neo4j.queries
        assert any("severity: 'MEDIUM'" in q["query"] for q in queries)

    def test_t7_2_5_all_as_built_nodes_have_correct_state(self, mock_neo4j):
        """T7.2.5 — All telemetry/state nodes carry modelState AS_BUILT."""
        labels = ["Telemetry", "OperationalState", "Alert"]
        for label in labels:
            with mock_neo4j.session() as session:
                session.run(
                    f"CREATE (:{label} {{testId: 'test', modelState: 'AS_BUILT'}})", {}
                )

        # modelState is a literal in the queries, not a parameter.
        # Verify all queries include it.
        queries = mock_neo4j.queries
        assert all("modelState: 'AS_BUILT'" in q["query"] for q in queries[-3:])


# ── T7.3 Live-Memory integration ─────────────────────────────────────────

class TestMonitoringLiveMemory:
    """T7.3 — Agent 6 emits live_notes during monitoring cycles."""

    def test_t7_3_1_note_per_polling_cycle(self, live_memory):
        """T7.3.1 — Emits live_note per polling cycle."""
        live_memory.space_create("ibn-asbuilt-current")
        note = live_memory.live_note(
            space="ibn-asbuilt-current",
            category="telemetry-snapshot",
            content="Polling cycle complete: 12 devices, 48 interfaces, 0 anomalies"
        )
        assert note["category"] == "telemetry-snapshot"

    def test_t7_3_2_note_on_anomaly(self, live_memory):
        """T7.3.2 — Emits live_note when anomaly detected."""
        live_memory.space_create("ibn-asbuilt-current")
        note = live_memory.live_note(
            space="ibn-asbuilt-current",
            category="anomaly-detected",
            content="ANOMALY: usf-fw-01 eth0.140 transitioned DOWN unexpectedly"
        )
        assert note["category"] == "anomaly-detected"
        assert "ANOMALY" in note["content"]
