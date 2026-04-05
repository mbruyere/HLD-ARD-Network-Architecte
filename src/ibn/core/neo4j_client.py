"""
Neo4j client wrapper for the IBN system.

Provides:
- Connection management (driver singleton)
- Canned Cypher queries (stored-procedure style) that insulate agents from schema changes
- modelState enforcement on every write

Usage::

    from ibn.core.neo4j_client import Neo4jClient

    client = Neo4jClient.from_env()
    client.create_intent(intent)
    client.create_deployment_event(event)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Optional

from neo4j import GraphDatabase, Driver, Session

from ibn.core.models import (
    Intent, Configuration, DeploymentEvent,
    Telemetry, OperationalState, Alert, AgentExecution,
)


class Neo4jClient:
    """Thread-safe Neo4j client with canned query library."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "Neo4jClient":
        return cls(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            user=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )

    # ------------------------------------------------------------------
    # Session context manager
    # ------------------------------------------------------------------

    @contextmanager
    def _session(self):
        session: Session = self._driver.session(database=self._database)
        try:
            yield session
        finally:
            session.close()

    def close(self):
        self._driver.close()

    # ------------------------------------------------------------------
    # L4 — Intent
    # ------------------------------------------------------------------

    def create_intent(self, intent: Intent) -> dict:
        """Create an Intent node in L4.  Returns the created node properties."""
        with self._session() as s:
            result = s.run(
                """
                MERGE (i:Intent {intentId: $intentId})
                ON CREATE SET
                    i.statement   = $statement,
                    i.type        = $type,
                    i.subject     = $subject,
                    i.action      = $action,
                    i.target      = $target,
                    i.status      = $status,
                    i.modelState  = $modelState,
                    i.createdAt   = $createdAt,
                    i.authorId    = $authorId,
                    i.priority    = $priority
                RETURN i
                """,
                intentId   = intent.intentId,
                statement  = intent.statement,
                type       = intent.type,
                subject    = intent.subject,
                action     = intent.action,
                target     = intent.target,
                status     = intent.status,
                modelState = intent.modelState.value,
                createdAt  = intent.createdAt,
                authorId   = intent.authorId,
                priority   = intent.priority,
            )
            record = result.single()
            return dict(record["i"]) if record else {}

    def update_intent_status(self, intent_id: str, status: str) -> None:
        with self._session() as s:
            s.run(
                "MATCH (i:Intent {intentId: $id}) SET i.status = $status",
                id=intent_id, status=status,
            )

    def get_active_intents(self) -> list[dict]:
        """Return all intents with status ACTIVE (POR model state)."""
        with self._session() as s:
            result = s.run(
                "MATCH (i:Intent {status: 'ACTIVE', modelState: 'POR'}) RETURN i"
            )
            return [dict(r["i"]) for r in result]

    # ------------------------------------------------------------------
    # L5 — Configuration
    # ------------------------------------------------------------------

    def create_configuration(self, config: Configuration) -> dict:
        with self._session() as s:
            result = s.run(
                """
                CREATE (c:Configuration {
                    configId:   $configId,
                    deviceId:   $deviceId,
                    content:    $content,
                    version:    $version,
                    modelState: $modelState,
                    createdAt:  $createdAt
                }) RETURN c
                """,
                configId   = config.configId,
                deviceId   = config.deviceId,
                content    = config.content,
                version    = config.version,
                modelState = config.modelState.value,
                createdAt  = config.createdAt,
            )
            record = result.single()
            return dict(record["c"]) if record else {}

    def create_deployment_event(self, event: DeploymentEvent) -> dict:
        with self._session() as s:
            result = s.run(
                """
                CREATE (e:DeploymentEvent {
                    eventId:        $eventId,
                    targetDeviceId: $targetDeviceId,
                    status:         $status,
                    modelState:     $modelState,
                    timestamp:      $timestamp,
                    configId:       $configId,
                    errorMessage:   $errorMessage,
                    rollbackFrom:   $rollbackFrom,
                    rollbackTo:     $rollbackTo
                }) RETURN e
                """,
                eventId        = event.eventId,
                targetDeviceId = event.targetDeviceId,
                status         = event.status,
                modelState     = event.modelState.value,
                timestamp      = event.timestamp,
                configId       = event.configId,
                errorMessage   = event.errorMessage,
                rollbackFrom   = event.rollbackFrom,
                rollbackTo     = event.rollbackTo,
            )
            record = result.single()
            return dict(record["e"]) if record else {}

    # ------------------------------------------------------------------
    # L5 — Telemetry & OperationalState
    # ------------------------------------------------------------------

    def create_telemetry(self, t: Telemetry) -> dict:
        with self._session() as s:
            result = s.run(
                """
                CREATE (n:Telemetry {
                    deviceId:      $deviceId,
                    metric:        $metric,
                    value:         $value,
                    interfaceName: $interfaceName,
                    modelState:    $modelState,
                    timestamp:     $timestamp
                }) RETURN n
                """,
                deviceId      = t.deviceId,
                metric        = t.metric,
                value         = str(t.value),
                interfaceName = t.interfaceName,
                modelState    = t.modelState.value,
                timestamp     = t.timestamp,
            )
            record = result.single()
            return dict(record["n"]) if record else {}

    def upsert_operational_state(self, ops: OperationalState) -> None:
        with self._session() as s:
            s.run(
                """
                MERGE (o:OperationalState {deviceId: $deviceId})
                SET o.operState         = $operState,
                    o.cpuUtilization    = $cpu,
                    o.memoryUtilization = $mem,
                    o.modelState        = $modelState,
                    o.timestamp         = $timestamp
                """,
                deviceId   = ops.deviceId,
                operState  = ops.operState,
                cpu        = ops.cpuUtilization,
                mem        = ops.memoryUtilization,
                modelState = ops.modelState.value,
                timestamp  = ops.timestamp,
            )

    # ------------------------------------------------------------------
    # L6 — Alerts
    # ------------------------------------------------------------------

    def create_alert(self, alert: Alert) -> dict:
        with self._session() as s:
            result = s.run(
                """
                CREATE (a:Alert {
                    alertId:    $alertId,
                    severity:   $severity,
                    metric:     $metric,
                    value:      $value,
                    threshold:  $threshold,
                    deviceId:   $deviceId,
                    modelState: $modelState,
                    timestamp:  $timestamp
                }) RETURN a
                """,
                alertId   = alert.alertId,
                severity  = alert.severity.value,
                metric    = alert.metric,
                value     = alert.value,
                threshold = alert.threshold,
                deviceId  = alert.deviceId,
                modelState= alert.modelState.value,
                timestamp = alert.timestamp,
            )
            record = result.single()
            return dict(record["a"]) if record else {}

    # ------------------------------------------------------------------
    # L9 — AgentExecution audit
    # ------------------------------------------------------------------

    def record_agent_execution(self, ae: AgentExecution) -> None:
        with self._session() as s:
            s.run(
                """
                CREATE (:AgentExecution {
                    agentId:      $agentId,
                    action:       $action,
                    inputRef:     $inputRef,
                    outputRef:    $outputRef,
                    modelState:   $modelState,
                    timestamp:    $timestamp,
                    durationMs:   $durationMs,
                    errorMessage: $errorMessage
                })
                """,
                agentId      = ae.agentId,
                action       = ae.action,
                inputRef     = ae.inputRef,
                outputRef    = ae.outputRef,
                modelState   = ae.modelState.value,
                timestamp    = ae.timestamp,
                durationMs   = ae.durationMs,
                errorMessage = ae.errorMessage,
            )

    # ------------------------------------------------------------------
    # Generic read helpers
    # ------------------------------------------------------------------

    def run_query(self, cypher: str, **params) -> list[dict[str, Any]]:
        """Execute arbitrary Cypher and return list of record dicts."""
        with self._session() as s:
            result = s.run(cypher, **params)
            return [r.data() for r in result]
