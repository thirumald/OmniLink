// Runtime configuration. The container entrypoint overwrites this file from environment variables.
// devAuth enables header-based identity for local development only (services must run with OMNILINK_AUTH_MODE=dev).
window.__OMNILINK__ = {
  apiBase: 'http://localhost:9080',
  issuer: 'http://localhost:8080/realms/omnilink',
  clientId: 'omnilink-console',
  realtimeUrl: 'ws://localhost:9080/connection/websocket',
  nodeRedUrl: 'http://localhost:1880',
  grafanaUrl: 'http://localhost:3000',
  mapCenter: [54.3773, 24.4539],
  devAuth: { user: 'dev.operator', tenant: 'abudhabi', roles: 'platform-admin' },
};
