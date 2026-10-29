import { HttpErrorResponse } from '@angular/common/http';

export function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    return (err.error as { message?: string } | null)?.message ?? `Request failed (${err.status})`;
  }
  return err instanceof Error ? err.message : 'Unexpected error';
}
