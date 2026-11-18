import { DatePipe } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { EChartsCoreOption } from 'echarts/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, of, switchMap, timer } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { Alarm, Device } from '../../core/models';
import { CityMap } from '../map/city-map';

const POLL_MS = 15_000;

@Component({
  selector: 'ol-dashboard',
  imports: [NgxEchartsDirective, RouterLink, DatePipe, CityMap],
  template: `
    <h1>{{ i18n.t('dashboard') }}</h1>
    <section class="kpis">
      <div class="card kpi"><span class="muted">{{ i18n.t('open_alarms') }}</span><b>{{ alarms().length }}</b></div>
      <div class="card kpi crit"><span class="muted">{{ i18n.t('critical') }}</span><b>{{ p1() }}</b></div>
      <div class="card kpi"><span class="muted">{{ i18n.t('devices_total') }}</span><b>{{ devices().length }}</b></div>
      <div class="card kpi warn"><span class="muted">{{ i18n.t('offline') }}</span><b>{{ offline() }}</b></div>
    </section>

    <section class="grid">
      <div class="card map-card">
        <ol-city-map [devices]="devices()" [alarmedEntities]="alarmedEntities()" />
      </div>
      <div class="card">
        <h3>{{ i18n.t('alarms') }} · {{ i18n.t('priority') }}</h3>
        <div echarts [options]="byPriority()" class="chart"></div>
      </div>
      <div class="card wide">
        <h3>{{ i18n.t('open_alarms') }}</h3>
        <table>
          <thead><tr><th>{{ i18n.t('priority') }}</th><th>{{ i18n.t('message') }}</th><th>{{ i18n.t('entity') }}</th><th>{{ i18n.t('raised') }}</th></tr></thead>
          <tbody>
            @for (a of alarms().slice(0, 8); track a.alarm_id) {
              <tr><td><span class="prio p{{ a.priority }}">P{{ a.priority }}</span></td><td>{{ a.message }}</td>
                <td class="mono">{{ a.entity_id.split(':').slice(-1)[0] }}</td><td>{{ a.raised_at | date: 'short' }}</td></tr>
            } @empty {
              <tr><td colspan="4" class="muted">{{ i18n.t('no_data') }}</td></tr>
            }
          </tbody>
        </table>
        <a routerLink="/alarms">{{ i18n.t('alarms') }} →</a>
      </div>
    </section>
  `,
  styles: `
    .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 14px; }
    .kpi { display: flex; flex-direction: column; gap: 6px; }
    .kpi b { font-size: 30px; font-weight: 700; }
    .kpi.crit b { color: var(--critical); }
    .kpi.warn b { color: var(--warning); }
    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
    .map-card { height: 420px; padding: 0; overflow: hidden; }
    .chart { height: 360px; }
    .wide { grid-column: 1 / -1; }
  `,
})
export class Dashboard {
  private readonly api = inject(ApiService);
  protected readonly i18n = inject(I18nService);

  protected readonly alarms = toSignal(
    timer(0, POLL_MS).pipe(switchMap(() => this.api.alarms('open').pipe(catchError(() => of([] as Alarm[]))))),
    { initialValue: [] as Alarm[] },
  );
  protected readonly devices = toSignal(
    timer(0, 60_000).pipe(switchMap(() => this.api.devices({ limit: 5000 }).pipe(catchError(() => of([] as Device[]))))),
    { initialValue: [] as Device[] },
  );
  protected readonly p1 = computed(() => this.alarms().filter((a) => a.priority === 1).length);
  protected readonly offline = computed(() => this.devices().filter((d) => d.status === 'offline').length);
  protected readonly alarmedEntities = computed(() => this.alarms().map((a) => a.entity_id));
  protected readonly byPriority = computed<EChartsCoreOption>(() => {
    const counts = [1, 2, 3, 4].map((p) => this.alarms().filter((a) => a.priority === p).length);
    return {
      grid: { left: 36, right: 12, top: 12, bottom: 28 },
      xAxis: { type: 'category', data: ['P1', 'P2', 'P3', 'P4'], axisLabel: { color: '#94a3b8' } },
      yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      series: [{ type: 'bar', data: counts.map((v, i) => ({ value: v, itemStyle: { color: ['#ef4444', '#f59e0b', '#38bdf8', '#64748b'][i] } })), barWidth: '45%' }],
      tooltip: { trigger: 'axis' },
    };
  });
}
