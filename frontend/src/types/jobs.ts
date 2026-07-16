

export type JobStatus =
  | 'queued'
  | 'validating'
  | 'running'
  | 'completed'
  | 'failed'
  | 'partial';

export interface BulkJob {
  id: number;
  job_type: string;
  status: JobStatus;
  is_terminal: boolean;
  total_rows: number;
  processed_rows: number;
  success_count: number;
  error_count: number;
  errors: Array<{ row: number; errors: string[] }>;
  result: Record<string, unknown>;
  request_id: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}


const JOB_TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set(['completed', 'failed', 'partial']);

export function isTerminalStatus(status: JobStatus): boolean {
  return JOB_TERMINAL_STATUSES.has(status);
}
