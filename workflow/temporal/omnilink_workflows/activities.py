"""Temporal activities — the only place workflows touch the outside world (platform APIs)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from temporalio import activity

API = os.environ.get("OMNILINK_API", "http://apisix:9080")


@dataclass
class IncidentInput:
    tenant: str
    alarm_id: str
    entity_id: str
    priority: int
    message: str


async def _client() -> httpx.AsyncClient:
    token = await _token()
    return httpx.AsyncClient(base_url=API, timeout=10, headers={"Authorization": f"Bearer {token}"})


async def _token() -> str:
    url = os.environ.get("OIDC_TOKEN_URL")
    if not url:
        return "dev"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(url, data={"grant_type": "client_credentials", "client_id": os.environ["OIDC_CLIENT_ID"],
                                    "client_secret": os.environ["OIDC_CLIENT_SECRET"]})
        r.raise_for_status()
        return r.json()["access_token"]


@activity.defn
async def create_incident(inp: IncidentInput) -> str:
    async with await _client() as c:
        r = await c.post("/v1/incidents", json={"alarm_id": inp.alarm_id, "entity_id": inp.entity_id,
                                                  "priority": inp.priority, "title": inp.message})
        r.raise_for_status()
        return r.json()["incident_id"]


@activity.defn
async def point_cameras(inp: IncidentInput, radius_m: int, preset: str) -> int:
    """Send ptz.goto_preset to PTZ cameras near the alarmed entity; returns how many were commanded."""
    async with await _client() as c:
        ent = await c.get(f"/v1/entities/{inp.entity_id}")
        ent.raise_for_status()
        loc = ent.json().get("location")
        if not loc:
            return 0
        cams = await c.get("/v1/devices", params={"type": "Camera", "near": f"{loc['lat']},{loc['lon']}",
                                                  "radius_m": radius_m})
        n = 0
        for cam in cams.json():
            if not cam.get("attributes", {}).get("ptz"):
                continue
            r = await c.post(f"/v1/devices/{cam['id']}/commands", json={
                "connector_id": cam["connector_id"], "action": "ptz.goto_preset", "params": {"preset": preset}})
            n += r.status_code < 300
        return n


@activity.defn
async def notify(inp: IncidentInput, level: str, channels: list[str], group: str) -> None:
    async with await _client() as c:
        r = await c.post("/v1/notify", json={"tenant": inp.tenant, "group": group, "channels": channels,
                                             "subject": f"[P{inp.priority}] {inp.message}",
                                             "body": f"Alarm {inp.alarm_id} on {inp.entity_id}. Escalation level: {level}",
                                             "ref": inp.alarm_id})
        r.raise_for_status()


@activity.defn
async def close_incident(incident_id: str, resolution: str) -> None:
    async with await _client() as c:
        r = await c.post(f"/v1/incidents/{incident_id}/close", json={"resolution": resolution})
        r.raise_for_status()
