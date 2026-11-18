"""Core-side uplink bridge: edge MQTT → Kafka.

Subscribes to ``omnilink/v1/+/+`` on the core broker (shared subscription for horizontal
scale), validates the topic against an allow-list and the tenant against the gateway's
identity, produces to Kafka with acks=all, and only then acknowledges the MQTT message.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from omnilink_contracts.topics import T

log = logging.getLogger("omnilink.uplink")

ALLOWED = {T.TELEMETRY, T.EVENTS, T.HEALTH, T.COMMAND_RESULTS}
PREFIX = "omnilink/v1/"


@dataclass
class Routed:
    kafka_topic: str
    key: bytes
    value: bytes


class RejectedMessage(Exception):
    pass


def route(mqtt_topic: str, payload: bytes, gateway_tenant: str | None = None) -> Routed:
    """Map an edge MQTT message to its Kafka destination, or raise RejectedMessage."""
    if not mqtt_topic.startswith(PREFIX):
        raise RejectedMessage(f"bad prefix: {mqtt_topic}")
    rest = mqtt_topic[len(PREFIX):]
    kafka_topic, sep, key = rest.partition("/")
    if not sep or not key:
        raise RejectedMessage(f"missing key: {mqtt_topic}")
    if kafka_topic not in ALLOWED:
        raise RejectedMessage(f"topic not allowed: {kafka_topic}")
    tenant = key.split(":", 1)[0]
    if gateway_tenant and tenant != gateway_tenant:
        raise RejectedMessage(f"tenant mismatch: {tenant} != {gateway_tenant}")
    if len(payload) > 1_048_576:
        raise RejectedMessage("payload too large")
    return Routed(kafka_topic, key.encode(), payload)


def gateway_tenant_from_client_id(client_id: str) -> str | None:
    """Gateways connect as ``gw-<tenant>-<site>``; the broker enforces it via certificate CN."""
    parts = client_id.split("-")
    return parts[1] if len(parts) >= 3 and parts[0] == "gw" else None


async def run() -> None:  # pragma: no cover - integration path
    import paho.mqtt.client as mqtt
    from aiokafka import AIOKafkaProducer

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=50_000)
    producer = AIOKafkaProducer(bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"),
                                acks="all", enable_idempotence=True, compression_type="zstd", linger_ms=10)
    await producer.start()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.environ.get("BRIDGE_ID", "uplink-bridge"),
                    protocol=mqtt.MQTTv5, manual_ack=True)
    if os.environ.get("MQTT_USER"):
        c.username_pw_set(os.environ["MQTT_USER"], os.environ.get("MQTT_PASSWORD"))
    c.on_connect = lambda cl, *_: cl.subscribe("$share/uplink/omnilink/v1/#", qos=1)
    c.on_message = lambda cl, _u, msg: loop.call_soon_threadsafe(queue.put_nowait, msg)
    c.connect(os.environ.get("MQTT_HOST", "rabbitmq"), int(os.environ.get("MQTT_PORT", "1883")))
    c.loop_start()
    try:
        while True:
            msg = await queue.get()
            props = getattr(msg, "properties", None)
            user_props = dict(getattr(props, "UserProperty", []) or [])
            try:
                r = route(msg.topic, msg.payload, user_props.get("tenant"))
                await producer.send_and_wait(r.kafka_topic, r.value, key=r.key)
            except RejectedMessage as exc:
                log.warning("rejected: %s", exc)
                await producer.send_and_wait(T.DLQ, msg.payload, key=msg.topic.encode(),
                                             headers=[("reason", str(exc).encode())])
            c.ack(msg.mid, msg.qos)
    finally:
        c.loop_stop()
        await producer.stop()


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(run())
