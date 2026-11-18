# 05 — Deployment

## Environments

| Environment | How | Purpose |
| --- | --- | --- |
| Developer laptop | `make devstack` (one process, in-memory, demo data) | UI and API development, demos without infrastructure |
| Dev / pilot | `deploy/compose/docker-compose.yml` with profiles per layer | Integration testing, POCs up to ~5,000 devices |
| Test / pre-prod / prod | Kubernetes (RKE2) + Argo CD; operators: Strimzi, CloudNativePG, Altinity ClickHouse operator, Flink Kubernetes Operator, Temporal Helm chart | Production, HA, DR |

## Docker Compose: bring it up layer by layer

```bash
cd deploy/compose && cp .env.example .env    # change every secret
docker compose --profile backbone up -d       # L1 Kafka, Apicurio, topics
docker compose --profile storage up -d        # L4 PostgreSQL, ClickHouse, Valkey, Debezium
docker compose --profile connectivity up -d   # L2/3 RabbitMQ MQTT, uplink bridge, HTTP ingest, sample connector
docker compose --profile processing up -d     # L5 Flink
docker compose --profile services up -d       # L6 asset registry, alarms, commands
docker compose --profile workflow up -d       # L7 Temporal, Node-RED, workflow worker
docker compose --profile api up -d            # L8 APISIX, query API, outbound, Centrifugo
docker compose --profile security --profile observability up -d   # L9
docker compose --profile ai up -d             # L10 assistant + Ollama (CPU)  | --profile ai-gpu for vLLM
docker compose --profile frontend up -d       # L11 console on :4200
```

Then:
1. Register the Debezium connector: `curl -X POST localhost:8083/connectors -H 'content-type: application/json' -d @storage/debezium/postgres-connector.json`
2. Submit the Flink jobs: `docker compose exec flink-jobmanager ./bin/sql-client.sh -f /opt/omnilink/sql/01_enrich.sql` (and `02_threshold_rules.sql`)
3. Register schemas: `python backbone/apicurio/register_schemas.py contracts/schemas`

## Production topology (indicative)

| Tier | Devices | Ingest msg/s | K8s nodes | Notes |
| --- | --- | --- | --- | --- |
| Pilot | ≤ 5,000 | 5k | 6 | single cluster, no DR |
| City | ≤ 100,000 | 100k | 18–24 | 3 AZ/racks, warm DR site |
| National | 1M+ | 500k+ | 50+ multi-cluster | MirrorMaker 2, ClickHouse multi-shard |
| AI add-on | – | – | +1–2 GPU nodes (L40S / A100) | vLLM Qwen2.5-32B AWQ; scale by concurrent users |

Validate sizing with load tests against the client's real device inventory.
