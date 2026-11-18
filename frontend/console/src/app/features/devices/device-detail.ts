import { JsonPipe } from '@angular/common';
import { Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { EChartsCoreOption } from 'echarts/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import { of } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { CommandView } from '../../core/models';

@Component({
  selector: 'ol-device-detail',
  imports: [FormsModule, NgxEchartsDirective, JsonPipe],
  template: `
    @if (device.value(); as d) {
      <h1>{{ d.name }} <span class="muted mono small">{{ d.entity_id }}</span></h1>
      <section class="grid">
        <div class="card">
          <h3>{{ i18n.t('history') }}</h3>
          <div class="row">
            <select (change)="attr.set($any($event.target).value)" aria-label="attribute">
              @for (a of attributes(); track a) {
                <option [value]="a" [selected]="a === (attr() || attributes()[0])">{{ a }}</option>
              }
            </select>
            <select [(ngModel)]="range" (ngModelChange)="rangeSig.set($event)">
              <option value="-24h">24 h</option><option value="-7d">7 d</option><option value="-30d">30 d</option>
            </select>
          </div>
          <div echarts [options]="chart()" class="chart"></div>
        </div>
        <div class="card">
          <h3>{{ i18n.t('status') }}</h3>
          <dl>
            <dt>{{ i18n.t('type') }}</dt><dd>{{ d.entity_type }}</dd>
            <dt>{{ i18n.t('status') }}</dt><dd><span class="status {{ d.status }}">{{ d.status }}</span></dd>
            <dt>Vendor</dt><dd>{{ d.vendor }} {{ d.model }}</dd>
            <dt>Site</dt><dd>{{ d.site_path }}</dd>
            <dt>Connector</dt><dd class="mono">{{ d.connector_id }}</dd>
          </dl>
          <pre class="attrs">{{ d.attributes | json }}</pre>

          @if (auth.has('operator') && d.connector_id) {
            <h3>{{ i18n.t('send_command') }}</h3>
            <form (ngSubmit)="send(d.id, d.connector_id!)" class="cmd">
              <label>{{ i18n.t('action') }}
                <input name="action" [(ngModel)]="action" placeholder="ptz.goto_preset, write_point…" required />
              </label>
              <label>{{ i18n.t('params') }}<textarea name="params" [(ngModel)]="paramsText" rows="3"></textarea></label>
              <button class="primary" type="submit">{{ i18n.t('send') }}</button>
            </form>
            @if (lastCommand(); as c) {
              <p class="muted">→ {{ c.status }} {{ c.detail ?? '' }}</p>
            }
          }
        </div>
      </section>
    } @else if (device.error()) {
      <p class="muted">Device not found.</p>
    }
  `,
  styles: `
    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
    .chart { height: 340px; }
    .small { font-size: 12px; font-weight: 400; }
    dl { display: grid; grid-template-columns: 110px 1fr; gap: 6px 10px; margin: 0 0 12px; }
    dt { color: var(--text-2); }
    dd { margin: 0; }
    .attrs { font-size: 12px; background: var(--surface-3); padding: 8px; border-radius: 6px; max-height: 160px; overflow: auto; }
    .cmd { display: flex; flex-direction: column; gap: 8px; }
    label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-2); }
  `,
})
export class DeviceDetail {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  readonly id = input.required<string>(); // bound from the route param

  protected range = '-24h';
  protected action = '';
  protected paramsText = '{}';
  protected readonly attr = signal('');
  protected readonly rangeSig = signal('-24h');
  protected readonly lastCommand = signal<CommandView | null>(null);

  protected readonly device = rxResource({ params: () => this.id(), stream: ({ params }) => this.api.device(params) });
  protected readonly attributes = computed(() => {
    const d = this.device.value();
    const fromAttrs = (d?.attributes?.['telemetry'] as string[] | undefined) ?? [];
    return fromAttrs.length ? fromAttrs : ['value'];
  });
  private readonly series = rxResource({
    params: () => ({ d: this.device.value(), a: this.attr() || this.attributes()[0], r: this.rangeSig() }),
    stream: ({ params }) =>
      params.d ? this.api.timeseries(params.d.entity_id, params.a, params.r, params.r === '-24h' ? '1m' : '1h') : of(null),
  });
  protected readonly chart = computed<EChartsCoreOption>(() => {
    const pts = this.series.value()?.points ?? [];
    return {
      grid: { left: 44, right: 16, top: 16, bottom: 30 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'time', axisLabel: { color: '#94a3b8' } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      series: [
        { type: 'line', showSymbol: false, data: pts.map((p) => [p.ts, p.avg ?? p.value]), lineStyle: { width: 1.5 } },
        ...(pts[0]?.min !== undefined
          ? [{ type: 'line', showSymbol: false, data: pts.map((p) => [p.ts, p.max]), lineStyle: { opacity: 0.3 } },
             { type: 'line', showSymbol: false, data: pts.map((p) => [p.ts, p.min]), lineStyle: { opacity: 0.3 } }]
          : []),
      ],
    };
  });

  send(deviceId: string, connectorId: string): void {
    let params: Record<string, unknown> = {};
    try {
      params = JSON.parse(this.paramsText || '{}');
    } catch {
      this.lastCommand.set({ status: 'rejected', detail: 'parameters are not valid JSON' } as CommandView);
      return;
    }
    this.api.sendCommand(deviceId, { connector_id: connectorId, action: this.action.trim(), params }).subscribe({
      next: (c) => this.lastCommand.set(c),
      error: (e) => this.lastCommand.set({ status: 'rejected', detail: e.error?.detail ?? e.message } as CommandView),
    });
  }
}
