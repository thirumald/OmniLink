"""Modbus TCP adapter (pymodbus, BSD).

point_ref: ``<table>:<address>:<type>[:<word order>]``
  table  hr (holding), ir (input), co (coil), di (discrete input)
  type   bool, int16, uint16, int32, uint32, float32, float64
  order  be (default, big-endian words) or le (little-endian / word-swapped)
Optional unit id: settings.unit_id (default 1).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from omnilink_contracts import Command, CommandStatus, Quality
from omnilink_sdk import Connector, RawReading, register

_WORDS = {"bool": 1, "int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "float32": 2, "float64": 4}
_FMT = {"int16": "h", "uint16": "H", "int32": "i", "uint32": "I", "float32": "f", "float64": "d"}


@dataclass(frozen=True)
class ModbusRef:
    table: str
    address: int
    dtype: str
    order: str = "be"

    @property
    def count(self) -> int:
        return _WORDS[self.dtype]


def parse_ref(ref: str) -> ModbusRef:
    parts = ref.split(":")
    if len(parts) not in (3, 4) or parts[0] not in ("hr", "ir", "co", "di") or parts[2] not in _WORDS:
        raise ValueError(f"bad modbus point_ref: {ref}")
    return ModbusRef(parts[0], int(parts[1]), parts[2], parts[3] if len(parts) == 4 else "be")


def decode(registers: list[int], ref: ModbusRef):
    if ref.dtype == "bool":
        return bool(registers[0])
    words = list(registers[: ref.count])
    if ref.order == "le":
        words.reverse()
    raw = b"".join(w.to_bytes(2, "big") for w in words)
    return struct.unpack(">" + _FMT[ref.dtype], raw)[0]


def encode(value, ref: ModbusRef) -> list[int]:
    if ref.dtype == "bool":
        return [1 if value else 0]
    fmt = _FMT[ref.dtype]
    v = int(value) if fmt in "hHiI" else float(value)
    raw = struct.pack(">" + fmt, v)
    words = [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]
    if ref.order == "le":
        words.reverse()
    return words


@register("modbus")
class ModbusAdapter(Connector):
    async def connect(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        self.client = AsyncModbusTcpClient(self.settings["host"], port=int(self.settings.get("port", 502)), timeout=3)
        await self.client.connect()
        self.unit = int(self.settings.get("unit_id", 1))
        self.refs = {p.point_ref: parse_ref(p.point_ref) for p in self.config.points}

    async def read(self) -> list[RawReading]:
        out = []
        for ref_s, ref in self.refs.items():
            fn = {"hr": self.client.read_holding_registers, "ir": self.client.read_input_registers,
                  "co": self.client.read_coils, "di": self.client.read_discrete_inputs}[ref.table]
            rr = await fn(ref.address, count=ref.count, device_id=self.unit)
            if rr.isError():
                out.append(RawReading(ref_s, None, quality=Quality.BAD))
                continue
            regs = rr.bits if ref.table in ("co", "di") else rr.registers
            out.append(RawReading(ref_s, decode(regs, ref)))
        return out

    async def execute(self, cmd: Command):
        if cmd.action != "write_point":
            return await super().execute(cmd)
        pm = self.point_for_device(cmd.device_id, cmd.params.get("attribute"))
        if pm is None:
            return self.result(cmd, CommandStatus.REJECTED, "unknown point")
        ref = self.refs[pm.point_ref]
        raw = (float(cmd.params["value"]) - pm.offset) / pm.scale
        if ref.table == "co":
            rr = await self.client.write_coil(ref.address, bool(raw), device_id=self.unit)
        elif ref.table == "hr":
            rr = await self.client.write_registers(ref.address, encode(raw, ref), device_id=self.unit)
        else:
            return self.result(cmd, CommandStatus.REJECTED, "read-only table")
        return self.result(cmd, CommandStatus.FAILED if rr.isError() else CommandStatus.ACKED, str(rr))

    async def close(self) -> None:
        self.client.close()
