"""ONVIF adapter (onvif-zeep-async, MIT): device info, events (PullPoint), PTZ, snapshots.

Video streams are NOT ingested here — RTSP goes to the VMS / MediaMTX. This adapter
carries metadata, events and control. One instance serves many cameras:
settings.cameras: [{device_id, host, port, username, password}]
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from omnilink_contracts import Command, CommandStatus, DeviceEvent, Severity
from omnilink_sdk import Connector, RawReading, register

# ONVIF topic -> (canonical event_type, severity)
EVENT_MAP = {
    "tns1:VideoSource/MotionAlarm": ("motion", Severity.INFO),
    "tns1:RuleEngine/CellMotionDetector/Motion": ("motion", Severity.INFO),
    "tns1:RuleEngine/LineDetector/Crossed": ("line_crossing", Severity.WARNING),
    "tns1:RuleEngine/FieldDetector/ObjectsInside": ("intrusion", Severity.MAJOR),
    "tns1:VideoSource/GlobalSceneChange/ImagingService": ("tamper", Severity.MAJOR),
    "tns1:Device/Trigger/DigitalInput": ("digital_input", Severity.WARNING),
}


def map_event(topic: str, data: dict) -> tuple[str, Severity]:
    for key, mapped in EVENT_MAP.items():
        if topic.endswith(key.split(":", 1)[1]) or topic == key:
            return mapped
    return ("onvif_event", Severity.INFO)


@register("onvif")
class OnvifAdapter(Connector):
    async def connect(self) -> None:
        from onvif import ONVIFCamera

        self.cams = {}
        for cam in self.settings["cameras"]:
            c = ONVIFCamera(cam["host"], int(cam.get("port", 80)), cam["username"], cam["password"])
            await c.update_xaddrs()
            media = await c.create_media_service()
            profiles = await media.GetProfiles()
            self.cams[cam["device_id"]] = {"cam": c, "media": media, "profile": profiles[0].token}

    async def read(self) -> list[RawReading]:
        """Heartbeat: device clock reachability per camera (point_ref = '<device_id>:online')."""
        out = []
        for device_id, h in self.cams.items():
            try:
                dev = await h["cam"].create_devicemgmt_service()
                await dev.GetSystemDateAndTime()
                out.append(RawReading(f"{device_id}:online", True))
            except Exception:  # noqa: BLE001
                out.append(RawReading(f"{device_id}:online", False))
        return out

    async def subscribe(self, emit) -> None:
        async def pull(device_id, h):
            mgr = await h["cam"].create_pullpoint_manager(interval=60, subscription_lost_callback=lambda: None)
            svc = h["cam"].create_pullpoint_service()
            while True:
                msgs = await svc.PullMessages({"MessageLimit": 50, "Timeout": "PT10S"})
                for m in getattr(msgs, "NotificationMessage", []) or []:
                    topic = m.Topic._value_1
                    data = {i.Name: i.Value for i in (m.Message._value_1.Data.SimpleItem or [])}
                    event_type, sev = map_event(topic, data)
                    await emit(DeviceEvent(tenant=self.config.tenant, device_id=device_id, event_type=event_type,
                                           severity=sev, payload={"topic": topic, **data},
                                           source_ts=datetime.now(UTC), protocol="onvif"))
                await asyncio.sleep(0)
            _ = mgr

        await asyncio.gather(*(pull(d, h) for d, h in self.cams.items()))

    async def execute(self, cmd: Command):
        h = self.cams.get(cmd.device_id)
        if h is None:
            return self.result(cmd, CommandStatus.REJECTED, "unknown camera")
        if cmd.action.startswith("ptz."):
            ptz = await h["cam"].create_ptz_service()
            token = h["profile"]
            if cmd.action == "ptz.goto_preset":
                await ptz.GotoPreset({"ProfileToken": token, "PresetToken": str(cmd.params["preset"])})
            elif cmd.action == "ptz.move":
                v = cmd.params
                await ptz.ContinuousMove({"ProfileToken": token, "Velocity": {
                    "PanTilt": {"x": float(v.get("pan", 0)), "y": float(v.get("tilt", 0))},
                    "Zoom": {"x": float(v.get("zoom", 0))}}})
            elif cmd.action == "ptz.stop":
                await ptz.Stop({"ProfileToken": token})
            else:
                return await super().execute(cmd)
            return self.result(cmd, CommandStatus.ACKED)
        if cmd.action == "snapshot":
            uri = await h["media"].GetSnapshotUri({"ProfileToken": h["profile"]})
            return self.result(cmd, CommandStatus.ACKED, uri.Uri)
        return await super().execute(cmd)
