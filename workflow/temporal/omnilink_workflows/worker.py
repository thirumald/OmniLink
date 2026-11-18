"""Temporal worker + Kafka trigger (alarms → start / signal workflows idempotently)."""

from __future__ import annotations

import asyncio
import os

from omnilink_contracts import Alarm
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from .activities import IncidentInput, close_incident, create_incident, notify, point_cameras
from .workflows import IncidentEscalation

TASK_QUEUE = "omnilink-incidents"
MAX_PRIORITY_FOR_INCIDENT = int(os.environ.get("OMNILINK_INCIDENT_MAX_PRIORITY", "2"))


def workflow_id(alarm: Alarm) -> str:
    return f"incident-{alarm.tenant}-{alarm.alarm_id}"


def decide(alarm: Alarm) -> str | None:
    """Return 'start', 'ack', 'clear' or None for an alarm update."""
    if alarm.state == "active_unack" and alarm.occurrences == 1 and alarm.priority <= MAX_PRIORITY_FOR_INCIDENT:
        return "start"
    if alarm.state in ("active_ack",) and alarm.acked_by:
        return "ack"
    if alarm.state in ("cleared", "cleared_unack"):
        return "clear"
    return None


async def handle(client: Client, alarm: Alarm) -> None:
    action, wid = decide(alarm), workflow_id(alarm)
    if action == "start":
        try:
            await client.start_workflow(IncidentEscalation.run,
                                        IncidentInput(alarm.tenant, alarm.alarm_id, alarm.entity_id, alarm.priority,
                                                      alarm.message),
                                        id=wid, task_queue=TASK_QUEUE,
                                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        except WorkflowAlreadyStartedError:
            pass
    elif action in ("ack", "clear"):
        handle_ = client.get_workflow_handle(wid)
        try:
            if action == "ack":
                await handle_.signal(IncidentEscalation.acknowledged, alarm.acked_by)
            else:
                await handle_.signal(IncidentEscalation.alarm_cleared)
        except Exception:  # noqa: BLE001 - no incident for this alarm (low priority)
            pass


async def main() -> None:  # pragma: no cover
    from aiokafka import AIOKafkaConsumer
    from omnilink_contracts.topics import T

    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "temporal:7233"),
                                  namespace=os.environ.get("TEMPORAL_NAMESPACE", "omnilink"))
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[IncidentEscalation],
                    activities=[create_incident, point_cameras, notify, close_incident])
    consumer = AIOKafkaConsumer(T.ALARMS, bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
                                group_id="workflow-trigger", enable_auto_commit=False)
    await consumer.start()

    async def trigger():
        async for m in consumer:
            await handle(client, Alarm.from_bytes(m.value))
            await consumer.commit()

    try:
        await asyncio.gather(worker.run(), trigger())
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
