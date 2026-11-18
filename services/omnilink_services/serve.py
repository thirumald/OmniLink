"""Production factories: wire each service to Kafka/PostgreSQL from environment variables.

    uvicorn --factory omnilink_services.serve:alarm_service --host 0.0.0.0 --port 8002
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from omnilink_sdk import BufferedPublisher, KafkaPublisher, StoreForwardBuffer

from . import alarms, asset_registry, commands, outbound, query_api


def _publisher(name: str):
    return BufferedPublisher(KafkaPublisher(os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"), client_id=name),
                             StoreForwardBuffer(os.environ.get("OMNILINK_BUFFER_PATH", f"/var/lib/omnilink/{name}.db")))


def asset_registry_service():
    return asset_registry.build_app()  # PostgreSQL via DATABASE_URL


def alarm_service():
    return alarms.build_app(publisher=_publisher("alarm-service"), consume=True)


def command_service():
    return commands.build_app(publisher=_publisher("command-service"), consume=True)


def query_service():
    return query_api.build_app()


def outbound_service():
    app = outbound.build_app()

    async def relay():  # pragma: no cover - integration path
        from aiokafka import AIOKafkaConsumer
        from omnilink_contracts.topics import T

        c = AIOKafkaConsumer(T.ALARMS, T.EVENTS, T.TELEMETRY_ENRICHED, T.AI_SUGGESTIONS,
                             bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"), group_id="outbound")
        await c.start()
        try:
            async for m in c:
                await app.state.fan_out(m.topic, m.value)
        finally:
            await c.stop()

    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        task = asyncio.create_task(relay())
        async with inner(a):
            yield
        task.cancel()

    app.router.lifespan_context = lifespan
    return app
