# Layer 8 — API and External Integration (inbound / outbound)

**Purpose.** One governed front door for every consumer: external systems, partner agencies, the Angular console, Node-RED, Temporal and the AI assistant.

## 1. Components

| Component | Tech | Responsibility |
| --- | --- | --- |
| API gateway | Apache APISIX 3 (standalone YAML, GitOps) | Routing, OIDC/JWT (Keycloak), key-auth for partners, rate limits, CORS, request validation, Prometheus, WebSocket proxy |
| Query API | `omnilink_services.query_api` | Time series over ClickHouse: raw, 1 m, 1 h; safe parameterised SQL |
| Outbound service | `omnilink_services.outbound` | Webhook subscriptions (HMAC-SHA256 signed, retries, DLQ), `/v1/notify` (SMS via Jasmin SMPP gateway, email via SMTP, push via ntfy), live relay Kafka → Centrifugo |
| Real-time fan-out | Centrifugo v5 | WebSocket/SSE channels `alarms:<tenant>`, `telemetry:<tenant>:<entity>` with JWT channel auth |
| NGSI-LD / SensorThings | FIWARE Orion-LD, FROST-Server (optional) | Standards-based read access for third parties |
| API docs | OpenAPI 3.1 from each FastAPI service; AsyncAPI 3 for topics (`docs/api/asyncapi.yaml`) | Developer portal (Backstage) |

## 2. Route map (APISIX)

| Prefix | Upstream | Auth |
| --- | --- | --- |
| `/v1/devices`, `/v1/entities`, `/v1/connectors` | asset-registry:8001 | OIDC JWT |
| `/v1/alarms`, `/v1/incidents` | alarm-service:8002 | OIDC JWT |
| `/v1/commands`, `/v1/devices/*/commands` | command-service:8003 | OIDC JWT, 10 req/min per consumer |
| `/v1/timeseries` | query-api:8004 | OIDC JWT or partner key |
| `/v1/notify`, `/v1/webhooks` | outbound:8005 | OIDC JWT |
| `/v1/ingest/*` | http-ingest:8010 | partner key-auth, 1,000 req/s per key |
| `/v1/assistant/*` | assistant:8020 | OIDC JWT |
| `/connection/websocket` | centrifugo:8000 | Centrifugo JWT |

## 3. Outbound webhooks

Payload = canonical message JSON. Headers: `X-OmniLink-Event`, `X-OmniLink-Delivery` (UUID), `X-OmniLink-Timestamp`, `X-OmniLink-Signature: sha256=<hex(HMAC(secret, timestamp + "." + body))>`. Receivers reject timestamps older than 5 minutes. Retries: 1 s, 5 s, 30 s, 2 min, 10 min, then DLQ.

## 4. Acceptance criteria

- [ ] Query builder rejects injection attempts (unit tests); every query bounded by tenant and time range ≤ 400 days.
- [ ] Webhook signature verifiable with the documented algorithm (test vector in tests).
- [ ] Gateway adds < 5 ms p95.
