import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ErrorsApiService } from '../../core/api/errors-api.service';
import type { ErrorDetail, OccurrencePoint } from '../../core/api/models/errors';
import type { ReviewUpdate } from '../../core/api/models/reviews';
import { ReviewsApiService } from '../../core/api/reviews-api.service';
import { errorMessage } from '../../core/util';

@Injectable()
export class ErrorDetailStore {
  private readonly errorsApi = inject(ErrorsApiService);
  private readonly reviewsApi = inject(ReviewsApiService);

  private readonly _detail = signal<ErrorDetail | null>(null);
  private readonly _points = signal<OccurrencePoint[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<string | null>(null);
  private readonly _busy = signal(false);

  readonly detail = this._detail.asReadonly();
  readonly points = this._points.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();
  readonly busy = this._busy.asReadonly();

  async load(id: string) {
    this._loading.set(true);
    this._error.set(null);
    try {
      const to = new Date();
      const from = new Date(to.getTime() - 48 * 3600_000);
      const [detail, occ] = await Promise.all([
        firstValueFrom(this.errorsApi.get(id)),
        firstValueFrom(this.errorsApi.occurrences(id, 'hour', from.toISOString(), to.toISOString())),
      ]);
      this._detail.set(detail);
      this._points.set(occ.points);
    } catch (e) {
      this._error.set(errorMessage(e));
    } finally {
      this._loading.set(false);
    }
  }

  async decide(itemId: string, body: ReviewUpdate) {
    const id = this._detail()?.id;
    this._busy.set(true);
    try {
      await firstValueFrom(this.reviewsApi.update(itemId, body));
      if (id) await this.load(id);
    } catch {
      // toast shown by interceptor
    } finally {
      this._busy.set(false);
    }
  }
}
