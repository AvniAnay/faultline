import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import Keycloak from 'keycloak-js';
import { catchError, throwError } from 'rxjs';
import { APP_CONFIG } from '../config';
import type { ApiErrorBody } from '../api/models/me';
import { ToastService } from '../../shared/ui/toast.service';

/** Shows a toast for failed API calls using the backend's {code, message, details} body. */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const toast = inject(ToastService);
  const keycloak = inject(Keycloak);
  const base = inject(APP_CONFIG).apiBaseUrl;

  return next(req).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && req.url.startsWith(base)) {
        const body = err.error as Partial<ApiErrorBody> | null;
        if (err.status === 401) {
          void keycloak.login();
        } else if (err.status === 403) {
          toast.error('You are not allowed to do that.');
        } else if (err.status === 409 && req.url.endsWith('/runs/trigger')) {
          // handled by the caller with a specific message
        } else if (err.status === 0) {
          toast.error('Cannot reach the server.');
        } else {
          toast.error(body?.message ?? `Request failed (${err.status}).`);
        }
      }
      return throwError(() => err);
    }),
  );
};
