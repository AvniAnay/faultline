import { Component, input } from '@angular/core';

/** Use as attribute on a native button: <button uiButton variant="primary">. */
@Component({
  selector: 'button[uiButton]',
  host: {
    type: 'button',
    '[class]': 'classes()',
  },
  template: '<ng-content />',
})
export class UiButton {
  readonly variant = input<'primary' | 'secondary' | 'danger'>('secondary');

  protected classes() {
    const base =
      'inline-flex items-center gap-1 rounded px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ';
    switch (this.variant()) {
      case 'primary':
        return base + 'bg-accent text-white hover:bg-accent/90';
      case 'danger':
        return base + 'bg-sev-critical text-white hover:bg-sev-critical/90';
      default:
        return base + 'bg-surface text-fg ring-1 ring-line hover:bg-muted';
    }
  }
}
