-- Flink SQL: enrich telemetry with device/site context (temporal join on CDC upsert stream)
SET 'execution.checkpointing.interval' = '30s';
SET 'execution.checkpointing.mode' = 'EXACTLY_ONCE';
SET 'pipeline.name' = 'omnilink-01-enrich';

CREATE TABLE telemetry (
  event_id STRING, tenant STRING, device_id STRING, entity_id STRING, entity_type STRING,
  attribute STRING, `value` STRING, unit STRING, quality STRING,
  source_ts TIMESTAMP_LTZ(3), ingest_ts TIMESTAMP_LTZ(3), protocol STRING, point_ref STRING,
  proc_time AS PROCTIME(),
  WATERMARK FOR source_ts AS source_ts - INTERVAL '30' SECOND
) WITH (
  'connector' = 'kafka', 'topic' = 'omnilink.telemetry.v1',
  'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}', 'properties.group.id' = 'flink-enrich',
  'scan.startup.mode' = 'group-offsets', 'properties.auto.offset.reset' = 'earliest',
  'format' = 'json', 'json.timestamp-format.standard' = 'ISO-8601', 'json.ignore-parse-errors' = 'true'
);

CREATE TABLE devices (
  tenant_id STRING, id STRING, name STRING, entity_type STRING, vendor STRING, model STRING,
  site_path STRING, lat DOUBLE, lon DOUBLE,
  PRIMARY KEY (tenant_id, id) NOT ENFORCED
) WITH (
  'connector' = 'upsert-kafka', 'topic' = 'omnilink.cdc.devices.v1',
  'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}',
  'key.format' = 'json', 'value.format' = 'json'
);

CREATE TABLE telemetry_enriched (
  event_id STRING, tenant STRING, device_id STRING, entity_id STRING, entity_type STRING,
  attribute STRING, `value` STRING, unit STRING, quality STRING,
  source_ts STRING, ingest_ts STRING, protocol STRING,
  device_name STRING, vendor STRING, site_path STRING, lat DOUBLE, lon DOUBLE
) WITH (
  'connector' = 'kafka', 'topic' = 'omnilink.telemetry.enriched.v1',
  'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}',
  'key.format' = 'raw', 'key.fields' = 'event_id', 'value.format' = 'json',
  'sink.delivery-guarantee' = 'exactly-once', 'sink.transactional-id-prefix' = 'omnilink-enrich'
);

INSERT INTO telemetry_enriched
SELECT t.event_id, t.tenant, t.device_id, t.entity_id, t.entity_type, t.attribute, t.`value`, t.unit, t.quality,
       DATE_FORMAT(t.source_ts, 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z'''),
       DATE_FORMAT(t.ingest_ts, 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z'''),
       t.protocol, d.name, d.vendor, d.site_path, d.lat, d.lon
FROM telemetry AS t
LEFT JOIN devices FOR SYSTEM_TIME AS OF t.proc_time AS d
  ON t.tenant = d.tenant_id AND t.device_id = d.id;
