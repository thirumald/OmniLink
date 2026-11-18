// Mirrors libs/omnilink_contracts and service response models.

export type AlarmState = 'active_unack' | 'active_ack' | 'cleared_unack' | 'cleared' | 'shelved';

export interface Device {
  id: string;
  tenant: string;
  entity_id: string;
  entity_type: string;
  name: string;
  site_path?: string | null;
  connector_id?: string | null;
  vendor?: string | null;
  model?: string | null;
  lat?: number | null;
  lon?: number | null;
  status: string;
  last_seen?: string | null;
  attributes: Record<string, unknown>;
}

export interface Alarm {
  alarm_id: string;
  tenant: string;
  rule_id: string;
  entity_id: string;
  attribute?: string | null;
  priority: 1 | 2 | 3 | 4;
  state: AlarmState;
  message: string;
  raised_at: string;
  updated_at: string;
  acked_by?: string | null;
  last_value?: number | null;
  occurrences: number;
}

export interface Command {
  command_id: string;
  device_id: string;
  connector_id: string;
  action: string;
  params: Record<string, unknown>;
  requested_by: string;
  requested_at: string;
  ttl_s: number;
}

export interface CommandView {
  command: Command;
  status: 'pending' | 'sent' | 'acked' | 'failed' | 'expired' | 'rejected';
  approved_by?: string | null;
  detail?: string | null;
}

export interface TimeseriesPoint {
  ts: string;
  value?: number;
  avg?: number;
  min?: number;
  max?: number;
}

export interface Timeseries {
  entity_id: string;
  attribute: string;
  interval: 'raw' | '1m' | '1h';
  points: TimeseriesPoint[];
}

export interface PendingAction {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: 'pending' | 'executed' | 'rejected' | 'failed';
  result?: unknown;
}

export interface AssistantReply {
  session_id: string;
  answer: string;
  trace: { tool: string; arguments: Record<string, unknown>; outcome: string }[];
  pending_actions: PendingAction[];
}

export interface TriageSuggestion {
  alarm_id: string;
  summary: string;
  likely_causes: string[];
  recommended_actions: { tool: string; arguments: Record<string, unknown>; reason: string }[];
  references: string[];
  confidence: number;
  generated_by: 'llm' | 'fallback';
}

export interface FlowDraft {
  flow: Record<string, unknown>[];
  explanation: string;
  warnings: string[];
  status: 'draft';
}

export interface Webhook {
  id: string;
  url: string;
  topics: string[];
  filter: Record<string, unknown>;
}

/** Which operator actions are valid in each ISA-18.2 state (mirrors alarm-service). */
export function alarmActions(state: AlarmState): ('ack' | 'shelve' | 'clear')[] {
  switch (state) {
    case 'active_unack':
      return ['ack', 'shelve', 'clear'];
    case 'cleared_unack':
      return ['ack', 'clear'];
    case 'active_ack':
      return ['shelve', 'clear'];
    case 'shelved':
      return ['clear'];
    default:
      return [];
  }
}
