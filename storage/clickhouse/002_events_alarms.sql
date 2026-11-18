CREATE TABLE IF NOT EXISTS omnilink.events
(
    tenant LowCardinality(String), device_id String, entity_id Nullable(String),
    event_type LowCardinality(String), severity LowCardinality(String),
    ts DateTime64(3, 'UTC'), payload String, protocol LowCardinality(String), event_id String
)
ENGINE = MergeTree PARTITION BY (tenant, toYYYYMM(ts)) ORDER BY (tenant, event_type, ts)
TTL toDateTime(ts) + INTERVAL 2 YEAR;

CREATE TABLE IF NOT EXISTS omnilink.events_kafka
(event_id String, tenant String, device_id String, entity_id Nullable(String), event_type String,
 severity String, payload String, source_ts String, protocol String)
ENGINE = Kafka SETTINGS kafka_broker_list = 'kafka:9092', kafka_topic_list = 'omnilink.events.v1',
  kafka_group_name = 'clickhouse-events', kafka_format = 'JSONEachRow',
  input_format_json_read_objects_as_strings = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.events_mv TO omnilink.events AS
SELECT tenant, device_id, entity_id, event_type, severity,
       parseDateTime64BestEffort(source_ts, 3, 'UTC') AS ts, payload, protocol, event_id
FROM omnilink.events_kafka;

CREATE TABLE IF NOT EXISTS omnilink.alarms_history
(
    tenant LowCardinality(String), alarm_id String, rule_id String, entity_id String,
    priority UInt8, state LowCardinality(String), message String,
    updated_at DateTime64(3, 'UTC'), acked_by Nullable(String), last_value Nullable(Float64)
)
ENGINE = MergeTree PARTITION BY (tenant, toYYYYMM(updated_at)) ORDER BY (tenant, alarm_id, updated_at)
TTL toDateTime(updated_at) + INTERVAL 2 YEAR;

CREATE TABLE IF NOT EXISTS omnilink.alarms_kafka
(tenant String, alarm_id String, rule_id String, entity_id String, priority UInt8, state String,
 message String, updated_at String, acked_by Nullable(String), last_value Nullable(Float64))
ENGINE = Kafka SETTINGS kafka_broker_list = 'kafka:9092', kafka_topic_list = 'omnilink.alarms.v1',
  kafka_group_name = 'clickhouse-alarms', kafka_format = 'JSONEachRow', input_format_skip_unknown_fields = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.alarms_mv TO omnilink.alarms_history AS
SELECT tenant, alarm_id, rule_id, entity_id, priority, state, message,
       parseDateTime64BestEffort(updated_at, 3, 'UTC') AS updated_at, acked_by, last_value
FROM omnilink.alarms_kafka;
