-- Flink SQL: threshold rules with hysteresis → rule hits on state change only.
SET 'execution.checkpointing.interval' = '30s';
SET 'pipeline.name' = 'omnilink-02-threshold-rules';

CREATE TABLE enriched (
  tenant STRING, entity_id STRING, entity_type STRING, attribute STRING, `value` STRING, quality STRING,
  source_ts STRING, ts AS TO_TIMESTAMP_LTZ(UNIX_TIMESTAMP(source_ts, 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z''') * 1000, 3),
  proc_time AS PROCTIME(),
  WATERMARK FOR ts AS ts - INTERVAL '30' SECOND
) WITH ('connector' = 'kafka', 'topic' = 'omnilink.telemetry.enriched.v1',
        'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}', 'properties.group.id' = 'flink-rules',
        'scan.startup.mode' = 'group-offsets', 'properties.auto.offset.reset' = 'latest', 'format' = 'json');

CREATE TABLE rules (
  id STRING, tenant_id STRING, entity_type STRING, entity_id STRING, attribute STRING,
  `condition` STRING, threshold DOUBLE, hysteresis DOUBLE, enabled BOOLEAN,
  PRIMARY KEY (id) NOT ENFORCED
) WITH ('connector' = 'upsert-kafka', 'topic' = 'omnilink.cdc.alarm-rules.v1',
        'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}', 'key.format' = 'json', 'value.format' = 'json');

CREATE TABLE rule_hits (
  schema_version STRING, event_id STRING, tenant STRING, rule_id STRING, entity_id STRING, attribute STRING,
  `value` DOUBLE, threshold DOUBLE, `condition` STRING, active BOOLEAN, ts STRING
) WITH ('connector' = 'kafka', 'topic' = 'omnilink.rule-hits.v1',
        'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}', 'format' = 'json');

-- evaluate every reading against matching rules
CREATE TEMPORARY VIEW evaluated AS
SELECT e.tenant, r.id AS rule_id, e.entity_id, e.attribute, CAST(e.`value` AS DOUBLE) AS v,
       r.threshold, r.hysteresis, r.`condition`, e.ts,
       CASE r.`condition`
         WHEN 'gt'  THEN CAST(e.`value` AS DOUBLE) >  r.threshold
         WHEN 'gte' THEN CAST(e.`value` AS DOUBLE) >= r.threshold
         WHEN 'lt'  THEN CAST(e.`value` AS DOUBLE) <  r.threshold
         WHEN 'lte' THEN CAST(e.`value` AS DOUBLE) <= r.threshold
         WHEN 'eq'  THEN CAST(e.`value` AS DOUBLE) =  r.threshold
         WHEN 'ne'  THEN CAST(e.`value` AS DOUBLE) <> r.threshold END AS breach,
       CASE r.`condition`
         WHEN 'gt'  THEN CAST(e.`value` AS DOUBLE) <= r.threshold - r.hysteresis
         WHEN 'gte' THEN CAST(e.`value` AS DOUBLE) <  r.threshold - r.hysteresis
         WHEN 'lt'  THEN CAST(e.`value` AS DOUBLE) >= r.threshold + r.hysteresis
         WHEN 'lte' THEN CAST(e.`value` AS DOUBLE) >  r.threshold + r.hysteresis
         ELSE NOT (CASE r.`condition` WHEN 'eq' THEN CAST(e.`value` AS DOUBLE) = r.threshold
                                      ELSE CAST(e.`value` AS DOUBLE) <> r.threshold END) END AS normal
FROM enriched AS e
JOIN rules FOR SYSTEM_TIME AS OF e.proc_time AS r
  ON e.tenant = r.tenant_id AND e.attribute = r.attribute
 AND (r.entity_id = e.entity_id OR (r.entity_id IS NULL AND r.entity_type = e.entity_type))
WHERE r.enabled AND e.quality = 'good' AND TRY_CAST(e.`value` AS DOUBLE) IS NOT NULL;

-- Readings inside the hysteresis band are neither breach nor normal: drop them so consecutive
-- rows alternate only between real states, then emit a hit whenever the state flips.
CREATE TEMPORARY VIEW states AS
SELECT * FROM evaluated WHERE breach OR normal;

INSERT INTO rule_hits
SELECT '1.0', UUID(), tenant, rule_id, entity_id, attribute, v, threshold, `condition`, active,
       DATE_FORMAT(ts, 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z''')
FROM states
MATCH_RECOGNIZE (
  PARTITION BY tenant, rule_id, entity_id
  ORDER BY ts
  MEASURES B.attribute AS attribute, B.v AS v, B.threshold AS threshold,
           B.`condition` AS `condition`, B.ts AS ts, B.breach AS active
  ONE ROW PER MATCH
  AFTER MATCH SKIP TO LAST B
  PATTERN (A B)
  DEFINE B AS B.breach <> A.breach
);
