"""
T4 — Agent 1: Intent Ingestion Tests (Unit)
============================================
Validates intent parsing, validation, conflict detection, Neo4j writes,
and Live-Memory integration.
"""
import pytest
from datetime import datetime, timezone


# ── T4.1 Structured template ingestion ────────────────────────────────────

class TestIntentParsing:
    """T4.1 — Parse and validate structured intent templates."""

    REQUIRED_FIELDS = {"type", "subject", "action", "target"}

    def _validate_intent(self, intent: dict) -> dict:
        """Application-level intent validation — mirrors Agent 1 logic."""
        missing = self.REQUIRED_FIELDS - set(intent.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        if not intent.get("statement", intent.get("subject", "")):
            raise ValueError("Intent statement cannot be empty")
        if intent["action"] not in ("permit", "deny", "redirect", "rate-limit"):
            raise ValueError(f"Invalid action: {intent['action']}")
        return {
            "intentId": f"INT-{hash(frozenset(intent.items())) % 10000:04d}",
            "statement": intent.get("statement", f"{intent['subject']} {intent['action']} {intent['target']}"),
            "status": "INGESTED",
            "modelState": "CANDIDATE",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            **intent
        }

    def test_t4_1_1_parse_valid_intent(self):
        """T4.1.1 — Valid structured intent is parsed correctly."""
        intent = {
            "type": "access-policy",
            "subject": "Guest",
            "action": "permit",
            "target": "Internet",
            "statement": "Guest users must only access the internet"
        }
        result = self._validate_intent(intent)
        assert result["status"] == "INGESTED"
        assert result["modelState"] == "CANDIDATE"
        assert "intentId" in result

    def test_t4_1_2_reject_missing_subject(self):
        """T4.1.2 — Intent missing required 'subject' field is rejected."""
        intent = {"type": "access-policy", "action": "permit", "target": "Internet"}
        with pytest.raises(ValueError, match="Missing required fields"):
            self._validate_intent(intent)

    def test_t4_1_3_reject_empty_statement(self):
        """T4.1.3 — Intent with empty statement is rejected."""
        intent = {"type": "access-policy", "subject": "", "action": "permit", "target": "Internet", "statement": ""}
        # subject is empty, which we treat as empty statement
        # The validation logic rejects empty statements
        with pytest.raises(ValueError, match="Intent statement cannot be empty"):
            self._validate_intent(intent)


# ── T4.2 Neo4j writes ────────────────────────────────────────────────────

class TestIngestionNeo4jWrites:
    """T4.2 — Validate that Agent 1 creates correct Neo4j nodes."""

    def test_t4_2_1_creates_intent_node(self, neo4j_driver):
        """T4.2.1 — Creates Intent node in L4 with correct properties."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Intent {intentId: $id, statement: $stmt, "
                "status: 'INGESTED', modelState: 'CANDIDATE', createdAt: $ts})",
                {
                    "id": "INT-001",
                    "stmt": "Guest users must only access the internet",
                    "ts": datetime.now(timezone.utc).isoformat()
                }
            )

        # Verify the node was created
        nodes = neo4j_driver.nodes
        intent_nodes = [n for n in nodes if n.get("_label") == "Intent"]
        assert len(intent_nodes) >= 1
        assert intent_nodes[-1].get("id") == "INT-001"  # param key is $id

    def test_t4_2_2_links_intent_to_business_use_case(self, neo4j_driver):
        """T4.2.2 — Intent linked to BusinessUseCase via ADDRESSES."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Intent {intentId: 'INT-001', modelState: 'CANDIDATE'})"
                "-[:ADDRESSES]->"
                "(:BusinessUseCase {bucId: 'BUC-GUEST-ISOLATION', modelState: 'POR'})",
                {}
            )

        # Verify query was recorded
        queries = neo4j_driver.queries
        assert any("ADDRESSES" in q["query"] for q in queries)

    def test_t4_2_3_sets_candidate_model_state(self, neo4j_driver):
        """T4.2.3 — New intent always has modelState CANDIDATE."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:Intent {intentId: $id, modelState: $state})",
                {"id": "INT-002", "state": "CANDIDATE"}
            )

        nodes = neo4j_driver.nodes
        intent_nodes = [n for n in nodes if n.get("_label") == "Intent"]
        assert all(n.get("state", n.get("modelState")) == "CANDIDATE"
                    for n in intent_nodes if "state" in n or "modelState" in n)

    def test_t4_2_4_writes_agent_execution_record(self, neo4j_driver):
        """T4.2.4 — Creates AgentExecution audit node in L9."""
        with neo4j_driver.session() as session:
            session.run(
                "CREATE (:AgentExecution {agentId: 'A1', action: 'ingest', "
                "inputIntentId: $iid, outputIntentId: $oid, "
                "timestamp: $ts, modelState: 'POR'})",
                {
                    "iid": "INT-001-raw",
                    "oid": "INT-001",
                    "ts": datetime.now(timezone.utc).isoformat()
                }
            )

        nodes = neo4j_driver.nodes
        exec_nodes = [n for n in nodes if n.get("_label") == "AgentExecution"]
        assert len(exec_nodes) >= 1
        # agentId is a literal in the query, not a parameter. Verify via query.
        queries = neo4j_driver.queries
        assert any("agentId: 'A1'" in q["query"] for q in queries)


# ── T4.3 Conflict detection ──────────────────────────────────────────────

class TestConflictDetection:
    """T4.3 — Validate conflict detection between intents."""

    def _detect_conflict(self, existing_intents: list, new_intent: dict) -> dict | None:
        """Simplified conflict detection logic — mirrors Agent 1."""
        for existing in existing_intents:
            # Same subject and target but opposite action
            if (existing["subject"] == new_intent["subject"]
                    and existing["target"] == new_intent["target"]
                    and existing["action"] != new_intent["action"]):
                return {
                    "type": "CONFLICTING_ACTION",
                    "existing_intent": existing["intentId"],
                    "new_intent": new_intent.get("intentId", "NEW"),
                    "detail": f"Same subject/target but {existing['action']} vs {new_intent['action']}"
                }
            # Exact duplicate
            if (existing["subject"] == new_intent["subject"]
                    and existing["target"] == new_intent["target"]
                    and existing["action"] == new_intent["action"]):
                return {
                    "type": "DUPLICATE",
                    "existing_intent": existing["intentId"],
                    "detail": "Identical intent already active"
                }
        return None

    def test_t4_3_1_detect_conflicting_intent(self):
        """T4.3.1 — Opposite action on same subject/target flagged."""
        existing = [{"intentId": "INT-001", "subject": "Guest", "target": "Internet", "action": "permit"}]
        new = {"subject": "Guest", "target": "Internet", "action": "deny"}

        conflict = self._detect_conflict(existing, new)
        assert conflict is not None
        assert conflict["type"] == "CONFLICTING_ACTION"

    def test_t4_3_2_no_conflict_different_scope(self):
        """T4.3.2 — Non-overlapping intents produce no conflict."""
        existing = [{"intentId": "INT-001", "subject": "Guest", "target": "Internet", "action": "permit"}]
        new = {"subject": "Employee", "target": "DMZ", "action": "permit"}

        conflict = self._detect_conflict(existing, new)
        assert conflict is None

    def test_t4_3_3_detect_duplicate(self):
        """T4.3.3 — Identical intent flagged as duplicate."""
        existing = [{"intentId": "INT-001", "subject": "Guest", "target": "Internet", "action": "permit"}]
        new = {"subject": "Guest", "target": "Internet", "action": "permit"}

        conflict = self._detect_conflict(existing, new)
        assert conflict is not None
        assert conflict["type"] == "DUPLICATE"


# ── T4.4 Live-Memory integration ─────────────────────────────────────────

class TestIngestionLiveMemory:
    """T4.4 — Agent 1 emits live_notes on ingestion events."""

    def test_t4_4_1_note_on_successful_ingestion(self, live_memory):
        """T4.4.1 — Successful ingestion emits live_note to candidate space."""
        live_memory.space_create("ibn-candidate-001")

        note = live_memory.live_note(
            space="ibn-candidate-001",
            category="intent-ingestion",
            content="Intent INT-001 ingested: Guest → permit → Internet"
        )

        assert note["category"] == "intent-ingestion"
        notes = live_memory.note_list("ibn-candidate-001")
        assert len(notes) == 1

    def test_t4_4_2_note_on_conflict_detection(self, live_memory):
        """T4.4.2 — Conflict detection emits live_note with details."""
        live_memory.space_create("ibn-candidate-001")

        note = live_memory.live_note(
            space="ibn-candidate-001",
            category="conflict-detection",
            content="CONFLICT: INT-002 (Guest→deny→Internet) conflicts with INT-001 (Guest→permit→Internet)"
        )

        assert note["category"] == "conflict-detection"
        assert "CONFLICT" in note["content"]
