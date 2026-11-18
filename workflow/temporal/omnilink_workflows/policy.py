"""Escalation policy (pure data, deterministic — safe to use inside Temporal workflows)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EscalationLevel:
    name: str
    channels: tuple[str, ...]  # sms, email, push, radio
    recipients_group: str
    wait_s: int


@dataclass(frozen=True)
class EscalationPolicy:
    levels: tuple[EscalationLevel, ...] = field(default_factory=tuple)
    camera_radius_m: int = 300
    camera_preset: str = "incident"

    @staticmethod
    def for_priority(priority: int) -> EscalationPolicy:
        if priority == 1:
            return EscalationPolicy(levels=(
                EscalationLevel("duty-officer", ("sms", "push"), "duty-officers", 180),
                EscalationLevel("shift-supervisor", ("sms", "push", "email"), "supervisors", 300),
                EscalationLevel("operations-manager", ("sms", "email"), "managers", 600),
            ))
        if priority == 2:
            return EscalationPolicy(levels=(
                EscalationLevel("duty-officer", ("push",), "duty-officers", 300),
                EscalationLevel("shift-supervisor", ("sms", "push"), "supervisors", 900),
            ))
        return EscalationPolicy(levels=(EscalationLevel("duty-officer", ("push",), "duty-officers", 3600),))
