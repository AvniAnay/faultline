import { InjectionToken } from '@angular/core';

export interface AppConfig {
  apiBaseUrl: string;
  keycloak: { url: string; realm: string; clientId: string };
}

export const APP_CONFIG = new InjectionToken<AppConfig>('APP_CONFIG');
