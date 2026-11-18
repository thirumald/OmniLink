'use strict';
// Minimal OmniLink API client with OAuth2 client-credentials token caching (Node 20+ fetch).

class OmniLinkClient {
  constructor({ baseUrl, tokenUrl, clientId, clientSecret, fetchImpl }) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.tokenUrl = tokenUrl;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.fetch = fetchImpl || globalThis.fetch;
    this._token = null;
    this._exp = 0;
  }

  async token() {
    if (!this.tokenUrl) return 'dev';
    if (this._token && Date.now() < this._exp - 30_000) return this._token;
    const body = new URLSearchParams({ grant_type: 'client_credentials', client_id: this.clientId, client_secret: this.clientSecret });
    const r = await this.fetch(this.tokenUrl, { method: 'POST', body });
    if (!r.ok) throw new Error(`token request failed: ${r.status}`);
    const j = await r.json();
    this._token = j.access_token;
    this._exp = Date.now() + j.expires_in * 1000;
    return this._token;
  }

  async request(method, path, { query, body } = {}) {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(query || {})) if (v !== undefined && v !== '') url.searchParams.set(k, v);
    const headers = { Authorization: `Bearer ${await this.token()}`, 'Content-Type': 'application/json' };
    const r = await this.fetch(url.toString(), { method, headers, body: body ? JSON.stringify(body) : undefined });
    const text = await r.text();
    const data = text ? JSON.parse(text) : null;
    if (!r.ok) {
      const err = new Error(`${method} ${path} -> ${r.status}: ${data && data.detail ? data.detail : text}`);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  getDevice(id) { return this.request('GET', `/v1/devices/${encodeURIComponent(id)}`); }
  nearDevices(lat, lon, radius, type) { return this.request('GET', '/v1/devices', { query: { near: `${lat},${lon}`, radius_m: radius, type } }); }
  command(deviceId, cmd) { return this.request('POST', `/v1/devices/${encodeURIComponent(deviceId)}/commands`, { body: cmd }); }
  alarmAction(id, action, body) { return this.request('POST', `/v1/alarms/${encodeURIComponent(id)}/${action}`, { body }); }
  timeseries(q) { return this.request('GET', '/v1/timeseries', { query: q }); }
  notify(n) { return this.request('POST', '/v1/notify', { body: n }); }
}

module.exports = { OmniLinkClient };
