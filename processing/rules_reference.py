"""Reference semantics for threshold rules (the Flink job must match these outputs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from omnilink_contracts import RuleHit, TelemetryEvent

_OPS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
    "ne": lambda v, t: v != t,
}


@dataclass
class Rule:
    id: str
    tenant: str
    attribute: str
    condition: str
    threshold: float
    hysteresis: float = 0.0
    entity_type: str | None = None
    entity_id: str | None = None
    enabled: bool = True

    def applies(self, ev: TelemetryEvent) -> bool:
        if not self.enabled or ev.tenant != self.tenant or ev.attribute != self.attribute:
            return False
        if self.entity_id:
            return ev.entity_id == self.entity_id
        return ev.entity_type == self.entity_type

    def breach(self, v: float) -> bool:
        return _OPS[self.condition](v, self.threshold)

    def normal(self, v: float) -> bool:
        h = self.hysteresis
        if self.condition in ("gt", "gte"):
            return v <= self.threshold - h if self.condition == "gt" else v < self.threshold - h
        if self.condition in ("lt", "lte"):
            return v >= self.threshold + h if self.condition == "lt" else v > self.threshold + h
        return not self.breach(v)


class RuleEvaluator:
    def __init__(self, rules: list[Rule]):
        self.rules = rules
        self.active: dict[tuple[str, str], bool] = {}

    def evaluate(self, ev: TelemetryEvent) -> list[RuleHit]:
        if ev.quality != "good" or isinstance(ev.value, (bool, str, dict)):
            return []
        v = float(ev.value)
        hits = []
        for r in self.rules:
            if not r.applies(ev):
                continue
            key = (r.id, ev.entity_id)
            was = self.active.get(key, False)
            if not was and r.breach(v):
                self.active[key] = True
                hits.append(self._hit(r, ev, v, True))
            elif was and r.normal(v):
                self.active[key] = False
                hits.append(self._hit(r, ev, v, False))
        return hits

    @staticmethod
    def _hit(r: Rule, ev: TelemetryEvent, v: float, active: bool) -> RuleHit:
        ts: datetime = ev.source_ts
        return RuleHit(tenant=ev.tenant, rule_id=r.id, entity_id=ev.entity_id, attribute=ev.attribute, value=v,
                       threshold=r.threshold, condition=r.condition, active=active, ts=ts)
