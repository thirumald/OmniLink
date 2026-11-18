-- OmniLink telemetry store (ClickHouse 24.8 LTS). Single-node dev: drop ON CLUSTER and Replicated*.
CREATE DATABASE IF NOT EXISTS omnilink;

-- 1. Raw telemetry ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS omnilink.telemetry
(
    tenant        LowCardinality(String),
    entity_id     String,
    entity_type   LowCardinality(String),
    attribute     LowCardinality(String),
    device_id     String,
    ts            DateTime64(3, 'UTC'),
    ingest_ts     DateTime64(3, 'UTC'),
    value_num     Nullable(Float64),
    value_str     Nullable(String),
    unit          LowCardinality(Nullable(String)),
    quality       Enum8('good' = 1, 'uncertain' = 2, 'bad' = 3),
    protocol      LowCardinality(String),
    site_path     String DEFAULT '',          -- from Flink enrichment (ltree path)
    lat           Nullable(Float64),
    lon           Nullable(Float64),
    event_id      UUID
)
ENGINE = ReplacingMergeTree(ingest_ts)        -- dedupes replays on (order key, event_id)
PARTITION BY (tenant, toYYYYMM(ts))
ORDER BY (tenant, entity_id, attribute, ts, event_id)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- 2. Kafka consumer (enriched stream from Flink) -----------------------------------------
CREATE TABLE IF NOT EXISTS omnilink.telemetry_kafka
(
    event_id String, tenant String, device_id String, entity_id String, entity_type String,
    attribute String, value String, unit Nullable(String), quality String,
    source_ts String, ingest_ts String, protocol String,
    site_path Nullable(String), lat Nullable(Float64), lon Nullable(Float64)
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'omnilink.telemetry.enriched.v1',
         kafka_group_name = 'clickhouse-telemetry',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 4,
         kafka_handle_error_mode = 'stream',
         input_format_skip_unknown_fields = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.telemetry_mv TO omnilink.telemetry AS
SELECT
    tenant, entity_id, entity_type, attribute, device_id,
    parseDateTime64BestEffort(source_ts, 3, 'UTC') AS ts,
    parseDateTime64BestEffort(ingest_ts, 3, 'UTC') AS ingest_ts,
    toFloat64OrNull(value)                         AS value_num,
    if(isNull(toFloat64OrNull(value)), value, NULL) AS value_str,
    unit,
    CAST(quality, 'Enum8(\'good\' = 1, \'uncertain\' = 2, \'bad\' = 3)') AS quality,
    protocol, ifNull(site_path, '') AS site_path, lat, lon,
    toUUIDOrZero(event_id) AS event_id
FROM omnilink.telemetry_kafka
WHERE length(_error) = 0;

CREATE TABLE IF NOT EXISTS omnilink.kafka_errors
(topic String, offset UInt64, raw String, error String, at DateTime DEFAULT now())
ENGINE = MergeTree ORDER BY at TTL at + INTERVAL 14 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.telemetry_errors_mv TO omnilink.kafka_errors AS
SELECT _topic AS topic, _offset AS offset, _raw_message AS raw, _error AS error
FROM omnilink.telemetry_kafka WHERE length(_error) > 0;

-- 3. Rollups ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS omnilink.telemetry_1m
(
    tenant LowCardinality(String), entity_id String, attribute LowCardinality(String),
    bucket DateTime('UTC'),
    v_min SimpleAggregateFunction(min, Float64),
    v_max SimpleAggregateFunction(max, Float64),
    v_sum SimpleAggregateFunction(sum, Float64),
    v_cnt SimpleAggregateFunction(sum, UInt64),
    v_last AggregateFunction(argMax, Float64, DateTime64(3, 'UTC'))
)
ENGINE = AggregatingMergeTree
PARTITION BY (tenant, toYYYYMM(bucket))
ORDER BY (tenant, entity_id, attribute, bucket)
TTL bucket + INTERVAL 1 YEAR;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.telemetry_1m_mv TO omnilink.telemetry_1m AS
SELECT tenant, entity_id, attribute, toStartOfMinute(ts) AS bucket,
       min(value_num) AS v_min, max(value_num) AS v_max, sum(value_num) AS v_sum, count() AS v_cnt,
       argMaxState(value_num, ts) AS v_last
FROM omnilink.telemetry WHERE value_num IS NOT NULL AND quality = 'good'
GROUP BY tenant, entity_id, attribute, bucket;

CREATE TABLE IF NOT EXISTS omnilink.telemetry_1h AS omnilink.telemetry_1m
ENGINE = AggregatingMergeTree PARTITION BY (tenant, toYear(bucket))
ORDER BY (tenant, entity_id, attribute, bucket) TTL bucket + INTERVAL 5 YEAR;

CREATE MATERIALIZED VIEW IF NOT EXISTS omnilink.telemetry_1h_mv TO omnilink.telemetry_1h AS
SELECT tenant, entity_id, attribute, toStartOfHour(ts) AS bucket,
       min(value_num) AS v_min, max(value_num) AS v_max, sum(value_num) AS v_sum, count() AS v_cnt,
       argMaxState(value_num, ts) AS v_last
FROM omnilink.telemetry WHERE value_num IS NOT NULL AND quality = 'good'
GROUP BY tenant, entity_id, attribute, bucket;
