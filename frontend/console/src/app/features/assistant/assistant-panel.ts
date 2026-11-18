import { JsonPipe } from '@angular/common';
import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { PendingAction } from '../../core/models';

interface Turn {
  role: 'user' | 'assistant';
  text: string;
  trace?: { tool: string; outcome: string }[];
  actions?: PendingAction[];
}

@Component({
  selector: 'ol-assistant-panel',
  imports: [FormsModule, JsonPipe],
  template: `
    <section class="panel">
      <header>
        <strong>✦ {{ i18n.t('assistant') }}</strong>
        <button class="ghost" (click)="closed.emit()" aria-label="close">✕</button>
      </header>
      <p class="muted note">{{ i18n.t('approval_note') }}</p>

      <div class="turns">
        @for (t of turns(); track $index) {
          <div class="turn" [class.me]="t.role === 'user'">
            <div class="bubble">{{ t.text }}</div>
            @if (t.trace?.length) {
              <div class="trace">
                @for (s of t.trace; track $index) {
                  <span class="chip" [class.warn]="s.outcome !== 'ok'">{{ s.tool }} · {{ s.outcome }}</span>
                }
              </div>
            }
            @for (a of t.actions ?? []; track a.id) {
              <div class="action card">
                <div><strong>{{ a.tool }}</strong> <span class="muted">{{ a.status }}</span></div>
                <code>{{ a.arguments | json }}</code>
                @if (a.status === 'pending') {
                  <div class="row">
                    <button class="primary" [disabled]="!auth.has('operator')" (click)="decide(a, true)">{{ i18n.t('approve') }}</button>
                    <button class="ghost" (click)="decide(a, false)">{{ i18n.t('reject') }}</button>
                  </div>
                }
              </div>
            }
          </div>
        }
        @if (busy()) {
          <div class="turn"><div class="bubble muted">…</div></div>
        }
      </div>

      <form (ngSubmit)="send()" class="composer">
        <textarea name="q" [(ngModel)]="draft" rows="2" [placeholder]="i18n.t('ask_placeholder')"
                  (keydown.enter)="$event.preventDefault(); send()"></textarea>
        <button class="primary" type="submit" [disabled]="busy() || !draft.trim()">{{ i18n.t('send') }}</button>
      </form>
    </section>
  `,
  styles: `
    .panel { display: flex; flex-direction: column; height: 100%; background: var(--surface-2); }
    header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
    .note { font-size: 12px; padding: 8px 16px 0; margin: 0; }
    .turns { flex: 1; overflow: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 12px; }
    .turn { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
    .turn.me { align-items: flex-end; }
    .bubble { background: var(--surface-3); padding: 9px 12px; border-radius: 10px; max-width: 95%; white-space: pre-wrap; line-height: 1.45; }
    .me .bubble { background: var(--accent-soft); }
    .trace { display: flex; flex-wrap: wrap; gap: 4px; }
    .action { width: 100%; display: flex; flex-direction: column; gap: 6px; }
    code { font-size: 11.5px; white-space: pre-wrap; color: var(--text-2); }
    .composer { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); }
    textarea { flex: 1; resize: none; }
  `,
})
export class AssistantPanel {
  protected readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  readonly closed = output<void>();

  protected readonly turns = signal<Turn[]>([]);
  protected readonly busy = signal(false);
  protected draft = '';
  private sessionId?: string;

  send(): void {
    const q = this.draft.trim();
    if (!q || this.busy()) return;
    this.draft = '';
    this.turns.update((t) => [...t, { role: 'user', text: q }]);
    this.busy.set(true);
    this.api.chat(q, this.sessionId).subscribe({
      next: (r) => {
        this.sessionId = r.session_id;
        this.turns.update((t) => [...t, { role: 'assistant', text: r.answer, trace: r.trace, actions: r.pending_actions }]);
        this.busy.set(false);
      },
      error: (e) => {
        this.turns.update((t) => [...t, { role: 'assistant', text: `Error: ${e.error?.detail ?? e.message}` }]);
        this.busy.set(false);
      },
    });
  }

  decide(a: PendingAction, approve: boolean): void {
    this.api.decideAction(a.id, approve).subscribe({
      next: (res) => this.patch(a.id, res),
      error: (e) => this.patch(a.id, { ...a, status: 'failed', result: e.error?.detail }),
    });
  }

  private patch(id: string, upd: PendingAction): void {
    this.turns.update((ts) => ts.map((t) => ({ ...t, actions: t.actions?.map((x) => (x.id === id ? { ...x, ...upd } : x)) })));
  }
}
