import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { APP_CONFIG } from '../config';
import type { PendingReviews, ReviewItem, ReviewUpdate } from './models/reviews';
import type { Run } from './models/runs';

@Injectable({ providedIn: 'root' })
export class ReviewsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(APP_CONFIG).apiBaseUrl;

  pending() {
    return this.http.get<PendingReviews>(`${this.base}/reviews/pending`);
  }

  update(itemId: string, body: ReviewUpdate) {
    return this.http.put<ReviewItem>(`${this.base}/review-items/${encodeURIComponent(itemId)}`, body);
  }

  submit(runId: string) {
    return this.http.post<Run>(`${this.base}/runs/${encodeURIComponent(runId)}/review/submit`, {});
  }
}
