"""Publishers: Kafka (core), MQTT (edge uplink), in-memory (tests), buffered wrapper."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .buffer import StoreForwardBuffer

log = logging.getLogger("omnilink.publisher")


class Publisher(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, topic: str, key: bytes, value: bytes) -> None: ...


class MemoryPublisher:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail = fail

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        if self.fail:
            raise ConnectionError("uplink down")
        self.sent.append((topic, key, value))


class KafkaPublisher:
    """Idempotent, acks=all producer with zstd compression."""

    def __init__(self, bootstrap: str, client_id: str = "omnilink-connector", **extra):
        self.bootstrap = bootstrap
        self.client_id = client_id
        self.extra = extra
        self._p = None

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer

        self._p = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap,
            client_id=self.client_id,
            acks="all",
            enable_idempotence=True,
            compression_type="zstd",
            linger_ms=20,
            **self.extra,
        )
        await self._p.start()

    async def stop(self) -> None:
        if self._p:
            await self._p.stop()

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        await self._p.send_and_wait(topic, value=value, key=key)


class MqttPublisher:
    """Edge uplink over MQTT 5 (QoS 1). Topic = omnilink/v1/<kafka-topic>/<key>.

    The core-side uplink bridge (edge/uplink_bridge.py) maps it back to Kafka.
    """

    def __init__(self, host: str, port: int = 8883, client_id: str = "omnilink-edge", username: str | None = None,
                 password: str | None = None, tls: bool = True):
        self.host, self.port, self.client_id = host, port, client_id
        self.username, self.password, self.tls = username, password, tls
        self._c = None

    async def start(self) -> None:
        import paho.mqtt.client as mqtt

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, protocol=mqtt.MQTTv5)
        if self.username:
            c.username_pw_set(self.username, self.password)
        if self.tls:
            c.tls_set()
        c.connect(self.host, self.port, keepalive=30)
        c.loop_start()
        self._c = c

    async def stop(self) -> None:
        if self._c:
            self._c.loop_stop()
            self._c.disconnect()

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        info = self._c.publish(f"omnilink/v1/{topic}/{key.decode()}", value, qos=1)
        await asyncio.get_running_loop().run_in_executor(None, info.wait_for_publish, 5)
        if not info.is_published():
            raise ConnectionError("mqtt publish not acknowledged")


class BufferedPublisher:
    """Wraps an uplink; on failure records go to the durable buffer and are replayed in order."""

    def __init__(self, uplink: Publisher, buffer: StoreForwardBuffer, drain_interval_s: float = 2.0):
        self.uplink = uplink
        self.buffer = buffer
        self.drain_interval_s = drain_interval_s
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        await self.uplink.start()
        self._task = asyncio.create_task(self._drain_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self.uplink.stop()

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        # keep ordering: while a backlog exists, new records queue behind it
        if len(self.buffer):
            self.buffer.put(topic, key, value)
            return
        try:
            await self.uplink.send(topic, key, value)
        except Exception as exc:  # noqa: BLE001 - any uplink failure buffers
            log.warning("uplink failed, buffering: %s", exc)
            self.buffer.put(topic, key, value)

    async def drain_once(self) -> int:
        async with self._lock:
            sent = 0
            while True:
                batch = self.buffer.peek(500)
                if not batch:
                    return sent
                last_ok = None
                for rid, topic, k, v in batch:
                    try:
                        await self.uplink.send(topic, k, v)
                    except Exception:  # noqa: BLE001
                        break
                    last_ok, sent = rid, sent + 1
                if last_ok is None:
                    return sent
                self.buffer.ack(last_ok)
                if last_ok != batch[-1][0]:
                    return sent

    async def _drain_loop(self) -> None:
        while True:
            await asyncio.sleep(self.drain_interval_s)
            try:
                await self.drain_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("drain failed: %s", exc)
