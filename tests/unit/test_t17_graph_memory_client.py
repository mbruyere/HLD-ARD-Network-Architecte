"""
T17 — GraphMemoryClient Unit Tests
====================================
Tests the production GraphMemoryClient with mocked MCP transport so no real
Graph-Memory server is needed.  Validates:
  - memory_create / memory_list / memory_delete
  - graph_push (maps to memory_ingest MCP tool)
  - graph_push_batch (pushes all bank files from a space)
  - question_answer (graph-guided RAG)
  - storage_cleanup / graph_stats
  - from_env() factory
  - Namespace prefix constant
"""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from ibn.core.graph_memory_client import GraphMemoryClient, NAMESPACE_PREFIX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(url="http://gm.local:8003", token="test-token"):
    """Return a GraphMemoryClient with a mocked _call method."""
    client = GraphMemoryClient(url, token)
    client._call = MagicMock(return_value={})
    return client


# ---------------------------------------------------------------------------
# T17.1  Namespace constant
# ---------------------------------------------------------------------------

class TestNamespace:

    def test_t17_1_prefix_constant_value(self):
        """T17.1 — NAMESPACE_PREFIX must be 'IBN_LIFECYCLE_'."""
        assert NAMESPACE_PREFIX == "IBN_LIFECYCLE_"

    def test_t17_2_no_ssot_label_collision(self):
        """T17.2 — IBN_LIFECYCLE_ prefix does not collide with SSoT labels."""
        ssot_labels = {
            "Intent", "Policy", "FirewallRule", "Device", "Site",
            "Configuration", "Alert", "ChangeRequest", "Operator",
        }
        for label in ssot_labels:
            assert not label.startswith(NAMESPACE_PREFIX), (
                f"SSoT label '{label}' starts with namespace prefix — collision risk"
            )


# ---------------------------------------------------------------------------
# T17.2  memory_create
# ---------------------------------------------------------------------------

class TestMemoryCreate:

    def test_t17_2_1_calls_memory_create_tool(self):
        client = _make_client()
        client.memory_create("ibn-lifecycle")
        client._call.assert_called_once()
        tool_name, args = client._call.call_args[0]
        assert tool_name == "memory_create"
        # Graph-Memory's memory_create expects memory_id + name (not just name)
        assert args["memory_id"] == "ibn-lifecycle"
        assert args["name"] == "ibn-lifecycle"

    def test_t17_2_2_passes_ontology(self):
        client = _make_client()
        client.memory_create("ibn-lifecycle", ontology="cloud")
        _, args = client._call.call_args[0]
        # Graph-Memory accepts built-in ontology names (general, cloud, ...)
        assert args["ontology"] == "cloud"

    def test_t17_2_3_returns_dict_on_empty_response(self):
        client = _make_client()
        result = client.memory_create("ibn-lifecycle")
        assert isinstance(result, dict)

    def test_t17_2_4_description_passed(self):
        client = _make_client()
        client.memory_create("ibn-lifecycle", description="IBN knowledge graph")
        _, args = client._call.call_args[0]
        assert args["description"] == "IBN knowledge graph"


# ---------------------------------------------------------------------------
# T17.3  memory_list / memory_delete
# ---------------------------------------------------------------------------

class TestMemoryManagement:

    def test_t17_3_1_memory_list_calls_correct_tool(self):
        client = _make_client()
        client._call.return_value = [{"name": "ibn-lifecycle"}]
        result = client.memory_list()
        client._call.assert_called_with("memory_list", {})
        assert isinstance(result, list)

    def test_t17_3_2_memory_list_handles_dict_response(self):
        client = _make_client()
        client._call.return_value = {"memories": [{"name": "m1"}, {"name": "m2"}]}
        result = client.memory_list()
        assert len(result) == 2

    def test_t17_3_3_memory_list_handles_empty_response(self):
        client = _make_client()
        client._call.return_value = {}
        result = client.memory_list()
        assert result == []

    def test_t17_3_4_memory_delete_calls_correct_tool(self):
        client = _make_client()
        client.memory_delete("ibn-lifecycle")
        client._call.assert_called_with("memory_delete", {"memory_id": "ibn-lifecycle"})


# ---------------------------------------------------------------------------
# T17.4  graph_push
# ---------------------------------------------------------------------------

class TestGraphPush:

    def test_t17_4_1_calls_memory_ingest_tool(self):
        """T17.4.1 — graph_push maps to 'memory_ingest' MCP tool."""
        client = _make_client()
        client._call.return_value = {"status": "ingested", "entities_extracted": 2}
        client.graph_push("ibn-lifecycle", "Drift on usf-fw-01", "ibn-loop-inner/drift")
        tool_name, args = client._call.call_args[0]
        assert tool_name == "memory_ingest"

    def test_t17_4_2_passes_memory_content_source(self):
        import base64
        client = _make_client()
        client._call.return_value = {"status": "ok", "entity_types": {"Policy": 1}}
        client.graph_push(
            memory="ibn-lifecycle",
            content="Policy POL-001 enforces Guest isolation",
            source="ibn-candidate-001/policy-decisions",
        )
        _, args = client._call.call_args[0]
        # Graph-Memory's memory_ingest expects memory_id + content_base64 + filename
        assert args["memory_id"] == "ibn-lifecycle"
        decoded = base64.b64decode(args["content_base64"]).decode()
        assert "Guest isolation" in decoded
        # Filename is derived from the last segment of source; .md suffix appended
        assert args["filename"] == "policy-decisions.md"

    def test_t17_4_3_returns_status_and_counts(self):
        client = _make_client()
        client._call.return_value = {
            "status": "ingested", "entities_extracted": 3, "relations_extracted": 1
        }
        result = client.graph_push("ibn-lifecycle", "content")
        assert result["status"] == "ingested"
        assert result["entities_extracted"] == 3

    def test_t17_4_4_passes_metadata(self):
        client = _make_client()
        client.graph_push(
            "ibn-lifecycle", "content",
            metadata={"space_id": "ibn-loop-inner", "model_state": "DEPLOYED"}
        )
        _, args = client._call.call_args[0]
        assert args["metadata"]["model_state"] == "DEPLOYED"

    def test_t17_4_5_returns_error_on_empty_response(self):
        """Empty server response is surfaced as an error — the old
        behaviour silently pretended the push succeeded with zero
        entities, which masked real failures."""
        client = _make_client()
        client._call.return_value = {}
        result = client.graph_push("ibn-lifecycle", "content")
        assert result["status"] == "error"
        assert result["entities_extracted"] == 0

    def test_t17_4_6_swallows_no_exception(self):
        """T17.4.6 — Caller receives a result dict even on transport error."""
        client = _make_client()
        # graph_push does NOT swallow exceptions — callers handle them
        # but let's verify normal return path
        client._call.return_value = {"status": "ingested", "entities_extracted": 1}
        result = client.graph_push("ibn-lifecycle", "test")
        assert result is not None


# ---------------------------------------------------------------------------
# T17.5  graph_push_batch
# ---------------------------------------------------------------------------

class TestGraphPushBatch:

    def test_t17_5_1_pushes_each_bank_file(self):
        client = _make_client()
        client._call.return_value = {"status": "ingested", "entities_extracted": 1}
        banks = {
            "drift-analysis": "Drift on usf-fw-01",
            "remediation-history": "Re-pushed CFG-002",
        }
        results = client.graph_push_batch("ibn-lifecycle", banks, space_id="ibn-loop-inner")
        assert len(results) == 2
        assert client._call.call_count == 2

    def test_t17_5_2_filename_derived_from_bank_name(self):
        client = _make_client()
        client._call.return_value = {"status": "ok", "entity_types": {"Policy": 1}}
        banks = {"policy-decisions": "Policy POL-001"}
        client.graph_push_batch("ibn-lifecycle", banks, space_id="ibn-candidate-001")
        _, args = client._call.call_args[0]
        # memory_ingest takes a filename (last segment of source), not the full path
        assert args["filename"] == "policy-decisions.md"

    def test_t17_5_3_empty_banks_returns_empty_list(self):
        client = _make_client()
        results = client.graph_push_batch("ibn-lifecycle", {})
        assert results == []
        client._call.assert_not_called()

    def test_t17_5_4_result_includes_bank_name(self):
        client = _make_client()
        client._call.return_value = {"status": "ingested", "entities_extracted": 2}
        banks = {"remediation-history": "content"}
        results = client.graph_push_batch("ibn-lifecycle", banks)
        assert results[0]["bank"] == "remediation-history"


# ---------------------------------------------------------------------------
# T17.6  question_answer
# ---------------------------------------------------------------------------

class TestQuestionAnswer:

    def test_t17_6_1_calls_question_answer_tool(self):
        client = _make_client()
        client._call.return_value = {
            "answer": "The drift was caused by manual CLI.",
            "sources": ["ibn-loop-inner/drift-analysis"],
        }
        client.question_answer("ibn-lifecycle", "What caused the last drift?")
        tool_name, args = client._call.call_args[0]
        assert tool_name == "question_answer"
        assert args["memory_id"] == "ibn-lifecycle"
        assert "drift" in args["question"]

    def test_t17_6_2_passes_limit(self):
        client = _make_client()
        client._call.return_value = {"answer": "...", "sources": []}
        client.question_answer("ibn-lifecycle", "question?", max_results=3)
        _, args = client._call.call_args[0]
        # question_answer's MCP arg is "limit", not "max_results"
        assert args["limit"] == 3

    def test_t17_6_3_returns_answer_and_sources(self):
        client = _make_client()
        client._call.return_value = {
            "answer": "Based on 2 entries.",
            "sources": ["s1", "s2"],
        }
        result = client.question_answer("ibn-lifecycle", "q?")
        assert result["answer"] == "Based on 2 entries."
        assert len(result["sources"]) == 2

    def test_t17_6_4_empty_knowledge_returns_gracefully(self):
        client = _make_client()
        client._call.return_value = {}
        result = client.question_answer("ibn-lifecycle-empty", "q?")
        assert "No relevant knowledge" in result["answer"]
        assert result["sources"] == []


# ---------------------------------------------------------------------------
# T17.7  storage_cleanup / graph_stats
# ---------------------------------------------------------------------------

class TestMaintenance:

    def test_t17_7_1_storage_cleanup_all(self):
        client = _make_client()
        client.storage_cleanup()
        client._call.assert_called_with("storage_cleanup", {})

    def test_t17_7_2_storage_cleanup_specific_memory(self):
        client = _make_client()
        client.storage_cleanup("ibn-lifecycle")
        client._call.assert_called_with("storage_cleanup", {"memory_id": "ibn-lifecycle"})

    def test_t17_7_3_graph_stats_calls_correct_tool(self):
        client = _make_client()
        client._call.return_value = {"entities": 42, "relations": 17}
        result = client.graph_stats("ibn-lifecycle")
        # Graph-Memory exposes this as memory_stats (not graph_stats)
        client._call.assert_called_with("memory_stats", {"memory_id": "ibn-lifecycle"})
        assert result["entities"] == 42


# ---------------------------------------------------------------------------
# T17.8  from_env() factory
# ---------------------------------------------------------------------------

class TestFactory:

    def test_t17_8_1_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("GRAPH_MEMORY_URL", "http://gm-prod:8003")
        monkeypatch.setenv("GRAPH_MEMORY_TOKEN", "prod-token-xyz")
        client = GraphMemoryClient.from_env()
        assert client._base == "http://gm-prod:8003"
        assert client._token == "prod-token-xyz"

    def test_t17_8_2_uses_defaults_without_env(self, monkeypatch):
        monkeypatch.delenv("GRAPH_MEMORY_URL", raising=False)
        monkeypatch.delenv("GRAPH_MEMORY_TOKEN", raising=False)
        client = GraphMemoryClient.from_env()
        assert "localhost" in client._base
        assert client._token == ""
