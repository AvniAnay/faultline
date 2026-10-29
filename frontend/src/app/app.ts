import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthStore } from './core/auth/auth.store';
import { UiButton } from './shared/ui/button';
import { ToastOutlet } from './shared/ui/toast-outlet';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, UiButton, ToastOutlet],
  templateUrl: './app.html',
})
export class App {
  protected readonly auth = inject(AuthStore);

  constructor() {
    void this.auth.loadMe();
  }
}
