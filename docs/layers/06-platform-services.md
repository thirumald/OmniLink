# Layer 6 — Platform Services

**Purpose.** The domain services every application uses: what exists (asset registry), what is wrong (alarms), and how to act (commands).

## 1. Services

| Service | Port | Owns | Consumes | Produces |
| --- | --- | --- | --- | --- |
| `asset-registry` | 8001 | tenants, sites, devices, points, connectors (PostgreSQL) | – | CDC via Debezium |
| `alarm-service` | 8002 | alarms (PostgreSQL), ISA-18.2 lifecycle | `omnilink.rule-hits.v1`, `omnilink.health.v1` | `omnilink.alarms.v1` |
| `command-service` | 8003 | commands, approvals, audit | `omnilink.command-results.v1` | `omnilink.commands.v1` |

All three are FastAPI apps from one package (`services/omnilink_services`) sharing auth, tenant context, metrics and health endpoints. Each has a repository interface with an in-memory implementation (tests) and a PostgreSQL implementation (asyncpg, RLS via `SET app.tenant`).

## 2. Key APIs

| Method | Path | Role |
| --- | --- | --- |
| GET/POST | `/v1/devices`, `/v1/devices/{id}` | viewer / integrator |
| GET | `/v1/devices?near=lat,lon&radius_m=500&type=Camera` | viewer |
| GET | `/v1/connectors/{id}/config` | connector service account |
| GET | `/v1/alarms?state=active_unack&priority_max=2` | viewer |
| POST | `/v1/alarms/{id}/ack`, `/shelve`, `/clear` | operator |
| POST | `/v1/devices/{id}/commands` | operator (approval needed for actions in `APPROVAL_REQUIRED`) |
| POST | `/v1/commands/{id}/approve` | supervisor |
| GET | `/v1/commands/{id}` | viewer |

## 3. Alarm lifecycle (ISA-18.2)

```
active_unack --ack--> active_ack --rule normal--> cleared
active_unack --rule normal--> cleared_unack --ack--> cleared
any open --shelve(duration)--> shelved --expiry--> previous state
```

Repeated rule hits on an open alarm increment `occurrences`; one open alarm per (rule, entity). Device offline: no health heartbeat for 3 × interval raises a priority-2 `device-offline` alarm.

## 4. Command safety

- Commands carry `requested_by`, `ttl_s`; every command writes an audit row.
- Actions in the approval list (e.g. `write_point` on safety points, `reboot`) wait in `pending` until a second person with `supervisor` approves (four-eyes).
- Rate limit: 10 commands/min per device; OPA policy decides who may command which entity type.

## 5. Acceptance criteria

- [ ] State machine unit tests cover every transition and illegal transition.
- [ ] Duplicate rule hits do not create duplicate alarms.
- [ ] A command needing approval is not published until approved by a different user.
- [ ] p95 API latency < 100 ms at 500 req/s per service.
