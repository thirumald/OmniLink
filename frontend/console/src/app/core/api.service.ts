import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  Alarm,
  AssistantReply,
  CommandView,
  Device,
  FlowDraft,
  PendingAction,
  Timeseries,
  TriageSuggestion,
  Webhook,
} from './models';

function params(obj: Record<string, string | number | undefined | null>): HttpParams {
  let p = new HttpParams();
  for (const [k, v] of Object.entries(obj)) if (v !== undefined && v !== null && v !== '') p = p.set(k, String(v));
  return p;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  // ---- assets
  devices(q: { type?: string; near?: string; radius_m?: number; limit?: number } = {}): Observable<Device[]> {
    return this.http.get<Device[]>('/v1/devices', { params: params(q) });
  }
  device(id: string): Observable<Device> {
    return this.http.get<Device>(`/v1/devices/${encodeURIComponent(id)}`);
  }

  // ---- telemetry
  timeseries(entityId: string, attribute: string, from = '-24h', interval: 'raw' | '1m' | '1h' = '1h'): Observable<Timeseries> {
    return this.http.get<Timeseries>('/v1/timeseries', {
      params: params({ entity_id: entityId, attribute, from, to: 'now', interval }),
    });
  }

  // ---- alarms
  alarms(state = 'open', priorityMax = 4): Observable<Alarm[]> {
    return this.http.get<Alarm[]>('/v1/alarms', { params: params({ state, priority_max: priorityMax }) });
  }
  alarmAction(id: string, action: 'ack' | 'shelve' | 'clear', minutes?: number): Observable<Alarm> {
    return this.http.post<Alarm>(`/v1/alarms/${id}/${action}`, action === 'shelve' ? { minutes: minutes ?? 60 } : {});
  }

  // ---- commands
  sendCommand(deviceId: string, body: { connector_id: string; action: string; params: Record<string, unknown>; ttl_s?: number }) {
    return this.http.post<CommandView>(`/v1/devices/${encodeURIComponent(deviceId)}/commands`, body);
  }
  commands(status?: string): Observable<CommandView[]> {
    return this.http.get<CommandView[]>('/v1/commands', { params: params({ status }) });
  }
  approveCommand(id: string): Observable<CommandView> {
    return this.http.post<CommandView>(`/v1/commands/${id}/approve`, {});
  }

  // ---- integration
  webhooks(): Observable<Webhook[]> {
    return this.http.get<Webhook[]>('/v1/webhooks');
  }
  createWebhook(body: { name: string; url: string; secret: string; topics: string[]; filter: Record<string, unknown> }) {
    return this.http.post<{ id: string }>('/v1/webhooks', body);
  }
  deleteWebhook(id: string) {
    return this.http.delete<void>(`/v1/webhooks/${id}`);
  }

  // ---- AI assistant
  chat(message: string, sessionId?: string): Observable<AssistantReply> {
    return this.http.post<AssistantReply>('/v1/assistant/chat', { message, session_id: sessionId });
  }
  decideAction(id: string, approve: boolean): Observable<PendingAction> {
    return this.http.post<PendingAction>(`/v1/assistant/actions/${id}/${approve ? 'approve' : 'reject'}`, {});
  }
  triage(alarmId: string): Observable<TriageSuggestion> {
    return this.http.post<TriageSuggestion>(`/v1/assistant/triage/${alarmId}`, {});
  }
  draftWorkflow(request: string): Observable<FlowDraft> {
    return this.http.post<FlowDraft>('/v1/assistant/workflows/draft', { request });
  }
}
