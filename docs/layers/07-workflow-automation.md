# Layer 7 — Workflow Automation (n8n-style, open source)

**Purpose.** Let operators and integrators automate responses without writing services, while mission-critical processes run on a durable engine.

## 1. Two tiers

| Tier | Engine | Who builds | Typical flows |
| --- | --- | --- | --- |
| Visual / low-code | Node-RED 4 + `node-red-contrib-omnilink` nodes; Activepieces CE for business-app integrations | Integrators, operators | Device glue, notifications, data shares, small automations |
| Durable / critical | Temporal (Python SDK) workers in `workflow/temporal` | Platform engineers | Incident escalation, SLA timers, approvals, multi-day maintenance processes |

Both start from the same triggers: Kafka topics (alarms, events, telemetry), schedules, webhooks, and the AI assistant (Layer 10).

## 2. OmniLink Node-RED nodes

| Node | Does | Platform API |
| --- | --- | --- |
| `omnilink-config` | Holds base URL + OAuth2 client credentials (from OpenBao via env) | Keycloak token endpoint |
| `omnilink-asset` | Look up a device, or devices near a point | asset-registry `GET /v1/devices` |
| `omnilink-command` | Send a device command (respects approval rules) | command-service `POST /v1/devices/{id}/commands` |
| `omnilink-alarm` | Ack / shelve / clear an alarm | alarm-service |
| `omnilink-query` | Time series query | query-api `GET /v1/timeseries` |
| `omnilink-notify` | SMS / email / webhook via outbound | outbound `POST /v1/notify` |

Triggers use standard nodes: `kafka-consumer` (node-red-contrib-kafkajs, MIT) on `omnilink.alarms.v1` etc., or `mqtt in` on the core broker.

## 3. Temporal workflows shipped

| Workflow | Trigger | Steps |
| --- | --- | --- |
| `IncidentEscalation` | alarm priority ≤ 2 raised | create incident → point nearest cameras to preset → notify level 1 → wait for ack signal (5 min) → escalate level 2 → level 3 → close on clear |
| `DeviceOfflineMaintenance` | `device-offline` alarm | check upstream switch (SNMP command) → open maintenance ticket → wait for recovery or 24 h SLA → close/escalate |
| `ScheduledDataShare` | cron | query rollups → publish to partner webhook |

`workflow/temporal/trigger.py` consumes `omnilink.alarms.v1` and starts/signals workflows with deterministic IDs (`incident-<alarm_id>`) so replays never duplicate.

## 4. Governance

- Flows stored in Git (Node-RED projects), promoted dev → test → prod by CI; production editor is read-only.
- Secrets only from environment/OpenBao; never in flow JSON.
- Critical automations must run on Temporal; Node-RED flows that command safety points are blocked by the command-service approval rule.

## 5. Acceptance criteria

- [ ] Escalation policy tested with Temporal's time-skipping test environment.
- [ ] Trigger is idempotent: the same alarm event twice starts one workflow.
- [ ] Node-RED nodes load in Node-RED 4 and pass their unit tests (node-red-node-test-helper).
