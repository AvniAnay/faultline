import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import {
  INCLUDE_BEARER_TOKEN_INTERCEPTOR_CONFIG,
  includeBearerTokenInterceptor,
  provideKeycloak,
} from 'keycloak-angular';
import { routes } from './app.routes';
import { APP_CONFIG, AppConfig } from './core/config';
import { errorInterceptor } from './core/http/error.interceptor';

const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export const buildAppConfig = (config: AppConfig): ApplicationConfig => ({
  providers: [
    provideBrowserGlobalErrorListeners(),
    { provide: APP_CONFIG, useValue: config },
    provideKeycloak({
      config: config.keycloak,
      initOptions: { onLoad: 'login-required', pkceMethod: 'S256' },
    }),
    {
      // Bearer token only for requests to our API.
      provide: INCLUDE_BEARER_TOKEN_INTERCEPTOR_CONFIG,
      useValue: [{ urlPattern: new RegExp('^' + escapeRegex(config.apiBaseUrl)) }],
    },
    provideHttpClient(withInterceptors([includeBearerTokenInterceptor, errorInterceptor])),
    provideRouter(routes, withComponentInputBinding()),
  ],
});
