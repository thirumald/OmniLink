import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from omnilink_contracts import Command, CommandStatus, DeviceHealth, TelemetryEvent
from omnilink_sdk import (
    BufferedPublisher,
    Connector,
    ConnectorConfig,
    MemoryPublisher,
    Normaliser,
    RawReading,
    StoreForwardBuffer,
    convert_unit,
)
from omnilink_sdk.runner import ConnectorRunner

T0 = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)

CFG = ConnectorConfig.model_validate({
    "connector_id": "bms-a", "type": "bacnet", "tenant": "abudhabi", "offline_after_failures": 2,
    "points": [
        {"point_ref": "analogInput:3:presentValue", "device_id": "ahu-03", "entity_type": "AirHandlingUnit",
         "attribute": "supplyAirTemperature", "unit": "Cel", "source_unit": "degF", "deadband": 0.5},
        {"point_ref": "hr:200:uint16", "device_id": "pump-1", "entity_type": "WaterPump",
         "attribute": "pressure", "unit": "kPa", "scale": 0.1},
    ],
})


def run(coro):
    return asyncio.run(coro)


def test_unit_conversion():
    assert convert_unit(212, "degF", "Cel") == pytest.approx(100)
    assert convert_unit(5, "Cel", "Cel") == 5
    with pytest.raises(ValueError):
        convert_unit(1, "furlong", "m")


def test_normaliser_scale_unit_deadband():
    n = Normaliser(CFG)
    ev = n.normalise("analogInput:3:presentValue", 68.0, T0)
    assert ev.value == pytest.approx(20.0) and ev.unit == "Cel"
    assert ev.entity_id == "urn:ngsi-ld:AirHandlingUnit:abudhabi:ahu-03"
    assert n.normalise("analogInput:3:presentValue", 68.5, T0 + timedelta(seconds=10)) is None  # 0.28 C < deadband
    assert n.normalise("analogInput:3:presentValue", 70.0, T0 + timedelta(seconds=20)) is not None
    assert n.normalise("analogInput:3:presentValue", 70.0, T0 + timedelta(seconds=400)) is not None  # max silence
    assert n.normalise("hr:200:uint16", 1013, T0).value == pytest.approx(101.3)
    assert n.normalise("unmapped", 1, T0) is None


def test_buffer_preserves_order_and_survives_reopen(tmp_path):
    db = tmp_path / "buf.db"
    b = StoreForwardBuffer(db)
    for i in range(5):
        b.put("t", b"k", str(i).encode())
    b2 = StoreForwardBuffer(db)
    rows = b2.peek()
    assert [r[3] for r in rows] == [b"0", b"1", b"2", b"3", b"4"]
    b2.ack(rows[1][0])
    assert len(b2) == 3


def test_buffered_publisher_outage_and_replay():
    async def go():
        up = MemoryPublisher(fail=True)
        bp = BufferedPublisher(up, StoreForwardBuffer())
        for i in range(3):
            await bp.send("t", b"k", str(i).encode())
        assert len(bp.buffer) == 3 and up.sent == []
        up.fail = False
        await bp.send("t", b"k", b"3")  # queues behind backlog to keep order
        assert await bp.drain_once() == 4
        assert [v for _, _, v in up.sent] == [b"0", b"1", b"2", b"3"]
    run(go())


class FakeConnector(Connector):
    protocol = "bacnet"

    def __init__(self, cfg, fail=False):
        super().__init__(cfg)
        self.fail = fail

    async def read(self):
        if self.fail:
            raise TimeoutError("device unreachable")
        return [RawReading("analogInput:3:presentValue", 77.0, T0)]

    async def execute(self, cmd):
        return self.result(cmd, CommandStatus.ACKED, "ok")


def test_runner_publishes_canonical_and_tracks_health():
    async def go():
        pub = MemoryPublisher()
        c = FakeConnector(CFG)
        r = ConnectorRunner(c, pub)
        assert await r.poll_once() == 1
        topic, key, value = pub.sent[0]
        assert topic == "omnilink.telemetry.v1" and key == b"abudhabi:ahu-03"
        assert TelemetryEvent.from_bytes(value).value == pytest.approx(25.0)
        c.fail = True
        await r.poll_once()
        assert r.health().status == "degraded"
        await r.poll_once()
        h = r.health()
        assert isinstance(h, DeviceHealth) and h.status == "offline"
    run(go())


def test_runner_commands_expiry_and_routing():
    async def go():
        pub = MemoryPublisher()
        r = ConnectorRunner(FakeConnector(CFG), pub)
        other = Command(tenant="abudhabi", device_id="ahu-03", connector_id="someone-else", action="write_point",
                        requested_by="op")
        await r.handle_command(other)
        assert pub.sent == []
        old = Command(tenant="abudhabi", device_id="ahu-03", connector_id="bms-a", action="write_point",
                      requested_by="op", requested_at=datetime.now(UTC) - timedelta(minutes=5), ttl_s=30)
        await r.handle_command(old)
        ok = Command(tenant="abudhabi", device_id="ahu-03", connector_id="bms-a", action="write_point",
                     params={"value": 21}, requested_by="op")
        await r.handle_command(ok)
        statuses = [__import__("json").loads(v)["status"] for _, _, v in pub.sent]
        assert statuses == ["expired", "acked"]
    run(go())


def test_modbus_codec_round_trip():
    from adapters.modbus_adapter import decode, encode, parse_ref

    for ref_s, value in [("hr:1:float32", 12.5), ("hr:1:float32:le", -3.25), ("hr:1:int32", -70000),
                         ("hr:1:uint16", 65535), ("hr:1:float64", 1.0e10)]:
        ref = parse_ref(ref_s)
        assert decode(encode(value, ref), ref) == pytest.approx(value)
    with pytest.raises(ValueError):
        parse_ref("xx:1:float32")


def test_bacnet_ref_parsing():
    from adapters.bacnet_adapter import parse_ref

    ref = parse_ref("analogInput:3:presentValue")
    assert ref.object_id == "analogInput,3"
    assert parse_ref("binaryValue:7").prop == "presentValue"
    with pytest.raises(ValueError):
        parse_ref("bogus:1")


def test_mqtt_extraction_and_wildcards():
    from adapters.mqtt_adapter import extract, topic_matches

    assert topic_matches("city/+/001", "city/aq/001")
    assert topic_matches("city/#", "city/aq/001/x")
    assert not topic_matches("city/+/001", "city/aq/002")
    refs = ["city/aq/001#$.pm25", "city/aq/001#$.meta.sensors[1].v", "city/aq/002#$.pm25"]
    out = extract(refs, "city/aq/001", b'{"pm25": 41, "ts": "2026-11-18T08:00:00Z", "meta": {"sensors": [{"v":1},{"v":2}]}}')
    assert [(r.point_ref, r.value) for r in out] == [(refs[0], 41), (refs[1], 2)]
    assert out[0].ts == T0


def test_onvif_event_mapping():
    from adapters.onvif_adapter import map_event

    assert map_event("tns1:RuleEngine/FieldDetector/ObjectsInside", {})[0] == "intrusion"
    assert map_event("tns1:Unknown/Thing", {})[0] == "onvif_event"


def test_http_ingest_maps_and_rejects():
    from http_ingest.app import SourceMap, create_app

    pub = MemoryPublisher()
    sources = {"weather": SourceMap.model_validate({
        "tenant": "abudhabi", "entity_type": "WeatherObserved", "device_field": "station_id",
        "ts_field": "observed_at", "fields": {"temp_c": {"attribute": "temperature", "unit": "Cel"},
                                              "wind_kmh": {"attribute": "windSpeed", "unit": "m/s", "scale": 0.25}}})}
    with TestClient(create_app(sources, pub)) as client:
        r = client.post("/v1/ingest/weather", json=[
            {"station_id": "st-1", "observed_at": "2026-11-18T08:00:00Z", "temp_c": 29.5, "wind_kmh": 20},
            {"temp_c": 30},
        ])
        assert r.status_code == 202
        assert r.json()["accepted"] == 2 and r.json()["rejected"][0]["index"] == 1
        assert client.post("/v1/ingest/nope", json={}).status_code == 404
        r = client.post("/v1/ingest/weather/events", json={"device_id": "st-1", "event_type": "sensor_fault"})
        assert r.status_code == 202
    assert TelemetryEvent.from_bytes(pub.sent[1][2]).value == 5.0
    assert pub.sent[2][0] == "omnilink.events.v1"
