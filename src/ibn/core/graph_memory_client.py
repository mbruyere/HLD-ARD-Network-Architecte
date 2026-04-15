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
import base64
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("ibn.graph_memory")

NAMESPACE_PREFIX = "IBN_LIFECYCLE_"

# Default ontology when none is specified. Graph-Memory ships with a fixed
# set of built-in ontologies (general, cloud, legal, managed-services,
# presales, software-development). The ibn-lifecycle ontology lives in
# src/ibn/ontology/ibn_lifecycle_ontology.yaml but is not yet installed
# in the Graph-Memory container, so we fall back to "general".
DEFAULT_ONTOLOGY = "general"


# ---------------------------------------------------------------------------
# Async MCP transport helpers  (copied pattern from live_memory_client)
# ---------------------------------------------------------------------------

import atexit as _atexit
import threading as _threading

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[_threading.Thread] = None
_loop_lock = _threading.Lock()


def _shutdown_background_loop() -> None:
    global _loop, _loop_thread
    loop = _loop
    thread = _loop_thread
    if loop is not None and not loop.is_closed() and loop.is_running():
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    if loop is not None and not loop.is_closed():
        try:
            loop.close()
        except Exception:
            pass


def _get_background_loop() -> asyncio.AbstractEventLoop:
    """Persistent daemon-thread event loop — see ``live_memory_client``
    for the Python 3.14 + anyio TaskGroup / asyncio.run teardown bug
    this works around."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()

        def _runner(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _loop_thread = _threading.Thread(
            target=_runner, args=(_loop,), daemon=True, name="ibn-gm-loop",
        )
        _loop_thread.start()
        _atexit.register(_shutdown_background_loop)
        return _loop


def _run(coro_factory, *args, **kwargs):
    """Submit an async function to the persistent background loop."""
    loop = _get_background_loop()

    async def _wrapper():
        if asyncio.iscoroutine(coro_factory):
            return await coro_factory
        coro = coro_factory(*args, **kwargs)
        return await coro

    future = asyncio.run_coroutine_threadsafe(_wrapper(), loop)
    return future.result(timeout=120)


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
            # Not JSON — Graph-Memory returns plain-text error messages when
            # MCP tool arguments fail pydantic validation. Surface them as a
            # structured error dict so callers can detect the failure.
            if text.startswith("Error"):
                return {"status": "error", "message": text}
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
        # Pass factory (not a pre-created coroutine) — see _run() docstring.
        return _run(_call_mcp_tool, self._base, self._token, tool, args)

    # ------------------------------------------------------------------
    # Memory management
    # ------------------------------------------------------------------

    def memory_create(
        self,
        name: str,
        ontology: str = DEFAULT_ONTOLOGY,
        description: str = "",
    ) -> dict:
        """
        Create a named memory namespace in Graph-Memory.

        Parameters
        ----------
        name:
            Memory identifier (e.g. ``"ibn-lifecycle"``). Used as both the
            MCP ``memory_id`` and display name.
        ontology:
            Name of a built-in Graph-Memory ontology. One of:
            ``general``, ``cloud``, ``legal``, ``managed-services``,
            ``presales``, ``software-development``. Defaults to ``general``.
        description:
            Human-readable description stored with the memory.
        """
        args: dict = {
            "memory_id": name,
            "name": name,
            "ontology": ontology,
        }
        if description:
            args["description"] = description
        result = self._call("memory_create", args)
        return result if isinstance(result, dict) else {"status": "created", "memory": name}

    def memory_list(self) -> list[dict]:
        """Return all memories registered in Graph-Memory.

        Each entry is normalised to include both ``id`` and ``name`` keys so
        callers can use either.
        """
        result = self._call("memory_list", {})
        if isinstance(result, list):
            memories = result
        elif isinstance(result, dict):
            memories = result.get("memories", [])
        else:
            memories = []
        # Graph-Memory returns ``id`` for the memory identifier — expose it
        # as ``name`` too so callers that key on "name" still work.
        for m in memories:
            if "name" not in m and "id" in m:
                m["name"] = m["id"]
        return memories

    def memory_delete(self, name: str) -> dict:
        """Delete a memory namespace (removes all Neo4j nodes and Qdrant embeddings)."""
        result = self._call("memory_delete", {"memory_id": name})
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
        # Graph-Memory's memory_ingest expects base64-encoded content and a
        # filename (not a "source" string). Derive the filename from the
        # source path if provided, otherwise use a generic bank name.
        filename = source.rsplit("/", 1)[-1] if source else "bank.md"
        if not filename.endswith((".md", ".txt", ".pdf", ".docx")):
            filename = f"{filename}.md"

        args: dict = {
            "memory_id": memory,
            "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "filename": filename,
        }
        if metadata:
            args["metadata"] = metadata

        result = self._call("memory_ingest", args)

        if not isinstance(result, dict) or not result:
            return {"status": "error", "entities_extracted": 0, "relations_extracted": 0,
                    "message": "empty response from memory_ingest"}

        # Error responses from the server have status=error. Pass them through
        # so callers can detect failures instead of silently reporting success.
        if result.get("status") == "error":
            result.setdefault("entities_extracted", 0)
            result.setdefault("relations_extracted", 0)
            logger.warning("memory_ingest failed: %s", result.get("message", result))
            return result

        # Graph-Memory returns entity_types / relation_types as
        # {type_name: count} maps. Sum the counts to produce the
        # flat entities_extracted / relations_extracted keys the rest
        # of the codebase expects.
        entity_types = result.get("entity_types") or {}
        relation_types = result.get("relation_types") or {}
        if isinstance(entity_types, dict):
            result.setdefault("entities_extracted", sum(entity_types.values()))
        else:
            result.setdefault("entities_extracted", 0)
        if isinstance(relation_types, dict):
            result.setdefault("relations_extracted", sum(relation_types.values()))
        else:
            result.setdefault("relations_extracted", 0)
        # Normalise server's "ok" / missing status to the "ingested" contract
        # that the rest of the IBN codebase expects.
        if result.get("status") != "error":
            result["status"] = "ingested"
        return result

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
        args = {"memory_id": memory, "question": question, "limit": max_results}
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
            args["memory_id"] = memory
        result = self._call("storage_cleanup", args)
        return result if isinstance(result, dict) else {}

    def graph_stats(self, memory: str) -> dict:
        """Return entity/relation counts and embedding statistics for a memory."""
        result = self._call("memory_stats", {"memory_id": memory})
        return result if isinstance(result, dict) else {}
