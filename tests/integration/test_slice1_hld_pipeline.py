"""
Slice 1 — HLD-driven pipeline acceptance test.

Drives the HldCommitPipeline directly (bypasses the git hook for test
isolation) using a synthetic HLD diff. Asserts the full A1 → A2 → A3 →
A5 → A7 chain landed in Neo4j.

Skipped unless real Neo4j + Live-Memory are available.

Run with::

    NEO4J_URI=bolt://localhost:7687 \
    NEO4J_PASSWORD=ibn-closed-loop-2026 \
    LIVE_MEMORY_URL=http://localhost:8002 \
    LIVE_MEMORY_TOKEN=lm_pFx2stEGv0pm_OEU_0IUFmqjDRpdmqVoPvU7HGQHPqQ \
    pytest tests/integration/test_slice1_hld_pipeline.py -v
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# Slice 4: bypass the approval gate for these tests so the auto-flow
# behavior they were written against (Slice 1's) is preserved.
os.environ["IBN_AUTO_APPROVE"] = "1"


# ── Skip guards ────────────────────────────────────────────────────────────

USE_REAL_NEO4J = bool(os.environ.get("NEO4J_URI"))
USE_REAL_LIVE_MEMORY = bool(os.environ.get("LIVE_MEMORY_URL"))

REQUIRES_REAL_INFRA = pytest.mark.skipif(
    not (USE_REAL_NEO4J and USE_REAL_LIVE_MEMORY),
    reason="Slice 1 acceptance requires real Neo4j and Live-Memory",
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


@pytest.fixture
def synthetic_diff():
    """Return (vlan_id, fake_load_snapshots_fn) for one new population.

    The function shape matches ``ibn.pipeline.hld_commit.load_snapshots``
    so the test can monkey-patch it without touching git.
    """
    from ibn.parser.hld_parser import parse_hld

    real_path = Path(__file__).resolve().parents[2] / "Enterprise_Campus_Network_HLD (1).md"
    real_text = real_path.read_text(encoding="utf-8")
    test_vlan = 950 + (uuid.uuid4().int % 50)  # 950..999, avoids HLD VLANs

    new_row = (
        f"| Test Pop {test_vlan} | {test_vlan} | 5-10 | 2-5 | "
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
def cleanup_test_intent(real_neo4j):
    """Yield a callable that removes a test Intent + descendants by VLAN id."""
    created_vlans: list[int] = []

    def register(vlan: int):
        created_vlans.append(vlan)

    yield register

    for vlan in created_vlans:
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


# ── Acceptance tests ───────────────────────────────────────────────────────


@REQUIRES_REAL_INFRA
class TestSlice1Acceptance:
    """T-Slice1: end-to-end acceptance for the HLD-driven pipeline."""

    def test_pipeline_runs_all_stages_for_new_population(
        self, real_neo4j, synthetic_diff, cleanup_test_intent
    ):
        """A1 → A2 → A3 → A5 → A7 all execute and report ok."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_intent(test_vlan)

        hc.load_snapshots = fake_loader

        pipeline = HldCommitPipeline()
        result = pipeline.run(
            commit="ACCEPTANCE",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda prompt, choices: "a",  # standard-corporate template
        )

        assert result["cycle_complete"] is True

        stage_names = [s.name for s in result["stage_objects"]]
        assert "diff" in stage_names
        assert "A1 ingestion" in stage_names
        assert "A2 translation" in stage_names
        assert "A3 render" in stage_names
        assert "A5 deploy" in stage_names
        assert "A7 assessment" in stage_names

        # No stage should be in error state
        for s in result["stage_objects"]:
            assert s.status != "error", f"Stage {s.name} failed: {s.summary}"

    def test_intent_policy_rules_landed_in_neo4j(
        self, real_neo4j, synthetic_diff, cleanup_test_intent
    ):
        """The chain Intent → Policy → FirewallRule is queryable end-to-end."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_intent(test_vlan)
        hc.load_snapshots = fake_loader

        HldCommitPipeline().run(
            commit="ACCEPTANCE",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )

        intent_id = f"INT-HLD-{test_vlan}"
        rows = real_neo4j.run_query(
            """
            MATCH (i:Intent {intentId: $iid})-[:DECOMPOSED_INTO]->(p:Policy)
            OPTIONAL MATCH (p)-[:CONTAINS]->(r:FirewallRule)
            RETURN i.origin AS origin,
                   p.policyId AS policyId,
                   collect(r.ruleId) AS rules
            """,
            iid=intent_id,
        )
        assert rows, f"Intent {intent_id} did not land in Neo4j"
        row = rows[0]
        assert row["origin"].startswith("HLD:Enterprise_Campus_Network_HLD")
        assert row["policyId"] == f"POL-{intent_id}"
        # Standard-corporate template produces 5 firewall rules
        assert len(row["rules"]) == 5

    def test_idempotent_re_run_creates_no_new_intents(
        self, real_neo4j, synthetic_diff, cleanup_test_intent
    ):
        """Re-running the same diff produces no new Intents (re-commit no-op)."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_intent(test_vlan)
        hc.load_snapshots = fake_loader

        # First run
        result1 = HldCommitPipeline().run(
            commit="ACCEPTANCE-1",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )
        a1_first = next(s for s in result1["stage_objects"] if s.name == "A1 ingestion")
        assert "created=1" in a1_first.summary

        # Second run with the same diff
        result2 = HldCommitPipeline().run(
            commit="ACCEPTANCE-2",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=lambda p, c: "a",
        )
        a1_second = next(s for s in result2["stage_objects"] if s.name == "A1 ingestion")
        assert "created=0" in a1_second.summary
        assert "reused=1" in a1_second.summary

    def test_dialogue_function_is_called_with_choices(
        self, real_neo4j, synthetic_diff, cleanup_test_intent
    ):
        """The HLD dialogue is invoked exactly once per new population."""
        from ibn.pipeline.hld_commit import HldCommitPipeline
        import ibn.pipeline.hld_commit as hc

        test_vlan, fake_loader = synthetic_diff
        cleanup_test_intent(test_vlan)
        hc.load_snapshots = fake_loader

        calls: list[dict] = []

        def recording_dialogue(prompt, choices):
            calls.append({"prompt": prompt, "choices": list(choices)})
            return "b"

        HldCommitPipeline().run(
            commit="ACCEPTANCE",
            hld_path="Enterprise_Campus_Network_HLD (1).md",
            dialogue_fn=recording_dialogue,
        )

        assert len(calls) == 1
        assert "a" in calls[0]["choices"]
        assert "b" in calls[0]["choices"]
        assert "c" in calls[0]["choices"]
        assert "d" in calls[0]["choices"]
        assert f"VLAN {test_vlan}" in calls[0]["prompt"]
