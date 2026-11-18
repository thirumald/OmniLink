"""BACnet/IP adapter (bacpypes3, MIT).

point_ref: ``<objectType>:<instance>:<property>`` e.g. ``analogInput:3:presentValue``.
settings: address (local interface, e.g. 10.20.1.10/24), device_address (target IP), device_instance.
Writes use the priority array (default priority 8 = manual operator).
"""

from __future__ import annotations

from dataclasses import dataclass

from omnilink_contracts import Command, CommandStatus, Quality
from omnilink_sdk import Connector, RawReading, register

OBJECT_TYPES = {
    "analogInput", "analogOutput", "analogValue", "binaryInput", "binaryOutput", "binaryValue",
    "multiStateInput", "multiStateOutput", "multiStateValue", "schedule", "trendLog", "device",
}
WRITABLE = {"analogOutput", "analogValue", "binaryOutput", "binaryValue", "multiStateOutput", "multiStateValue"}


@dataclass(frozen=True)
class BacnetRef:
    object_type: str
    instance: int
    prop: str = "presentValue"

    @property
    def object_id(self) -> str:
        return f"{self.object_type},{self.instance}"


def parse_ref(ref: str) -> BacnetRef:
    parts = ref.split(":")
    if len(parts) not in (2, 3) or parts[0] not in OBJECT_TYPES:
        raise ValueError(f"bad bacnet point_ref: {ref}")
    return BacnetRef(parts[0], int(parts[1]), parts[2] if len(parts) == 3 else "presentValue")


@register("bacnet")
class BacnetAdapter(Connector):
    async def connect(self) -> None:
        from bacpypes3.app import Application
        from bacpypes3.argparse import SimpleArgumentParser

        args = SimpleArgumentParser().parse_args(["--address", self.settings["address"],
                                                  "--instance", str(self.settings.get("local_instance", 599))])
        self.app = Application.from_args(args)
        self.target = self.settings["device_address"]
        self.refs = {p.point_ref: parse_ref(p.point_ref) for p in self.config.points}

    async def discover(self) -> list[dict]:
        found = await self.app.who_is(timeout=3)
        return [{"device_instance": i.iAmDeviceIdentifier[1], "address": str(i.pduSource)} for i in found]

    async def read(self) -> list[RawReading]:
        out = []
        for ref_s, ref in self.refs.items():
            try:
                value = await self.app.read_property(self.target, ref.object_id, ref.prop)
                if hasattr(value, "value"):
                    value = value.value
                out.append(RawReading(ref_s, value if isinstance(value, (int, float, bool, str)) else str(value)))
            except Exception:  # noqa: BLE001 - device/property error -> bad quality
                out.append(RawReading(ref_s, None, quality=Quality.BAD))
        return out

    async def execute(self, cmd: Command):
        if cmd.action not in ("write_point", "relinquish"):
            return await super().execute(cmd)
        pm = self.point_for_device(cmd.device_id, cmd.params.get("attribute"))
        if pm is None:
            return self.result(cmd, CommandStatus.REJECTED, "unknown point")
        ref = self.refs[pm.point_ref]
        if ref.object_type not in WRITABLE:
            return self.result(cmd, CommandStatus.REJECTED, f"{ref.object_type} is not writable")
        priority = int(cmd.params.get("priority", 8))
        if cmd.action == "relinquish":
            from bacpypes3.primitivedata import Null

            value = Null(())
        else:
            value = (float(cmd.params["value"]) - pm.offset) / pm.scale
        await self.app.write_property(self.target, ref.object_id, ref.prop, value, priority=priority)
        return self.result(cmd, CommandStatus.ACKED, f"priority {priority}")

    async def close(self) -> None:
        self.app.close()
