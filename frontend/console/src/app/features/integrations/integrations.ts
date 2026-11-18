import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { Webhook } from '../../core/models';

const TOPICS = ['omnilink.alarms.v1', 'omnilink.events.v1', 'omnilink.telemetry.enriched.v1', 'omnilink.ai-suggestions.v1'];

@Component({
  selector: 'ol-integrations',
  imports: [FormsModule],
  template: `
    <h1>{{ i18n.t('integrations') }}</h1>
    <div class="card">
      <h3>{{ i18n.t('webhooks') }}</h3>
      <table>
        <thead><tr><th>URL</th><th>Topics</th><th>Filter</th><th></th></tr></thead>
        <tbody>
          @for (w of hooks(); track w.id) {
            <tr><td class="mono">{{ w.url }}</td><td>{{ w.topics.join(', ') }}</td><td class="mono small">{{ stringify(w.filter) }}</td>
              <td><button class="ghost" (click)="remove(w)">{{ i18n.t('delete') }}</button></td></tr>
          } @empty { <tr><td colspan="4" class="muted">{{ i18n.t('no_data') }}</td></tr> }
        </tbody>
      </table>
      <form class="add" (ngSubmit)="add()">
        <input name="name" [(ngModel)]="name" placeholder="Name" required />
        <input name="url" [(ngModel)]="url" placeholder="https://partner.example/hook" required />
        <input name="secret" [(ngModel)]="secret" placeholder="Signing secret (≥ 24 chars)" type="password" required />
        <select name="topic" [(ngModel)]="topic">@for (t of topics; track t) { <option [value]="t">{{ t }}</option> }</select>
        <input name="minp" [(ngModel)]="minPriority" type="number" min="1" max="4" placeholder="max priority" />
        <button class="primary" type="submit">{{ i18n.t('add') }}</button>
      </form>
      @if (error()) { <p class="err">{{ error() }}</p> }
      <p class="muted small">Deliveries are signed: X-OmniLink-Signature = sha256 HMAC of "timestamp.body". See docs/layers/08-api-integration.md.</p>
    </div>
  `,
  styles: `
    .add { display: grid; grid-template-columns: 1fr 2fr 1.5fr 1.5fr 110px auto; gap: 8px; margin-top: 12px; }
    .small { font-size: 12px; }
    .err { color: var(--critical); }
  `,
})
export class Integrations {
  private readonly api = inject(ApiService);
  protected readonly i18n = inject(I18nService);
  protected readonly hooks = signal<Webhook[]>([]);
  protected readonly error = signal('');
  protected readonly topics = TOPICS;
  protected name = '';
  protected url = '';
  protected secret = '';
  protected topic = TOPICS[0];
  protected minPriority: number | null = 2;

  constructor() {
    this.load();
  }

  stringify(v: unknown): string {
    return JSON.stringify(v);
  }

  add(): void {
    const filter = this.minPriority ? { min_priority: Number(this.minPriority) } : {};
    this.api.createWebhook({ name: this.name, url: this.url, secret: this.secret, topics: [this.topic], filter }).subscribe({
      next: () => {
        this.secret = '';
        this.error.set('');
        this.load();
      },
      error: (e) => this.error.set(typeof e.error?.detail === 'string' ? e.error.detail : 'Invalid webhook'),
    });
  }

  remove(w: Webhook): void {
    this.api.deleteWebhook(w.id).subscribe(() => this.load());
  }

  private load(): void {
    this.api.webhooks().subscribe({ next: (x) => this.hooks.set(x), error: () => this.hooks.set([]) });
  }
}
