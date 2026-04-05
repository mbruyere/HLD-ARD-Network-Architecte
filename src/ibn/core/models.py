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
    """L4 Intent node — output of Agent 1 (Ingestion)."""
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


VALID_INTENT_ACTIONS = {"permit", "deny", "redirect", "rate-limit"}


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
