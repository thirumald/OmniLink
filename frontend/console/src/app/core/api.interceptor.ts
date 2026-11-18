import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';
import { OMNILINK_CONFIG } from './config';

/** Prefixes /v1 calls with the gateway URL and attaches the bearer token (or dev identity headers). */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith('/v1/')) return next(req);
  const auth = inject(AuthService);
  const config = inject(OMNILINK_CONFIG);
  const token = auth.token();
  const setHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : auth.devHeaders();
  return next(req.clone({ url: config.apiBase + req.url, setHeaders }));
};
