import { Component, computed, input } from '@angular/core';

/** Always renders a text label; color is only a secondary cue. */
@Component({
  selector: 'ui-badge',
  template: `<span [class]="classes()"><ng-content /></span>`,
})
export class UiBadge {
  readonly tone = input<string>('neutral');

  protected readonly classes = computed(() => {
    const base = 'inline-block rounded px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ';
    switch (this.tone().toLowerCase()) {
      case 'critical':
        return base + 'bg-sev-critical text-white ring-sev-critical';
      case 'high':
        return base + 'bg-sev-high text-white ring-sev-high';
      case 'medium':
        return base + 'bg-sev-medium text-black ring-sev-medium';
      case 'low':
        return base + 'bg-sev-low text-white ring-sev-low';
      case 'ok':
        return base + 'bg-ok/15 text-ok ring-ok';
      default:
        return base + 'bg-muted text-fg ring-line';
    }
  });
}
