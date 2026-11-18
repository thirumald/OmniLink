'use strict';
const { OmniLinkClient } = require('./lib/client');

module.exports = function (RED) {
  function ConfigNode(n) {
    RED.nodes.createNode(this, n);
    this.client = new OmniLinkClient({
      baseUrl: n.baseUrl || process.env.OMNILINK_API || 'http://apisix:9080',
      tokenUrl: n.tokenUrl || process.env.OIDC_TOKEN_URL,
      clientId: this.credentials.clientId || process.env.OIDC_CLIENT_ID,
      clientSecret: this.credentials.clientSecret || process.env.OIDC_CLIENT_SECRET,
    });
  }
  RED.nodes.registerType('omnilink-config', ConfigNode, {
    credentials: { clientId: { type: 'text' }, clientSecret: { type: 'password' } },
  });

  // Shared wrapper: resolve config, run op(msg), set status, route errors to catch nodes.
  function makeNode(type, op) {
    function N(n) {
      RED.nodes.createNode(this, n);
      const node = this;
      node.conf = n;
      node.server = RED.nodes.getNode(n.server);
      node.on('input', async (msg, send, done) => {
        if (!node.server) { done(new Error('omnilink-config not set')); return; }
        node.status({ fill: 'blue', shape: 'dot', text: 'working' });
        try {
          msg.payload = await op(node.server.client, n, msg);
          node.status({ fill: 'green', shape: 'dot', text: 'ok' });
          send(msg);
          done();
        } catch (err) {
          node.status({ fill: 'red', shape: 'ring', text: String(err.status || 'error') });
          done(err);
        }
      });
    }
    RED.nodes.registerType(type, N);
  }

  const pick = (n, msg, key) => (msg[key] !== undefined ? msg[key] : n[key]);

  makeNode('omnilink-asset', (c, n, msg) => {
    if (pick(n, msg, 'lat') !== undefined && pick(n, msg, 'lat') !== '') {
      return c.nearDevices(pick(n, msg, 'lat'), pick(n, msg, 'lon'), pick(n, msg, 'radius') || 300, pick(n, msg, 'deviceType'));
    }
    return c.getDevice(pick(n, msg, 'deviceId'));
  });

  makeNode('omnilink-command', (c, n, msg) => c.command(pick(n, msg, 'deviceId'), {
    connector_id: pick(n, msg, 'connectorId'),
    action: pick(n, msg, 'action'),
    params: msg.params || (n.params ? JSON.parse(n.params) : {}),
    ttl_s: Number(pick(n, msg, 'ttl') || 30),
  }));

  makeNode('omnilink-alarm', (c, n, msg) => {
    const action = pick(n, msg, 'alarmAction') || 'ack';
    const body = action === 'shelve' ? { minutes: Number(pick(n, msg, 'minutes') || 60) } : undefined;
    return c.alarmAction(pick(n, msg, 'alarmId') || (msg.payload && msg.payload.alarm_id), action, body);
  });

  makeNode('omnilink-query', (c, n, msg) => c.timeseries({
    entity_id: pick(n, msg, 'entityId'), attribute: pick(n, msg, 'attribute'),
    from: pick(n, msg, 'from') || '-24h', to: pick(n, msg, 'to') || 'now', interval: pick(n, msg, 'interval') || '1h',
  }));

  makeNode('omnilink-notify', (c, n, msg) => c.notify({
    group: pick(n, msg, 'group'), channels: (pick(n, msg, 'channels') || 'push').split(','),
    subject: pick(n, msg, 'subject') || msg.topic || 'OmniLink notification',
    body: typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload),
  }));
};
