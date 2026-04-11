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
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import GraphDatabase, Driver, Session

from ibn.core.models import (
    Intent, Configuration, DeploymentEvent,
    Telemetry, OperationalState, Alert, AgentExecution,
    Device, LifecycleEvent, DeviceLifecycleState,
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
        """Create an Intent node in L4.  Returns the created node properties.

        Idempotent on ``intentId``: re-running with the same intentId is a
        no-op (MERGE + ON CREATE). The ``origin`` field is also written so
        HLD-driven intents can be looked up by source line later.
        """
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
                    i.priority    = $priority,
                    i.origin      = $origin
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
                origin     = intent.origin,
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

    def get_intent_by_origin(self, origin: str) -> Optional[dict]:
        """Look up an Intent by its origin string (e.g. ``HLD:file:line``).

        Used by Agent 1's HLD ingestion phase to detect re-commits and avoid
        creating duplicate Intent nodes when the operator commits the HLD
        without actually changing it.
        """
        with self._session() as s:
            result = s.run(
                "MATCH (i:Intent {origin: $origin}) RETURN i LIMIT 1",
                origin=origin,
            )
            record = result.single()
            return dict(record["i"]) if record else None

    # ------------------------------------------------------------------
    # L4 — Policy & FirewallRule  (output of Agent 2)
    # ------------------------------------------------------------------

    def create_policy(self, policy) -> dict:
        """Create or update a Policy node in L4 (idempotent on policyId)."""
        with self._session() as s:
            result = s.run(
                """
                MERGE (p:Policy {policyId: $policyId})
                SET p.name        = $name,
                    p.type        = $type,
                    p.intentId    = $intentId,
                    p.modelState  = $modelState,
                    p.createdAt   = $createdAt,
                    p.description = $description
                WITH p
                MATCH (i:Intent {intentId: $intentId})
                MERGE (i)-[:DECOMPOSED_INTO]->(p)
                RETURN p
                """,
                policyId    = policy.policyId,
                name        = policy.name,
                type        = policy.type,
                intentId    = policy.intentId,
                modelState  = policy.modelState.value,
                createdAt   = policy.createdAt,
                description = policy.description,
            )
            record = result.single()
            return dict(record["p"]) if record else {}

    def create_firewall_rule(self, rule) -> dict:
        """Create or update a FirewallRule node in L4 (idempotent on ruleId)."""
        with self._session() as s:
            result = s.run(
                """
                MERGE (r:FirewallRule {ruleId: $ruleId})
                SET r.policyId    = $policyId,
                    r.sourceZone  = $sourceZone,
                    r.destZone    = $destZone,
                    r.action      = $action,
                    r.sourceVlan  = $sourceVlan,
                    r.destVlan    = $destVlan,
                    r.protocol    = $protocol,
                    r.sourcePort  = $sourcePort,
                    r.destPort    = $destPort,
                    r.priority    = $priority,
                    r.modelState  = $modelState,
                    r.createdAt   = $createdAt,
                    r.description = $description
                WITH r
                MATCH (p:Policy {policyId: $policyId})
                MERGE (p)-[:CONTAINS]->(r)
                RETURN r
                """,
                ruleId      = rule.ruleId,
                policyId    = rule.policyId,
                sourceZone  = rule.sourceZone,
                destZone    = rule.destZone,
                action      = rule.action,
                sourceVlan  = rule.sourceVlan,
                destVlan    = rule.destVlan,
                protocol    = rule.protocol,
                sourcePort  = rule.sourcePort,
                destPort    = rule.destPort,
                priority    = rule.priority,
                modelState  = rule.modelState.value,
                createdAt   = rule.createdAt,
                description = rule.description,
            )
            record = result.single()
            return dict(record["r"]) if record else {}

    # ------------------------------------------------------------------
    # L1 — VLAN  (output of Agent 1's HLD ingestion phase, Slice 2)
    # ------------------------------------------------------------------

    def create_vlan(
        self,
        vlan_id: int,
        name: str,
        model_state: str = "CANDIDATE",
        origin: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> dict:
        """Create or update a VLAN node in L1 (idempotent on vlanId).

        When the HLD's population table introduces a new population, A1
        writes the corresponding L1 VLAN here. Switches consume these
        VLAN nodes at render time (Agent 3 vendor dispatch).

        ``intent_id`` is optional — when given, a TRACES_TO relationship
        is created from VLAN → Intent so the audit trail is queryable
        in either direction.
        """
        with self._session() as s:
            result = s.run(
                """
                MERGE (v:VLAN {vlanId: $vlanId})
                ON CREATE SET
                    v.name       = $name,
                    v.modelState = $modelState,
                    v.createdAt  = $createdAt,
                    v.origin     = $origin
                ON MATCH SET
                    v.name       = $name,
                    v.modelState = $modelState,
                    v.origin     = coalesce($origin, v.origin)
                RETURN v
                """,
                vlanId     = vlan_id,
                name       = name,
                modelState = model_state,
                createdAt  = datetime.now(timezone.utc).isoformat(),
                origin     = origin,
            )
            record = result.single()
            vlan = dict(record["v"]) if record else {}

            if intent_id:
                s.run(
                    """
                    MATCH (v:VLAN {vlanId: $vlanId})
                    MATCH (i:Intent {intentId: $intentId})
                    MERGE (v)-[:TRACES_TO]->(i)
                    """,
                    vlanId=vlan_id, intentId=intent_id,
                )
            return vlan

    # ------------------------------------------------------------------
    # L1 — Device  (output of A1's HLD device-ingest path, Slice 3)
    # ------------------------------------------------------------------

    def create_device(self, device: Device) -> dict:
        """Create or update a Device node in L1 (idempotent on deviceId).

        The Device gets a LOCATED_AT relationship to its Site (which is
        MERGED on the fly so re-runs don't fail when the Site doesn't
        exist yet — useful for HLD-driven flows that may declare devices
        before the operator has explicitly seeded sites).
        """
        with self._session() as s:
            result = s.run(
                """
                MERGE (d:Device {deviceId: $deviceId})
                SET d.hostname        = $hostname,
                    d.vendor          = $vendor,
                    d.platform        = $platform,
                    d.deviceRole      = $deviceRole,
                    d.siteId          = $siteId,
                    d.clabContainer   = $clabContainer,
                    d.mgmtIpv4        = $mgmtIpv4,
                    d.lifecycleState  = $lifecycleState,
                    d.modelState      = $modelState,
                    d.origin          = $origin,
                    d.createdAt       = coalesce(d.createdAt, $createdAt)
                WITH d
                MERGE (s:Site {siteId: $siteId})
                MERGE (d)-[:LOCATED_AT]->(s)
                RETURN d
                """,
                deviceId       = device.deviceId,
                hostname       = device.hostname,
                vendor         = device.vendor,
                platform       = device.platform,
                deviceRole     = device.deviceRole,
                siteId         = device.siteId,
                clabContainer  = device.clabContainer,
                mgmtIpv4       = device.mgmtIpv4,
                lifecycleState = device.lifecycleState.value,
                modelState     = device.modelState.value,
                origin         = device.origin,
                createdAt      = device.createdAt,
            )
            record = result.single()
            return dict(record["d"]) if record else {}

    def update_device_lifecycle(self, device_id: str, new_state: str) -> None:
        """Move a Device through its lifecycle state machine.

        Doesn't validate the transition — the provisioner is responsible
        for honoring the PLANNED → PROVISIONED → ACTIVE → RETIRED order.
        """
        with self._session() as s:
            s.run(
                "MATCH (d:Device {deviceId: $id}) SET d.lifecycleState = $state",
                id=device_id, state=new_state,
            )

    def get_device(self, device_id: str) -> Optional[dict]:
        """Look up a Device by its deviceId."""
        with self._session() as s:
            result = s.run(
                "MATCH (d:Device {deviceId: $id}) RETURN d",
                id=device_id,
            )
            record = result.single()
            return dict(record["d"]) if record else None

    def get_device_by_clab_container(self, container: str) -> Optional[dict]:
        """Look up a Device by its clabContainer property.

        Used by the provisioner to detect orphan containers (clab nodes
        that aren't reflected in Neo4j) and reconcile them.
        """
        with self._session() as s:
            result = s.run(
                "MATCH (d:Device {clabContainer: $c}) RETURN d LIMIT 1",
                c=container,
            )
            record = result.single()
            return dict(record["d"]) if record else None

    # ------------------------------------------------------------------
    # L8 — LifecycleEvent  (Slice 3)
    # ------------------------------------------------------------------

    def create_lifecycle_event(self, event: LifecycleEvent) -> dict:
        """Append a LifecycleEvent (L8) for a Device transition."""
        with self._session() as s:
            result = s.run(
                """
                CREATE (e:LifecycleEvent {
                    eventId:      $eventId,
                    deviceId:     $deviceId,
                    eventType:    $eventType,
                    fromState:    $fromState,
                    toState:      $toState,
                    timestamp:    $timestamp,
                    payload:      $payload,
                    errorMessage: $errorMessage
                })
                WITH e
                MATCH (d:Device {deviceId: $deviceId})
                MERGE (e)-[:RECORDS]->(d)
                RETURN e
                """,
                eventId      = event.eventId,
                deviceId     = event.deviceId,
                eventType    = event.eventType,
                fromState    = event.fromState,
                toState      = event.toState,
                timestamp    = event.timestamp,
                payload      = event.payload,
                errorMessage = event.errorMessage,
            )
            record = result.single()
            return dict(record["e"]) if record else {}

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
