"""Inbound REST / webhook ingest for external systems.

POST /v1/ingest/{source}          JSON object or array of readings
POST /v1/ingest/{source}/events   device events (e.g. from a VMS, PSIM, CitrineOS/OCPP webhooks)

Each `source` has a mapping (sources.yaml): which JSON fields carry device id, timestamp
and which fields become attributes. Authentication is enforced at APISIX (API key / OAuth2);
the source must also be enabled for the caller's tenant.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from omnilink_contracts import DeviceEvent, Severity, TelemetryEvent, entity_urn, topic_for
from omnilink_sdk import MemoryPublisher, Publisher
from pydantic import BaseModel, Field


class FieldMap(BaseModel):
    attribute: str
    unit: str | None = None
    scale: float = 1.0


class SourceMap(BaseModel):
    tenant: str
    entity_type: str
    device_field: str = "device_id"
    ts_field: str | None = "ts"
    fields: dict[str, FieldMap] = Field(default_factory=dict)


def load_sources(path: str | Path) -> dict[str, SourceMap]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {k: SourceMap.model_validate(v) for k, v in raw.items()}


def to_events(source: str, sm: SourceMap, record: dict[str, Any]) -> list[TelemetryEvent]:
    device_id = str(record.get(sm.device_field) or "")
    if not device_id:
        raise ValueError(f"missing '{sm.device_field}'")
    ts = datetime.now(UTC)
    if sm.ts_field and record.get(sm.ts_field):
        ts = datetime.fromisoformat(str(record[sm.ts_field]).replace("Z", "+00:00"))
    out = []
    for field, fm in sm.fields.items():
        if field not in record or record[field] is None:
            continue
        v = record[field]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = v * fm.scale
        out.append(TelemetryEvent(tenant=sm.tenant, device_id=device_id,
                                  entity_id=entity_urn(sm.entity_type, sm.tenant, device_id),
                                  entity_type=sm.entity_type, attribute=fm.attribute, value=v, unit=fm.unit,
                                  source_ts=ts, protocol="http", point_ref=f"source:{source}:{field}",
                                  tags={"source": source}))
    return out


class EventIn(BaseModel):
    device_id: str
    event_type: str
    severity: Severity = Severity.INFO
    ts: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def create_app(sources: dict[str, SourceMap], publisher: Publisher) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        await publisher.start()
        yield
        await publisher.stop()

    app = FastAPI(title="OmniLink HTTP Ingest", version="1.0.0", lifespan=lifespan)

    def source_map(source: str) -> SourceMap:
        sm = sources.get(source)
        if sm is None:
            raise HTTPException(404, f"unknown source '{source}'")
        return sm

    @app.post("/v1/ingest/{source}", status_code=202)
    async def ingest(source: str, request: Request, sm: SourceMap = Depends(source_map)):
        body = await request.json()
        records = body if isinstance(body, list) else [body]
        if len(records) > 10_000:
            raise HTTPException(413, "max 10,000 records per request")
        accepted, rejected = 0, []
        for i, rec in enumerate(records):
            try:
                for ev in to_events(source, sm, rec):
                    await publisher.send(topic_for(ev), ev.kafka_key().encode(), ev.to_bytes())
                    accepted += 1
            except Exception as exc:  # noqa: BLE001
                rejected.append({"index": i, "error": str(exc)[:200]})
        return {"accepted": accepted, "rejected": rejected}

    @app.post("/v1/ingest/{source}/events", status_code=202)
    async def ingest_event(source: str, ev: EventIn, sm: SourceMap = Depends(source_map)):
        de = DeviceEvent(tenant=sm.tenant, device_id=ev.device_id,
                         entity_id=entity_urn(sm.entity_type, sm.tenant, ev.device_id), event_type=ev.event_type,
                         severity=ev.severity, payload=ev.payload, source_ts=ev.ts or datetime.now(UTC),
                         protocol="http")
        await publisher.send(topic_for(de), de.kafka_key().encode(), de.to_bytes())
        return {"event_id": de.event_id}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "sources": sorted(sources)}

    return app


def _default_app() -> FastAPI:
    from omnilink_sdk import BufferedPublisher, KafkaPublisher, StoreForwardBuffer

    pub = BufferedPublisher(KafkaPublisher(os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"), "http-ingest"),
                            StoreForwardBuffer(os.environ.get("OMNILINK_BUFFER_PATH", "/tmp/http-ingest.db")))
    return create_app(load_sources(os.environ.get("OMNILINK_SOURCES", "connectors/http_ingest/sources.yaml")), pub)


app = _default_app() if os.environ.get("OMNILINK_SERVE") else create_app({}, MemoryPublisher())
