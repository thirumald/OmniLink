import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { catchError, of } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { Alarm, Device } from '../../core/models';
import { CityMap } from './city-map';

@Component({
  selector: 'ol-map-page',
  imports: [CityMap],
  template: `
    <div class="bar">
      <h1>{{ i18n.t('map') }}</h1>
      <select (change)="type.set($any($event.target).value)">
        <option value="">{{ i18n.t('type') }}: all</option>
        @for (t of types(); track t) { <option [value]="t">{{ t }}</option> }
      </select>
    </div>
    <div class="map-wrap card">
      <ol-city-map [devices]="filtered()" [alarmedEntities]="alarmed()" (selected)="open($event)" />
    </div>
  `,
  styles: `
    .bar { display: flex; align-items: center; justify-content: space-between; }
    .map-wrap { height: calc(100vh - 160px); padding: 0; overflow: hidden; }
  `,
})
export class MapPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly i18n = inject(I18nService);
  protected readonly type = signal('');
  private readonly devices = toSignal(this.api.devices({ limit: 5000 }).pipe(catchError(() => of([] as Device[]))), {
    initialValue: [] as Device[],
  });
  private readonly alarms = toSignal(this.api.alarms('open').pipe(catchError(() => of([] as Alarm[]))), {
    initialValue: [] as Alarm[],
  });
  protected readonly types = computed(() => [...new Set(this.devices().map((d) => d.entity_type))].sort());
  protected readonly filtered = computed(() => this.devices().filter((d) => !this.type() || d.entity_type === this.type()));
  protected readonly alarmed = computed(() => this.alarms().map((a) => a.entity_id));

  open(d: Device): void {
    this.router.navigate(['/devices', d.id]);
  }
}
