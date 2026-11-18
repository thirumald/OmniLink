'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { OmniLinkClient } = require('../lib/client');

function fakeFetch(log, responses) {
  return async (url, opts) => {
    log.push({ url: String(url), opts });
    const r = responses.shift();
    return { ok: r.status < 400, status: r.status, json: async () => r.body, text: async () => JSON.stringify(r.body) };
  };
}

test('caches OAuth2 token and builds command request', async () => {
  const log = [];
  const c = new OmniLinkClient({
    baseUrl: 'http://api/', tokenUrl: 'http://sso/token', clientId: 'nr', clientSecret: 's',
    fetchImpl: fakeFetch(log, [
      { status: 200, body: { access_token: 'T1', expires_in: 300 } },
      { status: 202, body: { status: 'sent' } },
      { status: 200, body: [] },
    ]),
  });
  const res = await c.command('cam-1', { connector_id: 'onvif-1', action: 'ptz.goto_preset', params: { preset: '2' } });
  assert.equal(res.status, 'sent');
  await c.nearDevices(24.45, 54.37, 300, 'Camera');
  assert.equal(log.length, 3, 'token requested once');
  assert.equal(log[1].url, 'http://api/v1/devices/cam-1/commands');
  assert.equal(log[1].opts.headers.Authorization, 'Bearer T1');
  assert.match(log[2].url, /near=24.45%2C54.37&radius_m=300&type=Camera/);
});

test('surfaces API errors with status', async () => {
  const c = new OmniLinkClient({ baseUrl: 'http://api', fetchImpl: fakeFetch([], [{ status: 429, body: { detail: 'rate' } }]) });
  await assert.rejects(c.getDevice('x'), (e) => e.status === 429 && /rate/.test(e.message));
});
