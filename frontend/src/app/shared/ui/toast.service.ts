import { Injectable, signal } from '@angular/core';

export interface Toast {
  id: number;
  kind: 'error' | 'info' | 'success';
  text: string;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 1;
  private readonly _toasts = signal<Toast[]>([]);
  readonly toasts = this._toasts.asReadonly();

  show(text: string, kind: Toast['kind'] = 'info') {
    const id = this.nextId++;
    this._toasts.update((t) => [...t, { id, kind, text }]);
    setTimeout(() => this.dismiss(id), 6000);
  }

  error(text: string) {
    this.show(text, 'error');
  }

  dismiss(id: number) {
    this._toasts.update((t) => t.filter((x) => x.id !== id));
  }
}
