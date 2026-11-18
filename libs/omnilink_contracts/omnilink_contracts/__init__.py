"""Canonical contracts for the Smart City Integration Platform (OmniLink)."""

from .models import (
    SCHEMA_VERSION,
    Alarm,
    AlarmState,
    Command,
    CommandResult,
    CommandStatus,
    DeviceEvent,
    DeviceHealth,
    HealthStatus,
    Quality,
    RuleHit,
    Severity,
    TelemetryEvent,
    entity_urn,
    parse_urn,
)
from .topics import TOPICS, Topic, topic_for

__all__ = [
    "SCHEMA_VERSION",
    "Alarm",
    "AlarmState",
    "Command",
    "CommandResult",
    "CommandStatus",
    "DeviceEvent",
    "DeviceHealth",
    "HealthStatus",
    "Quality",
    "RuleHit",
    "Severity",
    "TelemetryEvent",
    "Topic",
    "TOPICS",
    "entity_urn",
    "parse_urn",
    "topic_for",
]
