import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { APP_CONFIG } from '../config';
import type { Page } from './models/common';
import type { Run } from './models/runs';

@Injectable({ providedIn: 'root' })
export class RunsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(APP_CONFIG).apiBaseUrl;

  list(page = 1, pageSize = 20) {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.get<Page<Run>>(`${this.base}/runs`, { params });
  }

  trigger() {
    return this.http.post<Run>(`${this.base}/runs/trigger`, {});
  }
}
