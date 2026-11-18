"""Topic catalogue — single source of truth is backbone/kafka/topics.yaml.

The constants here mirror it so code never hard-codes topic strings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Alarm,
    Command,
    CommandResult,
    DeviceEvent,
    DeviceHealth,
    RuleHit,
    TelemetryEvent,
)


@dataclass(frozen=True)
class Topic:
    name: str
    model: type | None
    partitions: int
    retention_ms: int | None
    compacted: bool = False


_DAY = 86_400_000


class T:
    TELEMETRY = "omnilink.telemetry.v1"
    TELEMETRY_ENRICHED = "omnilink.telemetry.enriched.v1"
    EVENTS = "omnilink.events.v1"
    HEALTH = "omnilink.health.v1"
    RULE_HITS = "omnilink.rule-hits.v1"
    ALARMS = "omnilink.alarms.v1"
    COMMANDS = "omnilink.commands.v1"
    COMMAND_RESULTS = "omnilink.command-results.v1"
    CDC_DEVICES = "omnilink.cdc.devices.v1"
    CDC_ALARM_RULES = "omnilink.cdc.alarm-rules.v1"
    AI_SUGGESTIONS = "omnilink.ai-suggestions.v1"
    DLQ = "omnilink.dlq.v1"


TOPICS: dict[str, Topic] = {
    t.name: t
    for t in [
        Topic(T.TELEMETRY, TelemetryEvent, 48, 7 * _DAY),
        Topic(T.TELEMETRY_ENRICHED, None, 48, 3 * _DAY),
        Topic(T.EVENTS, DeviceEvent, 24, 7 * _DAY),
        Topic(T.HEALTH, DeviceHealth, 12, 3 * _DAY, compacted=True),
        Topic(T.RULE_HITS, RuleHit, 12, 3 * _DAY),
        Topic(T.ALARMS, Alarm, 12, 30 * _DAY),
        Topic(T.COMMANDS, Command, 12, 1 * _DAY),
        Topic(T.COMMAND_RESULTS, CommandResult, 12, 7 * _DAY),
        Topic(T.CDC_DEVICES, None, 6, None, compacted=True),
        Topic(T.CDC_ALARM_RULES, None, 3, None, compacted=True),
        Topic(T.AI_SUGGESTIONS, None, 6, 30 * _DAY),
        Topic(T.DLQ, None, 6, 14 * _DAY),
    ]
}

_BY_MODEL = {t.model: t.name for t in TOPICS.values() if t.model is not None}


def topic_for(message) -> str:
    """Return the topic a canonical message belongs on."""
    try:
        return _BY_MODEL[type(message)]
    except KeyError as exc:
        raise ValueError(f"no topic registered for {type(message).__name__}") from exc
