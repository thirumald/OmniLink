# Layer 9 — Security and Observability (cross-cutting)

## 1. Security

| Control | Implementation | Location |
| --- | --- | --- |
| User identity | Keycloak realm `omnilink`: OIDC, MFA (OTP/WebAuthn), LDAP/AD federation | `security/keycloak/realm-omnilink.json` |
| Roles | `viewer`, `operator`, `supervisor`, `integrator`, `platform-admin` (realm roles) | realm + `omnilink_services.common.IMPLIES` |
| Tenant isolation | `tenant` claim (user attribute mapper) → API checks + PostgreSQL RLS (`app.tenant`) + ClickHouse query filter | services, `002_rls.sql` |
| Service identity | OAuth2 client credentials per service (`omnilink-nodered`, `omnilink-temporal`, `omnilink-assistant`) | realm |
| Fine-grained policy | OPA: who may command which entity types and actions | `security/opa/omnilink.rego` |
| Device identity | mTLS, X.509 from step-ca; gateway CN `gw-<tenant>-<site>` | edge layer |
| Secrets | OpenBao (KV v2 + PKI); services read via agent sidecar; never in Git | deployment |
| Transport | TLS 1.3 everywhere outside the cluster; Cilium WireGuard inside | platform |
| Audit | hash-chained `audit_log`, immutable rules; command and alarm actions logged | `001_core.sql` |
| Supply chain | Trivy scan, Syft SBOM, Cosign signing in CI | `.github/workflows/ci.yml` |
| AI safety | approval gate for write tools, tool allow-list per role, prompt-injection filtering, full trace logging | Layer 10 |

## 2. Observability

| Signal | Path | Retention |
| --- | --- | --- |
| Metrics | services + connectors `/metrics` → Prometheus → remote-write VictoriaMetrics | 13 months |
| Traces | OpenTelemetry SDK → OTel Collector → Tempo | 14 days |
| Logs | stdout JSON → Fluent Bit → Loki | 30 days |
| Dashboards | Grafana provisioned from `observability/grafana/` | – |
| Alerts | Prometheus rules → Alertmanager → notify / Temporal runbooks | – |

Key SLOs and alerts (`observability/prometheus/rules.yml`): connector offline, buffer depth growing, Kafka consumer lag, API error rate > 1%, p95 latency, rule-hit latency.

## 3. Acceptance criteria

- [ ] Penetration test: no cross-tenant read through any API.
- [ ] OPA unit tests pass (`opa test security/opa`).
- [ ] Every service exposes `/metrics` and `/healthz`; Grafana dashboard shows all layers.
