-- OmniLink core relational schema (PostgreSQL 16 + PostGIS 3.4 + ltree)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
    id          text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    name        text NOT NULL,
    settings    jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sites (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   text NOT NULL REFERENCES tenants(id),
    path        ltree NOT NULL,                       -- city.district.site.building.floor.zone
    name        text NOT NULL,
    kind        text NOT NULL,                        -- district | site | building | floor | zone
    location    geometry(Point, 4326),
    boundary    geometry(MultiPolygon, 4326),
    UNIQUE (tenant_id, path)
);
CREATE INDEX sites_path_gist ON sites USING gist (path);
CREATE INDEX sites_location_gist ON sites USING gist (location);

CREATE TABLE connectors (
    id              text PRIMARY KEY,
    tenant_id       text NOT NULL REFERENCES tenants(id),
    type            text NOT NULL,                    -- mqtt | modbus | bacnet | opcua | onvif | snmp | http
    gateway_id      text,                             -- null = runs in core
    poll_interval_s numeric NOT NULL DEFAULT 10,
    settings        jsonb NOT NULL DEFAULT '{}',      -- secrets referenced as openbao:// paths only
    enabled         boolean NOT NULL DEFAULT true,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
    id           text NOT NULL,
    tenant_id    text NOT NULL REFERENCES tenants(id),
    entity_type  text NOT NULL,
    name         text NOT NULL,
    site_id      uuid REFERENCES sites(id),
    connector_id text REFERENCES connectors(id),
    vendor       text, model text, firmware text, serial text,
    location     geometry(Point, 4326),
    site_path    text,                                -- denormalised for CDC consumers (Flink enrichment)
    lat          double precision GENERATED ALWAYS AS (ST_Y(location)) STORED,
    lon          double precision GENERATED ALWAYS AS (ST_X(location)) STORED,
    attributes   jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'unknown',
    last_seen    timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX devices_location_gist ON devices USING gist (location);
CREATE INDEX devices_type ON devices (tenant_id, entity_type);

CREATE TABLE points (
    tenant_id    text NOT NULL,
    connector_id text NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    point_ref    text NOT NULL,
    device_id    text NOT NULL,
    attribute    text NOT NULL,
    unit         text, source_unit text,
    scale        double precision NOT NULL DEFAULT 1,
    "offset"     double precision NOT NULL DEFAULT 0,
    deadband     double precision NOT NULL DEFAULT 0,
    writable     boolean NOT NULL DEFAULT false,
    PRIMARY KEY (connector_id, point_ref),
    FOREIGN KEY (tenant_id, device_id) REFERENCES devices(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE alarm_rules (
    id           text PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES tenants(id),
    name         text NOT NULL,
    entity_type  text,                                -- applies to all entities of a type ...
    entity_id    text,                                -- ... or to one entity
    attribute    text NOT NULL,
    condition    text NOT NULL CHECK (condition IN ('gt','gte','lt','lte','eq','ne')),
    threshold    double precision NOT NULL,
    hysteresis   double precision NOT NULL DEFAULT 0,
    delay_s      integer NOT NULL DEFAULT 0,          -- condition must hold this long
    priority     smallint NOT NULL CHECK (priority BETWEEN 1 AND 4),
    message      text NOT NULL,
    enabled      boolean NOT NULL DEFAULT true,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (entity_type IS NOT NULL OR entity_id IS NOT NULL)
);

CREATE TABLE alarms (
    id            uuid PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES tenants(id),
    rule_id       text NOT NULL,
    entity_id     text NOT NULL,
    attribute     text,
    priority      smallint NOT NULL,
    state         text NOT NULL,
    message       text NOT NULL,
    raised_at     timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL,
    acked_by      text, acked_at timestamptz, cleared_at timestamptz, shelved_until timestamptz,
    last_value    double precision,
    occurrences   integer NOT NULL DEFAULT 1
);
-- one open alarm per (rule, entity)
CREATE UNIQUE INDEX alarms_open_uniq ON alarms (tenant_id, rule_id, entity_id) WHERE state <> 'cleared';
CREATE INDEX alarms_state ON alarms (tenant_id, state, priority);

CREATE TABLE commands (
    id            uuid PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES tenants(id),
    device_id     text NOT NULL,
    connector_id  text NOT NULL,
    action        text NOT NULL,
    params        jsonb NOT NULL,
    requested_by  text NOT NULL,
    approved_by   text,
    status        text NOT NULL,
    detail        text,
    requested_at  timestamptz NOT NULL,
    completed_at  timestamptz
);

CREATE TABLE webhook_subscriptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   text NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    url         text NOT NULL CHECK (url LIKE 'https://%'),
    secret_ref  text NOT NULL,                        -- openbao:// path to HMAC secret
    topics      text[] NOT NULL,
    filter      jsonb NOT NULL DEFAULT '{}',          -- e.g. {"entity_type": ["AirQualityObserved"], "min_priority": 2}
    enabled     boolean NOT NULL DEFAULT true
);

-- Append-only, hash-chained audit log
CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    tenant_id   text NOT NULL,
    actor       text NOT NULL,
    action      text NOT NULL,
    target      text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}',
    at          timestamptz NOT NULL DEFAULT now(),
    prev_hash   bytea,
    hash        bytea NOT NULL
);

CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger AS $$
DECLARE p bytea;
BEGIN
    SELECT hash INTO p FROM audit_log ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := p;
    NEW.hash := digest(coalesce(p, '') || convert_to(NEW.tenant_id || NEW.actor || NEW.action || NEW.target ||
                       NEW.detail::text || NEW.at::text, 'UTF8'), 'sha256');
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_chain_trg BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_chain();
CREATE RULE audit_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
