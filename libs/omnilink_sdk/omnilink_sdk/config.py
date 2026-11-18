"""Connector configuration models (loaded from YAML or the asset registry)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PointMap(BaseModel):
    point_ref: str
    device_id: str
    entity_type: str
    attribute: str
    local_id: str | None = None  # defaults to device_id
    unit: str | None = None  # target UCUM unit
    source_unit: str | None = None  # unit the device reports in
    scale: float = 1.0
    offset: float = 0.0
    deadband: float = 0.0  # absolute change needed to publish
    max_silence_s: int = 300  # publish anyway after this long, even inside deadband
    tags: dict[str, str] = Field(default_factory=dict)


class ConnectorConfig(BaseModel):
    connector_id: str
    type: str
    tenant: str
    poll_interval_s: float = 10.0
    command_timeout_s: float = 10.0
    heartbeat_s: float = 30.0
    offline_after_failures: int = 3
    settings: dict[str, Any] = Field(default_factory=dict)
    points: list[PointMap] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ConnectorConfig:
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def point_index(self) -> dict[str, PointMap]:
        return {p.point_ref: p for p in self.points}
