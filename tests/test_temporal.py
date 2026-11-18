"""Escalation workflow under Temporal's time-skipping test server (downloads the server on first run)."""

import asyncio
import uuid

import pytest
from omnilink_workflows.activities import IncidentInput
from omnilink_workflows.workflows import IncidentEscalation
from temporalio import activity
from temporalio.worker import Worker

notified: list[str] = []


@activity.defn(name="create_incident")
async def fake_create(inp: IncidentInput) -> str:
    return "INC-1"


@activity.defn(name="point_cameras")
async def fake_cams(inp: IncidentInput, radius: int, preset: str) -> int:
    return 2


@activity.defn(name="notify")
async def fake_notify(inp: IncidentInput, level: str, channels: list[str], group: str) -> None:
    notified.append(level)


@activity.defn(name="close_incident")
async def fake_close(incident_id: str, resolution: str) -> None:
    return None


def test_escalates_until_ack_then_closes_on_clear():
    try:
        from temporalio.testing import WorkflowEnvironment
    except ImportError:
        pytest.skip("temporalio testing unavailable")

    async def go():
        try:
            env = await asyncio.wait_for(WorkflowEnvironment.start_time_skipping(), 60)
        except Exception as exc:  # noqa: BLE001 - no network to fetch the test server
            pytest.skip(f"time-skipping server unavailable: {exc}")
        async with env:
            async with Worker(env.client, task_queue="tq", workflows=[IncidentEscalation],
                              activities=[fake_create, fake_cams, fake_notify, fake_close]):
                h = await env.client.start_workflow(IncidentEscalation.run,
                                                    IncidentInput("abudhabi", "a1", "urn:ngsi-ld:X:abudhabi:1", 1, "Flood"),
                                                    id=str(uuid.uuid4()), task_queue="tq")
                await env.sleep(200)  # level 1 waits 180 s -> escalate to level 2
                await h.signal(IncidentEscalation.acknowledged, "sup1")
                await env.sleep(10)
                await h.signal(IncidentEscalation.alarm_cleared)
                result = await h.result()
        assert notified == ["duty-officer", "shift-supervisor"]
        assert result["acked_by"] == "sup1" and result["cameras"] == 2 and result["incident_id"] == "INC-1"

    asyncio.run(go())
