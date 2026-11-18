import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { apiInterceptor } from './api.interceptor';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { OMNILINK_CONFIG, DEFAULT_CONFIG } from './config';
import { alarmActions } from './models';

describe('core', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([apiInterceptor])),
        provideHttpClientTesting(),
        {
          provide: OMNILINK_CONFIG,
          useValue: { ...DEFAULT_CONFIG, apiBase: 'http://gw', devAuth: { user: 'op1', tenant: 'abudhabi', roles: 'operator' } },
        },
      ],
    });
  });

  it('prefixes API calls with the gateway and adds dev identity headers', async () => {
    await TestBed.inject(AuthService).init();
    const http = TestBed.inject(HttpTestingController);
    TestBed.inject(ApiService).alarms('open', 2).subscribe();
    const req = http.expectOne((r) => r.url === 'http://gw/v1/alarms');
    expect(req.request.params.get('priority_max')).toBe('2');
    expect(req.request.headers.get('x-tenant')).toBe('abudhabi');
    req.flush([]);
    http.verify();
  });

  it('applies the role hierarchy', async () => {
    const auth = TestBed.inject(AuthService);
    await auth.init();
    expect(auth.has('operator')).toBe(true);
    expect(auth.has('viewer')).toBe(true);
    expect(auth.has('supervisor')).toBe(false);
  });

  it('offers only valid ISA-18.2 actions', () => {
    expect(alarmActions('active_unack')).toEqual(['ack', 'shelve', 'clear']);
    expect(alarmActions('cleared')).toEqual([]);
  });
});
