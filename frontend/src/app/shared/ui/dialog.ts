import { Component, ElementRef, input, output, viewChild } from '@angular/core';

@Component({
  selector: 'ui-dialog',
  template: `
    <dialog #dlg class="m-auto w-full max-w-md rounded bg-surface p-5 text-fg shadow-xl backdrop:bg-black/50" [attr.aria-label]="heading()" (close)="closed.emit()">
      <h2 class="mb-3 text-lg font-semibold">{{ heading() }}</h2>
      <ng-content />
    </dialog>
  `,
})
export class UiDialog {
  readonly heading = input.required<string>();
  readonly closed = output<void>();
  private readonly dlg = viewChild.required<ElementRef<HTMLDialogElement>>('dlg');

  open() {
    this.dlg().nativeElement.showModal();
  }

  close() {
    this.dlg().nativeElement.close();
  }
}
