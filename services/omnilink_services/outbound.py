"""Outbound integration: signed webhooks, notifications, live relay to Centrifugo."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .common import Principal, create_app, require

log = logging.getLogger("omnilink.outbound")
RETRY_DELAYS_S = (1, 5, 30, 120, 600)


def sign(secret: bytes, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: bytes, timestamp: str, body: bytes, signature: str, max_age_s: int = 300, now: float | None = None) -> bool:
    if abs((now or time.time()) - int(timestamp)) > max_age_s:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


@dataclass
class Subscription:
    id: str
    tenant: str
    url: str
    secret: bytes
    topics: list[str]
    filter: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def matches(self, topic: str, msg: dict) -> bool:
        if not self.enabled or topic not in self.topics or msg.get("tenant") != self.tenant:
            return False
        f = self.filter
        if "entity_type" in f and msg.get("entity_type") not in f["entity_type"]:
            return False
        if "min_priority" in f and msg.get("priority", 99) > f["min_priority"]:
            return False
        if "event_type" in f and msg.get("event_type") not in f["event_type"]:
            return False
        if "entity_id_prefix" in f and not str(msg.get("entity_id", "")).startswith(f["entity_id_prefix"]):
            return False
        return True


class Dispatcher:
    def __init__(self, client: httpx.AsyncClient, sleep=asyncio.sleep, dlq=None):
        self.client, self.sleep, self.dlq = client, sleep, dlq

    async def deliver(self, sub: Subscription, topic: str, body: bytes) -> bool:
        delivery = str(uuid.uuid4())
        for attempt, delay in enumerate((0,) + RETRY_DELAYS_S):
            if delay:
                await self.sleep(delay)
            ts = str(int(time.time()))
            headers = {"Content-Type": "application/json", "X-OmniLink-Event": topic, "X-OmniLink-Delivery": delivery,
                       "X-OmniLink-Timestamp": ts, "X-OmniLink-Signature": sign(sub.secret, ts, body)}
            try:
                r = await self.client.post(sub.url, content=body, headers=headers, timeout=10)
                if r.status_code < 300:
                    return True
                if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                    break  # permanent failure
            except httpx.HTTPError as exc:
                log.info("webhook %s attempt %d failed: %s", sub.id, attempt + 1, exc)
        if self.dlq:
            await self.dlq(sub, topic, body)
        return False


class SubscriptionIn(BaseModel):
    name: str
    url: HttpUrl
    secret: str = Field(min_length=24)
    topics: list[str]
    filter: dict[str, Any] = Field(default_factory=dict)


class NotifyIn(BaseModel):
    group: str
    channels: list[str] = Field(default_factory=lambda: ["push"])
    subject: str
    body: str
    ref: str | None = None
    tenant: str | None = None


class Notifier:
    """Channels: sms (Jasmin HTTP API), email (SMTP via aiosmtplib), push (ntfy). Directory lookup by group."""

    def __init__(self, client: httpx.AsyncClient, directory: dict[str, list[dict]] | None = None):
        self.client = client
        self.directory = directory or json.loads(os.environ.get("OMNILINK_DIRECTORY", "{}"))
        self.sent: list[dict] = []

    async def send(self, tenant: str, n: NotifyIn) -> int:
        people = self.directory.get(f"{tenant}:{n.group}", [])
        count = 0
        for person in people:
            for ch in n.channels:
                if ch == "sms" and person.get("phone"):
                    await self._sms(person["phone"], f"{n.subject}\n{n.body}"[:450])
                elif ch == "push" and person.get("push_topic"):
                    await self.client.post(f"{os.environ.get('NTFY_URL', 'http://ntfy')}/{person['push_topic']}",
                                           content=n.body.encode(), headers={"Title": n.subject, "Priority": "high"})
                elif ch == "email" and person.get("email"):
                    await self._email(person["email"], n.subject, n.body)
                else:
                    continue
                self.sent.append({"to": person.get("name"), "channel": ch, "subject": n.subject})
                count += 1
        return count

    async def _sms(self, phone: str, text: str):
        await self.client.get(os.environ.get("JASMIN_URL", "http://jasmin:1401/send"),
                              params={"username": os.environ.get("JASMIN_USER", ""), "password": os.environ.get("JASMIN_PASSWORD", ""),
                                      "to": phone, "content": text})

    async def _email(self, to: str, subject: str, body: str):  # pragma: no cover
        from email.message import EmailMessage

        import aiosmtplib

        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = os.environ.get("SMTP_FROM", "omnilink@localhost"), to, subject
        m.set_content(body)
        await aiosmtplib.send(m, hostname=os.environ.get("SMTP_HOST", "smtp"), port=int(os.environ.get("SMTP_PORT", "587")),
                              start_tls=True, username=os.environ.get("SMTP_USER"), password=os.environ.get("SMTP_PASSWORD"))


def centrifugo_channel(topic: str, msg: dict) -> str | None:
    tenant = msg.get("tenant")
    if topic.startswith("omnilink.alarms"):
        return f"alarms:{tenant}"
    if topic.startswith("omnilink.telemetry.enriched"):
        return f"telemetry:{tenant}"
    if topic.startswith("omnilink.events"):
        return f"events:{tenant}"
    return None


def build_app(client: httpx.AsyncClient | None = None, notifier: Notifier | None = None):
    client = client or httpx.AsyncClient()
    notifier = notifier or Notifier(client)
    subs: dict[str, Subscription] = {}
    app = create_app("outbound", "OmniLink Outbound Integration")
    app.state.subs, app.state.notifier, app.state.dispatcher = subs, notifier, Dispatcher(client)

    @app.post("/v1/webhooks", status_code=201)
    async def create_sub(body: SubscriptionIn, p: Principal = Depends(require("integrator"))):
        if body.url.scheme != "https" and os.environ.get("OMNILINK_ALLOW_HTTP_WEBHOOKS") != "1":
            raise HTTPException(400, "webhook URL must be https")
        sid = str(uuid.uuid4())
        subs[sid] = Subscription(sid, p.tenant, str(body.url), body.secret.encode(), body.topics, body.filter)
        return {"id": sid}

    @app.get("/v1/webhooks")
    async def list_subs(p: Principal = Depends(require("integrator"))):
        return [{"id": s.id, "url": s.url, "topics": s.topics, "filter": s.filter} for s in subs.values()
                if s.tenant == p.tenant]

    @app.delete("/v1/webhooks/{sid}", status_code=204)
    async def delete_sub(sid: str, p: Principal = Depends(require("integrator"))):
        s = subs.get(sid)
        if not s or s.tenant != p.tenant:
            raise HTTPException(404, "not found")
        del subs[sid]

    @app.post("/v1/notify")
    async def notify(body: NotifyIn, p: Principal = Depends(require("operator"))):
        return {"sent": await notifier.send(p.tenant, body)}

    async def fan_out(topic: str, raw: bytes) -> int:
        msg = json.loads(raw)
        matched = [s for s in subs.values() if s.matches(topic, msg)]
        results = await asyncio.gather(*(app.state.dispatcher.deliver(s, topic, raw) for s in matched))
        ch = centrifugo_channel(topic, msg)
        if ch and os.environ.get("CENTRIFUGO_API_URL"):
            await client.post(os.environ["CENTRIFUGO_API_URL"] + "/api/publish", json={"channel": ch, "data": msg},
                              headers={"X-API-Key": os.environ.get("CENTRIFUGO_API_KEY", "")})
        return sum(results)

    app.state.fan_out = fan_out
    return app
