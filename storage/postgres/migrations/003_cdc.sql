-- Logical replication for Debezium CDC → Kafka (devices and alarm rules feed Flink enrichment and rules)
ALTER TABLE devices REPLICA IDENTITY FULL;
ALTER TABLE alarm_rules REPLICA IDENTITY FULL;
ALTER TABLE sites REPLICA IDENTITY FULL;
CREATE PUBLICATION omnilink_cdc FOR TABLE devices, alarm_rules, sites;
