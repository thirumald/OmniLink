# 07 — Bring-up runbook: the stack layer by layer, then the first real devices

This runbook brings up the pilot stack on one Docker host, verifying each layer before the next starts, then onboards simulated devices and then real ones. Every step is one command; each is idempotent, so after fixing a problem you just re-run that step.

## 1. Host

| Item | Pilot minimum | Recommended |
| --- | --- | --- |
| OS | Ubuntu 22.04/24.04 or RHEL 9, x86-64 | same |
| CPU / RAM | 8 vCPU / 16 GB (without AI) | 16 vCPU / 32 GB (with AI on CPU) |
| Disk | 100 GB SSD | 500 GB NVMe |
| GPU (optional) | – | 1× L40S / A100 48 GB for vLLM (profile `ai-gpu`) |
| Software | Docker Engine 24+, Compose v2, git, python3, openssl, curl | – |
| Internet | to pull images and models once (or a mirrored registry for air-gapped sites) | – |
| Network | a NIC that reaches the device VLANs (or edge gateways, §5.3) | – |

```bash
git clone https://github.com/thirumald/OmniLink.git && cd OmniLink
scripts/bringup.sh preflight     # host checks, .env with random secrets, builds images
```

## 2. Layer by layer

Run the steps in this order. Each one ends with ✔ lines (pass) or stops at a ✘ line (fail) that says what to check.

| # | Command | Starts | Verifies |
| --- | --- | --- | --- |
| 1 | `scripts/bringup.sh backbone` | Kafka, Apicurio, Kafka UI | broker ready, 12 `omnilink.*` topics, schemas registered with BACKWARD rule |
| 2 | `scripts/bringup.sh security` | Keycloak | realm discovery, client secrets set from `.env`, client-credentials token works |
| 3 | `scripts/bringup.sh storage` | PostgreSQL+PostGIS, ClickHouse, Valkey, Debezium | migrations applied (tables counted), ClickHouse schema, CDC connector RUNNING |
| 4 | `scripts/bringup.sh connectivity` | RabbitMQ MQTT, uplink bridge, HTTP ingest | MQTT listener on 1883, ingest `/healthz` |
| 5 | `scripts/bringup.sh processing` | Flink JobManager + TaskManager | enrichment and rules jobs submitted and RUNNING |
| 6 | `scripts/bringup.sh services` | asset registry, alarms, commands | `/healthz` of each |
| 7 | `scripts/bringup.sh workflow` | Temporal + UI, workflow worker, Node-RED | UIs up, OmniLink nodes installed in Node-RED |
| 8 | `scripts/bringup.sh api` | APISIX, query API, outbound, Centrifugo | anonymous call → 401; token call → 200 through the gateway |
| 9 | `scripts/bringup.sh observability` | Prometheus, VictoriaMetrics, OTel, Loki, Tempo, Grafana | Prometheus ready, Grafana healthy |
| 10 | `scripts/bringup.sh ai` | assistant, triage worker, Ollama, pgvector | models pulled, assistant `/healthz` |
| 11 | `scripts/bringup.sh frontend` | Angular console | console served on :4200 |
| 12 | `scripts/bringup.sh simulators` | MQTT AQ station + Modbus pump simulators and their connectors | site registered through the gateway |
| 13 | `scripts/bringup.sh verify` | – | telemetry on Kafka → Flink enrichment → ClickHouse rows → alarms |

Or run everything: `scripts/bringup.sh all`. Use `scripts/bringup.sh status`, `logs <service>` and `down` as needed.

**Why security comes second:** every API, worker and the console authenticate through Keycloak, so identity is up before anything that calls it.

### Endpoints after bring-up

| What | URL | Credentials |
| --- | --- | --- |
| Console | http://localhost:4200 | `operator.demo`, `supervisor.demo`, `integrator.demo` (temporary password `ChangeMe!2026`, change at first login) |
| API gateway | http://localhost:9080/v1/… | Bearer token from Keycloak |
| Keycloak admin | http://localhost:8080 | `admin` / `KEYCLOAK_ADMIN_PASSWORD` |
| Kafka UI | http://localhost:8086 | – |
| Flink | http://localhost:8081 | – |
| Temporal UI | http://localhost:8088 | – |
| Node-RED | http://localhost:1880 | secure the editor (adminAuth) before sharing |
| Grafana | http://localhost:3000 | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| RabbitMQ | http://localhost:15672 | `MQTT_USER` / `MQTT_PASSWORD` |

## 3. Prove the pipeline with simulators

`scripts/bringup.sh simulators` starts two simulated devices and registers them through `tools/onboard.py sites/pilot-simulators.yaml`:

| Device | Protocol | Behaviour | Rule |
| --- | --- | --- | --- |
| `aq-001` air-quality station | MQTT (`city/aq/001`) | PM2.5 ~30 µg/m³, jumps to ~70 after `SIM_SPIKE_AFTER` s | `pm25-high` > 55 → P2 alarm |
| `pump-sim-1` pump | Modbus TCP (`modbus-sim:5020`) | flow in gal/min (converted to L/s), pressure drops to ~210 kPa after `SIM_FAULT_AFTER` s | `pump-pressure-low` < 250 → P1 alarm → Temporal escalation |

Expected in the console: both devices on the map and in Devices, live charts, then a P2 and a P1 alarm. **AI triage** produces a suggestion, and Temporal UI shows `incident-…` for the P1.

## 4. Before connecting real devices: site survey

Collect this for every device and keep it in the project folder (not in Git, because it contains credentials):

| Item | Why |
| --- | --- |
| Device ID, type, name, location (lat/lon, site path) | Registry, map, enrichment, rules |
| IP / port / protocol version, unit ID / device instance / profile | Connector settings |
| Point list: register map (Modbus), object list (BACnet), node IDs (OPC UA), OIDs (SNMP), topics and payload sample (MQTT) | Point mapping |
| Engineering units as the device reports them, scaling | `source_unit`, `scale`, `offset` |
| Credentials (read-only first!) and how to rotate them | Stored only as `${ENV}` references |
| Which points may be written, and who approves writes | `writable`, OPA policy, approval rules |
| Network path and firewall owner | Opening the ports in §5.2 |

Start **read-only**. Enable writes per point only after an operator acceptance test with the site owner.

## 5. Connect the first real devices

### 5.1 Describe the site

```bash
cp sites/template-real-devices.yaml sites/<site>.yaml     # fill in from the survey
python tools/onboard.py sites/<site>.yaml --dry-run       # validates connectors, points, units, rules
```

Secrets stay as `${ONVIF_PASSWORD}`-style references; add their values to `deploy/compose/.env`. The registry stores only the references, and connectors expand them at start.

### 5.2 Network access per protocol

| Protocol | Ports (from OmniLink host to device) | Notes |
| --- | --- | --- |
| ONVIF | TCP 80/443 (device service), UDP 3702 multicast (discovery) | Video (RTSP 554) stays with the VMS; OmniLink takes events, PTZ and status |
| BACnet/IP | UDP 47808 | Who-Is is broadcast: run the BACnet connector with host networking (`--network host`) on the BMS VLAN, or use an edge gateway / BBMD |
| Modbus TCP | TCP 502 | One connection per unit ID; respect the PLC's connection limit |
| OPC UA | TCP 4840 | Prefer `Basic256Sha256,SignAndEncrypt` with a trusted client certificate |
| SNMP | UDP 161 (poll), UDP 162 (traps) | v3 authPriv for anything outside the lab |
| MQTT devices → OmniLink | TCP 1883 / 8883 (TLS) to the OmniLink host | Create a user per device or vendor in RabbitMQ |
| REST / webhooks → OmniLink | TCP 9080 (APISIX) | Partner key (`key-auth` consumer) per source |

### 5.3 Register and start connectors

```bash
# register through the gateway (client omnilink-onboarding)
docker compose -f deploy/compose/docker-compose.yml --profile tools run --rm -T \
  -e OIDC_CLIENT_ID=omnilink-onboarding -e OIDC_CLIENT_SECRET=$(grep ONBOARDING_CLIENT_SECRET deploy/compose/.env | cut -d= -f2) \
  toolbox tools/onboard.py sites/<site>.yaml --api http://apisix:9080 --out connectors/generated

# start one container per connector (config rendered by the registry)
docker compose -f deploy/compose/docker-compose.yml --profile tools run -d --name conn-meter-site01 \
  connector --config /repo/connectors/generated/meter-site01.yaml
# BACnet (broadcasts) — host networking:
docker compose -f deploy/compose/docker-compose.yml --profile tools run -d --name conn-bms-site01 --network host \
  -e KAFKA_BOOTSTRAP=localhost:29092 connector --config /repo/connectors/generated/bms-site01.yaml
```

When devices are on remote sites, deploy the edge gateway instead (Layer 3: K3s + `edge/k3s/connector-deployment.yaml`, `OMNILINK_UPLINK=mqtt` to the core broker). The connector configs are the same.

### 5.4 Acceptance per device

| Check | How | Pass |
| --- | --- | --- |
| Connector healthy | `docker logs conn-<id>`; metric `omnilink_connector_errors_total` | no read errors after 5 min |
| Values correct | compare console values with the device's own HMI/web UI | equal after unit conversion, within the device's precision |
| Timestamps | `source_ts` vs device clock | skew < 2 s (configure NTP on devices) |
| Rates | `omnilink_connector_published_total` | matches poll interval / deadband expectation |
| Rule and alarm | lower a rule threshold temporarily | alarm appears, acknowledge works, threshold restored |
| Command (if enabled) | one harmless write, e.g. PTZ preset, with the site owner present | device acts; result `acked`; audit row present |
| Outage | unplug the device for 5 min | DEGRADED/OFFLINE health, `device-offline` alarm, recovery clears it |

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `storage` step: tables missing | the PostgreSQL volume existed before migrations ran | `docker compose down postgres && docker volume rm omnilink_pg`, re-run `storage` |
| Debezium not RUNNING | replication slot or password | `curl localhost:8083/connectors/omnilink-postgres-cdc/status`; check `.env` and `wal_level=logical` |
| No enriched telemetry | Flink job failed | http://localhost:8081 → exceptions; the Kafka connector jar version must match Flink 1.20 |
| No ClickHouse rows | JSON mismatch | `select * from omnilink.kafka_errors order by at desc limit 5` |
| API returns 401 with a valid token | issuer mismatch | tokens must show `iss` = `http://localhost:8080/realms/omnilink` (set by `KC_HOSTNAME`) |
| MQTT connector cannot connect | broker credentials or protocol | RabbitMQ user/password; set `protocol: "3.1.1"` for older brokers |
| BACnet reads time out | broadcast or BBMD | host networking on the BMS VLAN; check `device_address` and instance |
| Modbus values look wrong | word order or scaling | try `:le` in the point_ref; check register offset (some maps are 1-based) |
| Assistant slow | CPU model | use `--profile ai-gpu` (vLLM) or a smaller model in `OMNILINK_LLM_MODEL` |
