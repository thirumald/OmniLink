import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AssistantPanel } from '../features/assistant/assistant-panel';
import { AuthService } from '../core/auth.service';
import { I18nService } from '../core/i18n.service';
import { RealtimeService } from '../core/realtime.service';

interface NavItem {
  path: string;
  key: string;
  icon: string;
  role?: 'operator' | 'supervisor' | 'integrator';
}

@Component({
  selector: 'ol-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AssistantPanel],
  template: `
    <div class="shell" [class.with-assistant]="assistantOpen()">
      <aside class="nav">
        <div class="brand"><span class="logo">◎</span> OmniLink</div>
        <nav>
          @for (item of nav; track item.path) {
            @if (!item.role || auth.has(item.role)) {
              <a [routerLink]="item.path" routerLinkActive="active">
                <span class="icon" aria-hidden="true">{{ item.icon }}</span>{{ i18n.t(item.key) }}
              </a>
            }
          }
        </nav>
        <div class="foot muted">
          <span class="dot" [class.on]="rt.connected() || auth.devMode"></span>
          {{ auth.devMode ? 'dev mode' : rt.connected() ? 'live' : 'offline' }}
        </div>
      </aside>

      <header class="top">
        <div class="tenant">{{ auth.tenant() }}</div>
        <div class="spacer"></div>
        <button class="ghost" (click)="i18n.toggle()" [attr.aria-label]="'language'">
          {{ i18n.lang() === 'en' ? 'العربية' : 'English' }}
        </button>
        <button class="primary" (click)="assistantOpen.set(!assistantOpen())">✦ {{ i18n.t('assistant') }}</button>
        <span class="user">{{ auth.user() }}</span>
        @if (!auth.devMode) {
          <button class="ghost" (click)="auth.logout()">{{ i18n.t('logout') }}</button>
        }
      </header>

      <main class="content"><router-outlet /></main>

      @if (assistantOpen()) {
        <ol-assistant-panel class="assistant" (closed)="assistantOpen.set(false)" />
      }
    </div>
  `,
  styles: `
    .shell { display: grid; grid-template-columns: 220px 1fr; grid-template-rows: 56px 1fr; height: 100vh; }
    .shell.with-assistant { grid-template-columns: 220px 1fr 400px; }
    .nav { grid-row: 1 / 3; background: var(--surface-2); border-inline-end: 1px solid var(--border); display: flex; flex-direction: column; }
    .brand { height: 56px; display: flex; align-items: center; gap: 8px; padding-inline: 18px; font-weight: 700; font-size: 17px; }
    .logo { color: var(--accent); font-size: 20px; }
    nav { display: flex; flex-direction: column; padding: 8px; gap: 2px; }
    nav a { display: flex; gap: 10px; align-items: center; padding: 9px 12px; border-radius: 8px; color: var(--text-2); text-decoration: none; }
    nav a:hover { background: var(--surface-3); color: var(--text); }
    nav a.active { background: var(--accent-soft); color: var(--text); }
    .icon { width: 18px; text-align: center; }
    .foot { margin-top: auto; padding: 14px 18px; font-size: 12px; display: flex; align-items: center; gap: 8px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--critical); }
    .dot.on { background: var(--good); }
    .top { display: flex; align-items: center; gap: 10px; padding-inline: 20px; border-bottom: 1px solid var(--border); }
    .tenant { font-weight: 600; text-transform: capitalize; }
    .spacer { flex: 1; }
    .user { color: var(--text-2); font-size: 13px; }
    .content { overflow: auto; padding: 20px; }
    .assistant { grid-column: 3; grid-row: 1 / 3; border-inline-start: 1px solid var(--border); }
  `,
})
export class Shell {
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  protected readonly rt = inject(RealtimeService);
  protected readonly assistantOpen = signal(false);

  protected readonly nav: NavItem[] = [
    { path: '/dashboard', key: 'dashboard', icon: '▦' },
    { path: '/map', key: 'map', icon: '⌖' },
    { path: '/devices', key: 'devices', icon: '◫' },
    { path: '/alarms', key: 'alarms', icon: '⚑' },
    { path: '/commands', key: 'commands', icon: '⇄', role: 'operator' },
    { path: '/automation', key: 'automation', icon: '⚙', role: 'integrator' },
    { path: '/integrations', key: 'integrations', icon: '⇋', role: 'integrator' },
  ];

  constructor() {
    this.rt.connect();
  }
}
