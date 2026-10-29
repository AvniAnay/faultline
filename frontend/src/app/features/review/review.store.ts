import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import type { PendingReviews, ReviewUpdate } from '../../core/api/models/reviews';
import { ReviewsApiService } from '../../core/api/reviews-api.service';
import { errorMessage } from '../../core/util';
import { ToastService } from '../../shared/ui/toast.service';

@Injectable()
export class ReviewStore {
  private readonly api = inject(ReviewsApiService);
  private readonly toast = inject(ToastService);

  private readonly _data = signal<PendingReviews>({ runs: [] });
  private readonly _loading = signal(false);
  private readonly _error = signal<string | null>(null);
  private readonly _busyIds = signal<ReadonlySet<string>>(new Set());

  readonly groups = computed(() => this._data().runs);
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();
  readonly busyIds = this._busyIds.asReadonly();

  async load() {
    this._loading.set(true);
    this._error.set(null);
    try {
      this._data.set(await firstValueFrom(this.api.pending()));
    } catch (e) {
      this._error.set(errorMessage(e));
    } finally {
      this._loading.set(false);
    }
  }

  async decide(itemId: string, body: ReviewUpdate) {
    this._busyIds.update((s) => new Set(s).add(itemId));
    try {
      const updated = await firstValueFrom(this.api.update(itemId, body));
      this._data.update((d) => ({
        runs: d.runs.map((g) => ({ ...g, items: g.items.map((i) => (i.id === itemId ? updated : i)) })),
      }));
    } catch {
      // toast shown by interceptor
    } finally {
      this._busyIds.update((s) => {
        const n = new Set(s);
        n.delete(itemId);
        return n;
      });
    }
  }

  async submit(runId: string) {
    try {
      await firstValueFrom(this.api.submit(runId));
      this.toast.show('Review submitted.', 'success');
      await this.load();
    } catch {
      await this.load(); // 422 etc.: toast shown by interceptor; refresh state
    }
  }
}
