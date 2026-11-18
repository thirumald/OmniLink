import { Injectable, inject, signal } from '@angular/core';
import { Centrifuge, Subscription } from 'centrifuge';
import { AuthService } from './auth.service';
import { OMNILINK_CONFIG } from './config';
import { Alarm } from './models';

/** Live updates from Centrifugo (fed by the outbound relay from Kafka). */
@Injectable({ providedIn: 'root' })
export class RealtimeService {
  private readonly config = inject(OMNILINK_CONFIG);
  private readonly auth = inject(AuthService);
  private client?: Centrifuge;
  private subs: Subscription[] = [];

  readonly connected = signal(false);
  readonly lastAlarm = signal<Alarm | null>(null);
  readonly lastSuggestion = signal<{ alarm_id: string; summary: string } | null>(null);

  connect(): void {
    if (this.client || this.auth.devMode) return; // dev mode: polling only
    this.client = new Centrifuge(this.config.realtimeUrl, { getToken: async () => this.auth.token() ?? '' });
    this.client.on('connected', () => this.connected.set(true));
    this.client.on('disconnected', () => this.connected.set(false));
    const tenant = this.auth.tenant();
    const alarms = this.client.newSubscription(`alarms:${tenant}`);
    alarms.on('publication', (ctx) => this.lastAlarm.set(ctx.data as Alarm));
    const ai = this.client.newSubscription(`assistant:${tenant}`);
    ai.on('publication', (ctx) => this.lastSuggestion.set(ctx.data));
    this.subs = [alarms, ai];
    this.subs.forEach((s) => s.subscribe());
    this.client.connect();
  }

  disconnect(): void {
    this.subs.forEach((s) => s.unsubscribe());
    this.client?.disconnect();
    this.client = undefined;
  }
}
