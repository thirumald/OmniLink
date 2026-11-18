#!/bin/sh
# Render runtime config from environment (no rebuild per city/tenant).
cat > /usr/share/nginx/html/config.js <<EOF
window.__OMNILINK__ = {
  apiBase: "${OMNILINK_API_BASE:-}",
  issuer: "${OMNILINK_OIDC_ISSUER:-http://localhost:8080/realms/omnilink}",
  clientId: "${OMNILINK_OIDC_CLIENT_ID:-omnilink-console}",
  realtimeUrl: "${OMNILINK_REALTIME_URL:-ws://localhost:9080/connection/websocket}",
  nodeRedUrl: "${OMNILINK_NODERED_URL:-http://localhost:1880}",
  grafanaUrl: "${OMNILINK_GRAFANA_URL:-http://localhost:3000}",
  mapStyle: "${OMNILINK_MAP_STYLE:-https://demotiles.maplibre.org/style.json}",
  mapCenter: [${OMNILINK_MAP_CENTER:-54.3773, 24.4539}]
};
EOF
