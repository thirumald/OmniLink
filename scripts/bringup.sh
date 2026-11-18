#!/usr/bin/env bash
# OmniLink layer-by-layer bring-up with verification after every step.
#
#   scripts/bringup.sh preflight      # checks host, creates .env with random secrets, builds images
#   scripts/bringup.sh backbone       # then: security storage connectivity processing services workflow api
#                                     #       observability ai frontend simulators verify
#   scripts/bringup.sh all            # every step in order, stops at the first failure
#   scripts/bringup.sh status | logs <service> | down
#
# Each step is idempotent: re-run it after fixing a problem.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/deploy/compose"
DC=(docker compose)
STEPS=(backbone security storage connectivity processing services workflow api observability ai frontend simulators verify)

log()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✘ %s\033[0m\n' "$*"; exit 1; }
run_tool() { local envs=(); while [[ "${1:-}" == -e ]]; do envs+=("$1" "$2"); shift 2; done
             "${DC[@]}" --profile tools run --rm -T "${envs[@]}" toolbox "$@"; }
health() { run_tool tools/healthcheck.py "$@"; }
envval() { grep -E "^$1=" .env | cut -d= -f2-; }
up()     { "${DC[@]}" --profile "$1" up -d "${@:2}"; }

preflight() {
  log "Preflight"
  command -v docker >/dev/null || die "docker not installed"
  docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin missing"
  ok "$(docker --version)"
  mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
  [[ $mem_gb -ge 32 ]] && ok "memory ${mem_gb} GB" || warn "memory ${mem_gb} GB — 32 GB recommended for --profile all (16 GB minimum without AI)"
  free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc 0-9)
  [[ $free_gb -ge 100 ]] && ok "disk ${free_gb} GB free" || warn "disk ${free_gb} GB free — 100 GB+ recommended"
  for p in 1883 3000 4200 5432 8080 8081 8083 8085 8086 8088 8123 9080 9090 1880 29092; do
    if (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then warn "port $p already in use"; fi
  done
  if [[ ! -f .env ]]; then
    cp .env.example .env
    for k in POSTGRES_PASSWORD CLICKHOUSE_PASSWORD MQTT_PASSWORD KEYCLOAK_ADMIN_PASSWORD OIDC_GATEWAY_SECRET NODERED_CLIENT_SECRET \
             TEMPORAL_CLIENT_SECRET ASSISTANT_CLIENT_SECRET ONBOARDING_CLIENT_SECRET CENTRIFUGO_API_KEY PARTNER_NCM_KEY GRAFANA_ADMIN_PASSWORD; do
      sed -i "s|^$k=.*|$k=$(openssl rand -hex 16)|" .env
    done
    chmod 600 .env
    ok "created deploy/compose/.env with random secrets (keep it safe)"
  else ok ".env present"; fi
  log "Building images (platform, flink, console)"
  "${DC[@]}" --profile all --profile tools build
  ok "images built"
}

backbone() {
  log "Layer 1 — event backbone"
  up backbone
  for i in $(seq 1 30); do
    "${DC[@]}" exec -T kafka /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 >/dev/null 2>&1 && break
    sleep 3; [[ $i == 30 ]] && die "kafka not ready"
  done; ok "kafka ready"
  run_tool -e REPLICATION_FACTOR=1 backbone/kafka/create_topics.py
  run_tool -m omnilink_contracts.export_schemas --out contracts/schemas --check
  health http://apicurio:8080/apis/registry/v3/system/info
  run_tool -e APICURIO_URL=http://apicurio:8080 backbone/apicurio/register_schemas.py contracts/schemas
  n=$("${DC[@]}" exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list | grep -c '^omnilink\.')
  [[ $n -ge 12 ]] && ok "$n omnilink topics" || die "expected 12 omnilink topics, found $n"
}

security() {
  log "Layer 9a — identity (Keycloak)"
  up security keycloak
  health --timeout 240 http://keycloak:8080/realms/omnilink/.well-known/openid-configuration
  run_tool tools/keycloak_setup.py --url http://keycloak:8080 --env deploy/compose/.env
  ok "console users: operator.demo / supervisor.demo / integrator.demo (temporary password ChangeMe!2026)"
}

storage() {
  log "Layer 4 — storage"
  up storage
  for i in $(seq 1 40); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$("${DC[@]}" ps -q postgres)")" == healthy ]] && break
    sleep 3; [[ $i == 40 ]] && die "postgres not healthy"
  done; ok "postgres ready"
  n=$("${DC[@]}" exec -T postgres psql -U "$(envval POSTGRES_USER)" -d omnilink -tAc "select count(*) from information_schema.tables where table_schema='public'")
  [[ $n -ge 9 ]] && ok "postgres schema: $n tables" || die "postgres migrations missing ($n tables) — volume created before migrations? run: docker compose down -v postgres"
  for i in $(seq 1 30); do
    n=$("${DC[@]}" exec -T clickhouse clickhouse-client -q "select count() from system.tables where database='omnilink'" 2>/dev/null || echo 0)
    [[ $n -ge 10 ]] && break; sleep 3
  done
  [[ $n -ge 10 ]] && ok "clickhouse schema: $n tables" || die "clickhouse init scripts did not run ($n tables)"
  health --timeout 180 http://debezium:8083/connectors
  run_tool tools/render_template.py storage/debezium/postgres-connector.json --env deploy/compose/.env > /tmp/omnilink-debezium.json
  curl -fsS -X PUT -H 'content-type: application/json' localhost:8083/connectors/omnilink-postgres-cdc/config \
       --data "$(python3 -c 'import json,sys; print(json.dumps(json.load(open("/tmp/omnilink-debezium.json"))["config"]))')" >/dev/null
  rm -f /tmp/omnilink-debezium.json
  sleep 5
  state=$(curl -fsS localhost:8083/connectors/omnilink-postgres-cdc/status | python3 -c 'import json,sys; print(json.load(sys.stdin)["connector"]["state"])')
  [[ $state == RUNNING ]] && ok "debezium CDC connector RUNNING" || die "debezium connector state: $state"
}

connectivity() {
  log "Layers 2/3 — connectivity and edge uplink"
  up connectivity
  for i in $(seq 1 30); do
    "${DC[@]}" exec -T rabbitmq rabbitmq-diagnostics -q check_port_listener 1883 >/dev/null 2>&1 && break
    sleep 3; [[ $i == 30 ]] && die "MQTT listener not up"
  done; ok "MQTT broker listening on 1883"
  health http://http-ingest:8010/healthz
}

processing() {
  log "Layer 5 — stream processing (Flink)"
  up processing
  health --timeout 180 http://flink-jobmanager:8081/overview
  for job in 01_enrich 02_threshold_rules; do
    name="omnilink-${job//_/-}"
    running=$(curl -fsS localhost:8081/jobs/overview | python3 -c "import json,sys; print(sum(j['state']=='RUNNING' and j['name']=='$name' for j in json.load(sys.stdin)['jobs']))")
    if [[ $running -ge 1 ]]; then ok "flink job $job already running"; continue; fi
    run_tool tools/render_template.py processing/flink/sql/$job.sql --set KAFKA_BOOTSTRAP=kafka:9092 > /tmp/$job.sql
    "${DC[@]}" cp /tmp/$job.sql flink-jobmanager:/tmp/$job.sql
    "${DC[@]}" exec -T flink-jobmanager ./bin/sql-client.sh -f /tmp/$job.sql >/dev/null
    rm -f /tmp/$job.sql
    ok "submitted $job"
  done
  sleep 5
  n=$(curl -fsS localhost:8081/jobs/overview | python3 -c "import json,sys; print(sum(1 for j in json.load(sys.stdin)['jobs'] if j['state']=='RUNNING'))")
  [[ $n -ge 2 ]] && ok "$n Flink jobs RUNNING" || die "expected 2 running Flink jobs, found $n (see http://localhost:8081)"
}

services() {
  log "Layer 6 — platform services"
  up services
  health http://asset-registry:8001/healthz http://alarm-service:8002/healthz http://command-service:8003/healthz
}

workflow() {
  log "Layer 7 — workflow automation"
  up workflow
  health --timeout 180 http://temporal-ui:8080/ http://node-red:1880/
  "${DC[@]}" exec -T node-red npm install --prefix /data --no-fund --no-audit /opt/omnilink/node-red-contrib-omnilink node-red-contrib-kafkajs >/dev/null
  "${DC[@]}" restart node-red >/dev/null
  health --timeout 120 http://node-red:1880/
  ok "Node-RED with OmniLink nodes: http://localhost:1880 (import workflow/node-red/flows/flood-alarm.json)"
}

api() {
  log "Layer 8 — API gateway and integration"
  up api
  health http://query-api:8004/healthz http://outbound:8005/healthz "http://apisix:9080/v1/devices=401"
  ok "gateway rejects anonymous calls (401)"
  run_tool -e OIDC_CLIENT_ID=omnilink-onboarding -e "OIDC_CLIENT_SECRET=$(envval ONBOARDING_CLIENT_SECRET)" -c '
import httpx, os
t = httpx.post(os.environ["OIDC_TOKEN_URL"], data={"grant_type":"client_credentials","client_id":os.environ["OIDC_CLIENT_ID"],"client_secret":os.environ["OIDC_CLIENT_SECRET"]}).json()["access_token"]
r = httpx.get("http://apisix:9080/v1/devices", headers={"Authorization": "Bearer " + t})
print("  authenticated GET /v1/devices ->", r.status_code); raise SystemExit(r.status_code != 200)'
  ok "token flow works end to end (Keycloak -> APISIX -> asset registry)"
}

observability() {
  log "Layer 9b — observability"
  up observability
  health http://prometheus:9090/-/ready http://grafana:3000/api/health
  ok "Grafana: http://localhost:3000 (admin / GRAFANA_ADMIN_PASSWORD in .env) → OmniLink — Platform Health"
}

ai() {
  log "Layer 10 — AI assistant"
  up ai
  "${DC[@]}" exec -T ollama ollama pull "$(envval OMNILINK_LLM_MODEL)"
  "${DC[@]}" exec -T ollama ollama pull "$(envval OMNILINK_EMBED_MODEL)"
  health http://assistant:8020/healthz
  ok "assistant ready (CPU model; use --profile ai-gpu and vLLM for production speed)"
}

frontend() {
  log "Layer 11 — Angular console"
  up frontend
  health http://console:8080/
  ok "console: http://localhost:4200 (sign in as operator.demo)"
}

simulators() {
  log "First devices — simulators + onboarding"
  "${DC[@]}" --profile simulators up -d
  run_tool -e OIDC_CLIENT_ID=omnilink-onboarding -e "OIDC_CLIENT_SECRET=$(envval ONBOARDING_CLIENT_SECRET)" \
    tools/onboard.py sites/pilot-simulators.yaml --api http://apisix:9080 --out connectors/generated
  ok "simulated AQ station (MQTT) and pump (Modbus) registered; PM2.5 spike after ${SIM_SPIKE_AFTER:-300}s, pump fault after ${SIM_FAULT_AFTER:-600}s"
}

verify() {
  log "End-to-end verification"
  msg=$("${DC[@]}" exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
        --topic omnilink.telemetry.v1 --max-messages 1 --timeout-ms 30000 2>/dev/null || true)
  [[ -n "$msg" ]] && ok "telemetry on Kafka: ${msg:0:100}…" || die "no telemetry on omnilink.telemetry.v1 (check connector logs)"
  msg=$("${DC[@]}" exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
        --topic omnilink.telemetry.enriched.v1 --max-messages 1 --timeout-ms 30000 2>/dev/null || true)
  [[ -n "$msg" ]] && ok "Flink enrichment output present" || die "no enriched telemetry (check Flink at http://localhost:8081)"
  sleep 10
  n=$("${DC[@]}" exec -T clickhouse clickhouse-client -q "select count() from omnilink.telemetry")
  [[ $n -gt 0 ]] && ok "ClickHouse telemetry rows: $n" || die "no rows in ClickHouse (check omnilink.kafka_errors)"
  hits=$("${DC[@]}" exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
        --topic omnilink.alarms.v1 --from-beginning --max-messages 1 --timeout-ms 5000 2>/dev/null || true)
  [[ -n "$hits" ]] && ok "alarms flowing: ${hits:0:90}…" || warn "no alarms yet — they appear after the simulator spike (SIM_SPIKE_AFTER)"
  ok "open http://localhost:4200 — dashboard, map, devices aq-001 and pump-sim-1"
}

status() { "${DC[@]}" --profile all --profile simulators ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'; }

case "${1:-}" in
  preflight|backbone|security|storage|connectivity|processing|services|workflow|api|observability|ai|frontend|simulators|verify|status) "$1" ;;
  all) preflight; for s in "${STEPS[@]}"; do "$s"; done; log "OmniLink is up"; status ;;
  logs) "${DC[@]}" --profile all --profile simulators logs -f --tail 100 "${2:?service}" ;;
  down) "${DC[@]}" --profile all --profile simulators --profile tools down ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
