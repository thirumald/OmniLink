import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideOAuthClient } from 'angular-oauth2-oidc';
import { provideEchartsCore } from 'ngx-echarts';
import { routes } from './app.routes';
import { apiInterceptor } from './core/api.interceptor';
import { AuthService } from './core/auth.service';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptors([apiInterceptor])),
    provideOAuthClient(),
    provideEchartsCore({ echarts: () => import('echarts') }),
    provideAppInitializer(() => inject(AuthService).init()),
  ],
};
