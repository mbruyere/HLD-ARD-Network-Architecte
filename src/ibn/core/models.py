"""
Shared domain models for the IBN closed-loop system.

All Neo4j nodes are represented as dataclasses.  Every node carries a
``modelState`` — one of the five lifecycle states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Model state enum
# ---------------------------------------------------------------------------

class ModelState(str, Enum):
    WHAT_IF   = "WHAT_IF"
    CANDIDATE = "CANDIDATE"
    POR       = "POR"
    DEPLOYED  = "DEPLOYED"
    AS_BUILT  = "AS_BUILT"


# ---------------------------------------------------------------------------
# Device lifecycle (Slice 3)
# ---------------------------------------------------------------------------

class DeviceLifecycleState(str, Enum):
    """L8 lifecycle phase a Device walks through.

    PLANNED      — Device row exists in the HLD but not yet provisioned.
    PROVISIONED  — Container is up but not yet configured / verified.
    ACTIVE       — Container is up, config pushed, A7 verified COMPLIANT.
    DEGRADED     — Active but A7 currently reports drift.
    RETIRED      — HLD row removed; container torn down; configs archived.
    """
    PLANNED      = "PLANNED"
    PROVISIONED  = "PROVISIONED"
    ACTIVE       = "ACTIVE"
    DEGRADED     = "DEGRADED"
    RETIRED      = "RETIRED"


# ---------------------------------------------------------------------------
# Migration plan / approval gate (Slice 4)
# ---------------------------------------------------------------------------

class MigrationPlanStatus(str, Enum):
    """L7 MigrationPlan status — drives the approval state machine.

    PENDING     — A4 generated the plan, waiting for human signoff
    APPROVED    — operator ran `ibn approve`; CANDIDATE→POR transitioned
    APPLIED     — A3-A5-A7 ran successfully against the POR artifacts
    REJECTED    — operator ran `ibn reject`; artifacts archived
    SUPERSEDED  — replaced by a newer plan against the same intents
    """
    PENDING    = "PENDING"
    APPROVED   = "APPROVED"
    APPLIED    = "APPLIED"
    REJECTED   = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlanSeverity(str, Enum):
    """Slice 4 severity classifier output."""
    INFO     = "INFO"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO     = "Info"
    LOW      = "Low"
    MEDIUM   = "Medium"
    HIGH     = "High"
    CRITICAL = "Critical"


# ---------------------------------------------------------------------------
# L4 — Policy & Intent
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    """L4 Intent node — output of Agent 1 (Ingestion).

    The ``origin`` field traces the Intent back to its source-of-truth.
    For HLD-driven flow it should be set to ``HLD:<file>:<line>`` so the
    pipeline can diff against the document and avoid duplicate creation
    on re-commit. For operator-typed intents the field stays None.
    """
    intentId:    str
    statement:   str
    type:        str                        # e.g. "access-policy"
    subject:     str                        # e.g. "Guest"
    action:      str                        # permit | deny | redirect | rate-limit
    target:      str                        # e.g. "Internet"
    status:      str        = "INGESTED"   # INGESTED → TRANSLATED → ORCHESTRATED → ACTIVE
    modelState:  ModelState = ModelState.CANDIDATE
    createdAt:   str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    authorId:    Optional[str] = None
    priority:    int        = 100
    origin:      Optional[str] = None       # e.g. "HLD:Enterprise_Campus_Network_HLD.md:3176"


VALID_INTENT_ACTIONS = {"permit", "deny", "redirect", "rate-limit"}


@dataclass
class Policy:
    """L4 Policy node — output of Agent 2 (Intent→Policy).

    A Policy is the decomposition of one Intent into a named bundle of
    enforcement rules. One Intent typically produces one Policy with
    multiple FirewallRules attached.
    """
    policyId:    str
    name:        str                        # e.g. "POL-CONTRACTOR-ACCESS"
    type:        str                        # e.g. "access-policy" | "qos-policy"
    intentId:    str                        # parent Intent that produced this Policy
    modelState:  ModelState = ModelState.CANDIDATE
    createdAt:   str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: Optional[str] = None


@dataclass
class FirewallRule:
    """L4 FirewallRule node — output of Agent 2 (Intent→Policy).

    Vendor-neutral firewall rule. Maps to one or more vendor-specific
    statements at render time (Agent 3): VyOS ``set firewall name``,
    Cisco ASA ``access-list``, Palo Alto ``security rule``, etc.
    """
    ruleId:      str
    policyId:    str                        # parent Policy
    sourceZone:  str                        # e.g. "USER" | "DMZ_INFRA"
    destZone:    str                        # e.g. "INTERNET"
    action:      str                        # permit | deny
    sourceVlan:  Optional[int] = None       # may be None for zone-wide rules
    destVlan:    Optional[int] = None
    protocol:    Optional[str] = None       # tcp | udp | icmp | any
    sourcePort:  Optional[str] = None       # "any" | "80" | "1024-65535"
    destPort:    Optional[str] = None
    priority:    int        = 100
    modelState:  ModelState = ModelState.CANDIDATE
    createdAt:   str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: Optional[str] = None


VALID_FIREWALL_RULE_ACTIONS = {"permit", "deny"}


# ---------------------------------------------------------------------------
# L1 — Device  (Slice 3)
# ---------------------------------------------------------------------------

@dataclass
class Device:
    """L1 Device node — output of Agent 1 device-ingest path (Slice 3).

    Devices live in L1 (Infrastructure). The HLD's Device Inventory
    Table is the source-of-truth for which devices exist; A1 reconciles
    Neo4j against that table on every HLD commit.

    The ``clabContainer`` field is what A5's vendor dispatch uses as
    the docker target. ``mgmtIpv4`` is allocated by the provisioner
    and reflects the live management IP on the lab network.
    """
    deviceId:      str
    hostname:      str
    vendor:        str                       # "Nokia" | "Cisco" | "VyOS" | …
    platform:      str                       # "srlinux" | "vyos" | "ios-xe" | …
    deviceRole:    str                       # "ACCESS_SWITCH" | "FIREWALL" | …
    siteId:        str                       # "SITE-HQ-01"
    clabContainer: Optional[str] = None
    mgmtIpv4:      Optional[str] = None
    lifecycleState: DeviceLifecycleState = DeviceLifecycleState.PLANNED
    modelState:    ModelState = ModelState.CANDIDATE
    createdAt:     str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    origin:        Optional[str] = None      # "HLD:<file>:<line>"


# ---------------------------------------------------------------------------
# L8 — Lifecycle  (Slice 3)
# ---------------------------------------------------------------------------

@dataclass
class LifecycleEvent:
    """L8 LifecycleEvent node — written when a Device transitions states.

    Each event records a state transition (PLANNED→PROVISIONED, etc.)
    so the audit trail captures device birth and death, not just config
    changes. Provisioning failures also write events with errorMessage.
    """
    eventId:      str
    deviceId:     str
    eventType:    str                        # "PROVISIONED" | "RETIRED" | "PROVISION_FAILED" | …
    fromState:    Optional[str] = None
    toState:      Optional[str] = None
    timestamp:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload:      Optional[str] = None       # free-form JSON or text
    errorMessage: Optional[str] = None


# ---------------------------------------------------------------------------
# L7 — MigrationPlan  (Slice 4)
# ---------------------------------------------------------------------------

@dataclass
class MigrationPlan:
    """L7 MigrationPlan node — output of Agent 4 (Planning).

    A migration plan is the unit of operator review. It bundles
    everything Agent 1+2+Provisioning produced from a single HLD
    commit and asks "should this become reality?". Approval
    transitions the referenced CANDIDATE artifacts to POR. Rejection
    archives them.

    The ``commitSha`` field is the git SHA the plan was generated from
    (used as the correlation key by the approve/reject CLI).
    """
    planId:           str
    commitSha:        str
    intentIds:        list[str]
    policyIds:        list[str]
    configIds:        list[str]
    deviceIds:        list[str]
    blastRadius:      int                       # number of devices touched
    severity:         PlanSeverity
    summary:          str                       # one-line human description
    inverseSummary:   str                       # one-line rollback description
    status:           MigrationPlanStatus = MigrationPlanStatus.PENDING
    createdAt:        str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approvedAt:       Optional[str] = None
    approvedBy:       Optional[str] = None
    appliedAt:        Optional[str] = None
    rejectedAt:       Optional[str] = None
    rejectedBy:       Optional[str] = None
    rejectedReason:   Optional[str] = None


# ---------------------------------------------------------------------------
# L5 — Config & State
# ---------------------------------------------------------------------------

@dataclass
class Configuration:
    """L5 Configuration node — output of Agent 3 (Policy→Config)."""
    configId:    str
    deviceId:    str
    content:     str
    version:     int        = 1
    modelState:  ModelState = ModelState.CANDIDATE
    createdAt:   str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DeploymentEvent:
    """L5 DeploymentEvent node — written by Agent 5 (Orchestration)."""
    eventId:        str
    targetDeviceId: str
    status:         str         # DEPLOYED | FAILED | ROLLED_BACK
    modelState:     ModelState  = ModelState.DEPLOYED
    timestamp:      str         = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    configId:       Optional[str] = None
    errorMessage:   Optional[str] = None
    rollbackFrom:   Optional[str] = None
    rollbackTo:     Optional[str] = None


@dataclass
class Telemetry:
    """L5 Telemetry node — written by Agent 6 (Monitoring)."""
    deviceId:      str
    metric:        str
    value:         str | float
    interfaceName: Optional[str] = None
    modelState:    ModelState    = ModelState.AS_BUILT
    timestamp:     str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class OperationalState:
    """L5 OperationalState node — written by Agent 6 (Monitoring)."""
    deviceId:            str
    operState:           str    = "running"   # running | degraded | down
    cpuUtilization:      float  = 0.0
    memoryUtilization:   float  = 0.0
    modelState:          ModelState = ModelState.AS_BUILT
    timestamp:           str    = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# L6 — Incidents
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """L6 Alert node — raised by Agent 6 (Monitoring) or Agent 7 (Assessment)."""
    alertId:    str
    severity:   Severity
    metric:     str
    value:      float
    threshold:  float
    deviceId:   str
    modelState: ModelState = ModelState.AS_BUILT
    timestamp:  str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# L9 — People / Process
# ---------------------------------------------------------------------------

@dataclass
class AgentExecution:
    """L9 audit record — every agent action is recorded here."""
    agentId:        str
    action:         str
    inputRef:       Optional[str] = None
    outputRef:      Optional[str] = None
    modelState:     ModelState    = ModelState.POR
    timestamp:      str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    durationMs:     Optional[int] = None
    errorMessage:   Optional[str] = None
