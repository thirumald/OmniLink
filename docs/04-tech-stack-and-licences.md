# 04 — Tech stack and licences

**Policy:** only OSI-approved licences (Apache 2.0, MIT, BSD, MPL 2.0, EPL 2.0, LGPL; GPL/AGPL as unmodified separate services). Source-available licences (BSL, SSPL, SUL "fair-code", RSAL, Elastic, Timescale, Confluent Community) are excluded. Licences change, so re-verify at each release and keep an SBOM.

## Stack by layer

| Layer | Component | Licence | Licensed commercial alternative |
| --- | --- | --- | --- |
| 1 Backbone | Apache Kafka (KRaft), Apicurio Registry, Kafbat UI | Apache 2.0 | Confluent Platform, Redpanda Enterprise, Solace PubSub+ |
| 2 Connectivity | Connector SDK (ours), pymodbus, bacpypes3, asyncua, onvif-zeep-async, pysnmp, paho-mqtt | BSD / MIT / LGPL / EPL | Kepware KEPServerEX, Cogent DataHub, Litmus Edge |
| 2 MQTT broker | RabbitMQ 4 (native MQTT 5); NanoMQ at the edge | MPL 2.0 / MIT | HiveMQ Enterprise, EMQX Enterprise (EMQX moved to BSL) |
| 2 LoRaWAN | ChirpStack | MIT | The Things Industries, Actility |
| 3 Edge | K3s, NanoMQ, Node-RED | Apache 2.0 / MIT | AWS IoT Greengrass, Azure IoT Edge |
| 4 Storage | ClickHouse, PostgreSQL + PostGIS, Valkey, Ceph / SeaweedFS, Debezium | Apache 2.0 / PostgreSQL / GPL 2 / BSD / LGPL | AVEVA PI, InfluxDB Enterprise, Oracle Spatial, Redis Enterprise |
| 5 Processing | Apache Flink (+ Kubernetes Operator) | Apache 2.0 | Confluent Flink, Ververica Platform |
| 6 Services | FastAPI, Pydantic, asyncpg | MIT / Apache 2.0 | – |
| 7 Workflow | Node-RED, Temporal, (Activepieces CE optional) | Apache 2.0 / MIT / MIT | n8n Enterprise, Camunda 8, Power Automate |
| 8 API | Apache APISIX, Centrifugo | Apache 2.0 | Kong Enterprise, Apigee hybrid |
| 9 Security | Keycloak, OPA, OpenBao, step-ca, Wazuh | Apache 2.0 / MPL 2.0 / GPL 2 | Ping/ForgeRock, HashiCorp Vault Enterprise, Splunk ES |
| 9 Observability | Prometheus, VictoriaMetrics, Grafana, Loki, Tempo, OpenTelemetry | Apache 2.0 / AGPL 3.0 | Datadog, Dynatrace, Splunk Observability |
| 10 AI | vLLM, Qwen2.5 / Qwen3, Mistral Small, bge-m3, pgvector, MCP SDK, LiteLLM (core), Langfuse (core) | Apache 2.0 / MIT / PostgreSQL | Azure OpenAI, Anthropic, Google Vertex AI (if the client allows external AI) |
| 11 Front end | Angular, angular-oauth2-oidc, MapLibre GL, ECharts, centrifuge-js | MIT / BSD-3 / Apache 2.0 | Esri ArcGIS JS (maps), Highcharts |
| Platform | Kubernetes (RKE2), Argo CD, OpenTofu, Harbor, Cilium | Apache 2.0 / MPL 2.0 | Red Hat OpenShift, VMware Tanzu |

## Deliberately excluded

| Tool | Reason | Used instead |
| --- | --- | --- |
| n8n | Sustainable Use License (not OSI) | Node-RED + Temporal |
| EMQX 5.9+ | BSL 1.1 | RabbitMQ MQTT, NanoMQ |
| Redis 7.4+ | RSAL/SSPL (AGPL option in Redis 8) | Valkey |
| HashiCorp Vault / Terraform | BSL 1.1 | OpenBao / OpenTofu |
| TimescaleDB advanced features | Timescale License | ClickHouse |
| Confluent Schema Registry | Confluent Community License | Apicurio |
| Llama models | Llama community licence (not OSI) | Qwen, Mistral (Apache 2.0) |
| MinIO community builds | AGPL with reduced community distribution | Ceph RGW, SeaweedFS |

A middle path for government go-lives is commercially supported builds of the same open-source projects (for example Red Hat Streams for Kafka, Red Hat build of Keycloak, EDB Postgres, Altinity ClickHouse, Grafana Enterprise). This keeps the architecture and adds vendor SLAs.
