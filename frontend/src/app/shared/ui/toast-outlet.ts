import { Component, inject } from '@angular/core';
import { ToastService } from './toast.service';

@Component({
  selector: 'ui-toast-outlet',
  template: `
    <div class="fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" role="region" aria-label="Notifications">
      @for (t of toasts.toasts(); track t.id) {
        <div
          class="flex items-start justify-between gap-2 rounded border-l-4 bg-surface p-3 text-sm shadow-lg ring-1 ring-line"
          [class.border-sev-critical]="t.kind === 'error'"
          [class.border-ok]="t.kind === 'success'"
          [class.border-accent]="t.kind === 'info'"
          [attr.role]="t.kind === 'error' ? 'alert' : 'status'"
        >
          <span><strong class="font-semibold">{{ t.kind === 'error' ? 'Error: ' : '' }}</strong>{{ t.text }}</span>
          <button type="button" class="rounded px-1 hover:bg-muted focus-visible:outline-2 focus-visible:outline-accent" aria-label="Dismiss" (click)="toasts.dismiss(t.id)">&times;</button>
        </div>
      }
    </div>
  `,
})
export class ToastOutlet {
  protected readonly toasts = inject(ToastService);
}
