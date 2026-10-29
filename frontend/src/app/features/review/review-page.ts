import { DatePipe } from '@angular/common';
import { Component, inject, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthStore } from '../../core/auth/auth.store';
import type { ReviewItem } from '../../core/api/models/reviews';
import { UiBadge } from '../../shared/ui/badge';
import { UiButton } from '../../shared/ui/button';
import { UiDialog } from '../../shared/ui/dialog';
import { ReviewItemCard } from './review-item';
import { ReviewStore } from './review.store';

@Component({
  selector: 'app-review-page',
  imports: [DatePipe, RouterLink, UiBadge, UiButton, UiDialog, ReviewItemCard],
  providers: [ReviewStore],
  templateUrl: './review-page.html',
})
export class ReviewPage {
  protected readonly store = inject(ReviewStore);
  protected readonly auth = inject(AuthStore);
  protected readonly dialog = viewChild.required(UiDialog);
  protected readonly submitRunId = signal<string | null>(null);

  constructor() {
    void this.store.load();
  }

  protected hasPending(items: ReviewItem[]) {
    return items.some((i) => i.decision === 'pending');
  }

  protected count(items: ReviewItem[], d: ReviewItem['decision']) {
    return items.filter((i) => i.decision === d).length;
  }

  protected askSubmit(runId: string) {
    this.submitRunId.set(runId);
    this.dialog().open();
  }

  protected async confirm() {
    const id = this.submitRunId();
    this.dialog().close();
    if (id) await this.store.submit(id);
  }
}
