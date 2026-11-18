import { AfterViewInit, Component, ElementRef, OnDestroy, effect, inject, input, output, viewChild } from '@angular/core';
import maplibregl, { GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import type { FeatureCollection } from 'geojson';
import { OMNILINK_CONFIG } from '../../core/config';
import { Device } from '../../core/models';

/** Device map: one GeoJSON layer coloured by status, red halo on devices with open alarms. */
@Component({
  selector: 'ol-city-map',
  template: `<div #host class="map"></div>`,
  styles: `:host { display: block; height: 100%; min-height: 360px; } .map { width: 100%; height: 100%; border-radius: 10px; }`,
})
export class CityMap implements AfterViewInit, OnDestroy {
  private readonly config = inject(OMNILINK_CONFIG);
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  readonly devices = input<Device[]>([]);
  readonly alarmedEntities = input<string[]>([]);
  readonly selected = output<Device>();
  private map?: MlMap;
  private loaded = false;

  constructor() {
    effect(() => {
      const data = this.toGeoJson(this.devices(), new Set(this.alarmedEntities()));
      if (this.loaded) (this.map?.getSource('devices') as GeoJSONSource | undefined)?.setData(data);
    });
  }

  ngAfterViewInit(): void {
    this.map = new maplibregl.Map({
      container: this.host().nativeElement,
      style: this.config.mapStyle,
      center: this.config.mapCenter,
      zoom: 12,
      attributionControl: { compact: true },
    });
    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
    this.map.on('load', () => {
      const m = this.map!;
      m.addSource('devices', { type: 'geojson', data: this.toGeoJson(this.devices(), new Set(this.alarmedEntities())) });
      m.addLayer({
        id: 'alarm-halo', type: 'circle', source: 'devices', filter: ['==', ['get', 'alarmed'], true],
        paint: { 'circle-radius': 14, 'circle-color': '#ef4444', 'circle-opacity': 0.25 },
      });
      m.addLayer({
        id: 'devices', type: 'circle', source: 'devices',
        paint: {
          'circle-radius': 6,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#0b1220',
          'circle-color': ['match', ['get', 'status'], 'online', '#22c55e', 'offline', '#ef4444', 'degraded', '#f59e0b', '#94a3b8'],
        },
      });
      m.on('click', 'devices', (e) => {
        const id = e.features?.[0]?.properties?.['id'];
        const d = this.devices().find((x) => x.id === id);
        if (!d) return;
        new maplibregl.Popup({ offset: 10 })
          .setLngLat([d.lon!, d.lat!])
          .setHTML(`<strong>${escapeHtml(d.name)}</strong><br>${escapeHtml(d.entity_type)} · ${escapeHtml(d.status)}`)
          .addTo(m);
        this.selected.emit(d);
      });
      m.on('mouseenter', 'devices', () => (m.getCanvas().style.cursor = 'pointer'));
      m.on('mouseleave', 'devices', () => (m.getCanvas().style.cursor = ''));
      this.loaded = true;
    });
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  private toGeoJson(devices: Device[], alarmed: Set<string>): FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: devices
        .filter((d) => d.lat != null && d.lon != null)
        .map((d) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [d.lon!, d.lat!] },
          properties: { id: d.id, status: d.status, type: d.entity_type, alarmed: alarmed.has(d.entity_id) },
        })),
    };
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}
