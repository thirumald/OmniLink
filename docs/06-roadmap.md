# 06 — Roadmap and status

## Status of the reference implementation (this repository)

| Layer | Built | Verified here | Next |
| --- | --- | --- | --- |
| 1 Contracts and backbone | Models, topic catalogue, schema export/drift check, topic provisioner, Apicurio registration | Unit tests | Avro option; load test 500k msg/s |
| 2 Connectivity | SDK (normaliser, deadband, buffer, publishers, runner, health, metrics); MQTT, Modbus, BACnet, OPC UA, ONVIF, SNMP adapters; HTTP ingest | Unit tests for SDK, codecs, parsing, ingest API | Simulator contract tests per adapter; LoRaWAN, OCPP, DATEX II adapters |
| 3 Edge | Uplink bridge (allow-list, tenant check), NanoMQ config, K3s manifest | Unit tests for routing | Zero-touch provisioning, gateway OTA |
| 4 Storage | ClickHouse DDL with rollups, PostgreSQL schema with RLS and audit chain, Debezium config | Schema review | Migration tool (Atlas or sqitch), PgAssetRepo integration tests |
| 5 Processing | Flink SQL enrichment and threshold rules; reference rule semantics | Reference tests | Recorded-stream contract test Flink vs reference; data-quality job |
| 6 Services | Asset registry, alarm service (ISA-18.2, incidents), command service (four-eyes, rate limit) | API and state-machine tests | PostgreSQL persistence for alarms/commands; OPA call from command service |
| 7 Workflow | Temporal escalation workflow, idempotent trigger, Node-RED nodes and reference flow | Trigger tests, Node tests; Temporal test runs in CI (needs the test server download) | Device-offline maintenance workflow; Activepieces piece |
| 8 API | APISIX config, query API, outbound webhooks (HMAC, retries), notify, Centrifugo | Query builder, signing, fan-out tests | AsyncAPI-generated docs portal (Backstage) |
| 9 Security / observability | Keycloak realm, OPA policy + tests, Prometheus rules, OTel, Grafana dashboard | Config review | Penetration test, SBOM and signing in CI |
| 10 AI assistant | Agent with approval gate, role-scoped tools, injection filtering, triage, workflow generator, RAG, MCP server | Scripted-LLM tests | pgvector persistence, red-team suite, evals with Langfuse |
| 11 Front end | Angular console: dashboard, map, devices, alarms + AI triage, commands, automation, integrations, assistant, EN/AR | `ng build`, unit tests, rendered against devstack | Accessibility audit, map clustering, e2e tests |

## Delivery phases (12 months)

| Phase | Months | Scope | Gate |
| --- | --- | --- | --- |
| Foundation | 1–2 | Kubernetes, GitOps, Kafka, PostgreSQL, Keycloak, observability, contracts v1 | Design sign-off |
| Core MVP | 3–5 | Wave-1 adapters, Flink enrichment, ClickHouse, registry, alarms, Node-RED, console MVP | MVP with 5,000 devices |
| Scale and automate | 6–8 | OPC UA/LoRaWAN/NTCIP/OCPP, Temporal workflows, APISIX portal, multi-tenancy, AI assistant beta | 500k msg/s load test |
| Harden and go live | 9–12 | DR, penetration test, 1.5× load test, Arabic UI review, assistant red-team, pilot city go-live | Production readiness |
