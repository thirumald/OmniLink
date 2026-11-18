import asyncio
import struct
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/simulators")]

from keycloak_setup import CLIENT_SECRETS, read_env  # noqa: E402
from onboard import load_site  # noqa: E402
from render_template import render  # noqa: E402


def test_site_files_validate():
    s = load_site(ROOT / "sites/pilot-simulators.yaml")
    assert len(s.devices) == 2 and {r.id for r in s.rules} == {"pm25-high", "pump-pressure-low"}
    assert s.connectors[0].settings["password"] == "${MQTT_PASSWORD}"  # secrets stay references
    load_site(ROOT / "sites/template-real-devices.yaml")


@pytest.mark.parametrize("mutate,err", [
    (lambda d: d["devices"][0].update(connector="nope"), "unknown connector"),
    (lambda d: d["connectors"][0].update(type="carrier-pigeon"), "unknown type"),
    (lambda d: d["devices"][1]["points"].append(dict(d["devices"][1]["points"][0])), "duplicate point_ref"),
    (lambda d: d["devices"][1]["points"][0].update(source_unit="furlong"), "no unit conversion"),
    (lambda d: d["rules"][0].update(entity_type="Volcano"), "no device of type"),
])
def test_site_validation_errors(tmp_path, mutate, err):
    d = yaml.safe_load((ROOT / "sites/pilot-simulators.yaml").read_text())
    mutate(d)
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ValueError, match=err):
        load_site(p)


def test_render_template_and_env(tmp_path):
    assert render("a=${X} b=${Y}", {"X": "1", "Y": "2"}) == "a=1 b=2"
    with pytest.raises(KeyError, match="MISSING"):
        render("${MISSING}", {})
    env = read_env(ROOT / "deploy/compose/.env.example")
    assert all(v in env for v in CLIENT_SECRETS.values()), "every Keycloak client secret must be in .env.example"
    deb = render((ROOT / "storage/debezium/postgres-connector.json").read_text(), env)
    assert "omnilink.cdc.alarm-rules.v1" in deb and "${" not in deb


def test_flink_sql_renders_and_compose_env_covers_placeholders():
    for f in (ROOT / "processing/flink/sql").glob("*.sql"):
        assert "${" not in render(f.read_text(), {"KAFKA_BOOTSTRAP": "kafka:9092"})
    compose = (ROOT / "deploy/compose/docker-compose.yml").read_text()
    env = read_env(ROOT / "deploy/compose/.env.example")
    import re

    used = {m for m in re.findall(r"\$\{([A-Z0-9_]+)(?::-[^}]*)?\}", compose)}
    assert used <= set(env), f"missing in .env.example: {used - set(env)}"


def test_modbus_simulator_speaks_modbus():
    import modbus_sim

    modbus_sim.set_float(modbus_sim.HR, 100, 12.5)
    resp = modbus_sim.handle_pdu(struct.pack(">BHH", 3, 100, 2))
    assert resp[:2] == bytes([3, 4]) and struct.unpack(">f", resp[2:6])[0] == 12.5
    assert modbus_sim.handle_pdu(struct.pack(">BHH", 3, 5000, 2))[0] == 0x83  # illegal address
    assert modbus_sim.handle_pdu(bytes([0x2B, 0, 0]))[0] == 0xAB  # illegal function
    modbus_sim.handle_pdu(struct.pack(">BHHB", 16, 10, 2, 4) + struct.pack(">HH", 7, 9))
    assert modbus_sim.HR[10:12] == [7, 9]


def test_modbus_adapter_against_simulator():
    import modbus_sim

    pytest.importorskip("pymodbus")
    import adapters.modbus_adapter  # noqa: F401
    from omnilink_contracts import TelemetryEvent
    from omnilink_sdk import ConnectorConfig, MemoryPublisher, registry
    from omnilink_sdk.runner import ConnectorRunner

    async def go():
        modbus_sim.set_float(modbus_sim.HR, 100, 100.0)  # gal/min
        modbus_sim.IR[200] = 3500
        modbus_sim.CO[1] = True
        server = await asyncio.start_server(modbus_sim.serve_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        cfg = ConnectorConfig.from_yaml(ROOT / "connectors/examples/modbus-sim.yaml")
        cfg.settings.update(host="127.0.0.1", port=port)
        c = registry["modbus"](cfg)
        await c.connect()
        pub = MemoryPublisher()
        assert await ConnectorRunner(c, pub).poll_once() == 3
        await c.close()
        server.close()
        return {e.attribute: e.value for e in (TelemetryEvent.from_bytes(v) for *_, v in pub.sent)}

    vals = asyncio.run(go())
    assert vals["flowRate"] == pytest.approx(6.30902, rel=1e-4)  # 100 gal/min -> L/s
    assert vals["pressure"] == pytest.approx(350.0) and vals["running"] is True
