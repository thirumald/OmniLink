# Layer 2 — Connectivity (Connector SDK and Protocol Adapters)

**Purpose.** Turn any device or external system into canonical events, and carry commands back to it. Protocol knowledge lives only here.

## 1. Components

| Component | Tech | Responsibility |
| --- | --- | --- |
| `omnilink_sdk` | Python 3.12 asyncio | Connector base class, point mapping, normaliser, publishers, store-and-forward buffer, runner, metrics |
| Protocol adapters | one container each | MQTT, Modbus TCP, BACnet/IP, OPC UA, ONVIF, SNMP, HTTP/webhook ingest (wave 1); LoRaWAN via ChirpStack MQTT, NTCIP via SNMP, OCPP via CitrineOS webhooks (wave 2) |
| Core MQTT broker | RabbitMQ 4 native MQTT 5 (MPL 2.0) | Device-facing MQTT for the core; edge uses NanoMQ |
| HTTP ingest | FastAPI behind APISIX | Inbound REST/webhooks from external systems |

## 2. Connector contract

```python
class Connector(ABC):
    async def connect(self) -> None
    async def close(self) -> None
    async def read(self) -> list[RawReading]          # polling adapters
    async def subscribe(self, emit) -> None            # push adapters (MQTT, ONVIF events)
    async def execute(self, cmd: Command) -> CommandResult
    async def discover(self) -> list[dict]             # optional
```

`RawReading(point_ref, value, ts, quality)` is the only thing an adapter produces. The SDK does the rest:

1. **Point map** (`points:` in connector YAML) maps `point_ref` → device, entity, attribute, unit, scale, offset, deadband.
2. **Normaliser** applies scale/offset, unit conversion to UCUM, deadband suppression, quality propagation → `TelemetryEvent`.
3. **Publisher** sends to Kafka (core) or MQTT (edge); wrapped by **BufferedPublisher** (SQLite, 72 h) when the uplink fails.
4. **Runner** drives poll loops, push subscriptions, command consumption, health heartbeats and Prometheus metrics.

## 3. Point reference formats

| Protocol | `point_ref` example | Meaning |
| --- | --- | --- |
| MQTT | `city/aq/001#$.pm25` | topic + JSONPath-lite key |
| Modbus | `hr:100:float32:be` | holding register 100, float32, big-endian word order |
| BACnet | `analogInput:3:presentValue` | object type : instance : property |
| OPC UA | `ns=2;s=Pump1.Flow` | node id |
| SNMP | `1.3.6.1.2.1.1.3.0` | OID |
| ONVIF | `event:tns1:VideoSource/MotionAlarm` | event topic |
| HTTP | `source:<name>:<field>` | inbound JSON field |

## 4. Commands supported (wave 1)

| Adapter | Actions |
| --- | --- |
| Modbus | `write_point` (register/coil) |
| BACnet | `write_point` (priority array, default 8), `relinquish` |
| OPC UA | `write_point`, `call_method` |
| ONVIF | `ptz.goto_preset`, `ptz.move`, `ptz.stop`, `snapshot` |
| SNMP | `set` (v3 only in production) |
| MQTT | `publish` to mapped command topic |

Every command is checked for expiry (`ttl_s`), executed with a timeout, and answered with a `CommandResult`.

## 5. Configuration (example)

```yaml
connector_id: bms-tower-a
type: bacnet
tenant: abudhabi
poll_interval_s: 10
settings: { address: 10.20.1.15/24, device_instance: 1201 }
points:
  - point_ref: analogInput:3:presentValue
    device_id: ahu-03
    entity_type: AirHandlingUnit
    attribute: supplyAirTemperature
    unit: Cel
    source_unit: degF
    deadband: 0.2
```

## 6. Acceptance criteria

- [ ] Each adapter passes the SDK contract test suite against its simulator.
- [ ] Unit conversion, scaling and deadband covered by unit tests.
- [ ] Uplink outage of 1 hour loses zero readings; replay preserves order.
- [ ] Health heartbeat every 30 s; device marked offline after 3 missed reads.
- [ ] One adapter process handles ≥ 5,000 points at 10 s polling.
