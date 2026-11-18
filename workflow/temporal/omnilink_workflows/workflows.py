"""Durable workflows (Temporal). Deterministic: no I/O here, only activities, timers and signals."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import IncidentInput, close_incident, create_incident, notify, point_cameras
    from .policy import EscalationPolicy

RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(minutes=1), maximum_attempts=10)
SHORT = timedelta(seconds=30)


@workflow.defn
class IncidentEscalation:
    """Escalate an alarm until someone acknowledges it or the alarm clears."""

    def __init__(self) -> None:
        self.acked_by: str | None = None
        self.cleared = False
        self.level_reached = ""

    @workflow.signal
    def acknowledged(self, user: str) -> None:
        self.acked_by = user

    @workflow.signal
    def alarm_cleared(self) -> None:
        self.cleared = True

    @workflow.query
    def status(self) -> dict:
        return {"acked_by": self.acked_by, "cleared": self.cleared, "level": self.level_reached}

    @workflow.run
    async def run(self, inp: IncidentInput) -> dict:
        policy = EscalationPolicy.for_priority(inp.priority)
        incident_id = await workflow.execute_activity(create_incident, inp, start_to_close_timeout=SHORT,
                                                      retry_policy=RETRY)
        cams = await workflow.execute_activity(point_cameras, args=[inp, policy.camera_radius_m, policy.camera_preset],
                                               start_to_close_timeout=timedelta(minutes=1), retry_policy=RETRY)
        for level in policy.levels:
            if self.acked_by or self.cleared:
                break
            self.level_reached = level.name
            await workflow.execute_activity(notify, args=[inp, level.name, list(level.channels), level.recipients_group],
                                            start_to_close_timeout=SHORT, retry_policy=RETRY)
            try:
                await workflow.wait_condition(lambda: self.acked_by is not None or self.cleared,
                                              timeout=timedelta(seconds=level.wait_s))
            except TimeoutError:
                continue
        # once acknowledged, keep the incident open until the alarm clears (max 7 days)
        try:
            await workflow.wait_condition(lambda: self.cleared, timeout=timedelta(days=7))
            resolution = f"alarm cleared; acknowledged by {self.acked_by or 'nobody'}"
        except TimeoutError:
            resolution = "auto-closed after 7 days without clear"
        await workflow.execute_activity(close_incident, args=[incident_id, resolution], start_to_close_timeout=SHORT,
                                        retry_policy=RETRY)
        return {"incident_id": incident_id, "cameras": cams, "acked_by": self.acked_by,
                "level_reached": self.level_reached, "resolution": resolution}
