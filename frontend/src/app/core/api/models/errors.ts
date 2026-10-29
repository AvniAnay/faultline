import type { Page } from './common';
import type { UserRef } from './me';
import type { ReviewItem } from './reviews';

export type { Page };
export type Severity = 'Critical' | 'High' | 'Medium' | 'Low';
export type Category =
  | 'System'
  | 'Application'
  | 'Database'
  | 'Network'
  | 'Security'
  | 'Infrastructure'
  | 'Third-party'
  | 'Unknown';
export type FingerprintStatus = 'new' | 'open' | 'acknowledged' | 'resolved' | 'ignored' | 'merged';

export const SEVERITIES: Severity[] = ['Critical', 'High', 'Medium', 'Low'];
export const CATEGORIES: Category[] = [
  'System', 'Application', 'Database', 'Network', 'Security', 'Infrastructure', 'Third-party', 'Unknown',
];
export const STATUSES: FingerprintStatus[] = ['new', 'open', 'acknowledged', 'resolved', 'ignored', 'merged'];

export interface Sample {
  redacted_text: string;
  seen_at: string;
}

export interface ResolutionDraft {
  summary: string;
  probable_cause: string;
  steps: string[];
  sources: string[];
  confidence: 'high' | 'medium' | 'low';
  origin: 'kb' | 'web' | 'llm_only';
}

export interface Resolution extends ResolutionDraft {
  id: string;
  fingerprint_id: string;
  status: 'draft' | 'approved' | 'rejected';
  approved_by: UserRef | null;
  approved_at: string | null;
}

export interface ErrorSummary {
  id: string;
  service: string;
  level: string;
  template: string;
  category: Category | null;
  severity: Severity | null;
  team_name: string | null;
  status: FingerprintStatus;
  first_seen: string;
  last_seen: string;
  total_count: number;
}

export interface ReviewHistoryEntry {
  review_item_id: string;
  run_id: string;
  decision: 'pending' | 'approved' | 'edited' | 'rejected';
  reviewer: UserRef | null;
  comment: string | null;
  decided_at: string | null;
}

export interface ErrorDetail extends ErrorSummary {
  drain_cluster_id: string | number | null;
  samples: Sample[];
  latest_flags: string[];
  resolutions: Resolution[];
  pending_review_item: ReviewItem | null;
  review_history: ReviewHistoryEntry[];
}

export interface OccurrencePoint {
  bucket_start: string;
  count: number;
}

export interface Occurrences {
  bucket: 'hour' | 'day';
  points: OccurrencePoint[];
}

export type ErrorsPage = Page<ErrorSummary>;
