"""Kafka worker: new P1/P2 alarms -> triage suggestion -> omnilink.ai-suggestions.v1 (shown in the console)."""

from __future__ import annotations

import asyncio
import json
import os

from omnilink_contracts import Alarm
from omnilink_contracts.topics import T

from .llm import OpenAICompatibleLLM
from .platform import PlatformClient, service_token
from .rag import MemoryKnowledgeBase
from .tools import ToolContext
from .triage import triage

MAX_PRIORITY = int(os.environ.get("OMNILINK_TRIAGE_MAX_PRIORITY", "2"))


def should_triage(a: Alarm) -> bool:
    return a.state == "active_unack" and a.occurrences == 1 and a.priority <= MAX_PRIORITY


async def main() -> None:  # pragma: no cover - integration path
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    llm = OpenAICompatibleLLM()
    kb = MemoryKnowledgeBase(llm)  # swap for PgKnowledgeBase in production
    consumer = AIOKafkaConsumer(T.ALARMS, bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
                                group_id="ai-triage")
    producer = AIOKafkaProducer(bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"), acks="all")
    await consumer.start()
    await producer.start()
    try:
        async for m in consumer:
            alarm = Alarm.from_bytes(m.value)
            if not should_triage(alarm):
                continue
            ctx = ToolContext(alarm.tenant, "ai-triage", {"viewer"}, PlatformClient(await service_token()), kb)
            s = await triage(llm, ctx, json.loads(alarm.model_dump_json()))
            await producer.send_and_wait(T.AI_SUGGESTIONS, s.model_dump_json().encode(),
                                         key=f"{alarm.tenant}:{alarm.alarm_id}".encode())
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
