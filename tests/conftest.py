"""
Shared fixtures for IBN Closed-Loop Architecture test suite.

Mock-first strategy: all tests run against mocked infrastructure by default.
Set environment variables to switch to real instances:

    NEO4J_URI=bolt://localhost:7687          → use real Neo4j
    LIVE_MEMORY_URL=http://localhost:8002     → use real Live-Memory
    GRAPH_MEMORY_URL=http://localhost:8002    → use real Graph-Memory
    NETLAB_SSH_HOST=192.168.1.100            → use real NetLab devices
"""

import os
import json
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Environment flags — detect real infrastructure
# ---------------------------------------------------------------------------

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))
USE_REAL_LIVE_MEMORY = bool(os.environ.get("LIVE_MEMORY_URL"))
USE_REAL_GRAPH_MEMORY = bool(os.environ.get("GRAPH_MEMORY_URL"))
USE_REAL_NETLAB = bool(os.environ.get("NETLAB_SSH_HOST"))

skip_without_neo4j = pytest.mark.skipif(
    not USE_REAL_NEO4J, reason="Requires real Neo4j (set NEO4J_URI)"
)
skip_without_live_memory = pytest.mark.skipif(
    not USE_REAL_LIVE_MEMORY, reason="Requires real Live-Memory (set LIVE_MEMORY_URL)"
)
skip_without_graph_memory = pytest.mark.skipif(
    not USE_REAL_GRAPH_MEMORY, reason="Requires real Graph-Memory (set GRAPH_MEMORY_URL)"
)
skip_without_netlab = pytest.mark.skipif(
    not USE_REAL_NETLAB, reason="Requires real NetLab (set NETLAB_SSH_HOST)"
)


# ---------------------------------------------------------------------------
# Neo4j mock
# ---------------------------------------------------------------------------

@dataclass
class MockNeo4jRecord:
    """Simulates a neo4j.Record."""
    data_dict: dict

    def data(self):
        return self.data_dict

    def __getitem__(self, key):
        return self.data_dict[key]


@dataclass
class MockNeo4jResult:
    """Simulates a neo4j.Result."""
    records: list = field(default_factory=list)

    def single(self):
        return self.records[0] if self.records else None

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return len(self.records)


class MockNeo4jSession:
    """In-memory Neo4j session mock with node/relationship tracking."""

    def __init__(self, graph_store):
        self._store = graph_store
        self._closed = False

    def run(self, query: str, parameters: dict = None):
        """Record the query and return a mock result.

        The mock recognises a handful of patterns used in tests:
        - CREATE queries → store nodes
        - MATCH ... RETURN → return matching nodes
        - CALL db.constraints() → return stored constraints
        """
        parameters = parameters or {}
        entry = {
            "query": query,
            "parameters": parameters,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._store["queries"].append(entry)

        # --- CREATE handling ---
        if query.strip().upper().startswith("CREATE"):
            node_id = str(uuid.uuid4())[:8]
            node = {**parameters, "_id": node_id, "_query": query}
            # Detect label from query (e.g. CREATE (:Intent { ... }))
            import re
            label_match = re.search(r"\(:(\w+)", query)
            label = label_match.group(1) if label_match else "Unknown"
            node["_label"] = label
            self._store["nodes"].append(node)
            return MockNeo4jResult([MockNeo4jRecord({"node": node, "id": node_id})])

        # --- MATCH handling ---
        if "RETURN count" in query.lower() or "return count" in query:
            # Count queries
            label_match = __import__("re").search(r"\(:(\w+)", query)
            label = label_match.group(1) if label_match else None
            count = sum(1 for n in self._store["nodes"] if n.get("_label") == label) if label else len(self._store["nodes"])
            return MockNeo4jResult([MockNeo4jRecord({"count": count})])

        if query.strip().upper().startswith("MATCH"):
            return MockNeo4jResult([MockNeo4jRecord(n) for n in self._store["nodes"][-5:]])

        # --- Constraints ---
        if "db.constraints" in query or "SHOW CONSTRAINTS" in query.upper():
            return MockNeo4jResult([
                MockNeo4jRecord(c) for c in self._store.get("constraints", [])
            ])

        return MockNeo4jResult()

    def close(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MockNeo4jDriver:
    """In-memory Neo4j driver mock."""

    def __init__(self):
        self._store = {"nodes": [], "relationships": [], "queries": [], "constraints": []}

    def session(self, database=None):
        return MockNeo4jSession(self._store)

    def close(self):
        pass

    @property
    def queries(self):
        return self._store["queries"]

    @property
    def nodes(self):
        return self._store["nodes"]

    def add_constraint(self, name, label, property_name):
        self._store["constraints"].append({
            "name": name, "label": label, "property": property_name
        })

    def seed_node(self, label: str, properties: dict):
        """Inject a node directly (for test setup)."""
        node = {**properties, "_label": label, "_id": str(uuid.uuid4())[:8]}
        self._store["nodes"].append(node)
        return node


@pytest.fixture
def neo4j_driver():
    """Provides a mock Neo4j driver (or real if NEO4J_URI is set)."""
    if USE_REAL_NEO4J:
        from neo4j import GraphDatabase
        uri = os.environ["NEO4J_URI"]
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        yield driver
        driver.close()
    else:
        yield MockNeo4jDriver()


# ---------------------------------------------------------------------------
# Live-Memory mock
# ---------------------------------------------------------------------------

class MockLiveMemoryClient:
    """In-memory Live-Memory MCP client mock."""

    def __init__(self):
        self.spaces: dict[str, dict] = {}
        self.notes: dict[str, list] = {}  # space_name → [notes]
        self.banks: dict[str, dict[str, str]] = {}  # space_name → {bank_name: content}
        self.tokens: list[dict] = []
        self.calls: list[dict] = []  # audit log of all MCP calls

    def _log(self, method: str, params: dict):
        self.calls.append({"method": method, "params": params, "ts": datetime.now(timezone.utc).isoformat()})

    # --- Space management ---
    def space_create(self, name: str, description: str = "", consolidation_rules: dict = None):
        self._log("space_create", {"name": name})
        self.spaces[name] = {
            "name": name, "description": description,
            "consolidation_rules": consolidation_rules or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.notes[name] = []
        self.banks[name] = {}
        return {"status": "created", "space": name}

    def space_list(self):
        self._log("space_list", {})
        return list(self.spaces.values())

    def space_rules(self, name: str):
        self._log("space_rules", {"name": name})
        return self.spaces.get(name, {}).get("consolidation_rules", {})

    # --- Notes ---
    def live_note(self, space: str, content: str, category: str = "general"):
        self._log("live_note", {"space": space, "category": category})
        if space not in self.notes:
            self.notes[space] = []
        note = {
            "id": str(uuid.uuid4())[:8],
            "space": space, "content": content, "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.notes[space].append(note)
        return note

    def note_list(self, space: str):
        self._log("note_list", {"space": space})
        return self.notes.get(space, [])

    # --- Bank ---
    def bank_consolidate(self, space: str):
        self._log("bank_consolidate", {"space": space})
        notes = self.notes.get(space, [])
        if not notes:
            return {"status": "no_notes", "banks_updated": 0}
        # Simulate consolidation: group notes by category → bank files
        by_category = {}
        for n in notes:
            by_category.setdefault(n["category"], []).append(n["content"])
        for cat, contents in by_category.items():
            bank_name = cat.replace(" ", "-")
            self.banks.setdefault(space, {})[bank_name] = "\n\n".join(contents)
        consumed = len(notes)
        self.notes[space] = []  # notes consumed
        return {"status": "consolidated", "notes_consumed": consumed, "banks_updated": len(by_category)}

    def bank_read_all(self, space: str):
        self._log("bank_read_all", {"space": space})
        return self.banks.get(space, {})

    # --- Tokens ---
    def token_create(self, name: str, role: str = "agent"):
        self._log("token_create", {"name": name, "role": role})
        token = {"name": name, "role": role, "token": f"mock-token-{uuid.uuid4().hex[:12]}"}
        self.tokens.append(token)
        return token


@pytest.fixture
def live_memory():
    """Provides a mock Live-Memory client."""
    return MockLiveMemoryClient()


# ---------------------------------------------------------------------------
# Graph-Memory mock
# ---------------------------------------------------------------------------

class MockGraphMemoryClient:
    """In-memory Graph-Memory MCP client mock."""

    def __init__(self):
        self.memories: dict[str, dict] = {}  # memory_name → config
        self.entities: list[dict] = []
        self.relations: list[dict] = []
        self.embeddings: list[dict] = []
        self.calls: list[dict] = []

    def _log(self, method: str, params: dict):
        self.calls.append({"method": method, "params": params, "ts": datetime.now(timezone.utc).isoformat()})

    def memory_create(self, name: str, ontology: dict = None):
        self._log("memory_create", {"name": name})
        self.memories[name] = {"name": name, "ontology": ontology or {}}
        return {"status": "created", "memory": name}

    def graph_push(self, memory: str, content: str, source: str = ""):
        self._log("graph_push", {"memory": memory, "source": source})
        # Simulate entity extraction
        entity = {
            "id": str(uuid.uuid4())[:8], "memory": memory,
            "content_preview": content[:100], "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.entities.append(entity)
        return {"status": "ingested", "entities_extracted": 1, "relations_extracted": 0}

    def question_answer(self, memory: str, question: str):
        self._log("question_answer", {"memory": memory, "question": question})
        # Return any matching entities as context
        relevant = [e for e in self.entities if e["memory"] == memory]
        if relevant:
            return {
                "answer": f"Based on {len(relevant)} knowledge entries in {memory}.",
                "sources": [e["content_preview"] for e in relevant[:3]],
            }
        return {"answer": "No relevant knowledge found.", "sources": []}

    def memory_list(self):
        self._log("memory_list", {})
        return list(self.memories.values())


@pytest.fixture
def graph_memory():
    """Provides a mock Graph-Memory client."""
    return MockGraphMemoryClient()


# ---------------------------------------------------------------------------
# NetLab mock
# ---------------------------------------------------------------------------

class MockNetLabDevice:
    """Simulates a NetLab virtual device."""

    def __init__(self, hostname: str, platform: str = "vyos"):
        self.hostname = hostname
        self.platform = platform
        self.running_config = ""
        self.interfaces: dict[str, dict] = {}
        self.operational_state = "running"
        self.command_log: list[dict] = []

    def push_config(self, config: str):
        self.command_log.append({"action": "push_config", "config": config[:200]})
        self.running_config = config
        return {"status": "ok", "device": self.hostname}

    def exec_command(self, command: str):
        self.command_log.append({"action": "exec", "command": command})
        # Simulate common show commands
        if "show configuration" in command:
            return self.running_config
        if "show interfaces" in command:
            return json.dumps(self.interfaces)
        if "show version" in command:
            return f"{self.platform} version 1.4-rolling"
        return ""

    def get_telemetry(self):
        return {
            "hostname": self.hostname,
            "state": self.operational_state,
            "interfaces": self.interfaces,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class MockNetLab:
    """Simulates a NetLab environment."""

    def __init__(self):
        self.devices: dict[str, MockNetLabDevice] = {}
        self.topology: dict = {}

    def add_device(self, hostname: str, platform: str = "vyos"):
        dev = MockNetLabDevice(hostname, platform)
        self.devices[hostname] = dev
        return dev

    def load_topology(self, topology_yaml: dict):
        self.topology = topology_yaml
        for name, attrs in topology_yaml.get("nodes", {}).items():
            self.add_device(name, attrs.get("device", "vyos"))

    def deploy_config(self, hostname: str, config: str):
        if hostname not in self.devices:
            raise KeyError(f"Device {hostname} not found in NetLab")
        return self.devices[hostname].push_config(config)

    def collect_telemetry(self, hostname: str = None):
        if hostname:
            return self.devices[hostname].get_telemetry()
        return {h: d.get_telemetry() for h, d in self.devices.items()}


@pytest.fixture
def netlab():
    """Provides a mock NetLab environment pre-loaded with HLD devices."""
    lab = MockNetLab()
    # Seed with HLD device inventory
    hld_devices = [
        ("acc-sw-01", "eos"), ("acc-sw-02", "eos"),
        ("acc-sw-03", "eos"), ("acc-sw-04", "eos"),
        ("agg-sw-01", "eos"), ("agg-sw-02", "eos"),
        ("usf-fw-01", "vyos"), ("usf-fw-02", "vyos"),
        ("dmzfw-01", "vyos"), ("dmzfw-02", "vyos"),
        ("edge-rt-01", "eos"), ("edge-rt-02", "eos"),
    ]
    for hostname, platform in hld_devices:
        lab.add_device(hostname, platform)
    return lab


# ---------------------------------------------------------------------------
# Event Bus mock
# ---------------------------------------------------------------------------

class MockEventBus:
    """Simulates the CDC / Kafka / Redis event bus."""

    def __init__(self):
        self.events: list[dict] = []
        self.subscriptions: dict[str, list] = {}  # event_type → [callbacks]

    def publish(self, event_type: str, payload: dict):
        event = {
            "type": event_type, "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.events.append(event)
        for callback in self.subscriptions.get(event_type, []):
            callback(event)
        return event

    def subscribe(self, event_type: str, callback):
        self.subscriptions.setdefault(event_type, []).append(callback)

    def get_events(self, event_type: str = None):
        if event_type:
            return [e for e in self.events if e["type"] == event_type]
        return self.events


@pytest.fixture
def event_bus():
    """Provides a mock event bus."""
    return MockEventBus()


# ---------------------------------------------------------------------------
# Helper: HLD seed data
# ---------------------------------------------------------------------------

HLD_VLANS = {
    100: "Employee", 110: "Voice", 120: "Printer", 130: "Video",
    140: "Guest", 150: "IoT", 160: "Management",
    200: "DMZ-Servers", 210: "DNS-DMZ", 220: "AD-DMZ", 230: "File-DMZ",
    240: "PBX-DMZ", 250: "Publish", 260: "Proxy", 270: "Management-DMZ",
    300: "Transit",
}

HLD_ZONES = ["USER", "DMZ_INFRA", "INTERNET", "MANAGEMENT"]

HLD_SEGMENTS = [
    "Employee", "Voice", "Printer", "Video", "Guest", "IoT", "Management",
]

MODEL_STATES = ["WHAT_IF", "CANDIDATE", "POR", "DEPLOYED", "AS_BUILT"]

SEVERITY_LEVELS = ["Info", "Low", "Medium", "High", "Critical"]

AGENT_NAMES = [
    "A1-Ingestion", "A2-Intent-Policy", "A3-Policy-Config",
    "A4-Planning", "A5-Orchestration", "A6-Monitoring",
    "A7-Assessment", "A8-Action", "A9-Abstraction", "A10-Reporting",
]


@pytest.fixture
def seeded_neo4j(neo4j_driver):
    """Neo4j driver pre-seeded with HLD baseline data (POR state)."""
    driver = neo4j_driver
    # Seed site
    driver.seed_node("Site", {
        "siteId": "HQ", "name": "Headquarters", "type": "large",
        "modelState": "POR",
    })
    # Seed devices
    for hostname, platform in [
        ("usf-fw-01", "vyos"), ("usf-fw-02", "vyos"),
        ("dmzfw-01", "vyos"), ("dmzfw-02", "vyos"),
    ]:
        driver.seed_node("Device", {
            "deviceId": hostname, "hostname": hostname, "platform": platform,
            "role": "firewall", "modelState": "POR",
        })
    # Seed VLANs
    for vid, name in HLD_VLANS.items():
        driver.seed_node("VLAN", {
            "vlanId": vid, "name": name, "modelState": "POR",
        })
    # Seed zones
    for zone in HLD_ZONES:
        driver.seed_node("Zone", {
            "zoneId": zone, "name": zone, "modelState": "POR",
        })
    return driver
