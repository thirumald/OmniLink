import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from omnilink_contracts import DeviceHealth, RuleHit, entity_urn
from omnilink_sdk import MemoryPublisher

H_OP = {"x-user": "op1", "x-tenant": "abudhabi", "x-roles": "operator"}
H_SUP = {"x-user": "sup1", "x-tenant": "abudhabi", "x-roles": "supervisor"}
H_VIEW = {"x-user": "v", "x-tenant": "abudhabi", "x-roles": "viewer"}
H_INT = {"x-user": "int", "x-tenant": "abudhabi", "x-roles": "integrator"}
H_OTHER = {"x-user": "x", "x-tenant": "rak", "x-roles": "platform-admin"}
T0 = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
URN = entity_urn("FloodSensor", "abudhabi", "fs-1")


@pytest.fixture(autouse=True)
def dev_auth(monkeypatch):
    monkeypatch.setenv("OMNILINK_AUTH_MODE", "dev")


def test_role_hierarchy():
    from omnilink_services.common import Principal

    sup = Principal("s", "t", {"supervisor"})
    assert sup.has("operator") and sup.has("viewer") and not sup.has("integrator")
    assert Principal("i", "t", {"integrator"}).has("viewer")
    assert not Principal("v", "t", {"viewer"}).has("operator")


# ---------------- asset registry ----------------
def test_asset_registry_crud_geo_and_connector_config():
    from omnilink_services.asset_registry import MemoryAssetRepo, build_app

    with TestClient(build_app(MemoryAssetRepo())) as c:
        for i, (lat, lon) in enumerate([(24.4539, 54.3773), (24.4545, 54.3780), (24.50, 54.50)]):
            r = c.put(f"/v1/devices/cam-{i}", headers=H_INT, json={
                "id": f"cam-{i}", "entity_type": "Camera", "name": f"Cam {i}", "lat": lat, "lon": lon,
                "connector_id": "onvif-1", "attributes": {"ptz": True}})
            assert r.status_code == 200
        near = c.get("/v1/devices", params={"near": "24.4539,54.3773", "radius_m": 300, "type": "Camera"}, headers=H_VIEW)
        assert [d["id"] for d in near.json()] == ["cam-0", "cam-1"]
        assert c.get("/v1/devices/cam-0", headers=H_OTHER).status_code == 404  # tenant isolation
        assert c.put("/v1/devices/x", headers=H_VIEW, json={"id": "x", "entity_type": "C", "name": "x"}).status_code == 403
        ent = c.get(f"/v1/entities/{entity_urn('Camera', 'abudhabi', 'cam-0')}", headers=H_VIEW).json()
        assert ent["location"] == {"lat": 24.4539, "lon": 54.3773}
        c.put("/v1/connectors/onvif-1", headers=H_INT, json={"id": "onvif-1", "type": "onvif"})
        c.post("/v1/connectors/onvif-1/points", headers=H_INT, json=[
            {"point_ref": "cam-0:online", "device_id": "cam-0", "attribute": "online"}])
        cfg = c.get("/v1/connectors/onvif-1/config", headers=H_INT).json()
        assert cfg["points"][0]["entity_type"] == "Camera"
        from omnilink_sdk import ConnectorConfig

        ConnectorConfig.model_validate(cfg)  # registry output feeds connectors directly


# ---------------- alarms ----------------
def hit(active, v=1.8, i=0):
    return RuleHit(tenant="abudhabi", rule_id="flood-high", entity_id=URN, attribute="waterLevel", value=v,
                   threshold=1.5, condition="gt", active=active, ts=T0 + timedelta(seconds=i))


def test_alarm_state_machine():
    from omnilink_services.alarms import AlarmEngine, IllegalTransition

    e = AlarmEngine({"flood-high": {"priority": 1, "message": "Flood level high"}})
    a = e.on_rule_hit(hit(True))
    assert a.state == "active_unack" and a.priority == 1
    a2 = e.on_rule_hit(hit(True, 1.9, 5))
    assert a2.alarm_id == a.alarm_id and a2.occurrences == 2  # no duplicate alarm
    assert e.ack(a.alarm_id, "op1").state == "active_ack"
    with pytest.raises(IllegalTransition):
        e.ack(a.alarm_id, "op1")
    assert e.on_rule_hit(hit(False, 1.2, 10)).state == "cleared"
    b = e.on_rule_hit(hit(True, 2.0, 20))
    assert b.alarm_id != a.alarm_id  # new episode
    assert e.on_rule_hit(hit(False, 1.0, 30)).state == "cleared_unack"
    assert e.ack(b.alarm_id, "op1").state == "cleared"


def test_shelve_and_unshelve():
    from omnilink_services.alarms import AlarmEngine

    e = AlarmEngine()
    a = e.on_rule_hit(hit(True))
    e.shelve(a.alarm_id, "sup", 30)
    assert e.alarms[a.alarm_id].state == "shelved"
    back = e.unshelve_expired(datetime.now(UTC) + timedelta(minutes=31))
    assert back[0].state == "active_unack"


def test_device_offline_alarm_from_health():
    from omnilink_services.alarms import AlarmEngine

    e = AlarmEngine()
    a = e.on_health(DeviceHealth(tenant="abudhabi", device_id="connector:bms-a", connector_id="bms-a", status="offline"))
    assert a.rule_id == "device-offline" and a.priority == 2
    assert e.on_health(DeviceHealth(tenant="abudhabi", device_id="connector:bms-a", connector_id="bms-a",
                                    status="online")).state == "cleared_unack"


def test_alarm_api_permissions_and_events():
    from omnilink_services.alarms import AlarmEngine, build_app

    eng, pub = AlarmEngine(), MemoryPublisher()
    a = eng.on_rule_hit(hit(True))
    with TestClient(build_app(eng, pub)) as c:
        assert c.post(f"/v1/alarms/{a.alarm_id}/ack", headers=H_VIEW).status_code == 403
        assert c.post(f"/v1/alarms/{a.alarm_id}/ack", headers=H_OTHER).status_code == 404
        assert c.post(f"/v1/alarms/{a.alarm_id}/ack", headers=H_OP).json()["state"] == "active_ack"
        assert c.post(f"/v1/alarms/{a.alarm_id}/ack", headers=H_OP).status_code == 409
        assert len(c.get("/v1/alarms", params={"state": "open"}, headers=H_VIEW).json()) == 1
        inc = c.post("/v1/incidents", headers=H_OP, json={"alarm_id": a.alarm_id, "entity_id": URN, "priority": 1,
                                                          "title": "Flood"}).json()
        again = c.post("/v1/incidents", headers=H_OP, json={"alarm_id": a.alarm_id, "entity_id": URN, "priority": 1,
                                                            "title": "Flood"}).json()
        assert inc["incident_id"] == again["incident_id"]
    assert pub.sent[0][0] == "omnilink.alarms.v1"


# ---------------- commands ----------------
def test_commands_dispatch_approval_and_rate_limit(monkeypatch):
    from omnilink_services import commands

    monkeypatch.setattr(commands, "RATE_PER_MIN", 3)
    pub = MemoryPublisher()
    with TestClient(commands.build_app(pub)) as c:
        r = c.post("/v1/devices/cam-1/commands", headers=H_OP, json={
            "connector_id": "onvif-1", "action": "ptz.goto_preset", "params": {"preset": "2"}})
        assert r.status_code == 202 and r.json()["status"] == "sent"
        r = c.post("/v1/devices/ahu-3/commands", headers=H_OP, json={"connector_id": "bms-a", "action": "reboot"})
        cid = r.json()["command"]["command_id"]
        assert r.json()["status"] == "pending" and len(pub.sent) == 1
        assert c.post(f"/v1/commands/{cid}/approve", headers=H_OP).status_code == 403  # operator can't approve
        self_approve = {**H_SUP, "x-user": "op1"}
        assert c.post(f"/v1/commands/{cid}/approve", headers=self_approve).status_code == 403  # four-eyes
        assert c.post(f"/v1/commands/{cid}/approve", headers=H_SUP).json()["status"] == "sent"
        assert len(pub.sent) == 2
        for _ in range(2):
            c.post("/v1/devices/cam-1/commands", headers=H_OP, json={"connector_id": "onvif-1", "action": "ptz.stop"})
        assert c.post("/v1/devices/cam-1/commands", headers=H_OP,
                      json={"connector_id": "onvif-1", "action": "ptz.stop"}).status_code == 429


# ---------------- query api ----------------
def test_query_builder_is_parameterised_and_bounded():
    from omnilink_services.query_api import build_query, parse_time

    now = T0
    sql, params = build_query("abudhabi", URN, "waterLevel", parse_time("-24h", now), now, "1h")
    assert "{entity:String}" in sql and URN not in sql
    assert params["start"] == "2026-11-17 08:00:00"
    with pytest.raises(ValueError):
        build_query("abudhabi", URN, "x'; DROP TABLE t; --", now - timedelta(hours=1), now, "raw")
    with pytest.raises(ValueError):
        build_query("abudhabi", URN, "v", now - timedelta(days=500), now, "raw")
    with pytest.raises(ValueError):
        build_query("abudhabi", "urn:bad", "v", now - timedelta(hours=1), now, "raw")


def test_query_api_calls_clickhouse():
    from omnilink_services.query_api import build_app

    seen = {}

    def handler(req: httpx.Request):
        seen["params"] = dict(req.url.params)
        return httpx.Response(200, json={"data": [{"ts": "2026-11-18 07:00:00", "avg": 1.2}]})

    app = build_app(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with TestClient(app) as c:
        r = c.get("/v1/timeseries", params={"entity_id": URN, "attribute": "waterLevel", "interval": "1h"}, headers=H_VIEW)
        assert r.status_code == 200 and r.json()["points"][0]["avg"] == 1.2
        assert seen["params"]["param_tenant"] == "abudhabi"
        other = entity_urn("FloodSensor", "rak", "fs-1")
        assert c.get("/v1/timeseries", params={"entity_id": other, "attribute": "waterLevel"}, headers=H_VIEW).status_code == 404


# ---------------- outbound ----------------
def test_webhook_signature_vector():
    from omnilink_services.outbound import sign, verify

    sig = sign(b"s3cret-s3cret-s3cret-s3cret", "1763452800", b'{"a":1}')
    assert sig == "sha256=" + __import__("hmac").new(b"s3cret-s3cret-s3cret-s3cret", b'1763452800.{"a":1}',
                                                     "sha256").hexdigest()
    assert verify(b"s3cret-s3cret-s3cret-s3cret", "1763452800", b'{"a":1}', sig, now=1763452800 + 10)
    assert not verify(b"s3cret-s3cret-s3cret-s3cret", "1763452800", b'{"a":1}', sig, now=1763452800 + 1000)


def test_webhook_fanout_filters_and_retries():
    from omnilink_services.outbound import build_app

    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        return httpx.Response(503 if len(calls) == 1 else 200)

    app = build_app(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def nosleep(_):
        return None

    app.state.dispatcher.sleep = nosleep
    with TestClient(app) as c:
        c.post("/v1/webhooks", headers=H_INT, json={"name": "cd", "url": "https://partner.example/hook",
                                                    "secret": "x" * 32, "topics": ["omnilink.alarms.v1"],
                                                    "filter": {"min_priority": 2}})
    low = json.dumps({"tenant": "abudhabi", "priority": 4}).encode()
    high = json.dumps({"tenant": "abudhabi", "priority": 1, "entity_id": URN}).encode()
    assert asyncio.run(app.state.fan_out("omnilink.alarms.v1", low)) == 0
    assert asyncio.run(app.state.fan_out("omnilink.alarms.v1", high)) == 1
    assert len(calls) == 2 and calls[1].headers["X-OmniLink-Signature"].startswith("sha256=")


def test_notify_uses_directory():
    from omnilink_services.outbound import Notifier, build_app

    sent = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)))
    notifier = Notifier(client, {"abudhabi:duty-officers": [{"name": "A", "phone": "+97150", "push_topic": "a"}]})
    with TestClient(build_app(client, notifier)) as c:
        r = c.post("/v1/notify", headers=H_OP, json={"group": "duty-officers", "channels": ["sms", "push"],
                                                     "subject": "Flood", "body": "Level 1.8 m"})
        assert r.json() == {"sent": 2}


# ---------------- workflow trigger ----------------
def test_workflow_trigger_decisions():
    from omnilink_contracts import Alarm
    from omnilink_workflows.policy import EscalationPolicy
    from omnilink_workflows.worker import decide, workflow_id

    a = Alarm(tenant="abudhabi", rule_id="flood-high", entity_id=URN, priority=1, message="m")
    assert decide(a) == "start" and workflow_id(a).startswith("incident-abudhabi-")
    assert decide(a.model_copy(update={"occurrences": 2})) is None  # repeat hit, no second incident
    assert decide(a.model_copy(update={"priority": 4})) is None
    assert decide(a.model_copy(update={"state": "active_ack", "acked_by": "op1"})) == "ack"
    assert decide(a.model_copy(update={"state": "cleared"})) == "clear"
    assert len(EscalationPolicy.for_priority(1).levels) == 3
