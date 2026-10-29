import type { Category, ResolutionDraft, Sample, Severity } from './errors';
import type { UserRef } from './me';
import type { Run } from './runs';

export type Decision = 'pending' | 'approved' | 'edited' | 'rejected';

export interface ProposedItem {
  flags: string[];
  window_count: number;
  category: Category;
  category_reason: string | null;
  severity: Severity;
  severity_reason: string | null;
  team_name: string | null;
  resolution: ResolutionDraft;
}

export interface ReviewEdits {
  severity?: Severity;
  category?: Category;
  resolution?: { summary?: string; probable_cause?: string; steps?: string[] };
}

export interface ReviewItem {
  id: string;
  run_id: string;
  fingerprint_id: string;
  error: {
    service: string;
    level: string;
    template: string;
    total_count: number;
    first_seen: string;
    last_seen: string;
    samples: Sample[];
  };
  proposed: ProposedItem;
  decision: Decision;
  edited: ReviewEdits | null;
  reviewer: UserRef | null;
  comment: string | null;
  decided_at: string | null;
}

export interface ReviewUpdate {
  decision: Exclude<Decision, 'pending'>;
  edited?: ReviewEdits;
  comment?: string;
}

export interface PendingReviews {
  runs: { run: Run; items: ReviewItem[] }[];
}
