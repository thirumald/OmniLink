"""Natural language → Node-RED flow draft, with a strict validator."""

from __future__ import annotations

import json
import re
import uuid

from .llm import LLM

ALLOWED_NODE_TYPES = {
    "tab", "inject", "debug", "function", "change", "switch", "delay", "trigger", "template", "json", "split", "join",
    "rbe", "filter", "catch", "status", "complete", "link in", "link out", "comment", "cronplus",
    "mqtt in", "mqtt out", "http request", "kafkajs-consumer",
    "omnilink-config", "omnilink-asset", "omnilink-command", "omnilink-alarm", "omnilink-query", "omnilink-notify",
}
SECRET_RE = re.compile(r"(password|secret|api[_-]?key|token)\s*[\"']?\s*[:=]\s*[\"'][^\"']{6,}", re.IGNORECASE)

GEN_PROMPT = """Create a Node-RED flow (JSON array) for this OmniLink automation request:
"{request}"
Rules:
- Use only these node types: {types}.
- Triggers: kafkajs-consumer on topics omnilink.alarms.v1, omnilink.events.v1 or omnilink.telemetry.enriched.v1; or inject/cronplus.
- Use omnilink-* nodes for platform actions; every omnilink-* node has "server": "omnilink-cfg".
- Include exactly one {{"id":"omnilink-cfg","type":"omnilink-config","name":"OmniLink"}} node. No credentials anywhere.
- All nodes have "z": "<tab id>", unique "id", and "wires" referencing existing ids.
Return JSON: {{"flow": [...], "explanation": "..."}}"""


class FlowValidationError(ValueError):
    pass


def validate_flow(flow: list[dict]) -> list[str]:
    """Return warnings; raise FlowValidationError on hard errors."""
    if not isinstance(flow, list) or not flow:
        raise FlowValidationError("flow must be a non-empty JSON array")
    ids = [n.get("id") for n in flow]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise FlowValidationError("every node needs a unique id")
    idset = set(ids)
    tabs = {n["id"] for n in flow if n.get("type") == "tab"}
    warnings = []
    for n in flow:
        t = n.get("type")
        if t not in ALLOWED_NODE_TYPES:
            raise FlowValidationError(f"node type '{t}' is not allowed")
        if t not in ("tab", "omnilink-config") and n.get("z") not in tabs:
            raise FlowValidationError(f"node {n['id']} is not on a tab")
        for port in n.get("wires", []) or []:
            for target in port:
                if target not in idset:
                    raise FlowValidationError(f"node {n['id']} wires to missing node {target}")
        if t.startswith("omnilink-") and t != "omnilink-config" and n.get("server") not in idset:
            raise FlowValidationError(f"node {n['id']} has no omnilink-config server")
        if t == "function":
            warnings.append(f"function node {n['id']} contains custom code — review before deploying")
    if SECRET_RE.search(json.dumps(flow)):
        raise FlowValidationError("flow contains inline credentials")
    if not any(n.get("type") == "omnilink-command" for n in flow) and not any(n.get("type") == "omnilink-notify" for n in flow):
        warnings.append("flow has no action node (command or notify)")
    return warnings


async def draft_flow(llm: LLM, request: str, attempts: int = 2) -> dict:
    prompt = GEN_PROMPT.format(request=request[:2000], types=", ".join(sorted(ALLOWED_NODE_TYPES)))
    messages = [{"role": "system", "content": "You are a Node-RED expert. Return only JSON."},
                {"role": "user", "content": prompt}]
    last_error = None
    for _ in range(attempts):
        reply = await llm.chat(messages, json_mode=True)
        try:
            data = json.loads(reply.content or "")
            flow = data["flow"]
            warnings = validate_flow(flow)
            label = f"AI draft {uuid.uuid4().hex[:6]}"
            for n in flow:
                if n.get("type") == "tab":
                    n["label"], n["disabled"] = f"{label}: {n.get('label', 'flow')}", True  # drafts start disabled
            return {"flow": flow, "explanation": data.get("explanation", ""), "warnings": warnings, "status": "draft"}
        except (json.JSONDecodeError, KeyError, FlowValidationError) as exc:
            last_error = str(exc)
            messages += [{"role": "assistant", "content": reply.content or ""},
                         {"role": "user", "content": f"That flow is invalid: {last_error}. Fix it and return the full JSON."}]
    raise FlowValidationError(f"could not produce a valid flow: {last_error}")
