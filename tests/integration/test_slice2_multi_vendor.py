"""
Slice 2 — Multi-vendor pipeline acceptance test.

Drives the HldCommitPipeline directly with a synthetic HLD diff and asserts:
  - Both `firewalls` (VyOS) AND `switches` (SR Linux) configurations land in Neo4j
  - The SR Linux Configuration content references the new VLAN
  - The L1 VLAN node is created and linked to the Intent
  - The new VLAN is actually present on the live SR Linux container
    (queried via `docker exec sr_cli`)
  - Idempotency holds across both vendor classes

Skipped unless real Neo4j + Live-Memory + the SR Linux container are available.

Run with::

    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_PASSWORD=ibn-closed-loop-2026 \
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_pFx2stEGv0pm_OEU_0IUFmqjDRpdmqVoPvU7HGQHPqQ \
    pytest tests/integration/test_slice2_multi_vendor.py -v
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

# Slice 4: bypass the approval gate so Slice 2's auto-flow assertions hold.
os.environ["IBN_AUTO_APPROVE"] = "1"


# ── Skip guards ────────────────────────────────────────────────────────────

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))
USE_REAL_LIVE_MEMORY = bool(os.environ.get("LIVE_MEMORY_URL"))

SRL_CONTAINER = "clab-ibnlab-switches-acc-sw-01"


def _srl_container_running() -> bool:
    """Return True iff the SR Linux containerlab node is up."""
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return SRL_CONTAINER in out.decode()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


REQUIRES_REAL_INFRA = pytest.mark.skipif(
    not (USE_REAL_NEO4J and USE_REAL_LIVE_MEMORY and _srl_container_running()),
    reason=(
        "Slice 2 acceptance requires real Neo4j, Live-Memory, and the "
        f"{SRL_CONTAINER} container running"
    ),
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_neo4j():
    from ibn.core.neo4j_client import Neo4jClient
    client = Neo4jClient(
        uri      = os.environ["NEO4J_URI"],
        user     = os.environ.get("NEO4J_USER", "neo4j"),
        password = os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def srl_device_seeded(real_neo4j):
    """Ensure the SR Linux device is seeded for the test module duration."""
    real_neo4j.run_query(
        "MERGE (s:Site {siteId: 'SITE-HQ-01'}) "
        "ON CREATE SET s.name = 'Headquarters', s.modelState = 'POR'"
    )
    real_neo4j.run_query(
        """
        MERGE (d:Device {deviceId: $id})
        SET d.hostname    = 'acc-sw-01',
            d.vendor      = 'Nokia',
            d.platform    = 'srlinux',
            d.deviceRole  = 'ACCESS_SWITCH',
            d.modelState  = 'POR',
            d.lifecycleState = 'ACTIVE'
        WITH d
        MATCH (s:Site {siteId: 'SITE-HQ-01'})
        MERGE (d)-[:LOCATED_AT]->(s)
        """,
        id=SRL_CONTAINER,
    )
    yield SRL_CONTAINER
    # Don't tear down the device — other tests / future hook runs use it.


@pytest.fixture
def synthetic_diff():
    """Synthesize a single new population for the test."""
    from ibn.parser.hld_parser import parse_hld

    real_path = Path(__file__).resolve().parents[2] / "Enterprise_Campus_Network_HLD (1).md"
    real_text = real_path.read_text(encoding="utf-8")
    test_vlan = 700 + (uuid.uuid4().int % 50)  # 700..749, well clear of HLD VLANs

    new_row = (
        f"| Slice2 Pop {test_vlan} | {test_vlan} | 5-10 | 2-5 | "
        f"Standard | AF21 | 1 Mbps |"
    )
    modified = real_text.replace(
        "| Operational Tech | 160 | 100-1000 | 20-200 | Med-High | AF32, EF | 0.1-0.5 Mbps |",
        (
            "| Operational Tech | 160 | 100-1000 | 20-200 | Med-High | AF32, EF | 0.1-0.5 Mbps |\n"
            + new_row
        ),
    )

    def fake_load_snapshots(commit, hld_path):
        return (
            parse_hld(real_text, source_path=hld_path),
            parse_hld(modified, source_path=hld_path),
        )

    return test_vlan, fake_load_snapshots


@pytest.fixture
def cleanup_test_vlan(real_neo4j):
    """Yield a callable to remove a test VLAN + Intent + descendants."""
    test_vlans: list[int] = []

    def register(vlan: int):
        test_vlans.append(vlan)

    yield register

    for vlan in test_vlans:
        intent_id = f"INT-HLD-{vlan}"
        real_neo4j.run_query(
            """
            MATCH (i:Intent {intentId: $iid})
            OPTIONAL MATCH (i)-[:DECOMPOSED_INTO]->(p:Policy)
            OPTIONAL MATCH (p)-[:CONTAINS]->(r:FirewallRule)
            DETACH DELETE i, p, r
            """,
            iid=intent_id,
        )
        real_neo4j.run_query(
            "MATCH (c:Configuration {intentId: $iid}) DETACH DELETE c",
            iid=intent_id,
        )
        real_neo4j.run_query(
            "MATCH (v:VLAN {vlanId: $vid}) DETACH DELETE v",
            vid=vlan,
        )


# ── Acceptance tests ───────────────────────────────────────────────────────


@REQUIRES_REAL_INFRA
class TestSlice2Acceptance:
    """T-Slice2: end-to-end acceptance for the multi-vendor pipeline."""

    def test_pipeline_renders_for_both_vendor_classes(
        self, real_neo4j, srl_device_seeded, synthetic_diff, cleanup_test_vlan
    ):
        """A3 produces Configuration nodes for VyOS firewalls AND the SR Linux switch."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_vlan(test_vlan)
        hc.load_snapshots = fake_loader

        result = HldCommitPipeline().run(
            commit="SLICE2-ACCEPT",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )
        assert result["cycle_complete"] is True

        # 5 Configuration nodes total: 4 VyOS + 1 SR Linux
        intent_id = f"INT-HLD-{test_vlan}"
        rows = real_neo4j.run_query(
            """
            MATCH (c:Configuration {intentId: $iid})
            OPTIONAL MATCH (c)-[:APPLIES_TO]->(d:Device)
            RETURN c.configId AS cid, d.deviceId AS device, d.platform AS platform
            """,
            iid=intent_id,
        )
        assert len(rows) >= 5, f"Expected ≥5 Configurations, got {len(rows)}"

        platforms = {r["platform"] for r in rows if r["platform"]}
        # The vyos firewalls in the seed have platform=None or 'vyos' depending
        # on which seed ran. The new SR Linux device has platform='srlinux'.
        assert "srlinux" in platforms, (
            f"SR Linux config not rendered. platforms seen: {platforms}"
        )

    def test_l1_vlan_node_created_and_linked(
        self, real_neo4j, srl_device_seeded, synthetic_diff, cleanup_test_vlan
    ):
        """A1 creates an L1 VLAN node with TRACES_TO link to the Intent."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_vlan(test_vlan)
        hc.load_snapshots = fake_loader

        HldCommitPipeline().run(
            commit="SLICE2-VLAN",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )

        rows = real_neo4j.run_query(
            """
            MATCH (v:VLAN {vlanId: $vid})-[:TRACES_TO]->(i:Intent)
            RETURN v.vlanId AS vid, v.name AS name, v.modelState AS state,
                   v.origin AS origin, i.intentId AS intent
            """,
            vid=test_vlan,
        )
        assert rows, f"L1 VLAN {test_vlan} not created or not linked to Intent"
        r = rows[0]
        assert r["vid"] == test_vlan
        assert r["name"].startswith("Slice2 Pop")
        assert r["origin"].startswith("HLD:")
        assert r["intent"] == f"INT-HLD-{test_vlan}"

    def test_srl_config_contains_new_vlan(
        self, real_neo4j, srl_device_seeded, synthetic_diff, cleanup_test_vlan
    ):
        """The Configuration content rendered for SR Linux references the new VLAN."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_vlan(test_vlan)
        hc.load_snapshots = fake_loader

        HldCommitPipeline().run(
            commit="SLICE2-CONTENT",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )

        rows = real_neo4j.run_query(
            """
            MATCH (c:Configuration {intentId: $iid})-[:APPLIES_TO]->(d:Device)
            WHERE d.platform = 'srlinux'
            RETURN c.content AS content
            """,
            iid=f"INT-HLD-{test_vlan}",
        )
        assert rows, "No SR Linux Configuration node was created"
        content = rows[0]["content"]
        assert f"vlan-id {test_vlan}" in content, (
            f"SR Linux config does not reference VLAN {test_vlan}.\n"
            f"Content snippet:\n{content[:500]}"
        )
        assert f"network-instance vlan-{test_vlan}" in content

    def test_srl_running_config_actually_updated_on_live_container(
        self, real_neo4j, srl_device_seeded, synthetic_diff, cleanup_test_vlan
    ):
        """A5 pushes the new VLAN to the live SR Linux container; sr_cli sees it."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_vlan(test_vlan)
        hc.load_snapshots = fake_loader

        HldCommitPipeline().run(
            commit="SLICE2-LIVE",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )

        # Query the live container's full running config — sr_cli requires
        # a key for `info from running /network-instance` so we just dump
        # everything and search.
        out = subprocess.check_output(
            ["docker", "exec", SRL_CONTAINER, "sr_cli", "info from running"],
            timeout=30,
        ).decode()
        assert f"network-instance vlan-{test_vlan}" in out, (
            f"VLAN {test_vlan} was not pushed to the live SR Linux container.\n"
            f"sr_cli output (last 1500 chars):\n{out[-1500:]}"
        )

    def test_idempotent_re_run_creates_no_new_artifacts(
        self, real_neo4j, srl_device_seeded, synthetic_diff, cleanup_test_vlan
    ):
        """Re-running the same diff produces no new Intents or VLAN nodes."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_vlan(test_vlan)
        hc.load_snapshots = fake_loader

        # First run
        result1 = HldCommitPipeline().run(
            commit="SLICE2-IDEMP-1",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )
        a1_first = next(s for s in result1["stage_objects"] if s.name == "A1 ingestion")
        assert "created=1" in a1_first.summary

        # Second run with the same diff
        result2 = HldCommitPipeline().run(
            commit="SLICE2-IDEMP-2",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )
        a1_second = next(s for s in result2["stage_objects"] if s.name == "A1 ingestion")
        assert "created=0" in a1_second.summary

        # Exactly one VLAN node should exist
        vlan_rows = real_neo4j.run_query(
            "MATCH (v:VLAN {vlanId: $vid}) RETURN count(v) AS n",
            vid=test_vlan,
        )
        assert vlan_rows[0]["n"] == 1
