"""Platform API client used by assistant tools — always with the requesting user's token."""

from __future__ import annotations

import os
from typing import Any

import httpx


class PlatformClient:
    def __init__(self, token: str, base_url: str | None = None, client: httpx.AsyncClient | None = None,
                 dev_headers: dict[str, str] | None = None):
        self.base_url = (base_url or os.environ.get("OMNILINK_API", "http://apisix:9080")).rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=20)
        self.headers = {"Authorization": f"Bearer {token}", **(dev_headers or {})}

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self.client.request(method, self.base_url + path, headers=self.headers, **kw)
        if r.status_code >= 400:
            detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
            raise PlatformError(r.status_code, str(detail)[:300])
        return r.json() if r.content else None

    async def devices(self, **params):
        return await self._req("GET", "/v1/devices", params={k: v for k, v in params.items() if v is not None})

    async def entity(self, entity_id: str):
        return await self._req("GET", f"/v1/entities/{entity_id}")

    async def timeseries(self, **params):
        return await self._req("GET", "/v1/timeseries", params=params)

    async def alarms(self, **params):
        return await self._req("GET", "/v1/alarms", params={k: v for k, v in params.items() if v is not None})

    async def incidents(self, **params):
        return await self._req("GET", "/v1/incidents", params=params)

    async def ack_alarm(self, alarm_id: str):
        return await self._req("POST", f"/v1/alarms/{alarm_id}/ack")

    async def shelve_alarm(self, alarm_id: str, minutes: int):
        return await self._req("POST", f"/v1/alarms/{alarm_id}/shelve", json={"minutes": minutes})

    async def command(self, device_id: str, body: dict):
        return await self._req("POST", f"/v1/devices/{device_id}/commands", json=body)

    async def notify(self, body: dict):
        return await self._req("POST", "/v1/notify", json=body)


class PlatformError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail
