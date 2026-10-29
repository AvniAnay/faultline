import { Component, computed, input, output } from '@angular/core';
import { UiButton } from './button';

@Component({
  selector: 'ui-pager',
  imports: [UiButton],
  template: `
    <nav class="flex items-center justify-between gap-2 text-sm" aria-label="Pagination">
      <span>{{ total() }} total &middot; page {{ page() }} of {{ pages() }}</span>
      <span class="flex gap-2">
        <button uiButton [disabled]="page() <= 1" (click)="pageChange.emit(page() - 1)">Previous</button>
        <button uiButton [disabled]="page() >= pages()" (click)="pageChange.emit(page() + 1)">Next</button>
      </span>
    </nav>
  `,
})
export class UiPager {
  readonly page = input.required<number>();
  readonly pageSize = input.required<number>();
  readonly total = input.required<number>();
  readonly pageChange = output<number>();
  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.pageSize())));
}
