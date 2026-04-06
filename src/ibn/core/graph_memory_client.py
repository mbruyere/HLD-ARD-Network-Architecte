"""
Graph-Memory MCP client (Tier 3 long-term knowledge graph).

Wraps the Graph-Memory Streamable-HTTP MCP server (Cloud-Temple) using the
official MCP SDK.  Provides a synchronous interface that mirrors the
Live-Memory client so agents don't need async/await.

Graph-Memory stores ontology-driven knowledge extracted from Live-Memory bank
files.  It exposes graph-guided RAG via ``question_answer()``, which traverses
the typed entity graph before falling back to Qdrant vector search.

Architecture fit:
  Tier 1: Neo4j SSoT    — WHAT the network IS
  Tier 2: Live-Memory   — WHY it is in that state  (live_note → bank_consolidate)
  Tier 3: Graph-Memory  — WHAT WAS LEARNED         (graph_push → question_answer)

Namespace isolation: every node in the knowledge graph carries the prefix
``IBN_LIFECYCLE_`` so it never collides with the 9-layer SSoT ontology that
lives in the same Neo4j instance.

Key MCP tools (Graph-Memory exposes ≈ 30):
  memory_create   → create a named memory with an ontology
  memory_list     → list all memories
  memory_ingest   → push content for entity/relation extraction (BGE-M3 embeddings)
  question_answer → graph-guided RAG query
  storage_cleanup → remove orphaned S3 objects

Usage::

    gm = GraphMemoryClient.from_env()
    gm.memory_create("ibn-lifecycle", ontology_path="src/ibn/ontology/ibn_lifecycle_ontology.yaml")
    gm.graph_push("ibn-lifecycle", content="Drift REM-001 on usf-fw-01 …", source="ibn-loop-inner/drift")
    answer = gm.question_answer("ibn-lifecycle", "What caused the last USF drift?")
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("ibn.graph_memory")

NAMESPACE_PREFIX = "IBN_LIFECYCLE_"


# ---------------------------------------------------------------------------
# Async MCP transport helpers  (copied pattern from live_memory_client)
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously, reusing a running loop when available."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _call_mcp_tool(base_url: str, token: str, tool_name: str, arguments: dict) -> Any:
    """Call a single Graph-Memory MCP tool via Streamable HTTP."""
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        raise ImportError(
            "mcp package not found. Install with: pip install mcp>=1.8.0"
        )

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    mcp_url = f"{base_url.rstrip('/')}/mcp"

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if hasattr(result, "content") and result.content:
        import json
        block = result.content[0]
        text = block.text if hasattr(block, "text") else str(block)
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text

    return {}


# ---------------------------------------------------------------------------
# GraphMemoryClient
# ---------------------------------------------------------------------------

class GraphMemoryClient:
    """
    Synchronous Graph-Memory MCP client.

    All methods call the Graph-Memory MCP server via Streamable HTTP.
    For unit tests, substitute MockGraphMemoryClient (defined in conftest.py).

    Namespace convention: every memory created by this client uses the
    ``IBN_LIFECYCLE_`` prefix for Neo4j labels, ensuring complete isolation
    from the 9-layer SSoT ontology.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 120.0):
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "GraphMemoryClient":
        return cls(
            base_url=os.environ.get("GRAPH_MEMORY_URL", "http://localhost:8003"),
            token=os.environ.get("GRAPH_MEMORY_TOKEN", ""),
        )

    def _call(self, tool: str, args: dict) -> Any:
        return _run(_call_mcp_tool(self._base, self._token, tool, args))

    # ------------------------------------------------------------------
    # Memory management
    # ------------------------------------------------------------------

    def memory_create(
        self,
        name: str,
        ontology_path: Optional[str] = None,
        description: str = "",
    ) -> dict:
        """
        Create a named memory namespace in Graph-Memory.

        Parameters
        ----------
        name:
            Memory name (e.g. ``"ibn-lifecycle"``).  All Neo4j labels will be
            prefixed with ``IBN_LIFECYCLE_`` automatically.
        ontology_path:
            Path to a YAML ontology file that guides entity/relation extraction.
            If omitted, Graph-Memory uses its default general ontology.
        description:
            Human-readable description stored with the memory.
        """
        args: dict = {"name": name, "description": description}
        if ontology_path:
            args["ontology_path"] = ontology_path
        result = self._call("memory_create", args)
        return result if isinstance(result, dict) else {"status": "created", "memory": name}

    def memory_list(self) -> list[dict]:
        """Return all memories registered in Graph-Memory."""
        result = self._call("memory_list", {})
        if isinstance(result, list):
            return result
        return result.get("memories", []) if isinstance(result, dict) else []

    def memory_delete(self, name: str) -> dict:
        """Delete a memory namespace (removes all Neo4j nodes and Qdrant embeddings)."""
        result = self._call("memory_delete", {"name": name})
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Content ingestion  (Live-Memory bank → Graph-Memory knowledge graph)
    # ------------------------------------------------------------------

    def graph_push(
        self,
        memory: str,
        content: str,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Push Markdown content to Graph-Memory for ontology-driven extraction.

        Graph-Memory runs an LLM extraction pipeline that:
          1. Identifies entities typed by the memory's ontology.
          2. Extracts typed relationships between entities.
          3. Stores entities/relations as Neo4j nodes with ``IBN_LIFECYCLE_*`` labels.
          4. Creates BGE-M3 1024-dim vector embeddings in Qdrant.

        Parameters
        ----------
        memory:
            Target memory name (must exist — call ``memory_create`` first).
        content:
            Markdown text to ingest (typically a bank file from Live-Memory).
        source:
            Origin identifier, e.g. ``"ibn-loop-inner/remediation-history"``.
        metadata:
            Optional key/value metadata attached to the ingested document.

        Returns
        -------
        dict with keys: ``status``, ``entities_extracted``, ``relations_extracted``.
        """
        args: dict = {
            "memory": memory,
            "content": content,
            "source": source,
        }
        if metadata:
            args["metadata"] = metadata
        result = self._call("memory_ingest", args)
        if isinstance(result, dict) and result:
            result.setdefault("status", "ingested")
            result.setdefault("entities_extracted", 0)
            result.setdefault("relations_extracted", 0)
            return result
        return {"status": "ingested", "entities_extracted": 0, "relations_extracted": 0}

    def graph_push_batch(
        self,
        memory: str,
        bank_files: dict[str, str],
        space_id: str = "",
    ) -> list[dict]:
        """
        Push all bank files from a Live-Memory space to Graph-Memory.

        Parameters
        ----------
        memory:
            Target Graph-Memory memory name.
        bank_files:
            Mapping of ``{bank_name: content}`` returned by
            ``LiveMemoryClient.bank_read_all()``.
        space_id:
            Live-Memory space the bank files came from (used as source prefix).

        Returns
        -------
        List of per-file ingest results.
        """
        results = []
        for bank_name, content in bank_files.items():
            source = f"{space_id}/{bank_name}" if space_id else bank_name
            result = self.graph_push(memory=memory, content=content, source=source)
            results.append({**result, "bank": bank_name})
            logger.info(
                "graph_push: memory=%s bank=%s entities=%s",
                memory, bank_name, result.get("entities_extracted", "?"),
            )
        return results

    # ------------------------------------------------------------------
    # Graph-guided RAG
    # ------------------------------------------------------------------

    def question_answer(
        self,
        memory: str,
        question: str,
        max_results: int = 5,
    ) -> dict:
        """
        Query the knowledge graph using graph-guided RAG.

        Graph-Memory first identifies relevant entities in Neo4j (fuzzy + semantic
        search), then constrains the Qdrant vector search to only documents linked
        to those entities.  This produces precise, context-filtered answers rather
        than noisy pure-vector results.

        Parameters
        ----------
        memory:
            Memory to query.
        question:
            Natural-language question, e.g.
            ``"What happened last time the USF firewall drifted?"``.
        max_results:
            Maximum number of source documents to include in the answer.

        Returns
        -------
        dict with keys: ``answer`` (str) and ``sources`` (list[str]).
        """
        args = {"memory": memory, "question": question, "max_results": max_results}
        result = self._call("question_answer", args)
        if isinstance(result, dict):
            result.setdefault("answer", "No relevant knowledge found.")
            result.setdefault("sources", [])
            return result
        return {"answer": "No relevant knowledge found.", "sources": []}

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def storage_cleanup(self, memory: Optional[str] = None) -> dict:
        """
        Remove orphaned S3 objects.

        Parameters
        ----------
        memory:
            If given, clean up only this memory's storage.  Otherwise clean all.
        """
        args = {}
        if memory:
            args["memory"] = memory
        result = self._call("storage_cleanup", args)
        return result if isinstance(result, dict) else {}

    def graph_stats(self, memory: str) -> dict:
        """Return entity/relation counts and embedding statistics for a memory."""
        result = self._call("graph_stats", {"memory": memory})
        return result if isinstance(result, dict) else {}
