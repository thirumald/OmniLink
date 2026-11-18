# Layer 11 — Front End (Angular Operator Console)

**Purpose.** One web console for command-centre operators, supervisors and integrators: live city state, alarms, device control, approvals, automation and the AI assistant.

## 1. Stack (all open source)

| Concern | Choice | Licence |
| --- | --- | --- |
| Framework | Angular 22 (standalone components, signals, zoneless change detection, lazy routes) | MIT |
| Auth | angular-oauth2-oidc — Authorization Code + PKCE against Keycloak | MIT |
| Maps | MapLibre GL JS with self-hosted vector tiles (OpenMapTiles / Protomaps) | BSD-3 |
| Charts | Apache ECharts via ngx-echarts | Apache 2.0 / MIT |
| Real time | centrifuge-js (WebSocket to Centrifugo) | MIT |
| Tests | Vitest via `@angular/build:unit-test` | MIT |
| i18n | English and Arabic with RTL (`dir="rtl"`), CSS logical properties throughout | – |

## 2. Screens

| Route | Role | What it does |
| --- | --- | --- |
| `/dashboard` | viewer | KPIs (open alarms, P1, devices, offline), device map with alarm halos, alarms by priority, latest alarms |
| `/map` | viewer | Full-screen city map, filter by entity type, click a device → detail |
| `/devices`, `/devices/:id` | viewer / operator | Searchable inventory; device detail with time series chart (raw / 1 m / 1 h), metadata and command form |
| `/alarms` | viewer / operator / supervisor | ISA-18.2 console: filter by state; ack / shelve / clear (by role); **AI triage** suggestion inline |
| `/commands` | operator | Pending approvals (four-eyes; requester cannot approve) and recent command history |
| `/automation` | integrator | Describe an automation in plain language → validated Node-RED draft → download / import; link to Node-RED |
| `/integrations` | integrator | Outbound webhook subscriptions with HMAC signing |
| Assistant panel | all | Chat with tool trace; proposed actions shown as cards with Approve / Reject |

## 3. Structure

```
frontend/console/src/app/
  core/       config (runtime), auth, API client + interceptor, realtime, i18n, models
  layout/     shell (navigation, top bar, assistant panel host)
  features/   dashboard, map, devices, alarms, commands, automation, integrations, assistant
```

- Runtime configuration from `public/config.js` (written by the container entrypoint), so one image serves every city/tenant.
- All API calls go through APISIX (`/v1/...`); the interceptor attaches the access token.
- UI hides actions a role cannot perform, but the services enforce every permission again.

## 4. Acceptance criteria

- [x] `ng build` production bundle; `ng test` passes.
- [ ] WCAG 2.1 AA: keyboard navigation, focus rings, contrast ≥ 4.5:1 (audit before go-live).
- [ ] Arabic RTL layout reviewed by native speakers.
- [ ] Map renders 50,000 devices at ≥ 30 fps (clustered layer above 10k points).
