import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { Device } from '../../core/models';

@Component({
  selector: 'ol-devices',
  imports: [RouterLink],
  template: `
    <div class="bar">
      <h1>{{ i18n.t('devices') }}</h1>
      <input type="search" [placeholder]="i18n.t('search')" (input)="q.set($any($event.target).value)" />
    </div>
    <div class="card">
      <table>
        <thead><tr><th>ID</th><th>Name</th><th>{{ i18n.t('type') }}</th><th>Site</th><th>Connector</th><th>{{ i18n.t('status') }}</th></tr></thead>
        <tbody>
          @for (d of filtered(); track d.id) {
            <tr>
              <td class="mono"><a [routerLink]="['/devices', d.id]">{{ d.id }}</a></td>
              <td>{{ d.name }}</td><td>{{ d.entity_type }}</td><td class="muted">{{ d.site_path }}</td>
              <td class="mono muted">{{ d.connector_id }}</td>
              <td><span class="status {{ d.status }}">{{ d.status }}</span></td>
            </tr>
          } @empty {
            <tr><td colspan="6" class="muted">{{ i18n.t('no_data') }}</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `.bar { display: flex; align-items: center; justify-content: space-between; } input { width: 280px; }`,
})
export class Devices {
  private readonly api = inject(ApiService);
  protected readonly i18n = inject(I18nService);
  protected readonly q = signal('');
  private readonly devices = toSignal(this.api.devices({ limit: 5000 }).pipe(catchError(() => of([] as Device[]))), {
    initialValue: [] as Device[],
  });
  protected readonly filtered = computed(() => {
    const q = this.q().toLowerCase();
    return this.devices().filter((d) => !q || `${d.id} ${d.name} ${d.entity_type} ${d.site_path ?? ''}`.toLowerCase().includes(q));
  });
}
