import { Injectable, computed, inject, signal } from '@angular/core';
import { OAuthService } from 'angular-oauth2-oidc';
import { OMNILINK_CONFIG } from './config';

export type Role = 'viewer' | 'operator' | 'supervisor' | 'integrator' | 'platform-admin';

const IMPLIES: Record<string, Role[]> = {
  'platform-admin': ['viewer', 'operator', 'supervisor', 'integrator', 'platform-admin'],
  supervisor: ['supervisor', 'operator', 'viewer'],
  operator: ['operator', 'viewer'],
  integrator: ['integrator', 'viewer'],
  viewer: ['viewer'],
};

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly config = inject(OMNILINK_CONFIG);
  private readonly oauth = inject(OAuthService, { optional: true });

  readonly user = signal('');
  readonly tenant = signal('');
  readonly roles = signal<string[]>([]);
  readonly ready = signal(false);
  readonly granted = computed(() => new Set(this.roles().flatMap((r) => IMPLIES[r] ?? [])));

  get devMode(): boolean {
    return !!this.config.devAuth;
  }

  async init(): Promise<void> {
    const dev = this.config.devAuth;
    if (dev) {
      this.user.set(dev.user);
      this.tenant.set(dev.tenant);
      this.roles.set(dev.roles.split(','));
      this.ready.set(true);
      return;
    }
    if (!this.oauth) return;
    this.oauth.configure({
      issuer: this.config.issuer,
      clientId: this.config.clientId,
      redirectUri: window.location.origin + '/',
      responseType: 'code',
      scope: 'openid profile email',
      requireHttps: false,
      showDebugInformation: false,
    });
    this.oauth.setupAutomaticSilentRefresh();
    await this.oauth.loadDiscoveryDocumentAndLogin();
    const claims = this.decode(this.oauth.getAccessToken());
    this.user.set(claims['preferred_username'] ?? claims['sub'] ?? '');
    this.tenant.set(claims['tenant'] ?? '');
    this.roles.set(claims['realm_access']?.roles ?? []);
    this.ready.set(true);
  }

  has(role: Role): boolean {
    return this.granted().has(role);
  }

  token(): string | null {
    return this.oauth?.getAccessToken() ?? null;
  }

  devHeaders(): Record<string, string> {
    const d = this.config.devAuth;
    return d ? { 'x-user': d.user, 'x-tenant': d.tenant, 'x-roles': d.roles } : {};
  }

  logout(): void {
    this.oauth?.logOut();
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private decode(token: string): Record<string, any> {
    try {
      return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    } catch {
      return {};
    }
  }
}
