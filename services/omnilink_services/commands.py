"""Command service: validated, audited, rate-limited, four-eyes approval for sensitive actions."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, HTTPException
from omnilink_contracts import Command, CommandResult, CommandStatus, topic_for
from omnilink_contracts.models import utcnow
from omnilink_sdk import MemoryPublisher, Publisher
from pydantic import BaseModel, Field

from .common import Principal, create_app, require

APPROVAL_REQUIRED = set(os.environ.get("OMNILINK_APPROVAL_ACTIONS", "reboot,write_point.safety,relinquish").split(","))
RATE_PER_MIN = int(os.environ.get("OMNILINK_COMMANDS_PER_DEVICE_MIN", "10"))


class CommandIn(BaseModel):
    connector_id: str
    action: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    params: dict[str, Any] = Field(default_factory=dict)
    ttl_s: int = Field(default=30, ge=1, le=3600)
    safety: bool = False  # caller marks writes to safety-classified points (also enforced from point metadata)


class CommandView(BaseModel):
    command: Command
    status: str
    approved_by: str | None = None
    detail: str | None = None


class CommandStore:
    def __init__(self):
        self.items: dict[str, CommandView] = {}
        self.audit: list[dict] = []
        self._rate: dict[str, deque] = defaultdict(deque)

    def rate_ok(self, key: str) -> bool:
        q, now = self._rate[key], time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MIN:
            return False
        q.append(now)
        return True

    def log(self, tenant: str, actor: str, event: str, target: str, **detail):
        self.audit.append({"tenant": tenant, "actor": actor, "event": event, "target": target, "detail": detail})


def needs_approval(body: CommandIn) -> bool:
    key = f"{body.action}.safety" if body.safety else body.action
    return key in APPROVAL_REQUIRED or body.action in APPROVAL_REQUIRED


def build_app(publisher: Publisher | None = None, store: CommandStore | None = None, consume: bool = False):
    pub = publisher or MemoryPublisher()
    store = store or CommandStore()

    async def result_loop():  # pragma: no cover - integration path
        from aiokafka import AIOKafkaConsumer
        from omnilink_contracts.topics import T

        c = AIOKafkaConsumer(T.COMMAND_RESULTS, bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
                             group_id="command-service")
        await c.start()
        try:
            async for m in c:
                on_result(CommandResult.from_bytes(m.value))
        finally:
            await c.stop()

    @asynccontextmanager
    async def lifespan(_app):
        import asyncio

        await pub.start()
        task = asyncio.create_task(result_loop()) if consume else None
        yield
        if task:
            task.cancel()
        await pub.stop()

    app = create_app("command-service", "OmniLink Command Service", lifespan)
    app.state.store = store

    async def dispatch(view: CommandView):
        cmd = view.command
        await pub.send(topic_for(cmd), cmd.kafka_key().encode(), cmd.to_bytes())
        view.status = CommandStatus.SENT.value

    @app.post("/v1/devices/{device_id}/commands", response_model=CommandView, status_code=202)
    async def create(device_id: str, body: CommandIn, p: Principal = Depends(require("operator"))):
        if not store.rate_ok(f"{p.tenant}:{device_id}"):
            raise HTTPException(429, f"max {RATE_PER_MIN} commands/min per device")
        cmd = Command(tenant=p.tenant, device_id=device_id, connector_id=body.connector_id, action=body.action,
                      params=body.params, requested_by=p.username or p.sub, ttl_s=body.ttl_s)
        view = CommandView(command=cmd, status=CommandStatus.PENDING.value)
        store.items[cmd.command_id] = view
        store.log(p.tenant, cmd.requested_by, "command.requested", device_id, action=body.action, params=body.params)
        if needs_approval(body):
            view.detail = "awaiting supervisor approval"
            return view
        await dispatch(view)
        return view

    @app.post("/v1/commands/{command_id}/approve", response_model=CommandView)
    async def approve(command_id: str, p: Principal = Depends(require("supervisor"))):
        view = store.items.get(command_id)
        if view is None or view.command.tenant != p.tenant:
            raise HTTPException(404, "command not found")
        if view.status != CommandStatus.PENDING.value:
            raise HTTPException(409, f"command is {view.status}")
        approver = p.username or p.sub
        if approver == view.command.requested_by:
            raise HTTPException(403, "four-eyes rule: approver must differ from requester")
        # re-issue with fresh timestamp so TTL counts from approval
        view.command = view.command.model_copy(update={"requested_at": utcnow()})
        view.approved_by, view.detail = approver, None
        store.log(p.tenant, approver, "command.approved", view.command.device_id, command_id=command_id)
        await dispatch(view)
        return view

    @app.get("/v1/commands", response_model=list[CommandView])
    async def list_commands(status: str | None = None, p: Principal = Depends(require("viewer"))):
        items = [v for v in store.items.values() if v.command.tenant == p.tenant and (status is None or v.status == status)]
        return sorted(items, key=lambda v: v.command.requested_at, reverse=True)[:200]

    @app.get("/v1/commands/{command_id}", response_model=CommandView)
    async def get(command_id: str, p: Principal = Depends(require("viewer"))):
        view = store.items.get(command_id)
        if view is None or view.command.tenant != p.tenant:
            raise HTTPException(404, "command not found")
        return view

    def on_result(res: CommandResult) -> None:
        view = store.items.get(res.command_id)
        if view:
            view.status, view.detail = res.status, res.detail
            store.log(res.tenant, "connector", f"command.{res.status}", res.device_id, command_id=res.command_id)

    app.state.on_result = on_result
    return app
