"""Raw reading → canonical TelemetryEvent: scaling, unit conversion, deadband."""

from __future__ import annotations

from datetime import datetime

from omnilink_contracts import Quality, TelemetryEvent, entity_urn

from .config import ConnectorConfig, PointMap

# (from, to) -> f(x). Extend as new device units appear.
_CONVERSIONS = {
    ("degF", "Cel"): lambda x: (x - 32) * 5 / 9,
    ("K", "Cel"): lambda x: x - 273.15,
    ("Cel", "degF"): lambda x: x * 9 / 5 + 32,
    ("W", "kW"): lambda x: x / 1000,
    ("Wh", "kW.h"): lambda x: x / 1000,
    ("mbar", "hPa"): lambda x: x,
    ("Pa", "hPa"): lambda x: x / 100,
    ("km/h", "m/s"): lambda x: x / 3.6,
    ("mph", "km/h"): lambda x: x * 1.609344,
    ("ft", "m"): lambda x: x * 0.3048,
    ("mm", "m"): lambda x: x / 1000,
    ("cm", "m"): lambda x: x / 100,
    ("psi", "kPa"): lambda x: x * 6.894757,
    ("gal/min", "L/s"): lambda x: x * 0.0630902,
}


def convert_unit(value: float, source: str | None, target: str | None) -> float:
    if not source or not target or source == target:
        return value
    try:
        return _CONVERSIONS[(source, target)](value)
    except KeyError as exc:
        raise ValueError(f"no conversion {source} -> {target}") from exc


class Normaliser:
    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.index = config.point_index()
        self._last: dict[str, tuple[float, datetime]] = {}

    def normalise(self, point_ref: str, value, ts: datetime, quality: Quality = Quality.GOOD) -> TelemetryEvent | None:
        """Return a TelemetryEvent, or None if unmapped or suppressed by deadband."""
        pm = self.index.get(point_ref)
        if pm is None:
            return None
        value = self._apply(pm, value)
        if self._suppressed(pm, value, ts, quality):
            return None
        return TelemetryEvent(
            tenant=self.config.tenant,
            device_id=pm.device_id,
            entity_id=entity_urn(pm.entity_type, self.config.tenant, pm.local_id or pm.device_id),
            entity_type=pm.entity_type,
            attribute=pm.attribute,
            value=value,
            unit=pm.unit,
            quality=quality,
            source_ts=ts,
            protocol=self.config.type,
            point_ref=point_ref,
            tags={"connector_id": self.config.connector_id, **pm.tags},
        )

    @staticmethod
    def _apply(pm: PointMap, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        v = value * pm.scale + pm.offset
        v = convert_unit(v, pm.source_unit, pm.unit)
        return round(v, 6)

    def _suppressed(self, pm: PointMap, value, ts: datetime, quality: Quality) -> bool:
        if pm.deadband <= 0 or quality != Quality.GOOD or not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        last = self._last.get(pm.point_ref)
        if last is not None:
            last_v, last_ts = last
            if abs(value - last_v) < pm.deadband and (ts - last_ts).total_seconds() < pm.max_silence_s:
                return True
        self._last[pm.point_ref] = (value, ts)
        return False
