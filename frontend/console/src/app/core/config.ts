import { InjectionToken } from '@angular/core';

export interface OmniLinkConfig {
  apiBase: string; // APISIX base URL ('' = same origin)
  issuer: string; // Keycloak realm URL
  clientId: string;
  realtimeUrl: string; // Centrifugo WebSocket via APISIX
  nodeRedUrl: string;
  grafanaUrl: string;
  mapStyle: string; // MapLibre style URL (self-hosted tiles, e.g. OpenMapTiles)
  mapCenter: [number, number]; // lon, lat
  devAuth?: { user: string; tenant: string; roles: string };
}

declare global {
  interface Window {
    __OMNILINK__?: Partial<OmniLinkConfig>;
  }
}

export const DEFAULT_CONFIG: OmniLinkConfig = {
  apiBase: '',
  issuer: 'http://localhost:8080/realms/omnilink',
  clientId: 'omnilink-console',
  realtimeUrl: 'ws://localhost:9080/connection/websocket',
  nodeRedUrl: 'http://localhost:1880',
  grafanaUrl: 'http://localhost:3000',
  mapStyle: 'https://demotiles.maplibre.org/style.json',
  mapCenter: [54.3773, 24.4539],
};

/** Runtime config from public/config.js (rendered by the container entrypoint), so one image serves every city. */
export function loadConfig(): OmniLinkConfig {
  return { ...DEFAULT_CONFIG, ...(typeof window !== 'undefined' ? window.__OMNILINK__ ?? {} : {}) };
}

export const OMNILINK_CONFIG = new InjectionToken<OmniLinkConfig>('OMNILINK_CONFIG', {
  providedIn: 'root',
  factory: loadConfig,
});
