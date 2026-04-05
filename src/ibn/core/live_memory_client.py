"""
Live-Memory MCP HTTP client (Tier 2 working memory).

Wraps the Live-Memory Streamable-HTTP MCP endpoints:
  POST /space/create       → space_create()
  GET  /space/list         → space_list()
  POST /note               → live_note()
  GET  /note/list          → note_list()
  POST /bank/consolidate   → bank_consolidate()
  GET  /bank/read-all      → bank_read_all()
  POST /token/create       → token_create()

All calls carry a bearer token in the Authorization header.

Usage::

    client = LiveMemoryClient.from_env()
    client.live_note("ibn-candidate-001", "Intent ingested", "intent-ingestion")
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class LiveMemoryClient:
    """Synchronous Live-Memory MCP client."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "LiveMemoryClient":
        return cls(
            base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
            token=os.environ.get("LIVE_MEMORY_TOKEN", ""),
        )

    def _post(self, path: str, body: dict) -> dict:
        resp = httpx.post(f"{self._base}{path}", json=body, headers=self._headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict = None) -> Any:
        resp = httpx.get(f"{self._base}{path}", params=params or {}, headers=self._headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Space management
    # ------------------------------------------------------------------

    def space_create(
        self,
        name: str,
        description: str = "",
        consolidation_rules: Optional[dict] = None,
    ) -> dict:
        return self._post("/space/create", {
            "name": name,
            "description": description,
            "consolidation_rules": consolidation_rules or {},
        })

    def space_list(self) -> list[dict]:
        return self._get("/space/list")

    def space_rules(self, name: str) -> dict:
        return self._get("/space/rules", {"name": name})

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def live_note(self, space: str, content: str, category: str = "general") -> dict:
        return self._post("/note", {"space": space, "content": content, "category": category})

    def note_list(self, space: str) -> list[dict]:
        return self._get("/note/list", {"space": space})

    # ------------------------------------------------------------------
    # Bank (consolidation)
    # ------------------------------------------------------------------

    def bank_consolidate(self, space: str) -> dict:
        return self._post("/bank/consolidate", {"space": space})

    def bank_read_all(self, space: str) -> dict:
        return self._get("/bank/read-all", {"space": space})

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def token_create(self, name: str, role: str = "agent") -> dict:
        return self._post("/token/create", {"name": name, "role": role})
