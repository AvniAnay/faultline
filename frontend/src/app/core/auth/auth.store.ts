import { Injectable, computed, inject, signal } from '@angular/core';
import Keycloak from 'keycloak-js';
import { MeApiService } from '../api/me-api.service';
import type { Me } from '../api/models/me';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly keycloak = inject(Keycloak);
  private readonly meApi = inject(MeApiService);

  private readonly _me = signal<Me | null>(null);
  readonly me = this._me.asReadonly();

  private readonly roles: string[] = this.keycloak.tokenParsed?.realm_access?.roles ?? [];
  readonly isAdmin = signal(this.roles.includes('faultline-admin')).asReadonly();
  readonly isViewer = computed(() => this.isAdmin() || this.roles.includes('faultline-viewer'));
  readonly roleLabel = computed(() => (this.isAdmin() ? 'admin' : 'viewer'));
  readonly displayName = computed(
    () =>
      this._me()?.display_name ??
      this._me()?.email ??
      (this.keycloak.tokenParsed?.['preferred_username'] as string | undefined) ??
      '',
  );

  async loadMe() {
    try {
      this._me.set(await firstValueFrom(this.meApi.get()));
    } catch {
      // error toast is shown by the error interceptor; name falls back to the token
    }
  }

  logout() {
    return this.keycloak.logout({ redirectUri: window.location.origin });
  }
}
