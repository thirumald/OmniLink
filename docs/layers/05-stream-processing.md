# Layer 5 — Stream Processing

**Purpose.** Turn canonical telemetry into enriched, rule-checked streams within one second of arrival.

## 1. Jobs (Apache Flink 1.20, Flink SQL)

| Job | Input | Output | Logic |
| --- | --- | --- | --- |
| `01_enrich` | `omnilink.telemetry.v1`, `omnilink.cdc.devices.v1` (upsert) | `omnilink.telemetry.enriched.v1` | Temporal join on (tenant, device_id) adds site path, lat/lon, device name, vendor |
| `02_threshold_rules` | enriched telemetry, `omnilink.cdc.alarm-rules.v1` | `omnilink.rule-hits.v1` | Join rules by entity or entity_type + attribute; emit hit on state change (normal → abnormal and back) with hysteresis |
| `03_quality` | enriched telemetry | `omnilink.events.v1` | Flat-line (no change for N minutes) and out-of-range detection as `data_quality` events |
| `04_live_minute` | enriched telemetry | Valkey + Centrifugo (via relay) | 1-minute averages for dashboards |

Heartbeat-loss (absence) detection runs in the alarm service from `omnilink.health.v1` because absence is easier to express with timers than SQL.

## 2. Operational settings

- Checkpointing every 30 s, exactly-once, RocksDB state backend, checkpoints in S3 (`s3://flink-checkpoints`).
- Watermarks: `source_ts - 30 s` bounded out-of-orderness; late data still written to storage but excluded from rules.
- Parallelism = Kafka partitions (48) for telemetry jobs.
- Kubernetes: Flink Kubernetes Operator (Apache 2.0), one FlinkDeployment per job, savepoint on upgrade.

## 3. Rule semantics

`condition ∈ {gt, gte, lt, lte, eq, ne}`; hit becomes active when the condition is true and clears when it is false beyond `hysteresis`. The Python reference implementation `processing/rules_reference.py` defines the exact semantics and is used in tests; the Flink SQL job must match it (contract test on recorded streams).

## 4. Acceptance criteria

- [ ] p95 device → rule-hit latency < 1 s at 500k msg/s.
- [ ] Job restart from checkpoint produces no duplicate rule hits (dedup by event key downstream).
- [ ] Reference and Flink outputs match on the recorded test stream.
