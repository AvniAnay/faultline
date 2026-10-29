import { DatePipe } from '@angular/common';
import { Component, computed, inject, input, output, signal } from '@angular/core';
import { CATEGORIES, SEVERITIES, type Category, type Severity } from '../../core/api/models/errors';
import type { ReviewItem, ReviewUpdate } from '../../core/api/models/reviews';
import { AuthStore } from '../../core/auth/auth.store';
import { UiBadge } from '../../shared/ui/badge';
import { UiButton } from '../../shared/ui/button';

/** One review item: proposal, current decision, and (admin only) approve/reject/edit. Store-agnostic. */
@Component({
  selector: 'app-review-item',
  imports: [DatePipe, UiBadge, UiButton],
  templateUrl: './review-item.html',
})
export class ReviewItemCard {
  readonly item = input.required<ReviewItem>();
  readonly busy = input(false);
  readonly showTemplate = input(true);
  readonly decide = output<ReviewUpdate>();

  protected readonly auth = inject(AuthStore);
  protected readonly severities = SEVERITIES;
  protected readonly categories = CATEGORIES;

  protected readonly editing = signal(false);
  protected readonly comment = signal('');
  protected readonly severity = signal<Severity>('Medium');
  protected readonly category = signal<Category>('Unknown');
  protected readonly summary = signal('');
  protected readonly cause = signal('');
  protected readonly steps = signal('');

  protected readonly current = computed(() => {
    const it = this.item();
    return {
      severity: it.edited?.severity ?? it.proposed.severity,
      category: it.edited?.category ?? it.proposed.category,
    };
  });

  protected startEdit() {
    const it = this.item();
    const r = { ...it.proposed.resolution, ...it.edited?.resolution };
    this.severity.set(this.current().severity);
    this.category.set(this.current().category);
    this.summary.set(r.summary);
    this.cause.set(r.probable_cause);
    this.steps.set(r.steps.join('\n'));
    this.editing.set(true);
  }

  protected send(decision: 'approved' | 'rejected') {
    this.decide.emit({ decision, ...this.commentPart() });
  }

  protected saveEdit() {
    this.decide.emit({
      decision: 'edited',
      edited: {
        severity: this.severity(),
        category: this.category(),
        resolution: {
          summary: this.summary(),
          probable_cause: this.cause(),
          steps: this.steps().split('\n').map((s) => s.trim()).filter(Boolean),
        },
      },
      ...this.commentPart(),
    });
    this.editing.set(false);
  }

  private commentPart() {
    const c = this.comment().trim();
    return c ? { comment: c } : {};
  }

  protected val(e: Event) {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }
}
