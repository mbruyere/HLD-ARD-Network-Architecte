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
