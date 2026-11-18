"""Canonical message models (schema v1).

Every message on the backbone is one of these models serialised as JSON.
Keys, URNs and timestamps follow docs/layers/01-contracts-backbone.md.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
_URN_RE = re.compile(r"^urn:ngsi-ld:([A-Za-z][A-Za-z0-9]*):([a-z0-9][a-z0-9-]*):([A-Za-z0-9._:-]+)$")
_TENANT_RE = r"^[a-z0-9][a-z0-9-]{1,62}$"


def utcnow() -> datetime:
    return datetime.now(UTC)


def entity_urn(entity_type: str, tenant: str, local_id: str) -> str:
    urn = f"urn:ngsi-ld:{entity_type}:{tenant}:{local_id}"
    if not _URN_RE.match(urn):
        raise ValueError(f"invalid entity URN: {urn}")
    return urn


def parse_urn(urn: str) -> tuple[str, str, str]:
    m = _URN_RE.match(urn)
    if not m:
        raise ValueError(f"invalid entity URN: {urn}")
    return m.group(1), m.group(2), m.group(3)


class Quality(str, Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class HealthStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class AlarmState(str, Enum):
    """ISA-18.2 alarm states."""

    ACTIVE_UNACK = "active_unack"
    ACTIVE_ACK = "active_ack"
    CLEARED_UNACK = "cleared_unack"
    CLEARED = "cleared"
    SHELVED = "shelved"


class CommandStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    ACKED = "acked"
    FAILED = "failed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant: str = Field(pattern=_TENANT_RE)

    def kafka_key(self) -> str:  # overridden where needed
        return f"{self.tenant}:{self.device_id}"

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode()

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls.model_validate_json(data)


Scalar = Union[bool, int, float, str]


class TelemetryEvent(_Envelope):
    device_id: str = Field(min_length=1, max_length=128)
    entity_id: str
    entity_type: str
    attribute: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    value: Union[Scalar, dict[str, Any]]
    unit: str | None = None
    quality: Quality = Quality.GOOD
    source_ts: datetime
    ingest_ts: datetime = Field(default_factory=utcnow)
    protocol: str
    point_ref: str
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("entity_id")
    @classmethod
    def _check_urn(cls, v: str) -> str:
        parse_urn(v)
        return v


class DeviceEvent(_Envelope):
    device_id: str
    entity_id: str | None = None
    event_type: str
    severity: Severity = Severity.INFO
    payload: dict[str, Any] = Field(default_factory=dict)
    source_ts: datetime
    ingest_ts: datetime = Field(default_factory=utcnow)
    protocol: str


class DeviceHealth(_Envelope):
    device_id: str
    connector_id: str
    status: HealthStatus
    last_seen: datetime | None = None
    reported_at: datetime = Field(default_factory=utcnow)
    metrics: dict[str, float] = Field(default_factory=dict)
    detail: str | None = None


class RuleHit(_Envelope):
    rule_id: str
    entity_id: str
    attribute: str
    value: float
    threshold: float
    condition: str  # gt, gte, lt, lte, eq, ne
    active: bool = True  # False = condition returned to normal
    ts: datetime

    def kafka_key(self) -> str:
        return f"{self.tenant}:{self.rule_id}:{self.entity_id}"


class Alarm(_Envelope):
    alarm_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    entity_id: str
    attribute: str | None = None
    priority: int = Field(ge=1, le=4)  # 1 = highest
    state: AlarmState = AlarmState.ACTIVE_UNACK
    message: str
    raised_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    acked_by: str | None = None
    acked_at: datetime | None = None
    cleared_at: datetime | None = None
    shelved_until: datetime | None = None
    last_value: float | None = None
    occurrences: int = 1

    def kafka_key(self) -> str:
        return f"{self.tenant}:{self.alarm_id}"


class Command(_Envelope):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    connector_id: str
    action: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")  # e.g. write_point, ptz.goto_preset, reboot
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str
    requested_at: datetime = Field(default_factory=utcnow)
    ttl_s: int = Field(default=30, ge=1, le=3600)

    def expired(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return (now - self.requested_at).total_seconds() > self.ttl_s


class CommandResult(_Envelope):
    command_id: str
    device_id: str
    status: CommandStatus
    detail: str | None = None
    completed_at: datetime = Field(default_factory=utcnow)


MODELS: dict[str, type[_Envelope]] = {
    "TelemetryEvent": TelemetryEvent,
    "DeviceEvent": DeviceEvent,
    "DeviceHealth": DeviceHealth,
    "RuleHit": RuleHit,
    "Alarm": Alarm,
    "Command": Command,
    "CommandResult": CommandResult,
}
