"""Time series query API over ClickHouse (HTTP interface, parameterised queries only)."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import Depends, HTTPException, Query
from omnilink_contracts import parse_urn

from .common import Principal, create_app, require

MAX_RANGE = timedelta(days=400)
_REL = re.compile(r"^-(\d+)([mhd])$")
TABLES = {"raw": "omnilink.telemetry", "1m": "omnilink.telemetry_1m", "1h": "omnilink.telemetry_1h"}


def parse_time(v: str, now: datetime) -> datetime:
    if v == "now":
        return now
    m = _REL.match(v)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"bad time '{v}'") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def build_query(tenant: str, entity_id: str, attribute: str, start: datetime, end: datetime, interval: str,
                limit: int = 10_000) -> tuple[str, dict[str, str]]:
    """Return (sql, params) using ClickHouse server-side parameters ({name:Type})."""
    if interval not in TABLES:
        raise ValueError("interval must be raw, 1m or 1h")
    if end <= start or end - start > MAX_RANGE:
        raise ValueError("time range must be positive and at most 400 days")
    parse_urn(entity_id)
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", attribute):
        raise ValueError("bad attribute")
    params = {"tenant": tenant, "entity": entity_id, "attr": attribute,
              "start": start.strftime("%Y-%m-%d %H:%M:%S"), "end": end.strftime("%Y-%m-%d %H:%M:%S"),
              "limit": str(int(limit))}
    where = ("tenant = {tenant:String} AND entity_id = {entity:String} AND attribute = {attr:String} "
             "AND %s >= {start:DateTime} AND %s < {end:DateTime}")
    if interval == "raw":
        sql = (f"SELECT ts, value_num AS value, quality FROM {TABLES['raw']} FINAL WHERE " + where % ("ts", "ts")
               + " ORDER BY ts LIMIT {limit:UInt32} FORMAT JSON")
    else:
        sql = (f"SELECT bucket AS ts, min(v_min) AS min, max(v_max) AS max, sum(v_sum)/sum(v_cnt) AS avg, "
               f"sum(v_cnt) AS count, argMaxMerge(v_last) AS last FROM {TABLES[interval]} WHERE "
               + where % ("bucket", "bucket") + " GROUP BY bucket ORDER BY bucket LIMIT {limit:UInt32} FORMAT JSON")
    return sql, params


def build_app(http: httpx.AsyncClient | None = None):
    app = create_app("query-api", "OmniLink Query API")
    ch_url = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")

    @app.get("/v1/timeseries")
    async def timeseries(entity_id: str, attribute: str, from_: str = Query("-24h", alias="from"), to: str = "now",
                         interval: str = Query("raw", pattern="^(raw|1m|1h)$"), limit: int = Query(10_000, le=100_000),
                         p: Principal = Depends(require("viewer"))):
        now = datetime.now(UTC)
        try:
            _, tenant, _ = parse_urn(entity_id)
            if tenant != p.tenant:
                raise HTTPException(404, "entity not found")
            sql, params = build_query(p.tenant, entity_id, attribute, parse_time(from_, now), parse_time(to, now),
                                      interval, limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        client = http or httpx.AsyncClient(timeout=30)
        r = await client.post(ch_url, content=sql, params={f"param_{k}": v for k, v in params.items()},
                              auth=(os.environ.get("CLICKHOUSE_USER", "omnilink_ro"), os.environ.get("CLICKHOUSE_PASSWORD", "")))
        if r.status_code != 200:
            raise HTTPException(502, "time series store error")
        body = r.json()
        return {"entity_id": entity_id, "attribute": attribute, "interval": interval, "points": body.get("data", [])}

    return app
