"""SNMP v2c/v3 adapter (pysnmp, BSD). Also the transport for NTCIP 1202/1203/1204 field devices.

point_ref: numeric OID. settings: host, version (2c|3), community or user/auth_key/priv_key.
"""

from __future__ import annotations

from omnilink_contracts import Command, CommandStatus, Quality
from omnilink_sdk import Connector, RawReading, register

# Useful NTCIP objects (VMS signs, signal controllers, ESS weather stations)
NTCIP_OIDS = {
    "ntcip.dms.messageActivate": "1.3.6.1.4.1.1206.4.2.3.6.3.0",
    "ntcip.ess.airTemperature": "1.3.6.1.4.1.1206.4.2.5.4.1.0",
    "ntcip.asc.phaseStatusGroupGreens": "1.3.6.1.4.1.1206.4.2.1.1.4.1.4.1",
}


def coerce(value):
    for cast in (int, float):
        try:
            return cast(str(value))
        except ValueError:
            continue
    return str(value)


@register("snmp")
class SnmpAdapter(Connector):
    async def connect(self) -> None:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData,
            ContextData,
            SnmpEngine,
            UdpTransportTarget,
            UsmUserData,
            usmAesCfb128Protocol,
            usmHMACSHAAuthProtocol,
        )

        s = self.settings
        self.engine = SnmpEngine()
        if str(s.get("version", "3")) == "3":
            self.auth = UsmUserData(s["user"], s["auth_key"], s["priv_key"],
                                    authProtocol=usmHMACSHAAuthProtocol, privProtocol=usmAesCfb128Protocol)
        else:
            self.auth = CommunityData(s.get("community", "public"), mpModel=1)
        self.target = await UdpTransportTarget.create((s["host"], int(s.get("port", 161))), timeout=2, retries=1)
        self.ctx = ContextData()

    async def read(self) -> list[RawReading]:
        from pysnmp.hlapi.v3arch.asyncio import ObjectIdentity, ObjectType, get_cmd

        oids = [p.point_ref for p in self.config.points]
        err_ind, err_status, _idx, binds = await get_cmd(
            self.engine, self.auth, self.target, self.ctx, *[ObjectType(ObjectIdentity(o)) for o in oids])
        if err_ind or err_status:
            return [RawReading(o, None, quality=Quality.BAD) for o in oids]
        return [RawReading(str(name), coerce(val)) for name, val in binds]

    async def execute(self, cmd: Command):
        if cmd.action != "set":
            return await super().execute(cmd)
        if str(self.settings.get("version", "3")) != "3" and not self.settings.get("allow_v2_set"):
            return self.result(cmd, CommandStatus.REJECTED, "SNMP SET requires v3")
        from pysnmp.hlapi.v3arch.asyncio import Integer, ObjectIdentity, ObjectType, OctetString, set_cmd

        val = cmd.params["value"]
        typed = Integer(val) if isinstance(val, int) else OctetString(str(val))
        err_ind, err_status, *_ = await set_cmd(self.engine, self.auth, self.target, self.ctx,
                                               ObjectType(ObjectIdentity(cmd.params["oid"]), typed))
        ok = not (err_ind or err_status)
        return self.result(cmd, CommandStatus.ACKED if ok else CommandStatus.FAILED, str(err_ind or err_status or ""))
