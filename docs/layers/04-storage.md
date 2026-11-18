# Layer 4 — Data Storage

**Purpose.** Persist every data class in the store built for it, with retention set per data class.

## 1. Stores

| Data class | Store | Schema location | Retention |
| --- | --- | --- | --- |
| Telemetry (raw) | ClickHouse `telemetry` (ReplicatedMergeTree) | `storage/clickhouse/001_telemetry.sql` | 90 days (TTL) |
| Telemetry rollups 1 min / 1 h / 1 day | ClickHouse AggregatingMergeTree + materialised views | same | 1 year / 5 years / 10 years |
| Device events, alarms history | ClickHouse `events`, `alarms_history` | `002_events_alarms.sql` | 2 years |
| Assets, devices, points, connectors, rules, alarms (current), commands, audit | PostgreSQL 16 + PostGIS + ltree | `storage/postgres/migrations/` | life of record; audit 7 years |
| Live state cache | Valkey | key `state:<entity_id>:<attr>` | TTL 1 h |
| Platform metrics | VictoriaMetrics | Prometheus remote write | 13 months |
| Files, snapshots, evidence | Ceph RGW / SeaweedFS (S3) | buckets `evidence` (object lock), `exports`, `snapshots` | policy |
| Embeddings for AI assistant | PostgreSQL + pgvector | `004_ai.sql` | life of document |

## 2. Ingestion into ClickHouse

ClickHouse consumes Kafka directly (Kafka table engine → materialised view → MergeTree). No extra sink service, exactly the fields in the canonical model. Bad rows go to `kafka_errors` via `kafka_handle_error_mode='stream'`.

## 3. Relational model (PostgreSQL)

`tenants` → `sites` (PostGIS point/polygon, `ltree` path city.district.site.building.floor.zone) → `devices` → `points`; `connectors` own points; `alarm_rules`, `alarms`, `commands`, `audit_log` (append-only, hash-chained), `webhook_subscriptions`. Row-level security on `tenant_id` for every table.

## 4. Acceptance criteria

- [ ] Insert 500k rows/s on a 3-shard × 2-replica ClickHouse cluster.
- [ ] Last-24-h query for one entity/attribute < 300 ms; 1-year hourly rollup < 3 s.
- [ ] RLS prevents cross-tenant reads (test with two tenant roles).
- [ ] Audit log tamper detection: altering a row breaks the hash chain check.
