"""Assistant tool registry. Read tools run immediately; write tools only produce proposals."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .platform import PlatformClient
from .rag import MemoryKnowledgeBase


@dataclass
class ToolContext:
    tenant: str
    user: str
    roles: set[str]
    platform: PlatformClient
    kb: MemoryKnowledgeBase


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[ToolContext, dict], Awaitable[Any]]
    write: bool = False
    min_role: str = "viewer"

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
N = {"type": "number"}
INT = {"type": "integer"}

# ---------------- read tools ----------------


async def _search_devices(ctx, a):
    near = f"{a['lat']},{a['lon']}" if "lat" in a and "lon" in a else None
    return await ctx.platform.devices(type=a.get("entity_type"), near=near, radius_m=a.get("radius_m", 500),
                                      limit=min(int(a.get("limit", 20)), 50))


async def _get_entity(ctx, a):
    return await ctx.platform.entity(a["entity_id"])


async def _query_timeseries(ctx, a):
    res = await ctx.platform.timeseries(entity_id=a["entity_id"], attribute=a["attribute"], **{"from": a.get("from", "-6h")},
                                        to=a.get("to", "now"), interval=a.get("interval", "1h"), limit=500)
    pts = res.get("points", [])
    vals = [p.get("avg", p.get("value")) for p in pts if p.get("avg", p.get("value")) is not None]
    summary = {"count": len(vals)}
    if vals:
        summary.update(min=min(vals), max=max(vals), last=vals[-1], mean=sum(vals) / len(vals))
    return {"summary": summary, "points": pts[-48:]}


async def _list_alarms(ctx, a):
    return await ctx.platform.alarms(state=a.get("state", "open"), priority_max=a.get("priority_max", 4))


async def _search_knowledge(ctx, a):
    hits = await ctx.kb.search(ctx.tenant, a["query"], k=min(int(a.get("k", 4)), 8))
    return [{"doc": h.doc, "text": h.text} for h in hits]


async def _list_incidents(ctx, a):
    return await ctx.platform.incidents(**({"status": a["status"]} if a.get("status") else {}))


# ---------------- write tools (executed only after approval) ----------------


async def _ack_alarm(ctx, a):
    return await ctx.platform.ack_alarm(a["alarm_id"])


async def _shelve_alarm(ctx, a):
    return await ctx.platform.shelve_alarm(a["alarm_id"], int(a["minutes"]))


async def _send_command(ctx, a):
    return await ctx.platform.command(a["device_id"], {"connector_id": a["connector_id"], "action": a["action"],
                                                       "params": a.get("params", {}), "ttl_s": 60})


async def _notify(ctx, a):
    return await ctx.platform.notify({"group": a["group"], "channels": a.get("channels", ["push"]),
                                      "subject": a["subject"], "body": a["body"]})


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("search_devices", "Find devices by type and/or within a radius of a location.",
         _obj({"entity_type": S, "lat": N, "lon": N, "radius_m": N, "limit": INT}), _search_devices),
    Tool("get_entity", "Get one entity (device) by NGSI-LD URN: location, status, attributes.",
         _obj({"entity_id": S}, ["entity_id"]), _get_entity),
    Tool("query_timeseries", "Get history of one attribute of an entity. from: -6h, -7d or ISO time. interval: raw, 1m, 1h.",
         _obj({"entity_id": S, "attribute": S, "from": S, "to": S, "interval": S}, ["entity_id", "attribute"]),
         _query_timeseries),
    Tool("list_alarms", "List alarms. state: open, active_unack, active_ack, cleared. priority_max 1-4 (1 = highest).",
         _obj({"state": S, "priority_max": INT}), _list_alarms),
    Tool("list_incidents", "List incidents, optionally by status (open, closed).", _obj({"status": S}), _list_incidents),
    Tool("search_knowledge", "Search runbooks, SOPs, device manuals and past incident reports.",
         _obj({"query": S, "k": INT}, ["query"]), _search_knowledge),
    Tool("ack_alarm", "PROPOSE acknowledging an alarm (needs user approval).", _obj({"alarm_id": S}, ["alarm_id"]),
         _ack_alarm, write=True, min_role="operator"),
    Tool("shelve_alarm", "PROPOSE shelving an alarm for N minutes (needs approval).",
         _obj({"alarm_id": S, "minutes": INT}, ["alarm_id", "minutes"]), _shelve_alarm, write=True, min_role="supervisor"),
    Tool("send_command", "PROPOSE a device command, e.g. ptz.goto_preset, write_point (needs approval).",
         _obj({"device_id": S, "connector_id": S, "action": S, "params": {"type": "object"}},
              ["device_id", "connector_id", "action"]), _send_command, write=True, min_role="operator"),
    Tool("notify", "PROPOSE sending a notification to a duty group (needs approval).",
         _obj({"group": S, "channels": {"type": "array", "items": S}, "subject": S, "body": S},
              ["group", "subject", "body"]), _notify, write=True, min_role="operator"),
]}

_IMPLIES = {"platform-admin": {"viewer", "operator", "supervisor", "integrator"},
            "supervisor": {"viewer", "operator", "supervisor"}, "operator": {"viewer", "operator"},
            "integrator": {"viewer", "integrator"}, "viewer": {"viewer"}}


def tools_for(roles: set[str]) -> list[Tool]:
    granted = set().union(*(_IMPLIES.get(r, set()) for r in roles)) if roles else set()
    return [t for t in TOOLS.values() if t.min_role in granted]


_INJECTION = re.compile(r"(ignore (all|previous|prior) instructions|you are now|system prompt|<\s*/?\s*(system|tool)\s*>)",
                        re.IGNORECASE)


def sanitize_tool_output(result: Any, limit: int = 12_000) -> str:
    """Serialise a tool result for the model; neutralise instruction-like text; cap size."""
    text = json.dumps(result, default=str, ensure_ascii=False)
    text = _INJECTION.sub("[filtered]", text)
    if len(text) > limit:
        text = text[:limit] + '... [truncated]'
    return f"<tool_result>{text}</tool_result>"
