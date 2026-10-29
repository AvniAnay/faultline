import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { buildAppConfig } from './app/app.config';
import type { AppConfig } from './app/core/config';

fetch('/config.json')
  .then((r) => {
    if (!r.ok) throw new Error(`config.json: ${r.status}`);
    return r.json() as Promise<AppConfig>;
  })
  .then((config) => bootstrapApplication(App, buildAppConfig(config)))
  .catch((err) => console.error(err));
