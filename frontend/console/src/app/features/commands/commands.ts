import { DatePipe, JsonPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { CommandView } from '../../core/models';

@Component({
  selector: 'ol-commands',
  imports: [DatePipe, JsonPipe],
  template: `
    <h1>{{ i18n.t('commands') }}</h1>
    <h3>{{ i18n.t('pending_approvals') }}</h3>
    <div class="card">
      <table>
        <thead><tr><th>Device</th><th>{{ i18n.t('action') }}</th><th>Params</th><th>By</th><th>At</th><th></th></tr></thead>
        <tbody>
          @for (c of pending(); track c.command.command_id) {
            <tr>
              <td class="mono">{{ c.command.device_id }}</td><td>{{ c.command.action }}</td>
              <td class="mono small">{{ c.command.params | json }}</td><td>{{ c.command.requested_by }}</td>
              <td>{{ c.command.requested_at | date: 'short' }}</td>
              <td>
                @if (auth.has('supervisor') && c.command.requested_by !== auth.user()) {
                  <button class="primary" (click)="approve(c)">{{ i18n.t('approve') }}</button>
                } @else {
                  <span class="muted small">needs another supervisor</span>
                }
              </td>
            </tr>
          } @empty { <tr><td colspan="6" class="muted">{{ i18n.t('no_data') }}</td></tr> }
        </tbody>
      </table>
    </div>
    <h3>Recent</h3>
    <div class="card">
      <table>
        <thead><tr><th>Device</th><th>{{ i18n.t('action') }}</th><th>{{ i18n.t('status') }}</th><th>By</th><th>Approved by</th><th>At</th></tr></thead>
        <tbody>
          @for (c of recent(); track c.command.command_id) {
            <tr><td class="mono">{{ c.command.device_id }}</td><td>{{ c.command.action }}</td><td>{{ c.status }}</td>
              <td>{{ c.command.requested_by }}</td><td>{{ c.approved_by ?? '—' }}</td><td>{{ c.command.requested_at | date: 'short' }}</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `.small { font-size: 12px; }`,
})
export class Commands {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  protected readonly pending = signal<CommandView[]>([]);
  protected readonly recent = signal<CommandView[]>([]);

  constructor() {
    this.load();
  }

  approve(c: CommandView): void {
    this.api.approveCommand(c.command.command_id).subscribe(() => this.load());
  }

  private load(): void {
    this.api.commands('pending').subscribe({ next: (x) => this.pending.set(x), error: () => this.pending.set([]) });
    this.api.commands().subscribe({ next: (x) => this.recent.set(x.slice(0, 50)), error: () => this.recent.set([]) });
  }
}
