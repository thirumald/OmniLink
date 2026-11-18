"""Connector runner: poll / subscribe loops, commands, health, metrics.

    python -m omnilink_sdk.runner --config connectors/examples/bacnet-tower-a.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import random
from datetime import datetime

from omnilink_contracts import (
    Command,
    CommandStatus,
    DeviceEvent,
    DeviceHealth,
    HealthStatus,
    topic_for,
)
from omnilink_contracts.topics import T
from prometheus_client import Counter, Gauge, start_http_server

from .base import Connector, RawReading, registry
from .buffer import StoreForwardBuffer
from .config import ConnectorConfig
from .normaliser import Normaliser
from .publisher import BufferedPublisher, KafkaPublisher, MqttPublisher, Publisher

log = logging.getLogger("omnilink.runner")

READINGS = Counter("omnilink_connector_readings_total", "Raw readings", ["connector"])
PUBLISHED = Counter("omnilink_connector_published_total", "Canonical messages published", ["connector", "topic"])
ERRORS = Counter("omnilink_connector_errors_total", "Errors", ["connector", "stage"])
BUFFER_DEPTH = Gauge("omnilink_connector_buffer_depth", "Records waiting in store-and-forward", ["connector"])
COMMANDS = Counter("omnilink_connector_commands_total", "Commands executed", ["connector", "status"])

ADAPTER_MODULES = {
    "mqtt": "adapters.mqtt_adapter",
    "modbus": "adapters.modbus_adapter",
    "bacnet": "adapters.bacnet_adapter",
    "opcua": "adapters.opcua_adapter",
    "onvif": "adapters.onvif_adapter",
    "snmp": "adapters.snmp_adapter",
}


class ConnectorRunner:
    def __init__(self, connector: Connector, publisher: Publisher):
        self.c = connector
        self.cfg = connector.config
        self.pub = publisher
        self.norm = Normaliser(self.cfg)
        self.failures = 0
        self.last_seen: datetime | None = None
        self._stop = asyncio.Event()

    # ---- data path -------------------------------------------------------
    async def emit(self, item: RawReading | DeviceEvent) -> None:
        if isinstance(item, DeviceEvent):
            await self._publish(item)
            return
        READINGS.labels(self.cfg.connector_id).inc()
        ev = self.norm.normalise(item.point_ref, item.value, item.ts, item.quality)
        if ev is not None:
            await self._publish(ev)
        self.last_seen = item.ts

    async def _publish(self, msg) -> None:
        topic = topic_for(msg)
        await self.pub.send(topic, msg.kafka_key().encode(), msg.to_bytes())
        PUBLISHED.labels(self.cfg.connector_id, topic).inc()

    async def poll_once(self) -> int:
        try:
            readings = await asyncio.wait_for(self.c.read(), timeout=max(self.cfg.poll_interval_s, 5))
            self.failures = 0
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            ERRORS.labels(self.cfg.connector_id, "read").inc()
            log.warning("read failed (%d): %s", self.failures, exc)
            return 0
        for r in readings:
            await self.emit(r)
        return len(readings)

    async def _poll_loop(self) -> None:
        backoff = self.cfg.poll_interval_s
        while not self._stop.is_set():
            n = await self.poll_once()
            backoff = self.cfg.poll_interval_s if self.failures == 0 else min(backoff * 2, 300)
            jitter = random.uniform(0, 0.1 * backoff)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff + jitter)
            except TimeoutError:
                pass
            log.debug("polled %d readings", n)

    # ---- commands ----------------------------------------------------------
    async def handle_command(self, cmd: Command) -> None:
        if cmd.connector_id != self.cfg.connector_id:
            return
        if cmd.expired():
            res = self.c.result(cmd, CommandStatus.EXPIRED, "ttl elapsed before execution")
        else:
            try:
                res = await asyncio.wait_for(self.c.execute(cmd), timeout=self.cfg.command_timeout_s)
            except TimeoutError:
                res = self.c.result(cmd, CommandStatus.FAILED, "device timeout")
            except Exception as exc:  # noqa: BLE001
                res = self.c.result(cmd, CommandStatus.FAILED, str(exc)[:500])
        COMMANDS.labels(self.cfg.connector_id, res.status).inc()
        await self._publish(res)

    async def _command_loop(self, bootstrap: str) -> None:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(T.COMMANDS, bootstrap_servers=bootstrap,
                                    group_id=f"connector-{self.cfg.connector_id}", enable_auto_commit=True,
                                    auto_offset_reset="latest")
        await consumer.start()
        try:
            async for msg in consumer:
                try:
                    await self.handle_command(Command.from_bytes(msg.value))
                except Exception as exc:  # noqa: BLE001
                    ERRORS.labels(self.cfg.connector_id, "command").inc()
                    log.error("bad command: %s", exc)
        finally:
            await consumer.stop()

    # ---- health ------------------------------------------------------------
    def health(self) -> DeviceHealth:
        if self.failures >= self.cfg.offline_after_failures:
            status = HealthStatus.OFFLINE
        elif self.failures:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.ONLINE
        buf = getattr(self.pub, "buffer", None)
        depth = float(len(buf)) if buf is not None else 0.0
        BUFFER_DEPTH.labels(self.cfg.connector_id).set(depth)
        return DeviceHealth(tenant=self.cfg.tenant, device_id=f"connector:{self.cfg.connector_id}",
                            connector_id=self.cfg.connector_id, status=status, last_seen=self.last_seen,
                            metrics={"consecutive_failures": float(self.failures), "buffer_depth": depth})

    async def _health_loop(self) -> None:
        while not self._stop.is_set():
            await self._publish(self.health())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.cfg.heartbeat_s)
            except TimeoutError:
                pass

    async def run(self, kafka_bootstrap: str | None = None) -> None:
        await self.pub.start()
        await self.c.connect()
        tasks = [asyncio.create_task(self._health_loop()),
                 asyncio.create_task(self.c.subscribe(self.emit))]
        if type(self.c).read is not Connector.read:
            tasks.append(asyncio.create_task(self._poll_loop()))
        if kafka_bootstrap:
            tasks.append(asyncio.create_task(self._command_loop(kafka_bootstrap)))
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await self.c.close()
            await self.pub.stop()

    def stop(self) -> None:
        self._stop.set()


def build_publisher(cfg: ConnectorConfig) -> Publisher:
    mode = os.environ.get("OMNILINK_UPLINK", "kafka")
    if mode == "mqtt":
        uplink = MqttPublisher(os.environ["OMNILINK_MQTT_HOST"], int(os.environ.get("OMNILINK_MQTT_PORT", "8883")),
                               client_id=cfg.connector_id, username=os.environ.get("OMNILINK_MQTT_USER"),
                               password=os.environ.get("OMNILINK_MQTT_PASSWORD"),
                               tls=os.environ.get("OMNILINK_MQTT_TLS", "true") == "true")
    else:
        uplink = KafkaPublisher(os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"), client_id=cfg.connector_id)
    buf = StoreForwardBuffer(os.environ.get("OMNILINK_BUFFER_PATH", f"/var/lib/omnilink/{cfg.connector_id}.db"))
    return BufferedPublisher(uplink, buf)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    cfg = ConnectorConfig.from_yaml(args.config)
    importlib.import_module(ADAPTER_MODULES[cfg.type])
    connector = registry[cfg.type](cfg)
    start_http_server(int(os.environ.get("METRICS_PORT", "9108")))
    runner = ConnectorRunner(connector, build_publisher(cfg))
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP") if os.environ.get("OMNILINK_UPLINK", "kafka") == "kafka" else None
    asyncio.run(runner.run(bootstrap))


if __name__ == "__main__":
    main()
