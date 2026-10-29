import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ErrorsApiService } from '../../core/api/errors-api.service';
import type { ErrorsPage, FingerprintStatus } from '../../core/api/models/errors';
import type { Run } from '../../core/api/models/runs';
import { RunsApiService } from '../../core/api/runs-api.service';
import { errorMessage } from '../../core/util';
import { ToastService } from '../../shared/ui/toast.service';

const POLL_MS = 5000;

@Injectable()
export class ErrorsStore {
  private readonly errorsApi = inject(ErrorsApiService);
  private readonly runsApi = inject(RunsApiService);
  private readonly toast = inject(ToastService);
  private timer?: ReturnType<typeof setInterval>;

  readonly pageSize = 25;
  private readonly _data = signal<ErrorsPage | null>(null);
  private readonly _page = signal(1);
  private readonly _status = signal<FingerprintStatus | ''>('');
  private readonly _loading = signal(false);
  private readonly _error = signal<string | null>(null);
  private readonly _latestRun = signal<Run | null>(null);
  private readonly _triggering = signal(false);

  readonly data = this._data.asReadonly();
  readonly page = this._page.asReadonly();
  readonly status = this._status.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();
  readonly latestRun = this._latestRun.asReadonly();
  readonly triggering = this._triggering.asReadonly();

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  async init() {
    await Promise.all([this.load(), this.refreshRun()]);
  }

  async load() {
    this._loading.set(true);
    this._error.set(null);
    try {
      const status = this._status();
      this._data.set(
        await firstValueFrom(
          this.errorsApi.list({ page: this._page(), pageSize: this.pageSize, statuses: status ? [status] : [] }),
        ),
      );
    } catch (e) {
      this._error.set(errorMessage(e));
    } finally {
      this._loading.set(false);
    }
  }

  setStatus(status: FingerprintStatus | '') {
    this._status.set(status);
    this._page.set(1);
    return this.load();
  }

  setPage(page: number) {
    this._page.set(page);
    return this.load();
  }

  async refreshRun() {
    try {
      const res = await firstValueFrom(this.runsApi.list(1, 1));
      const prev = this._latestRun();
      const run = res.items[0] ?? null;
      this._latestRun.set(run);
      if (run?.status === 'running') {
        this.startPolling();
      } else {
        this.stopPolling();
        if (prev?.status === 'running') void this.load(); // run just finished: refresh table
      }
    } catch {
      this.stopPolling(); // toast already shown by interceptor
    }
  }

  async trigger() {
    this._triggering.set(true);
    try {
      await firstValueFrom(this.runsApi.trigger());
      this.toast.show('Run started. It runs in the background and may take several minutes.', 'success');
      await this.refreshRun();
    } catch (e) {
      if (e instanceof HttpErrorResponse && e.status === 409) {
        this.toast.error('A run is already in progress.');
        await this.refreshRun();
      }
    } finally {
      this._triggering.set(false);
    }
  }

  private startPolling() {
    this.timer ??= setInterval(() => void this.refreshRun(), POLL_MS);
  }

  private stopPolling() {
    clearInterval(this.timer);
    this.timer = undefined;
  }
}
