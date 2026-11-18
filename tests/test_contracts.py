from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from omnilink_contracts import (
    TOPICS,
    Alarm,
    Command,
    RuleHit,
    TelemetryEvent,
    entity_urn,
    parse_urn,
    topic_for,
)
from omnilink_contracts.export_schemas import render
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


def telemetry(**kw):
    base = dict(
        tenant="abudhabi",
        device_id="aq-001",
        entity_id=entity_urn("AirQualityObserved", "abudhabi", "aq-001"),
        entity_type="AirQualityObserved",
        attribute="pm25",
        value=41.5,
        unit="ug/m3",
        source_ts=NOW,
        protocol="mqtt",
        point_ref="city/aq/001/pm25",
    )
    base.update(kw)
    return TelemetryEvent(**base)


def test_urn_round_trip():
    urn = entity_urn("Streetlight", "rak", "sl-0042")
    assert parse_urn(urn) == ("Streetlight", "rak", "sl-0042")
    with pytest.raises(ValueError):
        entity_urn("Streetlight", "RAK UPPER", "x")


def test_telemetry_round_trip_and_key():
    ev = telemetry()
    back = TelemetryEvent.from_bytes(ev.to_bytes())
    assert back == ev
    assert ev.kafka_key() == "abudhabi:aq-001"
    assert topic_for(ev) == "omnilink.telemetry.v1"


def test_telemetry_rejects_bad_input():
    with pytest.raises(ValidationError):
        telemetry(entity_id="not-a-urn")
    with pytest.raises(ValidationError):
        telemetry(attribute="pm 2.5")
    with pytest.raises(ValidationError):
        telemetry(unknown_field=1)


def test_rule_hit_and_alarm_keys():
    hit = RuleHit(tenant="t1", rule_id="r1", entity_id=entity_urn("X", "t1", "a"), attribute="v",
                  value=5, threshold=4, condition="gt", ts=NOW)
    assert hit.kafka_key().startswith("t1:r1:urn:")
    alarm = Alarm(tenant="t1", rule_id="r1", entity_id=hit.entity_id, priority=1, message="high")
    assert alarm.kafka_key() == f"t1:{alarm.alarm_id}"
    with pytest.raises(ValidationError):
        Alarm(tenant="t1", rule_id="r1", entity_id=hit.entity_id, priority=9, message="x")


def test_command_expiry():
    cmd = Command(tenant="t1", device_id="cam-1", connector_id="onvif-1", action="ptz.goto_preset",
                  params={"preset": "2"}, requested_by="op1", requested_at=NOW, ttl_s=30)
    assert not cmd.expired(NOW + timedelta(seconds=10))
    assert cmd.expired(NOW + timedelta(seconds=31))


def test_topics_yaml_matches_catalogue():
    import yaml

    doc = yaml.safe_load((ROOT / "backbone/kafka/topics.yaml").read_text())
    yaml_topics = {t["name"]: t["partitions"] for t in doc["topics"]}
    assert yaml_topics == {name: t.partitions for name, t in TOPICS.items()}


def test_committed_schemas_have_no_drift():
    committed = ROOT / "contracts/schemas"
    for fname, text in render().items():
        assert (committed / fname).read_text() == text, f"{fname} drifted — run make contracts"
