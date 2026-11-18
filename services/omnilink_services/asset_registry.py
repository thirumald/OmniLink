"""Asset registry: devices, sites, connectors and point maps (PostgreSQL + PostGIS)."""

from __future__ import annotations

import math
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol

from fastapi import Depends, HTTPException, Query
from omnilink_contracts import entity_urn, parse_urn
from pydantic import BaseModel, Field

from .common import Principal, create_app, require


class DeviceIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    entity_type: str
    name: str
    site_path: str | None = None
    connector_id: str | None = None
    vendor: str | None = None
    model: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Device(DeviceIn):
    tenant: str
    entity_id: str
    status: str = "unknown"
    last_seen: datetime | None = None


class PointIn(BaseModel):
    point_ref: str
    device_id: str
    attribute: str
    unit: str | None = None
    source_unit: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    deadband: float = 0.0
    writable: bool = False


class ConnectorIn(BaseModel):
    id: str
    type: str
    gateway_id: str | None = None
    poll_interval_s: float = 10
    settings: dict[str, Any] = Field(default_factory=dict)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class AssetRepo(Protocol):
    async def upsert_device(self, tenant: str, d: DeviceIn) -> Device: ...
    async def get_device(self, tenant: str, device_id: str) -> Device | None: ...
    async def list_devices(self, tenant: str, entity_type: str | None, near: tuple[float, float] | None,
                           radius_m: float, limit: int) -> list[Device]: ...
    async def upsert_connector(self, tenant: str, c: ConnectorIn) -> None: ...
    async def add_points(self, tenant: str, connector_id: str, points: list[PointIn]) -> None: ...
    async def connector_config(self, tenant: str, connector_id: str) -> dict | None: ...


class MemoryAssetRepo:
    def __init__(self):
        self.devices: dict[tuple[str, str], Device] = {}
        self.connectors: dict[str, dict] = {}
        self.points: dict[str, list[PointIn]] = {}

    async def upsert_device(self, tenant, d):
        dev = Device(**d.model_dump(), tenant=tenant, entity_id=entity_urn(d.entity_type, tenant, d.id))
        self.devices[(tenant, d.id)] = dev
        return dev

    async def get_device(self, tenant, device_id):
        return self.devices.get((tenant, device_id))

    async def list_devices(self, tenant, entity_type, near, radius_m, limit):
        out = [d for (t, _), d in self.devices.items() if t == tenant and (not entity_type or d.entity_type == entity_type)]
        if near:
            out = [d for d in out if d.lat is not None and haversine_m(near[0], near[1], d.lat, d.lon) <= radius_m]
            out.sort(key=lambda d: haversine_m(near[0], near[1], d.lat, d.lon))
        return out[:limit]

    async def upsert_connector(self, tenant, c):
        self.connectors[c.id] = {"tenant": tenant, **c.model_dump()}

    async def add_points(self, tenant, connector_id, points):
        self.points.setdefault(connector_id, []).extend(points)

    async def connector_config(self, tenant, connector_id):
        c = self.connectors.get(connector_id)
        if not c or c["tenant"] != tenant:
            return None
        pts = []
        for p in self.points.get(connector_id, []):
            dev = self.devices.get((tenant, p.device_id))
            if dev:
                pts.append({**p.model_dump(exclude={"writable"}), "entity_type": dev.entity_type})
        return {"connector_id": c["id"], "type": c["type"], "tenant": tenant, "poll_interval_s": c["poll_interval_s"],
                "settings": c["settings"], "points": pts}


class PgAssetRepo:  # pragma: no cover - exercised in integration tests against PostgreSQL
    def __init__(self, pool):
        self.pool = pool

    async def _conn(self, tenant):
        conn = await self.pool.acquire()
        await conn.execute("SELECT set_config('app.tenant', $1, false)", tenant)
        return conn

    async def upsert_device(self, tenant, d):
        conn = await self._conn(tenant)
        try:
            await conn.execute(
                """INSERT INTO devices (id, tenant_id, entity_type, name, connector_id, vendor, model, location, attributes,
                                        site_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,
                           CASE WHEN $8::float8 IS NULL THEN NULL ELSE ST_SetSRID(ST_MakePoint($9, $8), 4326) END, $10,
                           (SELECT id FROM sites WHERE tenant_id=$2 AND path = $11::ltree))
                   ON CONFLICT (tenant_id, id) DO UPDATE SET entity_type=EXCLUDED.entity_type, name=EXCLUDED.name,
                     connector_id=EXCLUDED.connector_id, vendor=EXCLUDED.vendor, model=EXCLUDED.model,
                     location=EXCLUDED.location, attributes=EXCLUDED.attributes, site_id=EXCLUDED.site_id, updated_at=now()""",
                d.id, tenant, d.entity_type, d.name, d.connector_id, d.vendor, d.model, d.lat, d.lon, d.attributes,
                d.site_path)
        finally:
            await self.pool.release(conn)
        return Device(**d.model_dump(), tenant=tenant, entity_id=entity_urn(d.entity_type, tenant, d.id))

    async def get_device(self, tenant, device_id):
        rows = await self._query(tenant, "WHERE d.id = $2", [device_id], 1)
        return rows[0] if rows else None

    async def list_devices(self, tenant, entity_type, near, radius_m, limit):
        where, args = ["TRUE"], []
        if entity_type:
            args.append(entity_type)
            where.append(f"d.entity_type = ${len(args) + 1}")
        order = "d.id"
        if near:
            args += [near[1], near[0], radius_m]
            n = len(args) + 1
            where.append(f"ST_DWithin(d.location::geography, ST_SetSRID(ST_MakePoint(${n-2}, ${n-1}),4326)::geography, ${n})")
            order = f"d.location <-> ST_SetSRID(ST_MakePoint(${n-2}, ${n-1}),4326)"
        return await self._query(tenant, "WHERE " + " AND ".join(where), args, limit, order)

    async def _query(self, tenant, where, args, limit, order="d.id"):
        conn = await self._conn(tenant)
        try:
            rows = await conn.fetch(
                f"""SELECT d.*, ST_Y(d.location) lat, ST_X(d.location) lon, s.path::text site_path
                    FROM devices d LEFT JOIN sites s ON s.id = d.site_id
                    {where.replace('$2', '$2')} AND d.tenant_id = $1 ORDER BY {order} LIMIT {int(limit)}""",
                tenant, *args)
        finally:
            await self.pool.release(conn)
        return [Device(id=r["id"], tenant=tenant, entity_type=r["entity_type"], name=r["name"], site_path=r["site_path"],
                       connector_id=r["connector_id"], vendor=r["vendor"], model=r["model"], lat=r["lat"], lon=r["lon"],
                       attributes=r["attributes"] or {}, status=r["status"], last_seen=r["last_seen"],
                       entity_id=entity_urn(r["entity_type"], tenant, r["id"])) for r in rows]

    async def upsert_connector(self, tenant, c):
        conn = await self._conn(tenant)
        try:
            await conn.execute("""INSERT INTO connectors (id, tenant_id, type, gateway_id, poll_interval_s, settings)
                                  VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,
                                  gateway_id=EXCLUDED.gateway_id, poll_interval_s=EXCLUDED.poll_interval_s,
                                  settings=EXCLUDED.settings, updated_at=now()""",
                               c.id, tenant, c.type, c.gateway_id, c.poll_interval_s, c.settings)
        finally:
            await self.pool.release(conn)

    async def add_points(self, tenant, connector_id, points):
        conn = await self._conn(tenant)
        try:
            await conn.executemany(
                """INSERT INTO points (tenant_id, connector_id, point_ref, device_id, attribute, unit, source_unit, scale,
                   "offset", deadband, writable) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (connector_id, point_ref) DO UPDATE SET device_id=EXCLUDED.device_id,
                   attribute=EXCLUDED.attribute, unit=EXCLUDED.unit, scale=EXCLUDED.scale, "offset"=EXCLUDED."offset" """,
                [(tenant, connector_id, p.point_ref, p.device_id, p.attribute, p.unit, p.source_unit, p.scale, p.offset,
                  p.deadband, p.writable) for p in points])
        finally:
            await self.pool.release(conn)

    async def connector_config(self, tenant, connector_id):
        conn = await self._conn(tenant)
        try:
            c = await conn.fetchrow("SELECT * FROM connectors WHERE id=$1", connector_id)
            if not c:
                return None
            pts = await conn.fetch("""SELECT p.*, d.entity_type FROM points p JOIN devices d
                                      ON d.tenant_id=p.tenant_id AND d.id=p.device_id WHERE p.connector_id=$1""", connector_id)
        finally:
            await self.pool.release(conn)
        return {"connector_id": c["id"], "type": c["type"], "tenant": tenant, "poll_interval_s": float(c["poll_interval_s"]),
                "settings": c["settings"],
                "points": [{k: p[k] for k in ("point_ref", "device_id", "attribute", "unit", "source_unit", "scale",
                                              "offset", "deadband", "entity_type")} for p in pts]}


def build_app(repo: AssetRepo | None = None):
    state: dict[str, Any] = {"repo": repo}

    @asynccontextmanager
    async def lifespan(_app):
        if state["repo"] is None:
            import asyncpg

            pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=2, max_size=20)
            state["repo"] = PgAssetRepo(pool)
        yield

    app = create_app("asset-registry", "OmniLink Asset Registry", lifespan)
    r = lambda: state["repo"]  # noqa: E731

    @app.put("/v1/devices/{device_id}", response_model=Device)
    async def put_device(device_id: str, d: DeviceIn, p: Principal = Depends(require("integrator"))):
        if d.id != device_id:
            raise HTTPException(400, "id mismatch")
        return await r().upsert_device(p.tenant, d)

    @app.get("/v1/devices/{device_id}", response_model=Device)
    async def get_device(device_id: str, p: Principal = Depends(require("viewer"))):
        d = await r().get_device(p.tenant, device_id)
        if not d:
            raise HTTPException(404, "device not found")
        return d

    @app.get("/v1/entities/{entity_id}")
    async def get_entity(entity_id: str, p: Principal = Depends(require("viewer"))):
        """NGSI-LD style lookup used by workflows and the AI assistant."""
        try:
            etype, tenant, local_id = parse_urn(entity_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if tenant != p.tenant:
            raise HTTPException(404, "entity not found")
        d = await r().get_device(p.tenant, local_id)
        if not d:
            raise HTTPException(404, "entity not found")
        loc = {"lat": d.lat, "lon": d.lon} if d.lat is not None else None
        return {"id": entity_id, "type": etype, "name": d.name, "device_id": d.id, "location": loc,
                "site_path": d.site_path, "status": d.status, "attributes": d.attributes}

    @app.get("/v1/devices", response_model=list[Device])
    async def list_devices(type: str | None = None, near: str | None = Query(None, pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?$"),
                           radius_m: float = Query(500, gt=0, le=50_000), limit: int = Query(200, le=5000),
                           p: Principal = Depends(require("viewer"))):
        pt = tuple(float(x) for x in near.split(",")) if near else None
        return await r().list_devices(p.tenant, type, pt, radius_m, limit)

    @app.put("/v1/connectors/{connector_id}", status_code=204)
    async def put_connector(connector_id: str, c: ConnectorIn, p: Principal = Depends(require("integrator"))):
        if c.id != connector_id:
            raise HTTPException(400, "id mismatch")
        await r().upsert_connector(p.tenant, c)

    @app.post("/v1/connectors/{connector_id}/points", status_code=204)
    async def add_points(connector_id: str, points: list[PointIn], p: Principal = Depends(require("integrator"))):
        await r().add_points(p.tenant, connector_id, points)

    @app.get("/v1/connectors/{connector_id}/config")
    async def connector_config(connector_id: str, p: Principal = Depends(require("integrator"))):
        cfg = await r().connector_config(p.tenant, connector_id)
        if not cfg:
            raise HTTPException(404, "connector not found")
        return cfg

    return app
