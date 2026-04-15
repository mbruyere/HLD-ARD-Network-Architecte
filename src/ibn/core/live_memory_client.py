"""
Live-Memory MCP client (Tier 2 working memory).

Wraps the Live-Memory Streamable-HTTP MCP server using the official MCP SDK.
Provides a synchronous interface so agents don't need async/await.

The real server speaks MCP Streamable HTTP (POST /mcp).
Unit tests inject MockLiveMemoryClient instead of this class.

MCP tools exposed by Live-Memory:
  space_create   → create a memory space
  space_list     → list all spaces
  live_note      → append a note to a space
  note_list      → list notes in a space
  bank_consolidate → trigger LLM consolidation
  bank_read_all  → read all bank files in a space

Usage::

    client = LiveMemoryClient.from_env()
    client.live_note("ibn-loop-inner", "Drift detected on usf-fw-01", "drift-detection")
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Persistent background event loop
# ---------------------------------------------------------------------------
# On Python 3.14.3 + mcp 1.27 + httpx 0.28 + anyio 4.13, calling
# ``asyncio.run(coro)`` where ``coro`` uses ``streamablehttp_client`` hangs
# in the teardown phase — the coroutine returns but the loop never closes.
# Process exit short-circuits the hang, which is why one-shot scripts
# work but library code embedded in longer-lived processes stalls.
#
# The fix: keep a single event loop alive in a daemon background thread
# for the process lifetime. Submit each MCP coroutine to that loop via
# ``asyncio.run_coroutine_threadsafe``. The loop never tears down, so the
# asyncio.run teardown bug can't trigger. Each coroutine's own ``async
# with streamablehttp_client`` cleans up inline via its TaskGroup before
# the future resolves.
# ---------------------------------------------------------------------------

import atexit as _atexit
import threading as _threading

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[_threading.Thread] = None
_loop_lock = _threading.Lock()


def _shutdown_background_loop() -> None:
    """Stop the background loop cleanly on interpreter exit.

    Without this, Python 3.14 can segfault (cosmetic, after all work
    is done) as it tears down the daemon thread while the loop is
    still running. We stop the loop via call_soon_threadsafe, then
    the runner returns and the thread exits naturally.
    """
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
    """Lazily start a daemon thread running a persistent event loop."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()

        def _runner(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _loop_thread = _threading.Thread(
            target=_runner, args=(_loop,), daemon=True, name="ibn-mcp-loop",
        )
        _loop_thread.start()
        _atexit.register(_shutdown_background_loop)
        return _loop


def _run(coro_factory, *args, **kwargs):
    """Run an async function synchronously via a persistent background loop.

    ``coro_factory`` can be an async callable (preferred — coroutine is
    created inside the background loop) or a pre-created coroutine
    (accepted for backward-compat).

    See the module-level comment above ``_get_background_loop`` for the
    Python 3.14 anyio TaskGroup / asyncio.run teardown bug this works
    around.
    """
    loop = _get_background_loop()

    async def _wrapper():
        if asyncio.iscoroutine(coro_factory):
            return await coro_factory
        coro = coro_factory(*args, **kwargs)
        return await coro

    future = asyncio.run_coroutine_threadsafe(_wrapper(), loop)
    return future.result(timeout=120)


async def _call_mcp_tool(base_url: str, token: str, tool_name: str, arguments: dict) -> Any:
    """Call a single Live-Memory MCP tool via Streamable HTTP."""
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        raise ImportError(
            "mcp package not found. Install with: pip install mcp>=1.8.0\n"
            "Or use MockLiveMemoryClient for unit tests."
        )

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    mcp_url = f"{base_url.rstrip('/')}/mcp"

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    # Unwrap content blocks (MCP returns list of TextContent)
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
# Client
# ---------------------------------------------------------------------------

# Valid categories in the Live-Memory MCP server
_VALID_CATEGORIES = frozenset({
    "observation", "decision", "todo", "insight", "question", "progress", "issue"
})

# Map internal agent category names → valid MCP category
_CATEGORY_MAP = {
    "general":              "observation",
    "deployment-start":     "progress",
    "device-result":        "observation",
    "rollback-triggered":   "issue",
    "rollback-result":      "observation",
    "verification-result":  "observation",
    "drift-detection":      "observation",
    "remediation":          "decision",
    "alert":                "issue",
    "intent-ingestion":     "progress",
    "conflict-check":       "observation",
    "monitoring":           "observation",
    "assessment":           "observation",
    "escalation":           "issue",
    "telemetry":            "observation",
}


def _normalize_category(category: str) -> str:
    """Map an internal agent category to a valid MCP Live-Memory category."""
    if category in _VALID_CATEGORIES:
        return category
    return _CATEGORY_MAP.get(category, "observation")


class LiveMemoryClient:
    """
    Synchronous Live-Memory MCP client.

    All methods call the MCP server via Streamable HTTP.
    Valid note categories: observation | decision | todo | insight | question | progress | issue
    For unit tests, use MockLiveMemoryClient from tests/conftest.py instead.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 60.0):
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "LiveMemoryClient":
        return cls(
            base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
            token=os.environ.get(
                "LIVE_MEMORY_TOKEN",
                os.environ.get("LM_AGENT_TOKEN", ""),
            ),
        )

    def _call(self, tool: str, args: dict) -> Any:
        # Pass the factory, not a pre-created coroutine — see _run() docstring.
        return _run(_call_mcp_tool, self._base, self._token, tool, args)

    # ------------------------------------------------------------------
    # Space management
    # ------------------------------------------------------------------

    def space_create(
        self,
        space_id: str,
        description: str = "",
        owner: str = "ibn-system",
        rules: str = "",
    ) -> dict:
        return self._call("space_create", {
            "space_id":    space_id,
            "description": description,
            "owner":       owner,
            "rules":       rules,
        })

    def space_list(self) -> list[dict]:
        result = self._call("space_list", {})
        if isinstance(result, list):
            return result
        return result.get("spaces", []) if isinstance(result, dict) else []

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def live_note(self, space: str, content: str, category: str = "observation") -> dict:
        mcp_category = _normalize_category(category)
        result = self._call("live_note", {
            "space_id": space,
            "content":  content,
            "category": mcp_category,
        })
        if isinstance(result, dict):
            result.setdefault("category", category)   # preserve original for callers
            result.setdefault("content", content)
        return result if isinstance(result, dict) else {"category": category, "content": content}

    def note_list(self, space: str, limit: int = 50) -> list[dict]:
        """List recent notes in a space (uses live_read MCP tool)."""
        result = self._call("live_read", {"space_id": space, "limit": limit})
        if isinstance(result, list):
            return result
        return result.get("notes", []) if isinstance(result, dict) else []

    # ------------------------------------------------------------------
    # Bank (consolidation)
    # ------------------------------------------------------------------

    def bank_consolidate(self, space: str) -> dict:
        result = self._call("bank_consolidate", {"space_id": space})
        return result if isinstance(result, dict) else {}

    def bank_read_all(self, space: str) -> dict:
        """Read every bank file in a space.

        Returns a flat ``{filename: content}`` mapping. Live-Memory's raw
        response wraps the files in a ``files`` list; we unwrap it so callers
        can iterate ``bank_files.items()`` directly.
        """
        result = self._call("bank_read_all", {"space_id": space})
        if not isinstance(result, dict):
            return {}
        files = result.get("files")
        if isinstance(files, list):
            return {
                f["filename"]: f.get("content", "")
                for f in files
                if isinstance(f, dict) and "filename" in f
            }
        # Fallback: if the server already returned a flat mapping, pass through.
        return result

    # ------------------------------------------------------------------
    # Tokens (admin only — requires admin token)
    # ------------------------------------------------------------------

    def token_create(self, name: str, role: str = "agent") -> dict:
        result = self._call("admin_create_token", {"name": name, "role": role})
        return result if isinstance(result, dict) else {}
