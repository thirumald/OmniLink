"""One-process dev stack: every OmniLink service in memory, seeded with demo data, behind one port.

    OMNILINK_AUTH_MODE=dev python tools/devstack.py            # API on http://localhost:9080
    (cd frontend/console && npx ng serve)                       # console on http://localhost:4200

Uses the real service code with in-memory stores. ClickHouse is replaced by a synthetic time series
generator and the LLM by a small demo model unless OMNILINK_LLM_URL points at a real endpoint.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ["libs/omnilink_contracts", "libs/omnilink_sdk", "services", "assistant", "."]:
    sys.path.insert(0, str(ROOT / p))
os.environ.setdefault("OMNILINK_AUTH_MODE", "dev")

import httpx  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from omnilink_assistant.app import build_app as assistant_app  # noqa: E402
from omnilink_assistant.llm import LLMReply, OpenAICompatibleLLM, ToolCall  # noqa: E402
from omnilink_contracts import RuleHit, entity_urn  # noqa: E402
from omnilink_sdk import MemoryPublisher  # noqa: E402
from omnilink_services import alarms, asset_registry, commands, outbound, query_api  # noqa: E402
from omnilink_services.asset_registry import DeviceIn  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

TENANT = "abudhabi"
NOW = datetime.now(UTC)

DEMO_DEVICES = [
    ("cam-corniche-01", "Camera", "Corniche PTZ 01", 24.4762, 54.3441, "online", {"ptz": True, "telemetry": ["online"]}),
    ("cam-corniche-02", "Camera", "Corniche PTZ 02", 24.4741, 54.3480, "online", {"ptz": True, "telemetry": ["online"]}),
    ("cam-khalifa-07", "Camera", "Khalifa St fixed 07", 24.4905, 54.3577, "offline", {"telemetry": ["online"]}),
    ("fs-corniche-3", "FloodSensor", "Corniche underpass flood sensor", 24.4755, 54.3455, "online", {"telemetry": ["waterLevel"]}),
    ("fs-mina-1", "FloodSensor", "Mina Rd flood sensor", 24.5150, 54.3790, "online", {"telemetry": ["waterLevel"]}),
    ("aq-markaziya", "AirQualityObserved", "Al Markaziya AQ station", 24.4875, 54.3600, "online", {"telemetry": ["pm25", "no2"]}),
    ("aq-mussafah", "AirQualityObserved", "Mussafah AQ station", 24.3540, 54.5020, "degraded", {"telemetry": ["pm25", "no2"]}),
    ("sl-ctrl-12", "StreetlightController", "Streetlight cabinet 12", 24.4600, 54.3700, "online", {"telemetry": ["power"]}),
    ("ahu-03", "AirHandlingUnit", "Tower A AHU 03", 24.4950, 54.3830, "online", {"telemetry": ["supplyAirTemperature"]}),
    ("ev-ch-04", "EVChargingStation", "Marina EV charger 04", 24.4770, 54.3220, "online", {"telemetry": ["power"]}),
]


def synthetic_clickhouse(request: httpx.Request) -> httpx.Response:
    """Fake ClickHouse HTTP endpoint: daily-cycle signal per attribute."""
    q = dict(request.url.params)
    start = datetime.strptime(q["param_start"], "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(q["param_end"], "%Y-%m-%d %H:%M:%S")
    step = timedelta(minutes=1) if "telemetry_1m" in request.content.decode() else timedelta(hours=1)
    if "omnilink.telemetry " in request.content.decode() + " ":
        step = timedelta(minutes=5)
    base = {"waterLevel": 0.6, "pm25": 38, "no2": 22, "power": 4.2, "supplyAirTemperature": 14}.get(q["param_attr"], 1)
    rows, t, i = [], start, 0
    while t < end and len(rows) < 2000:
        v = base * (1 + 0.25 * math.sin(i / 12)) + (0.9 if q["param_attr"] == "waterLevel" and end - t < timedelta(hours=2) else 0)
        rows.append({"ts": t.strftime("%Y-%m-%d %H:%M:%S"), "avg": round(v, 3), "min": round(v * 0.95, 3),
                     "max": round(v * 1.05, 3), "value": round(v, 3)})
        t, i = t + step, i + 1
    return httpx.Response(200, json={"data": rows})


class DemoLLM:
    """Offline stand-in: looks up open alarms, then summarises them. Real deployments use vLLM."""

    async def chat(self, messages, tools=None, json_mode=False):
        if json_mode:
            return LLMReply(json.dumps({"summary": "Water level at the Corniche underpass rose ~0.9 m in two hours; "
                                                   "neighbouring sensor Mina Rd is normal.",
                                        "likely_causes": ["storm drain blockage", "sensor fouling"],
                                        "recommended_actions": [{"tool": "send_command", "arguments": {
                                            "device_id": "cam-corniche-01", "connector_id": "onvif-core",
                                            "action": "ptz.goto_preset", "params": {"preset": "flood"}},
                                            "reason": "verify water on the road visually"}],
                                        "references": ["runbook-flood"], "confidence": 0.62}))
        if messages[-1]["role"] == "user":
            return LLMReply(None, [ToolCall("d1", "list_alarms", {"state": "open"})])
        data = messages[-1]["content"]
        n = data.count('"alarm_id"')
        return LLMReply(f"There are {n} open alarms. The highest priority is the Corniche underpass flood alarm (P1). "
                        "I can propose pointing Corniche PTZ 01 to the flood preset if you want.")

    async def embed(self, texts):
        return [[float((hash(t[i:i + 3]) % 97) / 97) for i in range(0, 64)] for t in texts]


def build():
    repo = asset_registry.MemoryAssetRepo()
    engine = alarms.AlarmEngine({"flood-high": {"priority": 1, "message": "Flood level high — Corniche underpass"},
                                 "pm25-high": {"priority": 3, "message": "PM2.5 above 55 µg/m³"}})
    cmd_store = commands.CommandStore()

    async def seed():
        for did, et, name, lat, lon, status, attrs in DEMO_DEVICES:
            d = await repo.upsert_device(TENANT, DeviceIn(id=did, entity_type=et, name=name, lat=lat, lon=lon,
                                                          connector_id="onvif-core" if et == "Camera" else "core-mqtt",
                                                          site_path="abudhabi.central", attributes=attrs))
            repo.devices[(TENANT, did)] = d.model_copy(update={"status": status})
        engine.on_rule_hit(RuleHit(tenant=TENANT, rule_id="flood-high", entity_id=entity_urn("FloodSensor", TENANT, "fs-corniche-3"),
                                   attribute="waterLevel", value=1.62, threshold=1.5, condition="gt", ts=NOW - timedelta(minutes=7)))
        engine.on_rule_hit(RuleHit(tenant=TENANT, rule_id="pm25-high", entity_id=entity_urn("AirQualityObserved", TENANT, "aq-mussafah"),
                                   attribute="pm25", value=61, threshold=55, condition="gt", ts=NOW - timedelta(minutes=40)))
        from omnilink_contracts import DeviceHealth

        engine.on_health(DeviceHealth(tenant=TENANT, device_id="cam-khalifa-07", connector_id="onvif-core", status="offline"))

    asyncio.run(seed())
    llm = OpenAICompatibleLLM() if os.environ.get("OMNILINK_LLM_URL") else DemoLLM()
    apps = {
        "asset": asset_registry.build_app(repo),
        "alarm": alarms.build_app(engine, MemoryPublisher()),
        "command": commands.build_app(MemoryPublisher(), cmd_store),
        "query": query_api.build_app(httpx.AsyncClient(transport=httpx.MockTransport(synthetic_clickhouse))),
        "outbound": outbound.build_app(),
    }

    # assistant tools call the platform through this same process
    async def loopback(request: httpx.Request) -> httpx.Response:
        transport = httpx.ASGITransport(app=router)
        async with httpx.AsyncClient(transport=transport, base_url="http://devstack") as c:
            r = await c.request(request.method, request.url.path, params=request.url.params, content=request.content,
                                headers=request.headers)
            return httpx.Response(r.status_code, content=r.content, headers=r.headers)

    apps["assistant"] = assistant_app(llm, httpx.AsyncClient(transport=httpx.MockTransport(loopback)))
    asyncio.run(apps["assistant"].state.kb.ingest(TENANT, "runbook-flood", (ROOT / "assistant/knowledge/runbook-flood.md").read_text()))

    def pick(path: str):
        if "/commands" in path:
            return apps["command"]
        for prefix, key in [("/v1/devices", "asset"), ("/v1/entities", "asset"), ("/v1/connectors", "asset"),
                            ("/v1/alarms", "alarm"), ("/v1/incidents", "alarm"), ("/v1/timeseries", "query"),
                            ("/v1/notify", "outbound"), ("/v1/webhooks", "outbound"), ("/v1/assistant", "assistant")]:
            if path.startswith(prefix):
                return apps[key]
        return None

    dist = ROOT / "frontend/console/dist/console/browser"
    static = StaticFiles(directory=dist, html=True) if dist.exists() else None

    async def router(scope, receive, send):
        if scope["type"] == "lifespan":
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            return
        app = pick(scope.get("path", ""))
        if app is not None:
            return await app(scope, receive, send)
        if static is not None:
            path = scope["path"]
            if path != "/" and not (dist / path.lstrip("/")).exists():
                scope = {**scope, "path": "/"}  # SPA fallback
            return await static(scope, receive, send)
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})

    return CORSMiddleware(router, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build(), host="0.0.0.0", port=int(os.environ.get("PORT", "9080")))
