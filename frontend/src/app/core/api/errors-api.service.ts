import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { APP_CONFIG } from '../config';
import type { ErrorDetail, ErrorsPage, FingerprintStatus, Occurrences } from './models/errors';

@Injectable({ providedIn: 'root' })
export class ErrorsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(APP_CONFIG).apiBaseUrl;

  list(opts: { page: number; pageSize: number; statuses: FingerprintStatus[]; sort?: string }) {
    let params = new HttpParams().set('page', opts.page).set('page_size', opts.pageSize);
    for (const s of opts.statuses) params = params.append('status', s);
    if (opts.sort) params = params.set('sort', opts.sort);
    return this.http.get<ErrorsPage>(`${this.base}/errors`, { params });
  }

  get(id: string) {
    return this.http.get<ErrorDetail>(`${this.base}/errors/${encodeURIComponent(id)}`);
  }

  occurrences(id: string, bucket: 'hour' | 'day', from: string, to: string) {
    const params = new HttpParams().set('bucket', bucket).set('from', from).set('to', to);
    return this.http.get<Occurrences>(`${this.base}/errors/${encodeURIComponent(id)}/occurrences`, { params });
  }
}
