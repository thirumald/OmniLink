"""Connector base class and adapter registry."""

from __future__ import annotations

from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from omnilink_contracts import Command, CommandResult, CommandStatus, DeviceEvent, Quality

from .config import ConnectorConfig


@dataclass
class RawReading:
    point_ref: str
    value: Any
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    quality: Quality = Quality.GOOD


Emit = Callable[[RawReading | DeviceEvent], Awaitable[None]]


class Connector(ABC):
    """Base class every protocol adapter extends.

    Polling adapters implement ``read``; push adapters implement ``subscribe``.
    Adapters that accept commands implement ``execute``.
    """

    protocol: str = "generic"

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.settings: dict[str, Any] = config.settings

    async def connect(self) -> None:  # pragma: no cover - default no-op
        return None

    async def close(self) -> None:  # pragma: no cover
        return None

    async def read(self) -> list[RawReading]:
        return []

    async def subscribe(self, emit: Emit) -> None:
        return None

    async def discover(self) -> list[dict]:
        return []

    async def execute(self, cmd: Command) -> CommandResult:
        return CommandResult(tenant=cmd.tenant, command_id=cmd.command_id, device_id=cmd.device_id,
                             status=CommandStatus.REJECTED, detail=f"{self.protocol} adapter does not support '{cmd.action}'")

    # helpers -------------------------------------------------------------
    def point_for_device(self, device_id: str, attribute: str | None = None):
        for p in self.config.points:
            if p.device_id == device_id and (attribute is None or p.attribute == attribute):
                return p
        return None

    def result(self, cmd: Command, status: CommandStatus, detail: str | None = None) -> CommandResult:
        return CommandResult(tenant=cmd.tenant, command_id=cmd.command_id, device_id=cmd.device_id,
                             status=status, detail=detail)


registry: dict[str, type[Connector]] = {}


def register(type_name: str):
    def deco(cls: type[Connector]) -> type[Connector]:
        registry[type_name] = cls
        cls.protocol = type_name
        return cls

    return deco
