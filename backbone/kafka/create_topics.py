"""Idempotently create / update Kafka topics from topics.yaml.

    KAFKA_BOOTSTRAP=localhost:9092 REPLICATION_FACTOR=1 python backbone/kafka/create_topics.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import yaml

HERE = Path(__file__).parent


def load_plan(path: Path = HERE / "topics.yaml", rf_override: int | None = None) -> list[dict]:
    doc = yaml.safe_load(path.read_text())
    defaults = doc.get("defaults", {})
    rf = rf_override or defaults.get("replication_factor", 1)
    plan = []
    for t in doc["topics"]:
        cfg = {**defaults.get("config", {}), **t.get("config", {})}
        if rf < 2:
            cfg.pop("min.insync.replicas", None)
        plan.append({"name": t["name"], "partitions": t["partitions"], "rf": rf, "config": cfg})
    return plan


async def apply(bootstrap: str, plan: list[dict]) -> None:
    from aiokafka.admin import AIOKafkaAdminClient, NewPartitions, NewTopic

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        new = [
            NewTopic(t["name"], t["partitions"], t["rf"], topic_configs=t["config"])
            for t in plan
            if t["name"] not in existing
        ]
        if new:
            await admin.create_topics(new)
            print("created:", ", ".join(t.name for t in new))
        grow = {}
        meta = await admin.describe_topics([t["name"] for t in plan if t["name"] in existing])
        for m in meta:
            want = next(t["partitions"] for t in plan if t["name"] == m["topic"])
            if len(m["partitions"]) < want:
                grow[m["topic"]] = NewPartitions(total_count=want)
        if grow:
            await admin.create_partitions(grow)
            print("grew partitions:", ", ".join(grow))
        print(f"{len(plan)} topics in plan, {len(existing & {t['name'] for t in plan})} already existed")
    finally:
        await admin.close()


if __name__ == "__main__":
    rf = int(os.environ["REPLICATION_FACTOR"]) if "REPLICATION_FACTOR" in os.environ else None
    asyncio.run(apply(os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"), load_plan(rf_override=rf)))
