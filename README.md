# OmniLink — Smart City Unified Integration Layer

OmniLink connects a city's critical devices and external systems through one open-source integration layer. That layer covers protocols, data, automation, APIs and an AI assistant. Cameras, building systems, traffic controllers, sensors, utilities and partner agencies all become one consistent, secure, real-time data stream that command centres, digital twins and applications can use.

> **Status:** reference implementation of all 11 layers. It is tested with unit and contract tests (Python and Angular) and runs end to end as a single-process dev stack. Production hardening is tracked in [docs/06-roadmap.md](docs/06-roadmap.md).

## What it does

| | |
| --- | --- |
| **Connect** | Connector SDK with adapters for MQTT, Modbus TCP, BACnet/IP, OPC UA, ONVIF, SNMP/NTCIP and REST/webhooks; LoRaWAN via ChirpStack; edge gateways with 72 h store-and-forward |
| **Normalise** | Canonical, versioned contracts (NGSI-LD URNs, UCUM units), point mapping, unit conversion, deadband |
| **Stream and store** | Kafka backbone → Flink enrichment and rules → ClickHouse (time series), PostgreSQL + PostGIS (relational), Valkey, S3 object storage |
| **Act** | Asset registry, ISA-18.2 alarms, commands with four-eyes approval, incidents |
| **Automate** | Node-RED with OmniLink nodes (an open-source alternative to n8n) and Temporal for durable escalation workflows |
| **Expose** | APISIX gateway, time series API, signed outbound webhooks, Centrifugo live feeds |
| **Assist** | LLM assistant on open-weight models: Q&A over live data, alarm triage, action proposals that need human approval, workflow generation, RAG, MCP |
| **Operate** | Angular console (English and Arabic), Keycloak SSO, OPA policies, Prometheus, Grafana, OpenTelemetry |

Everything in the stack is under an OSI-approved licence. See [docs/04-tech-stack-and-licences.md](docs/04-tech-stack-and-licences.md) for each component's licence and its licensed commercial alternatives.

## Quick start

```bash
# 1. Python tests (contracts, SDK, adapters, edge, processing, services, workflows, assistant)
pip install -r requirements-dev.txt
make test

# 2. One-process dev stack with demo data (all services in memory) + console
make console-build
make devstack                       # http://localhost:9080 serves the API and the console

# 3. Full containerised stack, layer by layer, each step verified (see docs/07-bring-up-runbook.md)
scripts/bringup.sh preflight
scripts/bringup.sh backbone        # then: security storage connectivity processing services workflow api
                                   #       observability ai frontend simulators verify   (or: all)

# 4. First real devices
cp sites/template-real-devices.yaml sites/my-site.yaml && python tools/onboard.py sites/my-site.yaml --dry-run
```

## Documentation

Start at [docs/README.md](docs/README.md):

- [What OmniLink is](docs/01-overview.md)
- [Architecture](docs/02-architecture.md)
- [How it is developed](docs/03-development-guide.md)
- [Tech stack and licences](docs/04-tech-stack-and-licences.md)
- [Deployment](docs/05-deployment.md)
- [Roadmap and status](docs/06-roadmap.md)
- [Bring-up runbook and first devices](docs/07-bring-up-runbook.md)
- A specification for each of the 11 layers in [docs/layers/](docs/layers/)

## Repository layout

```
libs/omnilink_contracts   Layer 1  canonical models, topic catalogue, JSON Schemas (contracts/schemas)
backbone/                 Layer 1  Kafka topics, Apicurio registration
libs/omnilink_sdk         Layer 2  Connector SDK (normaliser, buffer, publishers, runner)
connectors/               Layer 2  protocol adapters, HTTP ingest, example configs
edge/                     Layer 3  uplink bridge, NanoMQ, K3s manifests
storage/                  Layer 4  ClickHouse DDL, PostgreSQL migrations, Debezium
processing/               Layer 5  Flink SQL jobs, reference rule semantics
services/                 Layer 6/8 asset registry, alarms, commands, query API, outbound
workflow/                 Layer 7  Temporal workflows, Node-RED nodes and flows
gateway/                  Layer 8  APISIX, Centrifugo
security/, observability/ Layer 9  Keycloak realm, OPA, Prometheus, OTel, Grafana
assistant/                Layer 10 AI assistant (agent, triage, workflow generation, RAG, MCP)
frontend/console          Layer 11 Angular operator console
deploy/                   Docker Compose (dev/pilot); Kubernetes manifests (planned)
tools/devstack.py         all services in one process with demo data
scripts/bringup.sh        layer-by-layer bring-up with verification
tools/onboard.py, sites/  onboard connectors, devices, points and rules from a site file
tools/simulators/         MQTT air-quality and Modbus pump simulators
```
