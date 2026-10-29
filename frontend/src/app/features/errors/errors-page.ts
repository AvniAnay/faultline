import { DatePipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { AuthStore } from '../../core/auth/auth.store';
import { STATUSES, type FingerprintStatus } from '../../core/api/models/errors';
import { UiBadge } from '../../shared/ui/badge';
import { UiButton } from '../../shared/ui/button';
import { UiPager } from '../../shared/ui/pager';
import { ErrorsStore } from './errors.store';

@Component({
  selector: 'app-errors-page',
  imports: [DatePipe, UiBadge, UiButton, UiPager],
  providers: [ErrorsStore],
  templateUrl: './errors-page.html',
})
export class ErrorsPage {
  protected readonly store = inject(ErrorsStore);
  protected readonly auth = inject(AuthStore);
  private readonly router = inject(Router);
  protected readonly statuses = STATUSES;

  constructor() {
    void this.store.init();
  }

  protected open(id: string) {
    void this.router.navigate(['/errors', id]);
  }

  protected onStatus(event: Event) {
    void this.store.setStatus((event.target as HTMLSelectElement).value as FingerprintStatus | '');
  }
}
