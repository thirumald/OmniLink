"""MQTT 3.1.1/5 adapter (also used for LoRaWAN via ChirpStack's MQTT integration).

point_ref: ``<topic>#<json.path>`` e.g. ``city/aq/001#$.pm25`` or ``application/1/device/+/event/up#$.object.temp``.
Topic wildcards (+, #) are allowed; the matched topic segment for ``+`` is exposed as {device} in device_id.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from omnilink_contracts import Command, CommandStatus
from omnilink_sdk import Connector, RawReading, register


def json_path(doc: Any, path: str) -> Any:
    """Minimal JSONPath: $.a.b[0].c"""
    if path in ("", "$"):
        return doc
    cur = doc
    for part in path.lstrip("$").lstrip(".").replace("]", "").split("."):
        if not part:
            continue
        name, *idx = part.split("[")
        if name:
            cur = cur[name]
        for i in idx:
            cur = cur[int(i)]
    return cur


def topic_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, seg in enumerate(p):
        if seg == "#":
            return True
        if i >= len(t) or (seg != "+" and seg != t[i]):
            return False
    return len(p) == len(t)


def extract(point_refs: list[str], topic: str, payload: bytes) -> list[RawReading]:
    try:
        doc = json.loads(payload)
    except ValueError:
        doc = payload.decode(errors="replace")
    now = datetime.now(UTC)
    out = []
    for ref in point_refs:
        pattern, _, path = ref.partition("#")
        if not topic_matches(pattern, topic):
            continue
        try:
            value = json_path(doc, path or "$")
        except (KeyError, IndexError, TypeError):
            continue
        ts = now
        if isinstance(doc, dict) and isinstance(doc.get("ts"), str):
            try:
                ts = datetime.fromisoformat(doc["ts"].replace("Z", "+00:00"))
            except ValueError:
                pass
        out.append(RawReading(ref, value, ts))
    return out


@register("mqtt")
class MqttAdapter(Connector):
    async def connect(self) -> None:
        import paho.mqtt.client as mqtt

        s = self.settings
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100_000)
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.config.connector_id, protocol=mqtt.MQTTv5)
        if s.get("username"):
            c.username_pw_set(s["username"], s.get("password"))
        if s.get("tls", False):
            c.tls_set(ca_certs=s.get("ca_file"), certfile=s.get("cert_file"), keyfile=s.get("key_file"))
        refs = [p.point_ref for p in self.config.points]
        topics = sorted({r.partition("#")[0] for r in refs})

        def on_connect(client, *_):
            for t in topics:
                client.subscribe(t, qos=1)

        def on_message(_c, _u, msg):
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (msg.topic, msg.payload))

        c.on_connect, c.on_message = on_connect, on_message
        c.connect(s["host"], int(s.get("port", 1883)), keepalive=30)
        c.loop_start()
        self._client, self._refs = c, refs

    async def subscribe(self, emit) -> None:
        while True:
            topic, payload = await self._queue.get()
            for r in extract(self._refs, topic, payload):
                await emit(r)

    async def execute(self, cmd: Command):
        if cmd.action != "publish":
            return await super().execute(cmd)
        topic = cmd.params.get("topic") or self.settings.get("command_topic", "").format(device_id=cmd.device_id)
        if not topic:
            return self.result(cmd, CommandStatus.REJECTED, "no command topic")
        info = self._client.publish(topic, json.dumps(cmd.params.get("payload", {})), qos=1)
        await asyncio.get_running_loop().run_in_executor(None, info.wait_for_publish, 5)
        return self.result(cmd, CommandStatus.ACKED if info.is_published() else CommandStatus.FAILED)

    async def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
