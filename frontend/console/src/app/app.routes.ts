import { inject } from '@angular/core';
import { CanActivateFn, Routes } from '@angular/router';
import { AuthService, Role } from './core/auth.service';
import { Shell } from './layout/shell';

const role = (r: Role): CanActivateFn => () => inject(AuthService).has(r);

export const routes: Routes = [
  {
    path: '',
    component: Shell,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', loadComponent: () => import('./features/dashboard/dashboard').then((m) => m.Dashboard) },
      { path: 'map', loadComponent: () => import('./features/map/map-page').then((m) => m.MapPage) },
      { path: 'devices', loadComponent: () => import('./features/devices/devices').then((m) => m.Devices) },
      { path: 'devices/:id', loadComponent: () => import('./features/devices/device-detail').then((m) => m.DeviceDetail) },
      { path: 'alarms', loadComponent: () => import('./features/alarms/alarms').then((m) => m.Alarms) },
      {
        path: 'commands', canActivate: [role('operator')],
        loadComponent: () => import('./features/commands/commands').then((m) => m.Commands),
      },
      {
        path: 'automation', canActivate: [role('integrator')],
        loadComponent: () => import('./features/automation/automation').then((m) => m.Automation),
      },
      {
        path: 'integrations', canActivate: [role('integrator')],
        loadComponent: () => import('./features/integrations/integrations').then((m) => m.Integrations),
      },
      { path: '**', redirectTo: 'dashboard' },
    ],
  },
];
