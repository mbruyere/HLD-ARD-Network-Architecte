"""
ConsolidationManager — Live-Memory → Graph-Memory bridge with lifecycle triggers.

Implements the consolidation pipeline described in §10.5 of the IBN Closed-Loop
Architecture document:

    live_note()  →  bank_consolidate()  →  graph_push()  →  question_answer()

Trigger points (§10.6):
  1. Model state transitions  — What-If→Candidate, Candidate→POR, POR→Deployed,
                                 Deployed→As-Built  (subscribe to event bus)
  2. Note count threshold     — prevents unbounded accumulation in a space
  3. Inner loop iteration     — consolidate ibn-loop-inner after each remediation
  4. Periodic sweep           — consolidate all active spaces on a schedule

After consolidation, bank files are pushed to Graph-Memory only when the model
state is POR or above (Deployed, As-Built) — this preserves graph quality by
ensuring only approved knowledge enters the long-term store.

Usage::

    from ibn.core.consolidation_manager import ConsolidationManager

    mgr = ConsolidationManager(live_memory, graph_memory, event_bus)
    mgr.start()   # subscribe to event bus, start periodic sweep

    # Manual trigger (e.g., from a state-machine controller)
    mgr.on_model_state_transition(
        from_state="CANDIDATE", to_state="POR",
        space_id="ibn-candidate-001"
    )

    mgr.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ibn.core.live_memory_client import LiveMemoryClient
from ibn.core.graph_memory_client import GraphMemoryClient

logger = logging.getLogger("ibn.consolidation")

# Model states that trigger Graph-Memory push after consolidation
_PUSH_ELIGIBLE_STATES = frozenset({"POR", "DEPLOYED", "AS_BUILT"})

# Default note count threshold before auto-consolidation
DEFAULT_NOTE_THRESHOLD = 20

# How often (seconds) the periodic sweep runs
DEFAULT_SWEEP_INTERVAL = 3600  # 1 hour

# Graph-Memory memory name
GRAPH_MEMORY_NAME = "ibn-lifecycle"

# Model state → which space to consolidate when transitioning
_TRANSITION_SPACE_MAP = {
    ("WHAT_IF", "CANDIDATE"):  "ibn-whatif",
    ("CANDIDATE", "POR"):      "ibn-candidate",
    ("POR", "DEPLOYED"):       "ibn-por",
    ("DEPLOYED", "AS_BUILT"):  "ibn-deploy",
}


class ConsolidationResult:
    """Carries the outcome of a consolidation + optional graph push."""

    def __init__(
        self,
        space_id: str,
        notes_consumed: int,
        banks_updated: int,
        pushed_to_graph: bool,
        push_results: Optional[list] = None,
        error: Optional[str] = None,
    ):
        self.space_id = space_id
        self.notes_consumed = notes_consumed
        self.banks_updated = banks_updated
        self.pushed_to_graph = pushed_to_graph
        self.push_results = push_results or []
        self.error = error
        self.ok = error is None

    def __repr__(self) -> str:
        return (
            f"ConsolidationResult(space={self.space_id!r} "
            f"notes={self.notes_consumed} banks={self.banks_updated} "
            f"graph={'yes' if self.pushed_to_graph else 'no'} "
            f"ok={self.ok})"
        )


class ConsolidationManager:
    """
    Orchestrates the Live-Memory → Graph-Memory consolidation pipeline.

    Parameters
    ----------
    live_memory:
        LiveMemoryClient (real or mock).
    graph_memory:
        GraphMemoryClient (real or mock).
    event_bus:
        EventBus / RedisEventBus / MockEventBus.  If supplied, the manager
        subscribes to ``model.state.transition`` and ``inner.loop.complete``
        events on start().
    note_threshold:
        Auto-consolidate a space when its note count exceeds this value.
    sweep_interval:
        Seconds between periodic sweeps (pass 0 to disable).
    push_to_graph:
        Whether to push consolidated banks to Graph-Memory.
        Set to False in test environments without a real Graph-Memory instance.
    """

    def __init__(
        self,
        live_memory: LiveMemoryClient,
        graph_memory: GraphMemoryClient,
        event_bus=None,
        note_threshold: int = DEFAULT_NOTE_THRESHOLD,
        sweep_interval: int = DEFAULT_SWEEP_INTERVAL,
        push_to_graph: bool = True,
    ):
        self._lm = live_memory
        self._gm = graph_memory
        self._bus = event_bus
        self._note_threshold = note_threshold
        self._sweep_interval = sweep_interval
        self._push_to_graph = push_to_graph

        self._running = False
        self._sweep_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to event bus and start periodic sweep thread."""
        if self._bus is not None:
            self._bus.subscribe("model.state.transition", self._on_state_transition_event)
            self._bus.subscribe("inner.loop.complete", self._on_inner_loop_complete_event)
            logger.info("ConsolidationManager: subscribed to event bus")

        if self._sweep_interval > 0:
            self._running = True
            self._sweep_thread = threading.Thread(
                target=self._sweep_loop,
                name="consolidation-sweep",
                daemon=True,
            )
            self._sweep_thread.start()
            logger.info(
                "ConsolidationManager: periodic sweep every %ds", self._sweep_interval
            )

    def stop(self) -> None:
        """Stop the periodic sweep thread."""
        self._running = False
        if self._sweep_thread and self._sweep_thread.is_alive():
            self._sweep_thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Primary trigger: model state transition
    # ------------------------------------------------------------------

    def on_model_state_transition(
        self,
        from_state: str,
        to_state: str,
        space_id: str,
        push_override: Optional[bool] = None,
    ) -> ConsolidationResult:
        """
        Consolidate the space associated with *from_state* and optionally push
        the resulting bank files to Graph-Memory.

        Graph-Memory push is performed when *to_state* ∈ {POR, DEPLOYED, AS_BUILT}.

        Parameters
        ----------
        from_state / to_state:
            Model state strings (WHAT_IF, CANDIDATE, POR, DEPLOYED, AS_BUILT).
        space_id:
            The Live-Memory space to consolidate (e.g. ``"ibn-candidate-001"``).
        push_override:
            If True, always push to Graph-Memory regardless of to_state.
            If False, never push.  If None, apply the default eligibility rule.
        """
        logger.info(
            "State transition %s→%s: consolidating space %s",
            from_state, to_state, space_id,
        )
        should_push = (
            push_override
            if push_override is not None
            else (to_state in _PUSH_ELIGIBLE_STATES and self._push_to_graph)
        )
        return self._consolidate_and_push(space_id, push=should_push)

    # ------------------------------------------------------------------
    # Trigger: inner loop cycle complete
    # ------------------------------------------------------------------

    def on_inner_loop_complete(self) -> ConsolidationResult:
        """Consolidate ``ibn-loop-inner`` after each remediation cycle."""
        logger.info("Inner loop complete: consolidating ibn-loop-inner")
        return self._consolidate_and_push("ibn-loop-inner", push=self._push_to_graph)

    # ------------------------------------------------------------------
    # Trigger: note count threshold
    # ------------------------------------------------------------------

    def check_note_threshold(self, space_id: str) -> Optional[ConsolidationResult]:
        """
        Consolidate *space_id* if its note count exceeds the threshold.

        Returns a ConsolidationResult if consolidation was triggered, else None.
        """
        notes = self._lm.note_list(space_id)
        if len(notes) >= self._note_threshold:
            logger.info(
                "Note threshold (%d) exceeded in %s (%d notes) — consolidating",
                self._note_threshold, space_id, len(notes),
            )
            return self._consolidate_and_push(space_id, push=False)
        return None

    # ------------------------------------------------------------------
    # Core consolidation + push
    # ------------------------------------------------------------------

    def _consolidate_and_push(
        self,
        space_id: str,
        push: bool,
    ) -> ConsolidationResult:
        """
        1. Call ``bank_consolidate()`` on the space.
        2. If *push* is True, read all bank files and ingest them into Graph-Memory.
        """
        # Step 1 — consolidate
        try:
            cresult = self._lm.bank_consolidate(space_id)
        except Exception as exc:
            logger.error("bank_consolidate(%s) failed: %s", space_id, exc)
            return ConsolidationResult(
                space_id=space_id,
                notes_consumed=0,
                banks_updated=0,
                pushed_to_graph=False,
                error=str(exc),
            )

        notes_consumed = cresult.get("notes_consumed", 0)
        banks_updated = cresult.get("banks_updated", 0)
        status = cresult.get("status", "")

        if status == "no_notes":
            logger.debug("No notes to consolidate in %s", space_id)
            return ConsolidationResult(
                space_id=space_id,
                notes_consumed=0,
                banks_updated=0,
                pushed_to_graph=False,
            )

        logger.info(
            "Consolidated %s: %d notes → %d bank files",
            space_id, notes_consumed, banks_updated,
        )

        # Step 2 — push to Graph-Memory
        push_results: list = []
        pushed = False

        if push:
            try:
                banks = self._lm.bank_read_all(space_id)
                if banks:
                    self._ensure_memory_exists()
                    push_results = self._gm.graph_push_batch(
                        memory=GRAPH_MEMORY_NAME,
                        bank_files=banks,
                        space_id=space_id,
                    )
                    pushed = True
                    total_entities = sum(r.get("entities_extracted", 0) for r in push_results)
                    logger.info(
                        "Pushed %d bank files from %s → %s (%d entities)",
                        len(banks), space_id, GRAPH_MEMORY_NAME, total_entities,
                    )
            except Exception as exc:
                logger.error("graph_push_batch(%s) failed: %s", space_id, exc)
                return ConsolidationResult(
                    space_id=space_id,
                    notes_consumed=notes_consumed,
                    banks_updated=banks_updated,
                    pushed_to_graph=False,
                    push_results=push_results,
                    error=str(exc),
                )

        return ConsolidationResult(
            space_id=space_id,
            notes_consumed=notes_consumed,
            banks_updated=banks_updated,
            pushed_to_graph=pushed,
            push_results=push_results,
        )

    def _ensure_memory_exists(self) -> None:
        """Create the ``ibn-lifecycle`` memory if it doesn't exist yet."""
        try:
            memories = self._gm.memory_list()
            names = {m.get("name") for m in memories}
            if GRAPH_MEMORY_NAME not in names:
                self._gm.memory_create(GRAPH_MEMORY_NAME)
                logger.info("Created Graph-Memory '%s'", GRAPH_MEMORY_NAME)
        except Exception as exc:
            logger.warning("Could not verify Graph-Memory existence: %s", exc)

    # ------------------------------------------------------------------
    # Event bus handlers
    # ------------------------------------------------------------------

    def _on_state_transition_event(self, event: dict) -> None:
        """Handle ``model.state.transition`` events from the event bus."""
        payload = event.get("payload", {})
        from_state = payload.get("from_state", "")
        to_state = payload.get("to_state", "")
        space_id = payload.get("space_id", "")
        if from_state and to_state and space_id:
            self.on_model_state_transition(from_state, to_state, space_id)
        else:
            logger.warning("model.state.transition event missing fields: %s", payload)

    def _on_inner_loop_complete_event(self, event: dict) -> None:
        """Handle ``inner.loop.complete`` events from the event bus."""
        self.on_inner_loop_complete()

    # ------------------------------------------------------------------
    # Periodic sweep
    # ------------------------------------------------------------------

    def _sweep_loop(self) -> None:
        """Periodically consolidate all active Live-Memory spaces."""
        while self._running:
            try:
                self._sweep_once()
            except Exception as exc:
                logger.error("Consolidation sweep failed: %s", exc)
            time.sleep(self._sweep_interval)

    def _sweep_once(self) -> list[ConsolidationResult]:
        """Consolidate all spaces that have notes above the threshold."""
        results = []
        try:
            spaces = self._lm.space_list()
        except Exception as exc:
            logger.warning("Could not list Live-Memory spaces: %s", exc)
            return results

        for space in spaces:
            space_id = space.get("name") or space.get("space_id", "")
            if not space_id:
                continue
            result = self.check_note_threshold(space_id)
            if result:
                results.append(result)

        return results

    # ------------------------------------------------------------------
    # Query helper (delegates to Graph-Memory)
    # ------------------------------------------------------------------

    def query_knowledge(self, question: str, max_results: int = 5) -> dict:
        """
        Ask a question against the ``ibn-lifecycle`` knowledge graph.

        Convenience wrapper so agents don't need a direct reference to
        ``GraphMemoryClient``.
        """
        return self._gm.question_answer(
            memory=GRAPH_MEMORY_NAME,
            question=question,
            max_results=max_results,
        )
