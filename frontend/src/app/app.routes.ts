import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'errors' },
  {
    path: 'errors',
    loadComponent: () => import('./features/errors/errors-page').then((m) => m.ErrorsPage),
  },
  {
    path: 'errors/:id',
    loadComponent: () => import('./features/error-detail/error-detail-page').then((m) => m.ErrorDetailPage),
  },
  {
    path: 'review',
    loadComponent: () => import('./features/review/review-page').then((m) => m.ReviewPage),
  },
  { path: '**', redirectTo: 'errors' },
];
