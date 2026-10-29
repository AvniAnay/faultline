import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UiBadge } from '../../shared/ui/badge';
import { UiChart } from '../../shared/ui/chart';
import { ReviewItemCard } from '../review/review-item';
import { ErrorDetailStore } from './error-detail.store';

@Component({
  selector: 'app-error-detail-page',
  imports: [DatePipe, RouterLink, UiBadge, UiChart, ReviewItemCard],
  providers: [ErrorDetailStore],
  templateUrl: './error-detail-page.html',
})
export class ErrorDetailPage {
  readonly id = input.required<string>();
  protected readonly store = inject(ErrorDetailStore);

  protected readonly chartOption = computed(() => {
    const css = getComputedStyle(document.documentElement);
    return {
      color: [css.getPropertyValue('--color-accent').trim()],
      grid: { left: 40, right: 16, top: 16, bottom: 32 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: this.store.points().map((p) =>
          new Date(p.bucket_start).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit' }),
        ),
      },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', name: 'Occurrences', data: this.store.points().map((p) => p.count) }],
    };
  });

  constructor() {
    effect(() => void this.store.load(this.id()));
  }
}
