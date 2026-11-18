-- Row-level security: services set `SET app.tenant = '<tenant>'` per request/transaction.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sites','connectors','devices','points','alarm_rules','alarms','commands','webhook_subscriptions','audit_log']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting('app.tenant', true))
                     WITH CHECK (tenant_id = current_setting('app.tenant', true))$p$, t);
  END LOOP;
END $$;

-- platform operators (cross-tenant) use a role that bypasses RLS
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omnilink_platform') THEN
    CREATE ROLE omnilink_platform BYPASSRLS;
  END IF;
END $$;
