"""
Agent 1 — Intent Ingestion  (RFC 9315 §5.1.1, §4.2)

Responsibilities:
  1. Parse and validate structured intent templates (Phase 1)
  2. Parse HLD markdown sections into draft Intents (Slice 1 — population
     VLAN table; Slice 5 will extend to the rest of the document)
  3. Refine drafts via interactive operator dialogue (RFC 9315 §4.2)
  4. Conflict detection against active POR intents in Neo4j
  5. Create Intent nodes (L4) in CANDIDATE modelState
  6. Emit live_note() to the appropriate Live-Memory candidate space
  7. Publish intent.ingested event on the event bus
  8. Record AgentExecution audit node (L9)

Entry points
------------

Structured-template ingestion (existing API)::

    agent = Agent1Ingestion(neo4j, live_memory)
    result = agent.run(
        intent_data={...},
        candidate_space="ibn-candidate-001",
    )

HLD-driven ingestion (Slice 1)::

    agent = Agent1Ingestion(neo4j, live_memory)
    result = agent.ingest_hld_changeset(
        changeset=changeset,                # from ibn.parser.hld_parser
        source_path="Enterprise_Campus_Network_HLD (1).md",
        candidate_space="ibn-candidate-001",
        dialogue_fn=cli_dialogue,           # callable[[prompt], answer]; mockable
    )
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import (
    Intent, ModelState, VALID_INTENT_ACTIONS,
    Device, DeviceLifecycleState,
)


class ConflictError(ValueError):
    """Raised when a new intent conflicts with an existing active intent."""


class Agent1Ingestion(BaseAgent):

    AGENT_ID   = "A1"
    AGENT_NAME = "Ingestion"

    # ------------------------------------------------------------------
    # Required fields for structured template ingestion
    # ------------------------------------------------------------------
    _REQUIRED_FIELDS = {"type", "subject", "action", "target"}

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        intent_data:      dict = kwargs["intent_data"]
        candidate_space:  str  = kwargs.get("candidate_space", "ibn-candidate-001")
        author_id:        Optional[str] = kwargs.get("author_id")

        # 1. Validate
        intent = self._validate(intent_data, author_id)

        # 2. Conflict detection
        conflict = self._detect_conflict(intent)
        if conflict:
            self._note(
                candidate_space,
                f"CONFLICT: {intent.intentId} conflicts with {conflict['existing_intent']} "
                f"— {conflict['detail']}",
                category="conflict-detection",
            )
            raise ConflictError(
                f"Intent {intent.intentId} conflicts with {conflict['existing_intent']}: "
                f"{conflict['detail']}"
            )

        # 3. Persist to Neo4j (L4)
        self._neo4j.create_intent(intent)

        # 4. Live-Memory note
        self._note(
            candidate_space,
            f"Intent {intent.intentId} ingested: "
            f"{intent.subject} → {intent.action} → {intent.target}",
            category="intent-ingestion",
        )

        # 5. Publish event
        self._publish("intent.ingested", {
            "intentId":   intent.intentId,
            "subject":    intent.subject,
            "action":     intent.action,
            "target":     intent.target,
            "modelState": intent.modelState.value,
        })

        return {
            "id":          intent.intentId,
            "intentId":    intent.intentId,
            "status":      intent.status,
            "modelState":  intent.modelState.value,
            "conflict":    None,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, data: dict, author_id: Optional[str]) -> Intent:
        missing = self._REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        statement = data.get("statement", "").strip()
        if not statement:
            # Auto-generate from subject/action/target
            statement = (
                f"{data['subject']} {data['action']} {data['target']}"
            ).strip()
        if not statement:
            raise ValueError("Intent statement cannot be empty")

        action = data["action"]
        if action not in VALID_INTENT_ACTIONS:
            raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_INTENT_ACTIONS}")

        intent_id = data.get(
            "intentId",
            f"INT-{uuid.uuid4().hex[:8].upper()}",
        )

        return Intent(
            intentId   = intent_id,
            statement  = statement,
            type       = data["type"],
            subject    = data["subject"],
            action     = action,
            target     = data["target"],
            status     = "INGESTED",
            modelState = ModelState.CANDIDATE,
            authorId   = author_id,
            priority   = data.get("priority", 100),
        )

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _detect_conflict(self, new_intent: Intent) -> Optional[dict]:
        """
        Query Neo4j for active POR intents that overlap with the new one.
        Returns a conflict dict or None.
        """
        try:
            active = self._neo4j.get_active_intents()
        except Exception:
            # If we can't reach Neo4j for conflict check, log and proceed
            self._log.warning("Could not query active intents for conflict check")
            return None

        for existing in active:
            if (
                existing.get("subject") == new_intent.subject
                and existing.get("target") == new_intent.target
            ):
                if existing.get("action") != new_intent.action:
                    return {
                        "type":            "CONFLICTING_ACTION",
                        "existing_intent": existing["intentId"],
                        "new_intent":      new_intent.intentId,
                        "detail": (
                            f"Same subject/target but "
                            f"{existing['action']} vs {new_intent.action}"
                        ),
                    }
                else:
                    return {
                        "type":            "DUPLICATE",
                        "existing_intent": existing["intentId"],
                        "detail":          "Identical intent already active",
                    }

        return None

    # ------------------------------------------------------------------
    # HLD ingestion (Slice 1)
    # ------------------------------------------------------------------

    def ingest_hld_changeset(
        self,
        changeset,
        source_path: str,
        candidate_space: str = "ibn-candidate-001",
        dialogue_fn: Optional[Callable[[str, list[str]], str]] = None,
        author_id: Optional[str] = None,
    ) -> dict:
        """Ingest a parsed HLD ChangeSet into Neo4j as Intent nodes.

        For each added/modified population in the changeset, draft an
        Intent, refine it through operator dialogue, and persist it.
        Idempotent: re-ingesting an unchanged HLD produces no new Intents
        because each draft is keyed by ``origin = HLD:<file>:<line>``.

        Parameters
        ----------
        changeset:
            ``ibn.parser.hld_parser.ChangeSet`` instance.
        source_path:
            Path to the HLD file (used for the ``origin`` field).
        candidate_space:
            Live-Memory space to record the dialogue and intent narrative.
        dialogue_fn:
            ``(prompt, choices) -> answer_letter`` callable. The default
            uses stdin/stdout (CLI). Tests pass a mock that returns
            preset answers.
        author_id:
            Optional operator identifier for the audit trail.

        Returns
        -------
        dict with keys:
          - ``intents_created``: list of created Intent IDs (new only)
          - ``intents_existing``: list of pre-existing Intent IDs (idempotent re-runs)
          - ``dialogue_transcript``: list of {prompt, answer, intent_id}
          - ``changeset_summary``: human-readable summary of the diff
        """
        if dialogue_fn is None:
            dialogue_fn = self._default_cli_dialogue

        created: list[str] = []
        existing: list[str] = []
        transcript: list[dict] = []

        # Process additions and modifications. Removals are out of scope
        # for Slice 1 — Slice 5 will add a deletion path.
        targets = list(changeset.populations_added) + list(changeset.populations_modified)

        for pop in targets:
            origin = f"HLD:{source_path}:{pop.line_number}"

            # Idempotency: if an Intent with this origin already exists in
            # Neo4j, skip the dialogue and reuse it.
            existing_intent = self._neo4j.get_intent_by_origin(origin)
            if existing_intent:
                existing.append(existing_intent["intentId"])
                self._note(
                    candidate_space,
                    f"HLD re-commit: Intent {existing_intent['intentId']} "
                    f"already exists for {origin} — skipping",
                    category="hld-ingestion",
                )
                continue

            # Build the draft from the HLD row
            draft_intent, choices = self._draft_intent_from_population(pop, origin)

            # Dialogue: ask the operator to confirm the access pattern
            prompt = self._build_dialogue_prompt(pop, draft_intent, choices)
            answer = dialogue_fn(prompt, [c["letter"] for c in choices])
            chosen = self._apply_dialogue_answer(draft_intent, choices, answer)

            transcript.append({
                "prompt":   prompt,
                "answer":   answer,
                "intentId": chosen.intentId,
                "origin":   origin,
            })

            # Persist Intent (L4)
            self._neo4j.create_intent(chosen)
            created.append(chosen.intentId)

            # Persist L1 VLAN node so switches have data to render against.
            # The VLAN is the operator-visible reality of the population —
            # it lives in L1 Infrastructure even though the policy intent
            # lives in L4. Linking via TRACES_TO keeps the audit trail
            # queryable in either direction. (Slice 2)
            try:
                self._neo4j.create_vlan(
                    vlan_id     = pop.vlan,
                    name        = pop.name,
                    model_state = "CANDIDATE",
                    origin      = origin,
                    intent_id   = chosen.intentId,
                )
            except Exception as exc:
                self._log.warning(
                    "create_vlan failed for VLAN %s: %s — Intent kept, "
                    "but switches will not see this VLAN",
                    pop.vlan, exc,
                )

            self._note(
                candidate_space,
                (
                    f"HLD ingestion: Intent {chosen.intentId} from {origin}\n"
                    f"  Population: VLAN {pop.vlan} '{pop.name}'\n"
                    f"  Statement:  {chosen.statement}\n"
                    f"  Operator chose: {answer}\n"
                    f"  L1 VLAN {pop.vlan} created/updated"
                ),
                category="hld-ingestion",
            )

            self._publish("intent.ingested", {
                "intentId":   chosen.intentId,
                "subject":    chosen.subject,
                "action":     chosen.action,
                "target":     chosen.target,
                "modelState": chosen.modelState.value,
                "origin":     origin,
            })

        return {
            "intents_created":   created,
            "intents_existing":  existing,
            "dialogue_transcript": transcript,
            "changeset_summary": changeset.summary(),
        }

    # ------------------------------------------------------------------
    # HLD ingestion helpers
    # ------------------------------------------------------------------

    # Access-pattern templates that the dialogue offers the operator.
    # Each template maps to a (subject, action, target) tuple plus a
    # human-readable label. Slice 1 ships four templates that cover the
    # population types in the HLD VLAN table; Slice 5 will replace this
    # with HLD-derived templates.
    _ACCESS_TEMPLATES = [
        {
            "letter": "a",
            "label":  "standard-corporate (Internet + DMZ services, deny lateral)",
            "action": "permit",
            "target": "Internet+DMZ",
        },
        {
            "letter": "b",
            "label":  "guest-equivalent (Internet only, deny lateral and DMZ)",
            "action": "permit",
            "target": "Internet",
        },
        {
            "letter": "c",
            "label":  "restricted (DNS-DMZ only, deny everything else)",
            "action": "permit",
            "target": "DNS-DMZ",
        },
        {
            "letter": "d",
            "label":  "isolated (deny all egress)",
            "action": "deny",
            "target": "All",
        },
    ]

    def _draft_intent_from_population(self, pop, origin: str) -> tuple[Intent, list[dict]]:
        """Build a draft Intent from a PopulationEntry.

        The draft uses the first template as the default suggestion; the
        dialogue function picks the actual one. Returns ``(draft, choices)``.
        """
        intent_id = f"INT-HLD-{pop.vlan}"  # deterministic — supports re-commit idempotency
        # Default to template (a) — operator can override via dialogue
        default = self._ACCESS_TEMPLATES[0]

        draft = Intent(
            intentId   = intent_id,
            statement  = (
                f"Population '{pop.name}' (VLAN {pop.vlan}) — "
                f"{default['label']}"
            ),
            type       = "population-access",
            subject    = pop.name,
            action     = default["action"],
            target     = default["target"],
            status     = "INGESTED",
            modelState = ModelState.CANDIDATE,
            priority   = 100,
            origin     = origin,
        )
        return draft, list(self._ACCESS_TEMPLATES)

    def _build_dialogue_prompt(self, pop, draft: Intent, choices: list[dict]) -> str:
        lines = [
            f"HLD change detected: VLAN {pop.vlan} '{pop.name}'",
            f"  QoS priority: {pop.qos_priority}   bandwidth: {pop.bandwidth}",
            f"  Source line:  {draft.origin}",
            "",
            "Which access pattern should this population have?",
            "",
        ]
        for c in choices:
            lines.append(f"  ({c['letter']}) {c['label']}")
        lines.append("")
        lines.append("Enter (a/b/c/d): ")
        return "\n".join(lines)

    def _apply_dialogue_answer(
        self,
        draft: Intent,
        choices: list[dict],
        answer: str,
    ) -> Intent:
        letter = (answer or "").strip().lower()[:1]
        chosen_template = next((c for c in choices if c["letter"] == letter), choices[0])
        # Mutate the draft into the chosen template
        draft.action = chosen_template["action"]
        draft.target = chosen_template["target"]
        draft.statement = (
            f"Population '{draft.subject}' — {chosen_template['label']}"
        )
        return draft

    # ------------------------------------------------------------------
    # Default CLI dialogue (stdin/stdout)
    # ------------------------------------------------------------------

    def _default_cli_dialogue(self, prompt: str, choices: list[str]) -> str:
        """Default dialogue: print the prompt to stdout, read one letter from stdin.

        For non-interactive environments (CI, hooks running detached), set
        ``IBN_DIALOGUE_DEFAULT`` env var to the desired letter ('a'..'d')
        and the prompt is auto-answered without blocking.
        """
        env_default = os.environ.get("IBN_DIALOGUE_DEFAULT")
        if env_default:
            self._log.info(
                "HLD dialogue auto-answered from IBN_DIALOGUE_DEFAULT=%s",
                env_default,
            )
            return env_default
        try:
            print(prompt, flush=True)
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            # Fall back to template (a) when no operator is attached
            self._log.warning("HLD dialogue had no input — defaulting to (a)")
            return "a"

    # ------------------------------------------------------------------
    # HLD device ingestion (Slice 3)
    # ------------------------------------------------------------------

    def ingest_hld_devices(
        self,
        changeset,
        source_path: str,
        candidate_space: str = "ibn-candidate-001",
    ) -> dict:
        """Reconcile Neo4j Device nodes against the HLD Device Inventory Table.

        For each added/modified DeviceEntry, create or update a Device
        node in L1. For each removed entry, return the device id so the
        caller (orchestrator → Provisioner.retire) can tear it down.

        This is intentionally separate from ``ingest_hld_changeset()`` —
        the population path produces L4 Intents and L1 VLANs, the device
        path produces L1 Devices. The orchestrator calls both.

        Returns
        -------
        dict with keys:
          - ``devices_created``: list of new Device IDs
          - ``devices_updated``: list of modified Device IDs (already existed)
          - ``devices_to_retire``: list of Device IDs the operator removed
        """
        created: list[str] = []
        updated: list[str] = []
        to_retire: list[str] = []

        # Added devices
        for entry in changeset.devices_added:
            origin = f"HLD:{source_path}:{entry.line_number}"
            existing = self._neo4j.get_device(entry.device_id)
            device = Device(
                deviceId       = entry.device_id,
                hostname       = entry.device_id,  # use the HLD ID as hostname
                vendor         = entry.vendor,
                platform       = entry.platform.lower(),
                deviceRole     = entry.role,
                siteId         = f"SITE-{entry.site}-01" if not entry.site.startswith("SITE-") else entry.site,
                clabContainer  = entry.clab_container,
                mgmtIpv4       = entry.mgmt_ipv4,
                lifecycleState = DeviceLifecycleState.PLANNED,
                modelState     = ModelState.CANDIDATE,
                origin         = origin,
            )
            self._neo4j.create_device(device)
            if existing:
                updated.append(entry.device_id)
            else:
                created.append(entry.device_id)

            self._note(
                candidate_space,
                (
                    f"HLD device {'created' if not existing else 'updated'}: "
                    f"{entry.device_id} ({entry.vendor}/{entry.platform}, "
                    f"{entry.role}) at {entry.site} → "
                    f"container {entry.clab_container}"
                ),
                category="hld-device-ingestion",
            )
            self._publish("device.added" if not existing else "device.modified", {
                "deviceId":      entry.device_id,
                "vendor":        entry.vendor,
                "platform":      entry.platform.lower(),
                "clabContainer": entry.clab_container,
                "origin":        origin,
            })

        # Modified devices (separate loop because they go to a different
        # event type but reuse the same upsert logic above)
        for entry in changeset.devices_modified:
            if entry.device_id in created or entry.device_id in updated:
                continue  # already handled in devices_added pass
            origin = f"HLD:{source_path}:{entry.line_number}"
            device = Device(
                deviceId       = entry.device_id,
                hostname       = entry.device_id,
                vendor         = entry.vendor,
                platform       = entry.platform.lower(),
                deviceRole     = entry.role,
                siteId         = f"SITE-{entry.site}-01" if not entry.site.startswith("SITE-") else entry.site,
                clabContainer  = entry.clab_container,
                mgmtIpv4       = entry.mgmt_ipv4,
                # Don't reset lifecycleState on a property update — it's the
                # provisioner's job to drive the state machine. create_device
                # MERGEs and overwrites everything except createdAt; for
                # modified devices we want lifecycleState preserved, so we
                # read it back first and pass it through.
                lifecycleState = self._read_lifecycle(entry.device_id),
                modelState     = ModelState.CANDIDATE,
                origin         = origin,
            )
            self._neo4j.create_device(device)
            updated.append(entry.device_id)
            self._note(
                candidate_space,
                f"HLD device updated: {entry.device_id} (property change)",
                category="hld-device-ingestion",
            )
            self._publish("device.modified", {"deviceId": entry.device_id})

        # Removed devices — caller will retire them
        for entry in changeset.devices_removed:
            to_retire.append(entry.device_id)
            self._note(
                candidate_space,
                f"HLD device REMOVED: {entry.device_id} — queued for retirement",
                category="hld-device-ingestion",
            )
            self._publish("device.removed", {"deviceId": entry.device_id})

        return {
            "devices_created":   created,
            "devices_updated":   updated,
            "devices_to_retire": to_retire,
        }

    def _read_lifecycle(self, device_id: str) -> DeviceLifecycleState:
        """Look up a Device's current lifecycleState; default to PLANNED."""
        rec = self._neo4j.get_device(device_id)
        if not rec:
            return DeviceLifecycleState.PLANNED
        try:
            return DeviceLifecycleState(rec.get("lifecycleState", "PLANNED"))
        except ValueError:
            return DeviceLifecycleState.PLANNED
