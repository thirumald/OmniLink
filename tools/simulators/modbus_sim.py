"""Pump-station simulator: a minimal Modbus TCP server (stdlib only, no pymodbus version coupling).

Holding register 100-101 (float32, big-endian): flow in gal/min
Input register 200 (uint16): pressure x10 kPa   ·   Coil 1: running
Supports FC 1, 2, 3, 4 (read) and 5, 6, 16 (write).
    python tools/simulators/modbus_sim.py --port 5020 [--fault-after 180]   # pressure drops after N s
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import struct
import time

HR = [0] * 1024
IR = [0] * 1024
CO = [False] * 1024
DI = [False] * 1024


def set_float(table: list[int], addr: int, v: float) -> None:
    raw = struct.pack(">f", v)
    table[addr], table[addr + 1] = int.from_bytes(raw[:2], "big"), int.from_bytes(raw[2:], "big")


def handle_pdu(pdu: bytes) -> bytes:
    fc = pdu[0]
    try:
        if fc in (1, 2):
            addr, count = struct.unpack(">HH", pdu[1:5])
            bits = (CO if fc == 1 else DI)[addr:addr + count]
            out = bytearray((count + 7) // 8)
            for i, b in enumerate(bits):
                if b:
                    out[i // 8] |= 1 << (i % 8)
            return bytes([fc, len(out)]) + bytes(out)
        if fc in (3, 4):
            addr, count = struct.unpack(">HH", pdu[1:5])
            regs = (HR if fc == 3 else IR)[addr:addr + count]
            if len(regs) != count:
                raise IndexError
            return bytes([fc, 2 * count]) + b"".join(struct.pack(">H", r) for r in regs)
        if fc == 5:
            addr, val = struct.unpack(">HH", pdu[1:5])
            CO[addr] = val == 0xFF00
            return pdu[:5]
        if fc == 6:
            addr, val = struct.unpack(">HH", pdu[1:5])
            HR[addr] = val
            return pdu[:5]
        if fc == 16:
            addr, count, _n = struct.unpack(">HHB", pdu[1:6])
            for i in range(count):
                HR[addr + i] = struct.unpack(">H", pdu[6 + 2 * i:8 + 2 * i])[0]
            return pdu[:5]
        return bytes([fc | 0x80, 1])  # illegal function
    except (IndexError, struct.error):
        return bytes([fc | 0x80, 2])  # illegal data address


async def serve_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            header = await reader.readexactly(7)
            tid, pid, length, unit = struct.unpack(">HHHB", header)
            pdu = await reader.readexactly(length - 1)
            resp = handle_pdu(pdu)
            writer.write(struct.pack(">HHHB", tid, pid, len(resp) + 1, unit) + resp)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def update(fault_after: float) -> None:
    t0 = time.time()
    while True:
        t = time.time() - t0
        set_float(HR, 100, 420 + 60 * math.sin(t / 60) + random.uniform(-5, 5))
        fault = fault_after > 0 and t > fault_after
        IR[200] = int((2100 if fault else 3500) + random.uniform(-50, 50))
        CO[1] = True
        await asyncio.sleep(2)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--fault-after", type=float, default=0)
    a = ap.parse_args()
    asyncio.create_task(update(a.fault_after))
    server = await asyncio.start_server(serve_client, "0.0.0.0", a.port)
    print(f"modbus simulator listening on :{a.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
