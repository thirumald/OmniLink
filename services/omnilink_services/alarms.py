"""Alarm service: ISA-18.2 lifecycle from rule hits and device health."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Query
from omnilink_contracts import Alarm, AlarmState, DeviceHealth, HealthStatus, RuleHit, topic_for
from omnilink_sdk import MemoryPublisher, Publisher
from pydantic import BaseModel, Field

from .common import Principal, create_app, require

OPEN = {AlarmState.ACTIVE_UNACK.value, AlarmState.ACTIVE_ACK.value, AlarmState.CLEARED_UNACK.value,
        AlarmState.SHELVED.value}


class IllegalTransition(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class AlarmEngine:
    """Pure state machine + store. Persistence adapters wrap ``alarms`` (dict) in production."""

    def __init__(self, rules: dict[str, dict] | None = None):
        self.alarms: dict[str, Alarm] = {}
        self.rules = rules or {}  # rule_id -> {"priority": int, "message": str}
        self._shelved_from: dict[str, str] = {}

    def _open_for(self, tenant: str, rule_id: str, entity_id: str) -> Alarm | None:
        for a in self.alarms.values():
            if a.tenant == tenant and a.rule_id == rule_id and a.entity_id == entity_id and a.state in OPEN:
                return a
        return None

    def on_rule_hit(self, hit: RuleHit) -> Alarm | None:
        a = self._open_for(hit.tenant, hit.rule_id, hit.entity_id)
        rule = self.rules.get(hit.rule_id, {})
        if hit.active:
            if a is None:
                a = Alarm(tenant=hit.tenant, rule_id=hit.rule_id, entity_id=hit.entity_id, attribute=hit.attribute,
                          priority=rule.get("priority", 3),
                          message=rule.get("message", f"{hit.attribute} {hit.condition} {hit.threshold}"),
                          last_value=hit.value, raised_at=hit.ts, updated_at=hit.ts)
                self.alarms[a.alarm_id] = a
                return a
            changes: dict[str, Any] = {"occurrences": a.occurrences + 1, "last_value": hit.value, "updated_at": hit.ts}
            if a.state == AlarmState.CLEARED_UNACK.value:
                changes["state"] = AlarmState.ACTIVE_UNACK
            return self._save(a, **changes)
        if a is None:
            return None
        nxt = {AlarmState.ACTIVE_UNACK.value: AlarmState.CLEARED_UNACK,
               AlarmState.ACTIVE_ACK.value: AlarmState.CLEARED}.get(a.state)
        if nxt is None:
            return None
        return self._save(a, state=nxt, cleared_at=hit.ts, last_value=hit.value, updated_at=hit.ts)

    def ack(self, alarm_id: str, user: str) -> Alarm:
        a = self._get(alarm_id)
        nxt = {AlarmState.ACTIVE_UNACK.value: AlarmState.ACTIVE_ACK,
               AlarmState.CLEARED_UNACK.value: AlarmState.CLEARED}.get(a.state)
        if nxt is None:
            raise IllegalTransition(f"cannot ack alarm in state {a.state}")
        return self._save(a, state=nxt, acked_by=user, acked_at=_now(), updated_at=_now())

    def shelve(self, alarm_id: str, user: str, minutes: int) -> Alarm:
        a = self._get(alarm_id)
        if a.state not in OPEN or a.state == AlarmState.SHELVED.value:
            raise IllegalTransition(f"cannot shelve alarm in state {a.state}")
        self._shelved_from[alarm_id] = a.state
        return self._save(a, state=AlarmState.SHELVED, shelved_until=_now() + timedelta(minutes=minutes),
                          acked_by=user, updated_at=_now())

    def clear(self, alarm_id: str, user: str) -> Alarm:
        a = self._get(alarm_id)
        if a.state == AlarmState.CLEARED.value:
            raise IllegalTransition("already cleared")
        return self._save(a, state=AlarmState.CLEARED, cleared_at=_now(), acked_by=a.acked_by or user, updated_at=_now())

    def unshelve_expired(self, now: datetime | None = None) -> list[Alarm]:
        now = now or _now()
        out = []
        for a in list(self.alarms.values()):
            if a.state == AlarmState.SHELVED.value and a.shelved_until and a.shelved_until <= now:
                out.append(self._save(a, state=self._shelved_from.pop(a.alarm_id, AlarmState.ACTIVE_UNACK.value),
                                      shelved_until=None, updated_at=now))
        return out

    def on_health(self, h: DeviceHealth) -> Alarm | None:
        hit = RuleHit(tenant=h.tenant, rule_id="device-offline", entity_id=f"urn:ngsi-ld:Device:{h.tenant}:{_safe(h.device_id)}",
                      attribute="status", value=0.0 if h.status == HealthStatus.OFFLINE.value else 1.0, threshold=0.5,
                      condition="lt", active=h.status == HealthStatus.OFFLINE.value, ts=h.reported_at)
        self.rules.setdefault("device-offline", {"priority": 2, "message": f"Device offline: {h.device_id}"})
        return self.on_rule_hit(hit)

    def list(self, tenant: str, state: str | None = None, priority_max: int = 4) -> list[Alarm]:
        out = [a for a in self.alarms.values() if a.tenant == tenant and a.priority <= priority_max
               and (state is None or a.state == state or (state == "open" and a.state in OPEN))]
        return sorted(out, key=lambda a: (a.priority, a.raised_at))

    def _get(self, alarm_id: str) -> Alarm:
        try:
            return self.alarms[alarm_id]
        except KeyError as exc:
            raise KeyError(alarm_id) from exc

    def _save(self, a: Alarm, **changes) -> Alarm:
        upd = a.model_copy(update={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()})
        self.alarms[a.alarm_id] = upd
        return upd


def _safe(device_id: str) -> str:
    return "".join(c if c.isalnum() or c in "._:-" else "-" for c in device_id)


class IncidentIn(BaseModel):
    alarm_id: str
    entity_id: str
    priority: int = Field(ge=1, le=4)
    title: str


class CloseIn(BaseModel):
    resolution: str


class ShelveIn(BaseModel):
    minutes: int = Field(ge=1, le=7 * 24 * 60)


def build_app(engine: AlarmEngine | None = None, publisher: Publisher | None = None, consume: bool = False):
    engine = engine or AlarmEngine()
    pub = publisher or MemoryPublisher()

    async def emit(a: Alarm | None):
        if a is not None:
            await pub.send(topic_for(a), a.kafka_key().encode(), a.to_bytes())

    async def consumer_loop():  # pragma: no cover - integration path
        from aiokafka import AIOKafkaConsumer
        from omnilink_contracts.topics import T

        c = AIOKafkaConsumer(T.RULE_HITS, T.HEALTH, bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
                             group_id="alarm-service", enable_auto_commit=False)
        await c.start()
        try:
            async for m in c:
                a = engine.on_rule_hit(RuleHit.from_bytes(m.value)) if m.topic == T.RULE_HITS \
                    else engine.on_health(DeviceHealth.from_bytes(m.value))
                await emit(a)
                await c.commit()
        finally:
            await c.stop()

    async def shelve_loop():  # pragma: no cover
        while True:
            for a in engine.unshelve_expired():
                await emit(a)
            await asyncio.sleep(15)

    @asynccontextmanager
    async def lifespan(_app):
        await pub.start()
        tasks = [asyncio.create_task(shelve_loop())]
        if consume:
            tasks.append(asyncio.create_task(consumer_loop()))
        yield
        for t in tasks:
            t.cancel()
        await pub.stop()

    app = create_app("alarm-service", "OmniLink Alarm Service", lifespan)
    app.state.engine = engine

    def owned(alarm_id: str, p: Principal) -> Alarm:
        a = engine.alarms.get(alarm_id)
        if a is None or a.tenant != p.tenant:
            raise HTTPException(404, "alarm not found")
        return a

    @app.get("/v1/alarms", response_model=list[Alarm])
    async def list_alarms(state: str | None = Query(None), priority_max: int = Query(4, ge=1, le=4),
                          p: Principal = Depends(require("viewer"))):
        return engine.list(p.tenant, state, priority_max)

    @app.post("/v1/alarms/{alarm_id}/ack", response_model=Alarm)
    async def ack(alarm_id: str, p: Principal = Depends(require("operator"))):
        owned(alarm_id, p)
        try:
            a = engine.ack(alarm_id, p.username or p.sub)
        except IllegalTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        await emit(a)
        return a

    @app.post("/v1/alarms/{alarm_id}/shelve", response_model=Alarm)
    async def shelve(alarm_id: str, body: ShelveIn, p: Principal = Depends(require("supervisor"))):
        owned(alarm_id, p)
        try:
            a = engine.shelve(alarm_id, p.username or p.sub, body.minutes)
        except IllegalTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        await emit(a)
        return a

    @app.post("/v1/alarms/{alarm_id}/clear", response_model=Alarm)
    async def clear(alarm_id: str, p: Principal = Depends(require("supervisor"))):
        owned(alarm_id, p)
        try:
            a = engine.clear(alarm_id, p.username or p.sub)
        except IllegalTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        await emit(a)
        return a

    # ---- incidents (opened by workflows, closed when the alarm clears) -----------------
    incidents: dict[str, dict] = {}
    app.state.incidents = incidents

    @app.post("/v1/incidents", status_code=201)
    async def open_incident(body: IncidentIn, p: Principal = Depends(require("operator"))):
        for inc in incidents.values():  # idempotent per alarm
            if inc["alarm_id"] == body.alarm_id and inc["tenant"] == p.tenant:
                return inc
        inc_id = f"INC-{len(incidents) + 1:06d}"
        incidents[inc_id] = {"incident_id": inc_id, "tenant": p.tenant, "status": "open", "opened_at": _now().isoformat(),
                             **body.model_dump()}
        return incidents[inc_id]

    @app.post("/v1/incidents/{incident_id}/close")
    async def close_incident(incident_id: str, body: CloseIn, p: Principal = Depends(require("operator"))):
        inc = incidents.get(incident_id)
        if not inc or inc["tenant"] != p.tenant:
            raise HTTPException(404, "incident not found")
        inc.update(status="closed", resolution=body.resolution, closed_at=_now().isoformat())
        return inc

    @app.get("/v1/incidents")
    async def list_incidents(status: str | None = None, p: Principal = Depends(require("viewer"))):
        return [i for i in incidents.values() if i["tenant"] == p.tenant and (status is None or i["status"] == status)]

    return app
