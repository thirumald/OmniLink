import { JsonPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { OMNILINK_CONFIG } from '../../core/config';
import { I18nService } from '../../core/i18n.service';
import { FlowDraft } from '../../core/models';

@Component({
  selector: 'ol-automation',
  imports: [FormsModule, JsonPipe],
  template: `
    <div class="bar">
      <h1>{{ i18n.t('automation') }}</h1>
      <a class="button ghost" [href]="config.nodeRedUrl" target="_blank" rel="noopener">{{ i18n.t('open_node_red') }} ↗</a>
    </div>
    <div class="card">
      <h3>✦ {{ i18n.t('draft_workflow') }}</h3>
      <form (ngSubmit)="generate()" class="gen">
        <textarea name="req" [(ngModel)]="request" rows="3" [placeholder]="i18n.t('describe_automation')"></textarea>
        <div class="examples muted">
          @for (ex of examples; track ex) { <button type="button" class="chip" (click)="request = ex">{{ ex }}</button> }
        </div>
        <button class="primary" type="submit" [disabled]="busy() || request.trim().length < 5">{{ i18n.t('generate') }}</button>
      </form>
      @if (error()) { <p class="err">{{ error() }}</p> }
    </div>

    @if (draft(); as d) {
      <div class="card">
        <h3>Draft ({{ d.flow.length }} nodes) — disabled until reviewed in Node-RED</h3>
        <p>{{ d.explanation }}</p>
        @for (w of d.warnings; track w) { <p class="warn">⚠ {{ w }}</p> }
        <div class="row">
          <button class="primary" (click)="download(d)">{{ i18n.t('download') }}</button>
          <button class="ghost" (click)="copy(d)">Copy for Node-RED import</button>
        </div>
        <pre>{{ d.flow | json }}</pre>
      </div>
    }
  `,
  styles: `
    .bar { display: flex; align-items: center; justify-content: space-between; }
    .gen { display: flex; flex-direction: column; gap: 10px; }
    .examples { display: flex; flex-wrap: wrap; gap: 6px; }
    pre { max-height: 420px; overflow: auto; font-size: 12px; background: var(--surface-3); padding: 10px; border-radius: 8px; }
    .warn { color: var(--warning); }
    .err { color: var(--critical); }
  `,
})
export class Automation {
  private readonly api = inject(ApiService);
  protected readonly config = inject(OMNILINK_CONFIG);
  protected readonly i18n = inject(I18nService);
  protected request = '';
  protected readonly draft = signal<FlowDraft | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly examples = [
    'When a flood alarm is raised, point the nearest PTZ cameras to the flood preset and SMS the duty officers',
    'Every hour, send average PM2.5 per district to the open-data webhook',
    'If a streetlight controller goes offline for 10 minutes, notify the maintenance group',
  ];

  generate(): void {
    this.busy.set(true);
    this.error.set('');
    this.api.draftWorkflow(this.request).subscribe({
      next: (d) => {
        this.draft.set(d);
        this.busy.set(false);
      },
      error: (e) => {
        this.error.set(e.error?.detail ?? e.message);
        this.busy.set(false);
      },
    });
  }

  download(d: FlowDraft): void {
    const blob = new Blob([JSON.stringify(d.flow, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'omnilink-flow-draft.json';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  copy(d: FlowDraft): void {
    navigator.clipboard?.writeText(JSON.stringify(d.flow));
  }
}
