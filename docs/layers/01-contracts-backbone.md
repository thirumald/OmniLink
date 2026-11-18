# Layer 1 — Contracts and Event Backbone

**Purpose.** Define the canonical data contracts every other layer speaks, and run the Kafka backbone that carries them. Nothing downstream ever sees a vendor or protocol format.

## 1. Components

| Component | Tech | Licence | Responsibility |
| --- | --- | --- | --- |
| `omnilink_contracts` | Python 3.12+, Pydantic v2 | Apache 2.0 (ours) | Canonical models, topic catalogue, JSON Schema export |
| Kafka cluster | Apache Kafka 3.9 (KRaft) | Apache 2.0 | Durable event log, replay, partitioned by device |
| Schema registry | Apicurio Registry 3 | Apache 2.0 | Versioned JSON Schemas, BACKWARD compatibility |
| Kafka UI | Kafbat UI | Apache 2.0 | Topic browsing in dev/test |
| Topic provisioner | `backbone/create_topics.py` | ours | Idempotent topic creation from `topics.yaml` |

## 2. Canonical models (v1)

| Model | Key fields | Kafka key |
| --- | --- | --- |
| `TelemetryEvent` | tenant, device_id, entity_id (NGSI-LD URN), entity_type, attribute, value, unit (UCUM), quality, source_ts, ingest_ts, protocol, point_ref | `tenant:device_id` |
| `DeviceEvent` | tenant, device_id, event_type, severity, payload, source_ts | `tenant:device_id` |
| `DeviceHealth` | tenant, device_id, connector_id, status, last_seen, metrics | `tenant:device_id` |
| `RuleHit` | tenant, rule_id, entity_id, attribute, value, threshold, condition, ts | `tenant:rule_id:entity_id` |
| `Alarm` | alarm_id, tenant, rule_id, entity_id, priority (1–4), state (ISA-18.2), timestamps, ack_by | `tenant:alarm_id` |
| `Command` / `CommandResult` | command_id, tenant, device_id, connector_id, action, params, ttl_s, requested_by / status, detail | `tenant:device_id` |

Rules:
- Every message carries `schema_version`, `event_id` (UUIDv4) and UTC ISO-8601 timestamps.
- `entity_id` format: `urn:ngsi-ld:<EntityType>:<tenant>:<local-id>`.
- Units are UCUM codes (`Cel`, `%`, `m`, `kW.h`, `ug/m3`).
- Additive changes only within a major version; breaking change = new topic suffix (`.v2`).

## 3. Topic catalogue

| Topic | Partitions | Retention | Producer → Consumer |
| --- | --- | --- | --- |
| `omnilink.telemetry.v1` | 48 | 7 d | Connectors → Flink enrich |
| `omnilink.telemetry.enriched.v1` | 48 | 3 d | Flink → ClickHouse, live feed, Node-RED |
| `omnilink.events.v1` | 24 | 7 d | Connectors → ClickHouse, workflows |
| `omnilink.health.v1` | 12 | 3 d, compacted | Connectors → alarm-service, VictoriaMetrics |
| `omnilink.rule-hits.v1` | 12 | 3 d | Flink rules → alarm-service |
| `omnilink.alarms.v1` | 12 | 30 d | alarm-service → workflows, outbound, ClickHouse |
| `omnilink.commands.v1` | 12 | 1 d | command-service → connectors |
| `omnilink.command-results.v1` | 12 | 7 d | connectors → command-service |
| `omnilink.cdc.devices.v1` | 6 | compacted | Debezium (PostgreSQL) → Flink |
| `omnilink.cdc.alarm-rules.v1` | 3 | compacted | Debezium (PostgreSQL) → Flink |
| `omnilink.dlq.v1` | 6 | 14 d | any → ops review |

Production settings: replication factor 3, `min.insync.replicas=2`, producers `acks=all`, `enable.idempotence=true`, compression `zstd`.

## 4. Acceptance criteria

- [ ] `make contracts` regenerates JSON Schemas; CI fails if committed schemas drift from models.
- [ ] Schemas register in Apicurio with BACKWARD rule; an incompatible change is rejected.
- [ ] `create_topics.py` is idempotent and applies partition/retention settings from `topics.yaml`.
- [ ] Unit tests cover model validation, key derivation, URN format and round-trip serialisation.
- [ ] 3-broker cluster sustains 500k msg/s (1 KB) with p99 produce latency < 50 ms (load test, phase gate 3).
