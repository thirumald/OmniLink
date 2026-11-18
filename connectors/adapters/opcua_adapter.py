"""OPC UA client adapter (asyncua, LGPL).

point_ref: node id, e.g. ``ns=2;s=Pump1.Flow``. Uses subscriptions (data change) when
settings.subscribe is true, otherwise polling. Security: settings.security_string
e.g. ``Basic256Sha256,SignAndEncrypt,cert.pem,key.pem``.
"""

from __future__ import annotations

from omnilink_contracts import Command, CommandStatus, Quality
from omnilink_sdk import Connector, RawReading, register


@register("opcua")
class OpcUaAdapter(Connector):
    async def connect(self) -> None:
        from asyncua import Client

        self.client = Client(url=self.settings["endpoint"], timeout=5)
        if self.settings.get("security_string"):
            await self.client.set_security_string(self.settings["security_string"])
        if self.settings.get("username"):
            self.client.set_user(self.settings["username"])
            self.client.set_password(self.settings.get("password", ""))
        await self.client.connect()
        self.nodes = {p.point_ref: self.client.get_node(p.point_ref) for p in self.config.points}

    async def read(self) -> list[RawReading]:
        if self.settings.get("subscribe"):
            return []
        values = await self.client.read_values(list(self.nodes.values()))
        return [RawReading(ref, v) for ref, v in zip(self.nodes, values)]

    async def subscribe(self, emit) -> None:
        if not self.settings.get("subscribe"):
            return
        refs = {node.nodeid.to_string(): ref for ref, node in self.nodes.items()}

        class Handler:
            async def datachange_notification(self, node, val, data):
                status = data.monitored_item.Value.StatusCode
                q = Quality.GOOD if status.is_good() else Quality.UNCERTAIN
                ts = data.monitored_item.Value.SourceTimestamp
                reading = RawReading(refs[node.nodeid.to_string()], val, quality=q)
                if ts:
                    reading.ts = ts.replace(tzinfo=reading.ts.tzinfo) if ts.tzinfo is None else ts
                await emit(reading)

        sub = await self.client.create_subscription(int(self.settings.get("publishing_ms", 1000)), Handler())
        await sub.subscribe_data_change(list(self.nodes.values()))

    async def execute(self, cmd: Command):
        from asyncua import ua

        if cmd.action == "write_point":
            pm = self.point_for_device(cmd.device_id, cmd.params.get("attribute"))
            if pm is None:
                return self.result(cmd, CommandStatus.REJECTED, "unknown point")
            node = self.nodes[pm.point_ref]
            vtype = await node.read_data_type_as_variant_type()
            await node.write_value(ua.DataValue(ua.Variant((float(cmd.params["value"]) - pm.offset) / pm.scale, vtype)))
            return self.result(cmd, CommandStatus.ACKED)
        if cmd.action == "call_method":
            obj = self.client.get_node(cmd.params["object_node"])
            res = await obj.call_method(cmd.params["method_node"], *cmd.params.get("args", []))
            return self.result(cmd, CommandStatus.ACKED, str(res)[:500])
        return await super().execute(cmd)

    async def close(self) -> None:
        await self.client.disconnect()
