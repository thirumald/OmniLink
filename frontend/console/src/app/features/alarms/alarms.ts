import { DatePipe, PercentPipe } from '@angular/common';
import { Component, effect, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { Alarm, TriageSuggestion, alarmActions } from '../../core/models';
import { RealtimeService } from '../../core/realtime.service';

@Component({
  selector: 'ol-alarms',
  imports: [DatePipe, PercentPipe],
  template: `
    <div class="bar">
      <h1>{{ i18n.t('alarms') }}</h1>
      <div class="row">
        @for (s of states; track s) {
          <button [class.primary]="state() === s" [class.ghost]="state() !== s" (click)="state.set(s)">{{ s }}</button>
        }
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>{{ i18n.t('priority') }}</th><th>{{ i18n.t('message') }}</th><th>{{ i18n.t('entity') }}</th>
          <th>{{ i18n.t('status') }}</th><th>{{ i18n.t('raised') }}</th><th>#</th><th></th></tr></thead>
        <tbody>
          @for (a of alarms(); track a.alarm_id) {
            <tr [class.unack]="a.state.endsWith('unack')">
              <td><span class="prio p{{ a.priority }}">P{{ a.priority }}</span></td>
              <td>{{ a.message }} @if (a.last_value != null) { <span class="muted">({{ a.last_value }})</span> }</td>
              <td class="mono">{{ a.entity_id.split(':').slice(-1)[0] }}</td>
              <td>{{ a.state }}</td>
              <td>{{ a.raised_at | date: 'short' }}</td>
              <td>{{ a.occurrences }}</td>
              <td class="actions">
                @for (act of actionsFor(a); track act) {
                  <button class="ghost" (click)="act_(a, act)">{{ i18n.t(act) }}</button>
                }
                @if (auth.has('operator')) {
                  <button class="ai" (click)="triage(a)">✦ {{ i18n.t('suggest') }}</button>
                }
              </td>
            </tr>
            @if (suggestions()[a.alarm_id]; as s) {
              <tr class="suggestion"><td colspan="7">
                <div class="card inner">
                  <div><strong>✦</strong> {{ s.summary }}
                    <span class="muted">· {{ s.generated_by }} · {{ s.confidence | percent }}</span></div>
                  @if (s.likely_causes.length) { <div class="muted">Causes: {{ s.likely_causes.join('; ') }}</div> }
                  @for (r of s.recommended_actions; track $index) {
                    <div class="rec">→ <b>{{ r.tool }}</b> {{ r.reason }}</div>
                  }
                  @if (s.references.length) { <div class="muted">Runbooks: {{ s.references.join(', ') }}</div> }
                  <div class="muted small">Open the assistant to turn a recommendation into an approved action.</div>
                </div>
              </td></tr>
            }
          } @empty {
            <tr><td colspan="7" class="muted">{{ i18n.t('no_data') }}</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .bar { display: flex; align-items: center; justify-content: space-between; }
    tr.unack td:first-child { box-shadow: inset 3px 0 0 var(--critical); }
    .actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
    .ai { background: var(--accent-soft); border: 1px solid var(--accent); color: var(--text); }
    .inner { background: var(--surface-3); display: flex; flex-direction: column; gap: 4px; }
    .small { font-size: 12px; }
  `,
})
export class Alarms {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  private readonly rt = inject(RealtimeService);
  protected readonly states = ['open', 'active_unack', 'active_ack', 'shelved', 'cleared'];
  protected readonly state = signal('open');
  protected readonly alarms = signal<Alarm[]>([]);
  protected readonly suggestions = signal<Record<string, TriageSuggestion>>({});

  constructor() {
    effect(() => this.load(this.state()));
    effect(() => {
      if (this.rt.lastAlarm()) this.load(this.state()); // live refresh on alarm events
    });
  }

  protected actionsFor(a: Alarm) {
    return alarmActions(a.state).filter((x) => (x === 'ack' ? this.auth.has('operator') : this.auth.has('supervisor')));
  }

  protected act_(a: Alarm, action: 'ack' | 'shelve' | 'clear'): void {
    this.api.alarmAction(a.alarm_id, action, 60).subscribe(() => this.load(this.state()));
  }

  protected triage(a: Alarm): void {
    this.api.triage(a.alarm_id).subscribe((s) => this.suggestions.update((m) => ({ ...m, [a.alarm_id]: s })));
  }

  private load(state: string): void {
    this.api.alarms(state).subscribe({ next: (x) => this.alarms.set(x), error: () => this.alarms.set([]) });
  }
}
