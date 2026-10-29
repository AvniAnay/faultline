import type { UserRef } from './me';

export type RunStatus = 'requested' | 'running' | 'awaiting_review' | 'sending' | 'completed' | 'failed';

export interface RunStats {
  lines_scanned: number;
  lines_dropped_level: number;
  distinct_errors: number;
  flagged: number;
  llm_calls: number;
  llm_tokens: { prompt: number; completion: number; total: number };
  tavily_calls: number;
  redaction_counts: Record<string, number>;
  redaction_failures: number;
  emails_logged: number;
  duration_seconds?: number | null;
  error?: string | null;
}

export interface Run {
  id: string;
  requested_by: UserRef | null;
  started_at: string | null;
  finished_at: string | null;
  window_start: string | null;
  window_end: string | null;
  status: RunStatus;
  stats: RunStats;
  pending_review_count: number;
}
