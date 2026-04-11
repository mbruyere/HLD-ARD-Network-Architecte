"""
Agent 2 — Intent → Policy translation  (RFC 9315 §5.1.2)

Slice 1 scope: minimal rule-based decomposer that converts a population
Intent (produced by Agent 1's HLD ingestion phase) into a Policy plus a
small set of FirewallRules. The decomposition uses a hand-coded access
matrix derived from HLD §9 (DMZ Architecture) — the four templates that
A1's dialogue presents to the operator each map to a fixed rule set.

This is deliberately not a full policy engine. Slices 3 and 5 will:
  - replace the access-matrix with values pulled from the HLD §9 tables
  - add zone-pair policies, QoS policies, NAT, and routing
  - resolve population names → zone membership via Neo4j L2 queries

Entry point::

    agent = Agent2IntentPolicy(neo4j, live_memory)
    result = agent.run(intent_id="INT-HLD-141")
    # → creates Policy + FirewallRule nodes in L4 (CANDIDATE)
    # → returns {policyId, ruleIds, intentId}
"""
from __future__ import annotations

import uuid
from typing import Optional

from ibn.core.base_agent import BaseAgent
from ibn.core.models import (
    Policy,
    FirewallRule,
    ModelState,
    VALID_FIREWALL_RULE_ACTIONS,
)


# ---------------------------------------------------------------------------
# Access matrix — derived from HLD §9 DMZ Architecture
# ---------------------------------------------------------------------------
# Each entry maps an Intent.target value (set by A1's dialogue choice) to
# a list of FirewallRule recipes. Each recipe is (destZone, action,
# protocol, destPort, description).
#
# The four target patterns mirror the four templates A1 offers in
# _ACCESS_TEMPLATES:
#   - "Internet+DMZ"  → standard corporate
#   - "Internet"      → guest-equivalent
#   - "DNS-DMZ"       → restricted
#   - "All"           → isolated (deny all)
#
# Slice 3 will replace this dict with a Neo4j-driven lookup that joins
# Population × Zone × DmzService nodes from the HLD seed.
# ---------------------------------------------------------------------------

ACCESS_MATRIX: dict[str, list[dict]] = {
    "Internet+DMZ": [
        {"destZone": "INTERNET",  "action": "permit", "protocol": "any", "destPort": "any",
         "description": "Allow egress to Internet"},
        {"destZone": "DMZ_INFRA", "action": "permit", "protocol": "tcp", "destPort": "53",
         "description": "Allow DNS lookup to DMZ"},
        {"destZone": "DMZ_INFRA", "action": "permit", "protocol": "udp", "destPort": "53",
         "description": "Allow DNS lookup to DMZ"},
        {"destZone": "DMZ_INFRA", "action": "permit", "protocol": "tcp", "destPort": "389",
         "description": "Allow LDAP to AD DMZ"},
        {"destZone": "USER",      "action": "deny",   "protocol": "any", "destPort": "any",
         "description": "Deny lateral movement to other populations"},
    ],
    "Internet": [
        {"destZone": "INTERNET",  "action": "permit", "protocol": "any", "destPort": "any",
         "description": "Allow egress to Internet"},
        {"destZone": "DMZ_INFRA", "action": "deny",   "protocol": "any", "destPort": "any",
         "description": "Deny access to DMZ services"},
        {"destZone": "USER",      "action": "deny",   "protocol": "any", "destPort": "any",
         "description": "Deny lateral movement to other populations"},
    ],
    "DNS-DMZ": [
        {"destZone": "DMZ_INFRA", "action": "permit", "protocol": "tcp", "destPort": "53",
         "description": "Allow DNS lookup only"},
        {"destZone": "DMZ_INFRA", "action": "permit", "protocol": "udp", "destPort": "53",
         "description": "Allow DNS lookup only"},
        {"destZone": "INTERNET",  "action": "deny",   "protocol": "any", "destPort": "any",
         "description": "Deny Internet egress"},
        {"destZone": "USER",      "action": "deny",   "protocol": "any", "destPort": "any",
         "description": "Deny lateral movement"},
    ],
    "All": [
        {"destZone": "INTERNET",  "action": "deny", "protocol": "any", "destPort": "any",
         "description": "Isolated — deny Internet"},
        {"destZone": "DMZ_INFRA", "action": "deny", "protocol": "any", "destPort": "any",
         "description": "Isolated — deny DMZ"},
        {"destZone": "USER",      "action": "deny", "protocol": "any", "destPort": "any",
         "description": "Isolated — deny lateral"},
    ],
}


class Agent2IntentPolicy(BaseAgent):

    AGENT_ID   = "A2"
    AGENT_NAME = "IntentPolicy"

    # ------------------------------------------------------------------
    # Main logic
    # ------------------------------------------------------------------

    def _execute(self, **kwargs) -> dict:
        intent_id:       str = kwargs["intent_id"]
        candidate_space: str = kwargs.get("candidate_space", "ibn-candidate-001")

        # 1. Load the Intent
        intent = self._load_intent(intent_id)
        if intent is None:
            raise ValueError(f"Intent {intent_id} not found in Neo4j")

        # 2. Look up the access matrix for the chosen target
        target = intent.get("target", "")
        recipes = ACCESS_MATRIX.get(target)
        if recipes is None:
            self._log.warning(
                "No access matrix entry for target='%s' on intent %s — "
                "creating an empty Policy", target, intent_id,
            )
            recipes = []

        # 3. Create the Policy node (deterministic ID for idempotency)
        policy_id = f"POL-{intent_id}"
        policy = Policy(
            policyId    = policy_id,
            name        = f"POL-{intent.get('subject', 'UNKNOWN').upper().replace(' ', '-')}",
            type        = "access-policy",
            intentId    = intent_id,
            modelState  = ModelState.CANDIDATE,
            description = (
                f"Policy decomposed from {intent_id} "
                f"({intent.get('subject')} → {target})"
            ),
        )
        self._neo4j.create_policy(policy)

        # 4. Create FirewallRule nodes (one per recipe)
        source_zone = self._infer_source_zone(intent)
        rule_ids: list[str] = []
        for idx, recipe in enumerate(recipes, start=1):
            rule_id = f"RUL-{intent_id}-{idx:02d}"
            rule = FirewallRule(
                ruleId      = rule_id,
                policyId    = policy_id,
                sourceZone  = source_zone,
                destZone    = recipe["destZone"],
                action      = recipe["action"],
                protocol    = recipe.get("protocol"),
                destPort    = recipe.get("destPort"),
                priority    = 100 + idx,
                modelState  = ModelState.CANDIDATE,
                description = recipe.get("description"),
            )
            if rule.action not in VALID_FIREWALL_RULE_ACTIONS:
                raise ValueError(
                    f"Invalid firewall rule action '{rule.action}' on {rule_id}"
                )
            self._neo4j.create_firewall_rule(rule)
            rule_ids.append(rule_id)

        # 5. Mark the parent Intent as TRANSLATED
        try:
            self._neo4j.update_intent_status(intent_id, "TRANSLATED")
        except Exception as exc:
            self._log.warning("update_intent_status failed for %s: %s", intent_id, exc)

        # 6. Live-Memory note
        self._note(
            candidate_space,
            (
                f"A2: Intent {intent_id} → Policy {policy_id} "
                f"with {len(rule_ids)} firewall rules "
                f"(source={source_zone}, target={target})"
            ),
            category="policy-translation",
        )

        # 7. Publish event
        self._publish("policy.translated", {
            "intentId": intent_id,
            "policyId": policy_id,
            "ruleIds":  rule_ids,
        })

        return {
            "id":        policy_id,
            "policyId":  policy_id,
            "intentId":  intent_id,
            "ruleIds":   rule_ids,
            "ruleCount": len(rule_ids),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_intent(self, intent_id: str) -> Optional[dict]:
        rows = self._neo4j.run_query(
            "MATCH (i:Intent {intentId: $id}) RETURN i",
            id=intent_id,
        )
        if not rows:
            return None
        return dict(rows[0]["i"])

    def _infer_source_zone(self, intent: dict) -> str:
        """Map a population subject to its zone.

        Slice 1 uses a hard-coded mapping derived from the HLD: every
        non-DMZ population sits in the USER zone. Slice 3 will look this
        up from Neo4j L2 (Zone ↔ Population relationships) so the
        operator can move populations between zones via the HLD.
        """
        subject = (intent.get("subject") or "").lower()
        if "dmz" in subject:
            return "DMZ_INFRA"
        if "guest" in subject or "contractor" in subject or "visitor" in subject:
            return "GUEST"
        return "USER"
